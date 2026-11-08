"""Chat slash/bang commands shared by channel adapters: name -> aureon-agent CLI
subcommand (reused 1:1, no logic duplication)."""
import asyncio
import subprocess
import sys

SLASH_COMMANDS = {
    "sessions": ["sessions"],
    "doctor": ["doctor"],
    "status": ["status"],
    "version": ["version"],
    "mcp": ["mcp", "list"],
    "cron": ["cron", "list"],
    "logs": ["logs"],
    "skills": ["skills", "list"],
}


async def run_cli(cmd: str, cli_args: list, prefix: str = "/") -> str:
    """Run an aureon-agent CLI subcommand off-thread; never raises."""
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "aureon_agent.__main__", *cli_args],
            capture_output=True, text=True, timeout=60,
        )
        out = (proc.stdout or proc.stderr or "").strip()
    except Exception as e:
        out = f"Error running {prefix}{cmd}: {e}"
    return out or f"({prefix}{cmd} produced no output)"
