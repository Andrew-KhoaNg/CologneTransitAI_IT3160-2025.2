import json
import os
import sqlite3
from datetime import datetime, timezone


class TransitStorage:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS disabled_lines (
                    line TEXT PRIMARY KEY,
                    disabled_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS route_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_node INTEGER NOT NULL,
                    end_node INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    total_distance REAL,
                    path_json TEXT,
                    details_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def get_disabled_lines(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT line FROM disabled_lines ORDER BY line").fetchall()
        return [row["line"] for row in rows]

    def set_line_disabled(self, line, disabled):
        with self._connect() as conn:
            if disabled:
                conn.execute(
                    """
                    INSERT INTO disabled_lines (line, disabled_at)
                    VALUES (?, ?)
                    ON CONFLICT(line) DO UPDATE SET disabled_at = excluded.disabled_at
                    """,
                    (line, self._now()),
                )
            else:
                conn.execute("DELETE FROM disabled_lines WHERE line = ?", (line,))
        return self.get_disabled_lines()

    def save_route_query(self, start_node, end_node, result):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO route_history
                    (start_node, end_node, success, total_distance, path_json, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    start_node,
                    end_node,
                    1 if result.get("success") else 0,
                    result.get("total_distance"),
                    json.dumps(result.get("path"), ensure_ascii=False),
                    json.dumps(result.get("details"), ensure_ascii=False),
                    self._now(),
                ),
            )
