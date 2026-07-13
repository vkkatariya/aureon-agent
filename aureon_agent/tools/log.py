import os
import sqlite3
import json
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "tool_log.db")

def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                tool_name TEXT,
                inputs TEXT,
                result TEXT,
                exit_status TEXT,
                confirmation_status TEXT
            )
        """)

_init_db()

def log_tool_usage(tool_name: str, inputs: dict, result: str, exit_status: str, confirmation_status: str = "N/A"):
    """
    Append-only audit log for tool usage.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO tool_logs (timestamp, tool_name, inputs, result, exit_status, confirmation_status) VALUES (?, ?, ?, ?, ?, ?)",
                (timestamp, tool_name, json.dumps(inputs), result, exit_status, confirmation_status)
            )
    except Exception as e:
        print(f"Error logging tool usage: {e}")

def get_recent_tool_logs(limit: int = 10) -> list:
    """
    Retrieve the most recent tool logs.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tool_logs ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error fetching tool logs: {e}")
        return []
