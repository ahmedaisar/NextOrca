from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any


class SessionStoreError(RuntimeError):
    """A persistent session could not be created, loaded or updated."""


class SQLiteSessionStore:
    """Append-only local session/message store backed by SQLite."""

    def __init__(self, path: Path | str) -> None:
        requested = Path(path).expanduser()
        if requested.is_symlink():
            raise SessionStoreError("Refusing to use a symlink as the session database.")
        try:
            requested.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path = requested.resolve(strict=False)
            self._initialize()
            if hasattr(os, "chmod"):
                os.chmod(self.path, 0o600)
        except (OSError, sqlite3.Error) as exc:
            raise SessionStoreError("Session database could not be initialized.") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    workspace TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    message_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_events_session
                    ON events(session_id, event_id);
                """
            )
            connection.commit()
        finally:
            connection.close()

    def create_session(
        self,
        *,
        workspace: str,
        model: str,
        session_id: str | None = None,
    ) -> str:
        identifier = session_id or str(uuid.uuid4())
        if not identifier.strip() or len(identifier) > 128:
            raise SessionStoreError("Session ID must be between 1 and 128 characters.")
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO sessions(session_id, workspace, model) VALUES (?, ?, ?)",
                (identifier, workspace, model),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise SessionStoreError("Session ID already exists or is invalid.") from exc
        finally:
            connection.close()
        return identifier

    def ensure_session(
        self,
        session_id: str,
        *,
        workspace: str,
        model: str,
    ) -> dict[str, Any]:
        metadata = self.get_session(session_id)
        if metadata is None:
            self.create_session(workspace=workspace, model=model, session_id=session_id)
            metadata = self.get_session(session_id)
        if metadata is None:
            raise SessionStoreError("Session could not be loaded after creation.")
        if metadata["workspace"] != workspace:
            raise SessionStoreError(
                "Session belongs to a different workspace; refusing cross-workspace resume."
            )
        return metadata

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT session_id, workspace, model, created_at, updated_at "
                "FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            connection.close()

    def append_message(self, session_id: str, message: dict[str, Any]) -> int:
        if not isinstance(message, dict):
            raise SessionStoreError("Session messages must be JSON objects.")
        try:
            encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise SessionStoreError("Session message is not JSON serializable.") from exc

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                "FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            sequence = int(row["next_sequence"])
            connection.execute(
                "INSERT INTO messages(session_id, sequence, message_json) VALUES (?, ?, ?)",
                (session_id, sequence, encoded),
            )
            connection.execute(
                "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,),
            )
            connection.commit()
            return sequence
        except sqlite3.Error as exc:
            connection.rollback()
            raise SessionStoreError("Session message could not be saved.") from exc
        finally:
            connection.close()

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT message_json FROM messages WHERE session_id = ? ORDER BY sequence",
                (session_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise SessionStoreError("Session messages could not be loaded.") from exc
        finally:
            connection.close()
        try:
            messages = [json.loads(row["message_json"]) for row in rows]
        except (TypeError, json.JSONDecodeError) as exc:
            raise SessionStoreError("Session contains an invalid serialized message.") from exc
        if not all(isinstance(item, dict) for item in messages):
            raise SessionStoreError("Session contains a message with an invalid shape.")
        return messages

    def append_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        if not event_type:
            raise SessionStoreError("Session event type must not be empty.")
        try:
            encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise SessionStoreError("Session event is not JSON serializable.") from exc
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO events(session_id, event_type, event_json) VALUES (?, ?, ?)",
                (session_id, event_type, encoded),
            )
            connection.execute(
                "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,),
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise SessionStoreError("Session event could not be saved.") from exc
        finally:
            connection.close()

    def load_events(self, session_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT event_type, event_json FROM events "
                "WHERE session_id = ? ORDER BY event_id",
                (session_id,),
            ).fetchall()
        finally:
            connection.close()
        try:
            return [
                {"type": row["event_type"], **json.loads(row["event_json"])}
                for row in rows
            ]
        except (TypeError, json.JSONDecodeError) as exc:
            raise SessionStoreError("Session contains an invalid serialized event.") from exc
