"""SQLite-backed key-value memory store. note:* keys are injected into the
system prompt by context_builder; everything else is opaque agent scratch state."""
import json
import time

import aiosqlite

NOTE_PREFIX = "note:"


class Memory:
    def __init__(self, db_path="data/memory.db"):
        self.db_path = db_path
        self._db = None
        self._lock = None

    async def connect(self):
        import asyncio

        self._lock = asyncio.Lock()
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            "CREATE TABLE IF NOT EXISTS notes ("
            "key TEXT PRIMARY KEY, value TEXT, updated_at REAL)"
        )
        await self._db.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def set(self, key, value):
        encoded = json.dumps(value, default=str)
        async with self._lock:
            if key.startswith(NOTE_PREFIX):
                await self._db.execute(
                    "INSERT INTO notes (key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                    "updated_at=excluded.updated_at",
                    (key, encoded, time.time()),
                )
            else:
                await self._db.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, encoded),
                )
            await self._db.commit()

    async def get(self, key):
        table = "notes" if key.startswith(NOTE_PREFIX) else "meta"
        cursor = await self._db.execute(
            f"SELECT value FROM {table} WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

    async def keys(self, prefix=None):
        table = "notes" if prefix and prefix.startswith(NOTE_PREFIX) else "meta"
        cursor = await self._db.execute(f"SELECT key FROM {table}")
        rows = await cursor.fetchall()
        keys = [r[0] for r in rows]
        return [k for k in keys if not prefix or k.startswith(prefix)]

    async def get_notes(self):
        """Return note:* entries with the prefix stripped, for the context builder."""
        cursor = await self._db.execute("SELECT key, value FROM notes ORDER BY updated_at DESC")
        rows = await cursor.fetchall()
        return {key[len(NOTE_PREFIX):]: json.loads(value) for key, value in rows}
