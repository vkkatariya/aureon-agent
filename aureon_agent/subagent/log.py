import sqlite3
import time
import os

DB_PATH = "data/subagent_log.db"

def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dispatch_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                created_at REAL,
                task_description TEXT,
                backend TEXT,
                token_count INTEGER,
                exit_code INTEGER,
                duration_sec REAL,
                result_summary TEXT
            )
        """)

def log_subagent_dispatch(task_id: str, task_description: str, backend: str, token_count: int, exit_code: int, duration_sec: float, result_summary: str):
    _init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO dispatch_log 
            (task_id, created_at, task_description, backend, token_count, exit_code, duration_sec, result_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (task_id, time.time(), task_description, backend, token_count, exit_code, duration_sec, result_summary))

def get_recent_subagent_logs(limit: int = 10):
    _init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT * FROM dispatch_log
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
