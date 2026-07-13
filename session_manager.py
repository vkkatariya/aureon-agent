"""SQLite-backed chat session + message history, keyed by f"{channel}:{client_id}"."""
import asyncio
import json
import time

import aiosqlite


class SessionManager:
    def __init__(self, db_path="data/sessions.db"):
        self.db_path = db_path
        self._db = None
        self._locks = {}

    async def connect(self):
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "session_id TEXT PRIMARY KEY, channel TEXT, client_id TEXT, "
            "created_at REAL, updated_at REAL)"
        )
        await self._db.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "session_id TEXT, role TEXT, content TEXT, timestamp REAL, "
            "tool_calls TEXT, idx INTEGER, "
            "PRIMARY KEY (session_id, idx))"
        )
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    def _lock_for(self, session_id):
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    async def get_or_create_session(self, client_id, channel):
        session_id = f"{channel}:{client_id}"
        async with self._lock_for(session_id):
            cursor = await self._db.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            )
            if await cursor.fetchone() is None:
                now = time.time()
                await self._db.execute(
                    "INSERT INTO sessions (session_id, channel, client_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (session_id, channel, client_id, now, now),
                )
                await self._db.commit()
        return session_id

    async def add_message(self, session_id, role, content, tool_calls=None):
        async with self._lock_for(session_id):
            cursor = await self._db.execute(
                "SELECT COALESCE(MAX(idx), -1) + 1 FROM messages WHERE session_id = ?",
                (session_id,),
            )
            (next_idx,) = await cursor.fetchone()
            now = time.time()
            await self._db.execute(
                "INSERT INTO messages (session_id, role, content, timestamp, tool_calls, idx) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, role, content, now, json.dumps(tool_calls) if tool_calls else None, next_idx),
            )
            await self._db.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id)
            )
            await self._db.commit()

    async def get_history(self, session_id):
        cursor = await self._db.execute(
            "SELECT role, content, tool_calls FROM messages WHERE session_id = ? ORDER BY idx",
            (session_id,),
        )
        rows = await cursor.fetchall()
        history = []
        for role, content, tool_calls in rows:
            entry = {"role": role, "content": content}
            if tool_calls:
                entry["tool_calls"] = json.loads(tool_calls)
            history.append(entry)
        return history
