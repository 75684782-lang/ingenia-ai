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
    user_id TEXT,
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
    user_id TEXT,
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

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen TEXT,
    revoked INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS pair_codes (
    code TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_idem
    ON operations(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_operations_session ON operations(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agents_user ON agents(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
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
            self._migrate()
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user "
                "ON sessions(user_id, updated_at)"
            )
            self._conn.commit()

    def _migrate(self) -> None:
        for table, column, ddl in (
            ("sessions", "user_id", "TEXT"),
            ("operations", "user_id", "TEXT"),
        ):
            columns = {
                row["name"]
                for row in self._conn.execute(f"PRAGMA table_info({table})")
            }
            if column not in columns:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"
                )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ----------------------------- sessions -----------------------------
    def create_session(
        self, title: str, model: str | None = None, user_id: str | None = None
    ) -> str:
        session_id = uuid.uuid4().hex
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, user_id, title, model, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    user_id,
                    title[:120] or "Nueva conversación",
                    model,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return session_id

    def ensure_session(
        self, session_id: str | None, title: str, user_id: str | None = None
    ) -> str:
        if not session_id:
            return self.create_session(title, user_id=user_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT id, user_id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return self.create_session(title, user_id=user_id)
            if user_id is not None and row["user_id"] != user_id:
                return self.create_session(title, user_id=user_id)
        return session_id

    def get_session(
        self, session_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        with self._lock:
            if user_id is None:
                row = self._conn.execute(
                    "SELECT * FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
                    (session_id, user_id),
                ).fetchone()
        return dict(row) if row else None

    def list_sessions(
        self, limit: int = 50, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            if user_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM sessions WHERE user_id = ?"
                    " ORDER BY updated_at DESC LIMIT ?",
                    (user_id, limit),
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

    def get_messages(
        self,
        session_id: str,
        limit: int = 200,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if user_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT messages.* FROM messages "
                    "JOIN sessions ON sessions.id = messages.session_id "
                    "WHERE messages.session_id = ? AND sessions.user_id = ? "
                    "ORDER BY messages.id ASC LIMIT ?",
                    (session_id, user_id, limit),
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
        user_id: str | None = None,
    ) -> str:
        op_id = uuid.uuid4().hex
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO operations (id, user_id, session_id, tool, risk, status,"
                " args_json, result_json, error, idempotency_key, messages_json,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    op_id,
                    user_id,
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

    def get_operation(
        self, op_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        with self._lock:
            if user_id is None:
                row = self._conn.execute(
                    "SELECT * FROM operations WHERE id = ?", (op_id,)
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM operations WHERE id = ? AND user_id = ?",
                    (op_id, user_id),
                ).fetchone()
        return self._decode_operation(row)

    def find_by_idempotency(
        self, key: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        with self._lock:
            if user_id is None:
                row = self._conn.execute(
                    "SELECT * FROM operations WHERE idempotency_key = ? "
                    "AND user_id IS NULL",
                    (key,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM operations WHERE idempotency_key = ? AND user_id = ?",
                    (key, user_id),
                ).fetchone()
        return self._decode_operation(row)

    def list_operations(
        self,
        session_id: str | None = None,
        limit: int = 30,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if session_id and user_id:
                rows = self._conn.execute(
                    "SELECT * FROM operations WHERE session_id = ? AND user_id = ?"
                    " ORDER BY created_at DESC LIMIT ?",
                    (session_id, user_id, limit),
                ).fetchall()
            elif session_id:
                rows = self._conn.execute(
                    "SELECT * FROM operations WHERE session_id = ?"
                    " ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            elif user_id:
                rows = self._conn.execute(
                    "SELECT * FROM operations WHERE user_id = ?"
                    " ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM operations ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._decode_operation(r) for r in rows if r is not None]

    # ------------------------------ users -------------------------------
    def create_user(self, email: str, name: str, password_hash: str) -> dict[str, Any]:
        user_id = uuid.uuid4().hex
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (id, email, name, password_hash, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, email.lower().strip(), name.strip() or email, password_hash, now),
            )
            self._conn.commit()
        return {
            "id": user_id,
            "email": email.lower().strip(),
            "name": name.strip() or email,
            "created_at": now,
        }

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, name, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_auth(self, email: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
            ).fetchone()
        return dict(row) if row else None

    def create_auth_session(
        self, token_hash: str, user_id: str, expires_at: str
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (token_hash, user_id, _now(), expires_at),
            )
            self._conn.commit()

    def get_auth_user(self, token_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT u.id, u.email, u.name, u.created_at, s.expires_at"
                " FROM auth_sessions s JOIN users u ON u.id = s.user_id"
                " WHERE s.token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= _now():
                self._conn.execute(
                    "DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,)
                )
                self._conn.commit()
                return None
        return {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "created_at": row["created_at"],
        }

    def delete_auth_session(self, token_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,)
            )
            self._conn.commit()

    # ------------------------------ agents ------------------------------
    def create_pair_code(
        self, code: str, user_id: str, expires_at: str
    ) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM pair_codes WHERE user_id = ? OR used = 1 OR expires_at < ?",
                (user_id, _now()),
            )
            self._conn.execute(
                "INSERT INTO pair_codes (code, user_id, expires_at, used, created_at)"
                " VALUES (?, ?, ?, 0, ?)",
                (code, user_id, expires_at, _now()),
            )
            self._conn.commit()

    def consume_pair_code(self, code: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, expires_at, used FROM pair_codes WHERE code = ?",
                (code.upper().strip(),),
            ).fetchone()
            if row is None or row["used"] or row["expires_at"] < _now():
                return None
            cur = self._conn.execute(
                "UPDATE pair_codes SET used = 1 "
                "WHERE code = ? AND used = 0 AND expires_at >= ?",
                (code.upper().strip(), _now()),
            )
            if cur.rowcount != 1:
                self._conn.rollback()
                return None
            self._conn.commit()
            return row["user_id"]

    def create_agent(
        self, user_id: str, name: str, token_hash: str
    ) -> dict[str, Any]:
        agent_id = uuid.uuid4().hex
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO agents (id, user_id, name, token_hash, created_at, revoked)"
                " VALUES (?, ?, ?, ?, ?, 0)",
                (agent_id, user_id, name.strip()[:80] or "Mi PC", token_hash, now),
            )
            self._conn.commit()
        return {"id": agent_id, "name": name, "created_at": now}

    def get_agent_by_token(self, token_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agents WHERE token_hash = ? AND revoked = 0",
                (token_hash,),
            ).fetchone()
        return dict(row) if row else None

    def list_agents(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, created_at, last_seen, revoked FROM agents"
                " WHERE user_id = ? AND revoked = 0 ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def touch_agent(self, agent_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE agents SET last_seen = ? WHERE id = ?", (_now(), agent_id)
            )
            self._conn.commit()

    def revoke_agent(self, user_id: str, agent_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE agents SET revoked = 1 WHERE id = ? AND user_id = ?",
                (agent_id, user_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

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
