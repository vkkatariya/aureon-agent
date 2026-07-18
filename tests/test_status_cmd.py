"""Tests for the rich `/status` command (aureon_agent/status.py).

Covers graceful degradation when systemctl/git are absent, that the session
section reflects a seeded SessionManager row, and that no secret material ever
appears in the output."""
import asyncio

from aureon_agent import status as st


def _seed_sessions_db(data_dir):
    from session_manager import SessionManager

    async def _seed():
        sm = SessionManager(str(data_dir / "sessions.db"))
        await sm.connect()
        try:
            sid = await sm.get_or_create_session("723865496", "telegram")
            await sm.add_message(sid, "user", "hello there")
            await sm.add_message(sid, "assistant", "hi, how can i help")
            return sid
        finally:
            await sm.close()

    return asyncio.run(_seed())


def test_gather_status_graceful_when_systemctl_and_git_absent(tmp_path, monkeypatch):
    # Every external command fails -> fields degrade to n/a / unknown, no raise.
    def boom(*a, **k):
        raise FileNotFoundError("no such binary")

    monkeypatch.setattr(st.subprocess, "check_output", boom)

    data = st.gather_status(data_dir=str(tmp_path))

    assert data["status"] == "n/a"
    assert data["uptime_service"] == "n/a"
    assert data["commit"] == "unknown"
    # system uptime reads /proc directly, not a subprocess — still works on Linux
    assert isinstance(data["version"], str) and data["version"]


def test_session_section_reflects_seeded_db(tmp_path):
    sid = _seed_sessions_db(tmp_path)
    data = st.gather_status(data_dir=str(tmp_path))

    assert data["session_id"] == sid
    assert data["session_msgs"] == 2
    assert data["tokens_est"] > 0
    assert data["ctx_total"] >= data["ctx_used"]


def test_no_secrets_in_output(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "sk-super-secret-key-value-123")
    _seed_sessions_db(tmp_path)
    data = st.gather_status(data_dir=str(tmp_path))

    blob = " ".join(str(v) for v in data.values())
    assert "sk-super-secret-key-value-123" not in blob
    assert data["key"] == "set"  # presence only


def test_gather_status_empty_data_dir_no_raise(tmp_path):
    data = st.gather_status(data_dir=str(tmp_path))  # no sessions.db / cron.db
    assert data["session_id"] == "—"
    assert data["cron_total"] == 0
    assert data["compactions"] == "n/a"


def test_render_status_runs(tmp_path, capsys):
    data = st.gather_status(data_dir=str(tmp_path))
    st.render_status(data)
    out = capsys.readouterr().out
    assert "aureon-agent v" in out
    assert "Runtime" in out and "Session" in out


def test_context_window_lookup():
    assert st.context_window_for("minimax-m2.5:cloud") == 32_768
    assert st.context_window_for("totally-unknown-model") == st.DEFAULT_CONTEXT_WINDOW
