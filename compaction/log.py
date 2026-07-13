"""Append-only audit trail of compaction runs (data/compaction_log.db). Kept
separate from session_manager's messages table — messages is never rewritten."""
import os
import time
from dataclasses import dataclass
from typing import Optional

import aiosqlite

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS compaction_runs ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "session_id TEXT NOT NULL, "
    "created_at REAL NOT NULL, "
    "tokens_before INTEGER NOT NULL, "
    "tokens_after INTEGER NOT NULL, "
    "summary_text TEXT NOT NULL, "
    "model_used TEXT NOT NULL, "
    "context_window_used INTEGER NOT NULL, "
    "status TEXT NOT NULL)"
)
_INDEX = "CREATE INDEX IF NOT EXISTS idx_compaction_session ON compaction_runs(session_id, created_at DESC)"


@dataclass
class CompactionRun:
    session_id: str
    tokens_before: int
    tokens_after: int
    summary_text: str
    model_used: str
    context_window_used: int
    status: str = "ok"
    created_at: Optional[float] = None


class CompactionLog:
    def __init__(self, db_path="data/compaction_log.db"):
        self.db_path = db_path
        self._db = None

    async def connect(self):
        dirname = os.path.dirname(self.db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(_SCHEMA)
        await self._db.execute(_INDEX)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def record(self, run: CompactionRun) -> None:
        created_at = run.created_at if run.created_at is not None else time.time()
        await self._db.execute(
            "INSERT INTO compaction_runs (session_id, created_at, tokens_before, tokens_after, "
            "summary_text, model_used, context_window_used, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run.session_id, created_at, run.tokens_before, run.tokens_after,
             run.summary_text, run.model_used, run.context_window_used, run.status),
        )
        await self._db.commit()

    async def list_recent(self, session_id=None, model=None, limit=10):
        query = (
            "SELECT session_id, created_at, tokens_before, tokens_after, "
            "summary_text, model_used, context_window_used, status FROM compaction_runs"
        )
        clauses, params = [], []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if model:
            clauses.append("model_used = ?")
            params.append(model)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [
            CompactionRun(
                session_id=r[0], created_at=r[1], tokens_before=r[2], tokens_after=r[3],
                summary_text=r[4], model_used=r[5], context_window_used=r[6], status=r[7],
            )
            for r in rows
        ]
