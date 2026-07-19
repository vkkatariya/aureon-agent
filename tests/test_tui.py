"""Tests for the interactive TUI session (aureon_agent/repl.py).

Drives run_tui with a fake runtime (fake agent + SessionManager), scripting the
input line reader, so boot modes, /commands, handoff, and the typed-confirm
fallback are exercised without a real agent or terminal."""
import asyncio

import pytest

from aureon_agent import repl


# --- fakes ---------------------------------------------------------------

class FakeAgent:
    def __init__(self):
        self.runs = []

    async def run(self, history, session_id, callbacks):
        self.runs.append({"history": history, "session_id": session_id})
        return "agent reply"


class FakeSessions:
    def __init__(self, existing=None, history=None):
        self.existing = list(existing or [])
        self._history = history or []
        self.created = []
        self.added = []
        self.cleared = []
        self.closed = False

    async def get_or_create_session(self, client_id, channel):
        sid = f"{channel}:{client_id}"
        self.created.append(sid)
        self.existing.append(sid)
        return sid

    async def list_sessions(self):
        return [{"session_id": s} for s in self.existing]

    async def get_history(self, session_id):
        return list(self._history)

    async def add_message(self, session_id, role, content):
        self.added.append((session_id, role, content))

    async def clear_session(self, session_id):
        self.cleared.append(session_id)
        return 3

    async def close(self):
        self.closed = True


class _FakeMcp:
    async def disconnect_all(self):
        pass


class _FakeMemory:
    async def close(self):
        pass


def _patch_runtime(monkeypatch, agent, sessions):
    async def fake_build(*_a, **_k):
        return {"agent": agent, "sessions": sessions, "mcp_manager": _FakeMcp(),
                "memory": _FakeMemory(), "skills": None, "registry": None,
                "reload_task": None}
    monkeypatch.setattr("aureon_agent.cli.build_runtime", fake_build)


def _script_input(monkeypatch, lines):
    """Feed scripted lines to the REPL, then EOF (None)."""
    it = iter(lines)

    async def fake_read(_psession):
        return next(it, None)
    monkeypatch.setattr(repl, "_read_line", fake_read)


# --- boot modes ----------------------------------------------------------

def test_default_creates_tui_session(monkeypatch):
    agent, sessions = FakeAgent(), FakeSessions()
    _patch_runtime(monkeypatch, agent, sessions)
    _script_input(monkeypatch, ["/exit"])

    rc = asyncio.run(repl.run_tui())
    assert rc == 0
    assert sessions.created == ["tui:tty"]
    assert sessions.closed


def test_handoff_loads_history(monkeypatch):
    hist = [{"role": "user", "content": "earlier telegram msg"}]
    agent = FakeAgent()
    sessions = FakeSessions(existing=["telegram:723865496"], history=hist)
    _patch_runtime(monkeypatch, agent, sessions)
    _script_input(monkeypatch, ["continue please", "/exit"])

    rc = asyncio.run(repl.run_tui(handoff="telegram:723865496"))
    assert rc == 0
    assert len(agent.runs) == 1
    assert agent.runs[0]["session_id"] == "telegram:723865496"
    assert agent.runs[0]["history"] == hist  # loaded the telegram history
    # no new tui session created on handoff
    assert sessions.created == []


def test_handoff_unknown_errors(monkeypatch, capsys):
    agent, sessions = FakeAgent(), FakeSessions(existing=[])
    _patch_runtime(monkeypatch, agent, sessions)
    _script_input(monkeypatch, [])

    rc = asyncio.run(repl.run_tui(handoff="telegram:nope"))
    assert rc == 1
    assert "No such session" in capsys.readouterr().out
    assert sessions.closed  # still cleaned up


# --- commands ------------------------------------------------------------

def test_help_prints_command_list(monkeypatch, capsys):
    _patch_runtime(monkeypatch, FakeAgent(), FakeSessions())
    _script_input(monkeypatch, ["/help", "/exit"])
    asyncio.run(repl.run_tui())
    out = capsys.readouterr().out
    assert "/handoff" in out and "/skills" in out and "/new" in out


def test_new_confirmed_clears_session(monkeypatch):
    sessions = FakeSessions()
    _patch_runtime(monkeypatch, FakeAgent(), sessions)
    _script_input(monkeypatch, ["/new", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *_a: "yes")
    asyncio.run(repl.run_tui())
    assert sessions.cleared == ["tui:tty"]


def test_new_declined_keeps_history(monkeypatch):
    sessions = FakeSessions()
    _patch_runtime(monkeypatch, FakeAgent(), sessions)
    _script_input(monkeypatch, ["/new", "/exit"])
    monkeypatch.setattr("builtins.input", lambda *_a: "no")
    asyncio.run(repl.run_tui())
    assert sessions.cleared == []


def test_plain_message_calls_agent(monkeypatch):
    agent, sessions = FakeAgent(), FakeSessions()
    _patch_runtime(monkeypatch, agent, sessions)
    _script_input(monkeypatch, ["hello agent", "/exit"])
    asyncio.run(repl.run_tui())
    assert len(agent.runs) == 1
    # user + assistant persisted
    roles = [r for _sid, r, _c in sessions.added]
    assert roles == ["user", "assistant"]


# --- typed-confirm fallback ----------------------------------------------

def test_confirm_watcher_resolves_from_typed_input(monkeypatch):
    class _Router:
        pending_confirmations = {}

    router = _Router()

    async def _drive():
        fut = asyncio.get_event_loop().create_future()
        router.pending_confirmations["tui:tty"] = fut
        stop = asyncio.Event()
        monkeypatch.setattr("builtins.input", lambda *_a: "yes")
        watcher = asyncio.create_task(repl._confirm_watcher(router, "tui:tty", stop))
        result = await asyncio.wait_for(fut, timeout=2)
        stop.set()
        watcher.cancel()
        return result

    assert asyncio.run(_drive()) == "yes"


@pytest.mark.parametrize("cmd", list(repl.SHELL_COMMANDS))
def test_shell_commands_mapped(cmd):
    assert isinstance(repl.SHELL_COMMANDS[cmd], list)
