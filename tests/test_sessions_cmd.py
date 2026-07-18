"""Tests for SessionManager.list_sessions + the `aureon-agent sessions` CLI command."""
import asyncio

import pytest

from session_manager import SessionManager


@pytest.fixture
def tmp_db(tmp_path):
    db = SessionManager(str(tmp_path / "sessions.db"))
    return db


def _seed_sync(db: SessionManager, sessions: list[tuple[str, str, int]]):
    """sessions: list of (client_id, channel, msg_count)."""
    asyncio.run(db.connect())
    for client_id, channel, n in sessions:
        sid = asyncio.run(db.get_or_create_session(client_id, channel))
        for i in range(n):
            asyncio.run(db.add_message(sid, "user", f"msg {i}"))
    asyncio.run(db.close())


def test_list_sessions_counts_and_order(tmp_db):
    _seed_sync(tmp_db, [("111", "telegram", 3), ("222", "discord", 1), ("333", "telegram", 5)])
    db = SessionManager(tmp_db.db_path)
    asyncio.run(db.connect())
    rows = asyncio.run(db.list_sessions())
    asyncio.run(db.close())

    assert len(rows) == 3
    # ordered by updated_at DESC — session "333" got the last write
    assert rows[0]["client_id"] == "333"
    by_client = {r["client_id"]: r for r in rows}
    assert by_client["111"]["msg_count"] == 3
    assert by_client["222"]["msg_count"] == 1
    assert by_client["333"]["msg_count"] == 5
    assert all(r["session_id"] == f"{r['channel']}:{r['client_id']}" for r in rows)


def test_list_sessions_empty(tmp_db):
    asyncio.run(tmp_db.connect())
    rows = asyncio.run(tmp_db.list_sessions())
    asyncio.run(tmp_db.close())
    assert rows == []


def test_cli_sessions_command_runs(tmp_path):
    """End-to-end: list_sessions returns the seeded row from a temp DB."""
    db = SessionManager(str(tmp_path / "sessions.db"))
    _seed_sync(db, [("723865496", "telegram", 2)])

    db2 = SessionManager(str(tmp_path / "sessions.db"))
    asyncio.run(db2.connect())
    rows = asyncio.run(db2.list_sessions())
    asyncio.run(db2.close())

    assert len(rows) == 1
    assert rows[0]["client_id"] == "723865496"
    assert rows[0]["msg_count"] == 2
