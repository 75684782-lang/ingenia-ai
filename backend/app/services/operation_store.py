from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    model TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_name TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    tool TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL,
    args_json TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    idempotency_key TEXT,
    messages_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_idem
    ON operations(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_operations_session ON operations(session_id, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OperationStore:
    """SQLite-based persistence for sessions, messages, and operations."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ----------------------------- sessions -----------------------------
    def create_session(self, title: str, model: str | None = None) -> str:
        session_id = uuid.uuid4().hex
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, title, model, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, title[:120] or "Nueva conversación", model, now, now),
            )
            self._conn.commit()
        return session_id

    def ensure_session(self, session_id: str | None, title: str) -> str:
        if not session_id:
            return self.create_session(title)
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return self.create_session(title)
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def touch_session(self, session_id: str, model: str | None = None) -> None:
        with self._lock:
            if model:
                self._conn.execute(
                    "UPDATE sessions SET updated_at = ?, model = ? WHERE id = ?",
                    (_now(), model, session_id),
                )
            else:
                self._conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (_now(), session_id),
                )
            self._conn.commit()

    # ----------------------------- messages -----------------------------
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_name: str | None = None,
    ) -> int:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages (session_id, role, content, tool_name, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, tool_name, now),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get_messages(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------- operations ----------------------------
    def create_operation(
        self,
        tool: str,
        risk: str,
        args: dict[str, Any],
        status: str,
        session_id: str | None = None,
        idempotency_key: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> str:
        op_id = uuid.uuid4().hex
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO operations (id, session_id, tool, risk, status,"
                " args_json, result_json, error, idempotency_key, messages_json,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    op_id,
                    session_id,
                    tool,
                    risk,
                    status,
                    json.dumps(args, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error,
                    idempotency_key,
                    json.dumps(messages, ensure_ascii=False) if messages is not None else None,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return op_id

    def update_operation(
        self,
        op_id: str,
        status: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        params: list[Any] = [_now()]
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if result is not None:
            fields.append("result_json = ?")
            params.append(json.dumps(result, ensure_ascii=False))
        if error is not None:
            fields.append("error = ?")
            params.append(error)
        params.append(op_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE operations SET {', '.join(fields)} WHERE id = ?", params
            )
            self._conn.commit()

    def set_operation_messages(
        self, op_id: str, messages: list[dict[str, Any]]
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE operations SET messages_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(messages, ensure_ascii=False), _now(), op_id),
            )
            self._conn.commit()

    def get_operation(self, op_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM operations WHERE id = ?", (op_id,)
            ).fetchone()
        return self._decode_operation(row)

    def find_by_idempotency(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM operations WHERE idempotency_key = ?", (key,)
            ).fetchone()
        return self._decode_operation(row)

    def list_operations(
        self, session_id: str | None = None, limit: int = 30
    ) -> list[dict[str, Any]]:
        with self._lock:
            if session_id:
                rows = self._conn.execute(
                    "SELECT * FROM operations WHERE session_id = ?"
                    " ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM operations ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._decode_operation(r) for r in rows if r is not None]

    @staticmethod
    def _decode_operation(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["args"] = json.loads(data.pop("args_json") or "{}")
        result_json = data.pop("result_json", None)
        data["result"] = json.loads(result_json) if result_json else None
        messages_json = data.pop("messages_json", None)
        data["messages"] = json.loads(messages_json) if messages_json else None
        data.pop("idempotency_key", None)
        return data
