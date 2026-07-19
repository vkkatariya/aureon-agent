"""Interactive terminal agent session (Claude Code / Hermes / OpenClaw style).

Run `python -m aureon_agent.__main__ tui` to chat with the agent live in a
terminal. Boots either as a fresh `tui:tty` session or, with `--handoff
<channel:id>`, continues an existing chat (e.g. a Telegram conversation) by
loading its history.

Drives the same `agent.run` the bot uses (via `cli.build_runtime`), so behaviour
is identical to Telegram. Slash commands reuse the CLI subcommands; destructive
confirmations (`confirm_with_captain`) fall back to a typed yes/no prompt since
there's no Telegram keyboard here.
"""
from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys

from aureon_agent import __version__
from channels.base import Channel

# Slash command -> CLI subcommand (mirrors telegram.SLASH_COMMANDS).
SHELL_COMMANDS = {
    "sessions": ["sessions"],
    "doctor": ["doctor"],
    "status": ["status"],
    "version": ["version"],
    "mcp": ["mcp", "list"],
    "cron": ["cron", "list"],
    "logs": ["logs"],
    "skills": ["skills", "list"],
}

HELP = """Commands:
  /help              this message
  /new               start a fresh session (clears current history)
  /handoff <id>      continue another session (e.g. telegram:723865496)
  /sessions          list all chat sessions
  /skills            list loaded doctrine skills
  /status            agent status
  /doctor            health checks
  /mcp               MCP servers + tools
  /cron              cron jobs
  /logs              recent bot logs
  /version           agent version
  /exit              save + quit
Anything not starting with / is sent to the agent."""


class TuiChannel(Channel):
    """Minimal in-process channel so router.send_confirmation has somewhere to
    print. Streaming + input happen in the REPL loop, not here."""

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        print(f"\n{text}")

    async def edit_message(self, chat_id, message_id, text):
        pass

    async def send_action(self, chat_id, action):
        pass


def _on_token(token):
    sys.stdout.write(token)
    sys.stdout.flush()


async def _on_token_async(token):
    _on_token(token)


async def _on_tool_use(name, args):
    print(f"\n  · tool: {name}({', '.join(f'{k}={v!r}' for k, v in (args or {}).items())})")


async def _confirm_watcher(router, session_id, stop_event):
    """While the agent awaits a confirmation future, read a typed yes/no from
    stdin and resolve it (the TUI has no inline keyboard)."""
    while not stop_event.is_set():
        fut = router.pending_confirmations.get(session_id)
        if fut and not fut.done():
            try:
                ans = await asyncio.to_thread(input, "  confirm [yes/no]: ")
            except (EOFError, KeyboardInterrupt):
                ans = "no"
            if not fut.done():
                fut.set_result(ans.strip())
        await asyncio.sleep(0.1)


async def _read_line(psession):
    try:
        if psession is not None:
            return await psession.prompt_async()
        return await asyncio.to_thread(input, "aureon> ")
    except (EOFError, KeyboardInterrupt):
        return None


def _make_prompt_session():
    if not sys.stdin.isatty():
        return None  # piped/scripted input -> plain input()
    try:
        from prompt_toolkit import PromptSession
        return PromptSession(message="aureon> ", enable_history_search=True)
    except Exception:
        return None  # fall back to plain input()


async def _handle_chat(agent, sessions, router, state, line):
    session_id = state["session_id"]
    await sessions.add_message(session_id, "user", line)
    history = await sessions.get_history(session_id)
    
    chat_state = {"thinking_started": False, "thinking_ended": False}
    
    async def _local_on_thinking(token):
        if not chat_state["thinking_started"]:
            sys.stdout.write("\n\033[2m[thinking]\n")
            chat_state["thinking_started"] = True
        sys.stdout.write(token)
        sys.stdout.flush()
        
    async def _local_on_token(token):
        if chat_state["thinking_started"] and not chat_state["thinking_ended"]:
            sys.stdout.write("\033[0m\n\n")
            chat_state["thinking_ended"] = True
        await _on_token_async(token)

    callbacks = {
        "on_token": _local_on_token,
        "on_tool_use": _on_tool_use,
        "on_thinking": _local_on_thinking,
        "context": {
            "router": router,
            "session_id": session_id,
            "channel_name": state["channel_name"],
            "client_id": state["client_id"],
        },
    }
    stop = asyncio.Event()
    watcher = asyncio.create_task(_confirm_watcher(router, session_id, stop))
    try:
        resp = await agent.run(history, session_id, callbacks)
    finally:
        stop.set()
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
    print()  # newline after streamed tokens
    if resp:
        await sessions.add_message(session_id, "assistant", resp)


def _run_cli(cli_args):
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "aureon_agent.__main__", *cli_args],
            capture_output=True, text=True, timeout=60,
        )
        return (proc.stdout or proc.stderr or "").strip()
    except Exception as e:  # noqa: BLE001
        return f"Error: {e}"


async def _set_session(router, state, session_id):
    """Point the live TUI at session_id, registering a TuiChannel under its
    channel prefix so confirmations can print."""
    channel_name, client_id = session_id.split(":", 1)
    router.register(channel_name, TuiChannel())
    state.update(session_id=session_id, channel_name=channel_name, client_id=client_id)


async def _handle_command(line, agent, sessions, router, state):
    """Return "__exit__" to quit, else None."""
    parts = line[1:].split()
    cmd = parts[0].lower() if parts else ""
    args = parts[1:]

    if cmd in ("exit", "quit"):
        return "__exit__"
    if cmd == "help" or cmd == "":
        print(HELP)
        return None
    if cmd == "new":
        ans = await asyncio.to_thread(
            input, f"Clear history for {state['session_id']}? [yes/no]: ")
        if ans.strip().lower() in ("yes", "y"):
            cleared = await sessions.clear_session(state["session_id"])
            print(f"✅ New session — cleared {cleared} message(s).")
        else:
            print("Kept current history.")
        return None
    if cmd == "handoff":
        if not args:
            print("Usage: /handoff <channel:id>  (e.g. telegram:723865496)")
            return None
        target = args[0]
        rows = await sessions.list_sessions()
        if target not in {r["session_id"] for r in rows}:
            print(f"No such session: {target}. Try /sessions to list them.")
            return None
        await _set_session(router, state, target)
        n = len(await sessions.get_history(target))
        print(f"↪ handed off to {target} ({n} messages loaded).")
        return None
    if cmd in SHELL_COMMANDS:
        print(_run_cli(SHELL_COMMANDS[cmd]))
        return None

    print(f"Unknown command: /{cmd} (try /help)")
    return None


def _print_banner(session_id):
    print(f"aureon-agent v{__version__} — interactive session")
    print(f"session: {session_id}")
    print("type /help for commands, /exit to quit\n")


async def run_tui(handoff=None, session=None):
    from dotenv import load_dotenv
    load_dotenv(override=True)

    from aureon_agent.cli import build_runtime

    rt = await build_runtime(watch_skills=False, connect_mcp=False)
    agent, sessions = rt["agent"], rt["sessions"]
    mcp_manager = rt["mcp_manager"]
    memory = rt["memory"]

    from channels.router import ChannelRouter
    from aureon_agent.cli import WORKSPACE_DIR
    router = ChannelRouter(agent, sessions, WORKSPACE_DIR)

    rc = 0
    try:
        state = {}
        if handoff:
            rows = await sessions.list_sessions()
            if handoff not in {r["session_id"] for r in rows}:
                print(f"No such session to hand off: {handoff}. Use /sessions to list them.")
                return 1
            await _set_session(router, state, handoff)
        elif session:
            await _set_session(router, state, session)
        else:
            session_id = await sessions.get_or_create_session("tty", "tui")
            await _set_session(router, state, session_id)

        _print_banner(state["session_id"])
        psession = _make_prompt_session()
        thinking_status = "on" if agent.thinking else "off"
        print(f"[dim]interactive session · MCP tools offline (connect_mcp=False) · thinking: {thinking_status}[/dim]\n")

        while True:
            line = await _read_line(psession)
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                if await _handle_command(line, agent, sessions, router, state) == "__exit__":
                    break
            else:
                await _handle_chat(agent, sessions, router, state, line)
        print("\nbye.")
    finally:
        # MCP stdio teardown (anyio) can raise CancelledError / block; bound it
        # and swallow BaseException so exit never hangs on a lingering subprocess.
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(mcp_manager.disconnect_all(), timeout=5)
        # Close the aiosqlite connections (each runs a non-daemon thread that
        # would otherwise keep the interpreter alive after asyncio.run returns).
        with contextlib.suppress(BaseException):
            await sessions.close()
        with contextlib.suppress(BaseException):
            await memory.close()
    return rc


def cmd_tui(args):
    handoff = getattr(args, "handoff", None)
    session = getattr(args, "session", None)
    return asyncio.run(run_tui(handoff=handoff, session=session))
