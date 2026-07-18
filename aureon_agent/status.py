"""Rich `/status` — a single self-contained status block (service, runtime,
tokens/context, session, cron, MCP) mirroring the OpenClaw / Hermes status
pages. Gathered from local state + lightweight probes only — no agent round-trip,
no live LLM ping, no secrets printed.

`gather_status()` returns plain strings and never raises (degrades to "n/a" when
systemctl/git/db are unavailable), so it is trivially testable. `render_status()`
formats that dict with Rich for the terminal; the Telegram path wraps the CLI
output in a code block at the single `_on_command` delivery point.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from datetime import datetime, timezone

from aureon_agent import __version__

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SERVICE = "aureon-agent.service"

# Minimal, self-contained context-window lookup (session-compaction's fuller
# table isn't on this branch). Default 32K for unknown models.
MODEL_CONTEXT_WINDOWS = {
    "minimax-m2.5:cloud": 32_768,
    "minimax-m3": 1_000_000,
    "gemma4:31b-cloud": 131_072,
    "gpt-oss:120b-cloud": 131_072,
    "qwen3-coder:480b-cloud": 262_144,
}
DEFAULT_CONTEXT_WINDOW = 32_768


def context_window_for(model: str) -> int:
    return MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)


# --- helpers (each best-effort, never raises) ---------------------------

def _run(cmd, timeout=3) -> str:
    """Run a command, return stdout stripped, or '' on any failure."""
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL,
                                       timeout=timeout).strip()
    except Exception:
        return ""


def _fmt_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h or d:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


def _fmt_when(ts: float | None) -> str:
    if not ts:
        return "—"
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _service_active() -> str:
    state = _run(["systemctl", "--user", "is-active", SERVICE])
    return state or "n/a"


def _service_uptime() -> str:
    ts = _run(["systemctl", "--user", "show", SERVICE, "-p",
               "ActiveEnterTimestampMonotonic", "--value"])
    if ts and ts.isdigit() and int(ts) > 0:
        # monotonic microseconds since boot -> elapsed = now_monotonic - that
        elapsed = time.clock_gettime(time.CLOCK_MONOTONIC) - int(ts) / 1_000_000
        if elapsed >= 0:
            return _fmt_duration(elapsed)
    return "n/a"


def _system_uptime() -> str:
    try:
        with open("/proc/uptime") as f:
            return _fmt_duration(float(f.read().split()[0]))
    except Exception:
        return "n/a"


def _git_commit() -> str:
    return _run(["git", "-C", BASE_DIR, "rev-parse", "--short", "HEAD"]) or "unknown"


def _local_time() -> tuple[str, str]:
    tz_name = os.getenv("TZ", "Europe/Berlin")
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(tz_name))
        local = now.strftime(f"%A, %B %d, %Y - %H:%M ({tz_name})")
    except Exception:
        local = datetime.now().strftime("%A, %B %d, %Y - %H:%M (local)")
    utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return local, utc


async def _session_and_cron(data_dir: str) -> tuple[dict, dict]:
    session = {"id": "—", "channel": "—", "msgs": 0, "updated": "—",
               "tokens": 0, "duration": "—"}
    cron = {"total": 0, "enabled": 0, "due_soon": 0}

    sessions_db = os.path.join(data_dir, "sessions.db")
    if os.path.exists(sessions_db):
        try:
            from session_manager import SessionManager
            sm = SessionManager(sessions_db)
            await sm.connect()
            try:
                rows = await sm.list_sessions()
                if rows:
                    top = rows[0]
                    history = await sm.get_history(top["session_id"])
                    tokens = sum(len(m.get("content") or "") for m in history) // 4
                    created = top.get("created_at")
                    updated = top.get("updated_at")
                    session.update(
                        id=top["session_id"],
                        channel=f"{top.get('channel') or '—'}:{top.get('client_id') or '—'}",
                        msgs=top.get("msg_count", 0),
                        updated=_fmt_when(updated),
                        tokens=tokens,
                        duration=_fmt_duration((updated or 0) - (created or 0))
                        if created and updated else "—",
                    )
            finally:
                await sm.close()
        except Exception:
            pass

    cron_db = os.path.join(data_dir, "cron.db")
    if os.path.exists(cron_db):
        try:
            from aureon_agent.cron_db import CronDB
            db = CronDB(cron_db)
            await db.connect()
            try:
                jobs = await db.list_jobs()
                now = time.time()
                cron.update(
                    total=len(jobs),
                    enabled=sum(1 for j in jobs if j.get("enabled")),
                    due_soon=sum(1 for j in jobs if j.get("enabled")
                                 and j.get("next_run_at") and j["next_run_at"] - now < 3600),
                )
            finally:
                await db.close()
        except Exception:
            pass

    return session, cron


def gather_status(data_dir: str = DATA_DIR) -> dict:
    """Collect every status field as strings. Never raises; unavailable probes
    degrade to 'n/a'. No secrets — key material is reported as presence only."""
    model = os.getenv("OLLAMA_MODEL", "minimax-m2.5:cloud")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    fallback = os.getenv("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/v1")
    local_time, utc_time = _local_time()

    try:
        session, cron = asyncio.run(_session_and_cron(data_dir))
    except Exception:
        session = {"id": "—", "channel": "—", "msgs": 0, "updated": "—",
                   "tokens": 0, "duration": "—"}
        cron = {"total": 0, "enabled": 0, "due_soon": 0}

    ctx_total = context_window_for(model)
    ctx_used = session["tokens"]
    ctx_pct = round(ctx_used / ctx_total * 100, 1) if ctx_total else 0

    try:
        from aureon_agent.doctor import check_mcp_servers
        _, mcp_details = check_mcp_servers()
    except Exception:
        mcp_details = "n/a"

    active = _service_active()

    return {
        # A. service / uptime
        "version": __version__,
        "commit": _git_commit(),
        "time_local": local_time,
        "time_utc": utc_time,
        "uptime_service": _service_uptime(),
        "uptime_system": _system_uptime(),
        "status": active,
        # B. runtime / model
        "model": model,
        "base_url": base_url,
        "key": "set" if os.getenv("OLLAMA_API_KEY") else "none",
        "fallback": fallback,
        "execution": "direct",
        "runtime": "ollama",
        "think": os.getenv("AUREON_THINK", "off"),
        "fast": os.getenv("AUREON_FAST", "off"),
        # C. tokens / context
        "tokens_est": ctx_used,
        "ctx_used": ctx_used,
        "ctx_total": ctx_total,
        "ctx_pct": ctx_pct,
        "compactions": "n/a",  # compaction log not on this branch
        # D. session
        "session_id": session["id"],
        "session_channel": session["channel"],
        "session_msgs": session["msgs"],
        "session_duration": session["duration"],
        "session_updated": session["updated"],
        "agent_running": "Yes" if active == "active" else "No",
        # E. cron + mcp
        "cron_total": cron["total"],
        "cron_enabled": cron["enabled"],
        "cron_due_soon": cron["due_soon"],
        "mcp": mcp_details,
    }


def render_status(data: dict | None = None, data_dir: str = DATA_DIR) -> None:
    """Print the status block with Rich (terminal). Telegram wraps this stdout
    in a code block at the delivery point."""
    from rich.console import Console
    from rich.table import Table

    if data is None:
        data = gather_status(data_dir)

    console = Console()

    def section(title: str, rows: list[tuple[str, str]]):
        t = Table(show_header=False, box=None, pad_edge=False, title=title,
                  title_justify="left", title_style="bold cyan")
        t.add_column("k", style="dim")
        t.add_column("v")
        for k, v in rows:
            t.add_row(k, str(v))
        console.print(t)
        console.print()

    section(f"aureon-agent v{data['version']} ({data['commit']})", [
        ("Status", data["status"]),
        ("Time", data["time_local"]),
        ("Reference", data["time_utc"]),
        ("Uptime", f"service {data['uptime_service']} · system {data['uptime_system']}"),
    ])
    section("Runtime", [
        ("Model", f"{data['model']} · key {data['key']} · auto fallback"),
        ("Endpoint", data["base_url"]),
        ("Fallback", data["fallback"]),
        ("Execution", f"{data['execution']} · runtime {data['runtime']} · "
                      f"think {data['think']} · fast {data['fast']}"),
    ])
    section("Context", [
        ("Tokens", f"~{data['tokens_est']} (session estimate)"),
        ("Context", f"{data['ctx_used']}/{data['ctx_total']} ({data['ctx_pct']}%)"),
        ("Compactions", data["compactions"]),
    ])
    section("Session", [
        ("Session", f"{data['session_id']} ({data['session_channel']})"),
        ("Messages", data["session_msgs"]),
        ("Duration", data["session_duration"]),
        ("Updated", data["session_updated"]),
        ("Agent running", data["agent_running"]),
    ])
    section("Services", [
        ("Cron", f"{data['cron_total']} jobs ({data['cron_enabled']} enabled, "
                 f"{data['cron_due_soon']} due soon)"),
        ("MCP", data["mcp"]),
    ])


def cmd_status(_args=None) -> None:
    render_status()
