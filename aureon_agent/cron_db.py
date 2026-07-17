"""SQLite persistence for cron jobs and run history.

Tables:
  cron_jobs  — job definitions (schedule, prompt, delivery, etc.)
  cron_runs  — append-only audit log of every execution

Same WAL-mode aiosqlite pattern as memory.py and session_manager.py.
"""
import json
import logging
import os
import time
import uuid

import aiosqlite

logger = logging.getLogger(__name__)


def _uuid8() -> str:
    """8-char hex UUID for job IDs."""
    return uuid.uuid4().hex[:8]


class CronDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._init_tables()

    async def close(self):
        if self._db:
            await self._db.close()

    async def _init_tables(self):
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                schedule TEXT NOT NULL,
                schedule_type TEXT NOT NULL,
                prompt TEXT NOT NULL,
                skills TEXT DEFAULT '[]',
                deliver TEXT DEFAULT 'telegram',
                chat_id TEXT,
                model TEXT,
                timeout_sec INTEGER DEFAULT 300,
                repeat INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                tz TEXT DEFAULT 'UTC',
                exact INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                last_run_at REAL,
                next_run_at REAL,
                run_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS cron_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                session_id TEXT,
                started_at REAL NOT NULL,
                finished_at REAL,
                status TEXT NOT NULL,
                output TEXT,
                error TEXT,
                duration_sec REAL,
                FOREIGN KEY (job_id) REFERENCES cron_jobs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_cron_runs_job_id
                ON cron_runs(job_id);
            CREATE INDEX IF NOT EXISTS idx_cron_runs_started_at
                ON cron_runs(started_at);
        """)
        await self._db.commit()

    # ── Job CRUD ──────────────────────────────────────────────────

    async def add_job(self, *, name: str, schedule: str, schedule_type: str,
                      prompt: str, skills: list[str] | None = None,
                      deliver: str = "telegram", chat_id: str | None = None,
                      model: str | None = None, timeout_sec: int = 300,
                      repeat: int = 0, enabled: bool = True,
                      tz: str = "UTC", exact: bool = False,
                      next_run_at: float | None = None) -> dict:
        job_id = _uuid8()
        now = time.time()
        await self._db.execute(
            """INSERT INTO cron_jobs
               (id, name, schedule, schedule_type, prompt, skills, deliver,
                chat_id, model, timeout_sec, repeat, enabled, tz, exact,
                created_at, next_run_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, name, schedule, schedule_type, prompt,
             json.dumps(skills or []), deliver, chat_id, model,
             timeout_sec, repeat, int(enabled), tz, int(exact),
             now, next_run_at),
        )
        await self._db.commit()
        return await self.get_job(job_id)

    async def get_job(self, job_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT * FROM cron_jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_jobs(self) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM cron_jobs ORDER BY created_at DESC")
        return [dict(r) for r in await cursor.fetchall()]

    async def update_job(self, job_id: str, **fields) -> dict | None:
        if not fields:
            return await self.get_job(job_id)
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [job_id]
        await self._db.execute(
            f"UPDATE cron_jobs SET {sets} WHERE id = ?", vals)
        await self._db.commit()
        return await self.get_job(job_id)

    async def remove_job(self, job_id: str) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_due_jobs(self, now: float) -> list[dict]:
        cursor = await self._db.execute(
            """SELECT * FROM cron_jobs
               WHERE enabled = 1
                 AND next_run_at IS NOT NULL
                 AND next_run_at <= ?
               ORDER BY next_run_at ASC""",
            (now,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    # ── Run audit log ─────────────────────────────────────────────

    async def add_run(self, *, job_id: str, session_id: str,
                      started_at: float) -> int:
        cursor = await self._db.execute(
            """INSERT INTO cron_runs (job_id, session_id, started_at, status)
               VALUES (?, ?, ?, 'running')""",
            (job_id, session_id, started_at),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def finish_run(self, run_id: int, *, status: str,
                         output: str | None = None,
                         error: str | None = None,
                         duration_sec: float | None = None):
        # Truncate output to 10KB
        if output and len(output) > 10240:
            output = output[:10240] + "\n… (truncated)"
        await self._db.execute(
            """UPDATE cron_runs
               SET finished_at = ?, status = ?, output = ?,
                   error = ?, duration_sec = ?
               WHERE id = ?""",
            (time.time(), status, output, error, duration_sec, run_id),
        )
        await self._db.commit()

    async def list_runs(self, job_id: str, limit: int = 20) -> list[dict]:
        cursor = await self._db.execute(
            """SELECT * FROM cron_runs
               WHERE job_id = ?
               ORDER BY started_at DESC
               LIMIT ?""",
            (job_id, limit),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_last_run(self, job_id: str) -> dict | None:
        cursor = await self._db.execute(
            """SELECT * FROM cron_runs
               WHERE job_id = ?
               ORDER BY started_at DESC
               LIMIT 1""",
            (job_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
