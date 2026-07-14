import os
import sqlite3
import shutil
import sys
import subprocess
import httpx
from typing import Tuple

from aureon_agent.config import AureonConfig
from aureon_agent.tui import print_banner, print_table, print_status

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
ENV_PATH = os.path.join(BASE_DIR, ".env")

def check_python() -> Tuple[str, str]:
    if sys.version_info >= (3, 12):
        return "✅", f"Python {sys.version.split()[0]}"
    return "❌", f"Python {sys.version.split()[0]} (requires >= 3.12)"

def check_venv() -> Tuple[str, str]:
    is_venv = sys.prefix != sys.base_prefix
    if is_venv:
        return "✅", "Virtual environment active"
    return "❌", "Not running in a virtual environment"

def check_env() -> Tuple[str, str]:
    if not os.path.exists(ENV_PATH):
        return "❌", "Missing .env file"

    stat = os.stat(ENV_PATH)
    perms = oct(stat.st_mode)[-3:]
    if perms != "600":
        return "❌", f"Incorrect .env permissions: {perms} (should be 600)"

    config = AureonConfig.from_file(ENV_PATH)
    errors = config.validate()
    if errors:
        return "❌", "Validation failed: " + "; ".join(errors)

    if not config.TELEGRAM_BOT_TOKEN and not config.DISCORD_BOT_TOKEN:
        return "🟡", "No channels configured"

    # Captain's command: Telegram allowlist check
    if config.TELEGRAM_BOT_TOKEN and not config.TELEGRAM_ALLOWED_CHATS:
        return "❌", "TELEGRAM_ALLOWED_CHATS is empty"

    return "✅", "Valid and chmod 600"

def check_workspace() -> Tuple[str, str]:
    links = ["SOUL.md", "IDENTITY.md", "MEMORY.md", "skills", "memory"]
    broken = []
    for link in links:
        path = os.path.join(WORKSPACE_DIR, link)
        if not os.path.exists(path):
            broken.append(link)
    if broken:
        return "❌", f"Broken symlinks: {', '.join(broken)}"
    return "✅", "All symlinks resolve"

def check_tools_allowlist() -> Tuple[str, str]:
    from aureon_agent.tools.base import WorkspaceBoundTool
    if not os.path.exists(WorkspaceBoundTool.ALLOWED_RW):
        return "❌", f"RW workspace {WorkspaceBoundTool.ALLOWED_RW} missing"
    if not os.path.exists(WorkspaceBoundTool.ALLOWED_RO):
        return "❌", f"RO workspace {WorkspaceBoundTool.ALLOWED_RO} missing"
    return "✅", "Paths configured correctly"

def check_claude_cli() -> Tuple[str, str]:
    if shutil.which("claude"):
        return "✅", "claude-code CLI found"
    return "❌", "claude-code CLI missing"

def check_plan_node() -> Tuple[str, str]:
    from plan_node import has_plan
    # Just check if it crashes
    try:
        has_plan(".")
        return "✅", "Plan node OK"
    except Exception as e:
        return "❌", f"Plan node error: {e}"

def check_ollama() -> Tuple[str, str]:
    config = AureonConfig.from_file(ENV_PATH)
    try:
        res = httpx.get(f"{config.OLLAMA_BASE_URL}/models", timeout=3)
        res.raise_for_status()
        return "✅", f"Reachable ({config.OLLAMA_BASE_URL})"
    except Exception as e:
        return "❌", f"Unreachable: {e}"

def check_telegram() -> Tuple[str, str]:
    config = AureonConfig.from_file(ENV_PATH)
    if not config.TELEGRAM_BOT_TOKEN:
        return "🟡", "Not configured"
    try:
        res = httpx.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe", timeout=5).json()
        if res.get("ok"):
            return "✅", f"Bot: @{res['result']['username']}"
        return "❌", "Invalid token"
    except Exception as e:
        return "❌", f"API error: {e}"

def check_systemd() -> Tuple[str, str]:
    if not sys.platform.startswith("linux"):
        return "🟡", "Not Linux"
    try:
        res = subprocess.run(["systemctl", "--user", "is-active", "aureon-agent.service"], capture_output=True, text=True)
        status = res.stdout.strip()
        if status == "active":
            return "✅", "Active (running)"
        return "🟡", f"Status: {status}"
    except FileNotFoundError:
        return "🟡", "systemctl not found"

def check_smoke_tests() -> Tuple[str, str]:
    smoke_path = os.path.join(BASE_DIR, "tests", "smoke.py")
    if not os.path.exists(smoke_path):
        return "❌", "Smoke tests missing"
    
    try:
        res = subprocess.run([sys.executable, smoke_path], capture_output=True, text=True)
        if res.returncode == 0:
            return "✅", "Smoke tests passed"
        return "❌", "Smoke tests failed"
    except Exception as e:
        return "❌", f"Error: {e}"

def check_cron_scheduler() -> Tuple[str, str]:
    db_path = os.path.join(BASE_DIR, "data", "cron_jobs.db")
    if not os.path.exists(db_path):
        return "🟡", "No cron DB yet (starts on first bot run)"
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Count enabled jobs
        cursor = conn.execute("SELECT COUNT(*) FROM cron_jobs WHERE enabled = 1")
        enabled = cursor.fetchone()[0]
        # Check for stuck runs (running > 10 min)
        import time
        cutoff = time.time() - 600
        cursor = conn.execute(
            "SELECT COUNT(*) FROM cron_runs WHERE status = 'running' AND started_at < ?",
            (cutoff,))
        stuck = cursor.fetchone()[0]
        conn.close()
        if stuck > 0:
            return "🟡", f"{enabled} active jobs, {stuck} stuck run(s) (>10min)"
        return "✅", f"{enabled} active job(s)"
    except Exception as e:
        return "❌", f"DB error: {e}"

def main():
    print_banner()
    
    rows = []
    
    checks = [
        ("Python Version", check_python),
        ("Virtual Env", check_venv),
        ("Config (.env)", check_env),
        ("Workspace", check_workspace),
        ("Tools Allowlist", check_tools_allowlist),
        ("Claude CLI", check_claude_cli),
        ("Plan Node", check_plan_node),
        ("Ollama", check_ollama),
        ("Telegram API", check_telegram),
        ("systemd daemon", check_systemd),
        ("Cron Scheduler", check_cron_scheduler),
        ("Smoke Tests", check_smoke_tests)
    ]
    
    all_green = True
    any_red = False
    missing_config = False
    
    for name, func in checks:
        status, details = func()
        rows.append([name, status, details])
        if status == "❌":
            all_green = False
            any_red = True
            if name == "Config (.env)":
                missing_config = True
        elif status == "🟡":
            all_green = False
            
    print_table(["Check", "Status", "Details"], rows, title="Aureon Agent Health")
    
    if any_red:
        if missing_config:
            print_status("Missing or invalid configuration. Run `aureon-agent setup`.", "error")
            sys.exit(2)
        print_status("Some critical checks failed.", "error")
        sys.exit(1)
    elif not all_green:
        print_status("System is operational but has warnings.", "warn")
        sys.exit(0)
    else:
        print_status("All systems go! 🦾", "success")
        sys.exit(0)

if __name__ == "__main__":
    main()
