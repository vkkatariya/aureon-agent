import asyncio
import os
import sys
import subprocess
import time
import httpx
from typing import Tuple

from aureon_agent.config import AureonConfig
from aureon_agent.models import MODEL_CONTEXT_WINDOWS
from aureon_agent.tui import print_banner, print_table, print_status

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
ENV_PATH = os.path.join(BASE_DIR, ".env")
COMPACTION_LOG_PATH = os.path.join(BASE_DIR, "data", "compaction_log.db")
COMPACTION_STALE_DAYS = 7

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

def check_compaction_log() -> Tuple[str, str]:
    if not os.path.exists(COMPACTION_LOG_PATH):
        return "🟡", "No compaction runs yet"

    async def _last_run():
        from compaction.log import CompactionLog
        log = CompactionLog(COMPACTION_LOG_PATH)
        await log.connect()
        try:
            runs = await log.list_recent(limit=1)
        finally:
            await log.close()
        return runs[0] if runs else None

    try:
        run = asyncio.run(_last_run())
    except Exception as e:
        return "❌", f"compaction_log.db unreadable: {e}"

    if run is None:
        return "🟡", "No compaction runs yet"

    age_days = (time.time() - run.created_at) / 86400
    if age_days > COMPACTION_STALE_DAYS:
        return "🟡", f"Last compaction {age_days:.1f}d ago (session {run.session_id})"
    return "✅", f"Last compaction {age_days:.1f}d ago (session {run.session_id})"


def check_model_known() -> Tuple[str, str]:
    config = AureonConfig.from_file(ENV_PATH)
    if config.OLLAMA_MODEL in MODEL_CONTEXT_WINDOWS:
        return "✅", f"{config.OLLAMA_MODEL} ({MODEL_CONTEXT_WINDOWS[config.OLLAMA_MODEL]} tokens)"
    return "🟡", f"{config.OLLAMA_MODEL} not in MODEL_CONTEXT_WINDOWS — compaction will assume 32K"


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

def main():
    print_banner()
    
    rows = []
    
    checks = [
        ("Python Version", check_python),
        ("Virtual Env", check_venv),
        ("Config (.env)", check_env),
        ("Workspace", check_workspace),
        ("Ollama", check_ollama),
        ("Telegram API", check_telegram),
        ("systemd daemon", check_systemd),
        ("Compaction Log", check_compaction_log),
        ("Model Registry", check_model_known),
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
