from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any


class SessionStoreError(RuntimeError):
    """A persistent session could not be created, loaded or updated."""


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|secret|password|passwd|authorization)"
    r"\s*[:=]\s*(?:bearer\s+)?(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_SECRET_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
)


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
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    workspace TEXT NOT NULL,
                    path TEXT NOT NULL,
                    before_exists INTEGER NOT NULL,
                    before_content TEXT NOT NULL,
                    after_content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    undone_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_checkpoints_workspace
                    ON checkpoints(workspace, created_at);
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


    def create_checkpoint(
        self,
        *,
        workspace: str,
        path: str,
        before_exists: bool,
        before_content: str,
        after_content: str,
    ) -> str:
        if len(before_content.encode("utf-8")) > 512_000 or len(after_content.encode("utf-8")) > 512_000:
            raise SessionStoreError("Checkpoint content exceeds the 512 KB limit.")
        checkpoint_id = str(uuid.uuid4())
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO checkpoints(
                    checkpoint_id, workspace, path, before_exists,
                    before_content, after_content
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    workspace,
                    path,
                    1 if before_exists else 0,
                    before_content,
                    after_content,
                ),
            )
            connection.commit()
            return checkpoint_id
        except sqlite3.Error as exc:
            connection.rollback()
            raise SessionStoreError("Workspace checkpoint could not be saved.") from exc
        finally:
            connection.close()

    def get_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT checkpoint_id, workspace, path, before_exists,
                       before_content, after_content, created_at, undone_at
                FROM checkpoints WHERE checkpoint_id = ?
                """,
                (checkpoint_id,),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            connection.close()

    def list_checkpoints(self, workspace: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT checkpoint_id, path, created_at, undone_at
                FROM checkpoints WHERE workspace = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (workspace,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def mark_checkpoint_undone(self, checkpoint_id: str) -> None:
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE checkpoints SET undone_at = CURRENT_TIMESTAMP
                WHERE checkpoint_id = ? AND undone_at IS NULL
                """,
                (checkpoint_id,),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise SessionStoreError("Checkpoint does not exist or has already been undone.")
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise SessionStoreError("Checkpoint status could not be updated.") from exc
        finally:
            connection.close()


    def metrics_summary(
        self,
        *,
        workspace: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate local model metrics without sending telemetry off-device."""
        filters = ["e.event_type = ?"]
        parameters: list[Any] = ["model_metrics"]
        if workspace is not None:
            filters.append("s.workspace = ?")
            parameters.append(workspace)
        if session_id is not None:
            filters.append("s.session_id = ?")
            parameters.append(session_id)
        query = (
            "SELECT s.session_id, e.event_json FROM events e "
            "JOIN sessions s ON s.session_id = e.session_id "
            "WHERE " + " AND ".join(filters) + " ORDER BY e.event_id"
        )

        connection = self._connect()
        try:
            rows = connection.execute(query, parameters).fetchall()
        except sqlite3.Error as exc:
            raise SessionStoreError("Model metrics could not be loaded.") from exc
        finally:
            connection.close()

        summary: dict[str, Any] = {
            "request_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_latency_ms": 0.0,
            "average_latency_ms": 0.0,
            "fallback_count": 0,
            "sessions": 0,
            "by_provider": {},
            "by_task": {},
        }
        session_ids: set[str] = set()
        for row in rows:
            try:
                metrics = json.loads(row["event_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise SessionStoreError("Stored model metrics are invalid JSON.") from exc
            if not isinstance(metrics, dict):
                raise SessionStoreError("Stored model metrics have an invalid shape.")

            summary["request_count"] += 1
            session_ids.add(row["session_id"])
            if metrics.get("status") == "success":
                summary["success_count"] += 1
            else:
                summary["failure_count"] += 1
            summary["input_tokens"] += max(0, int(metrics.get("input_tokens", 0) or 0))
            summary["output_tokens"] += max(0, int(metrics.get("output_tokens", 0) or 0))
            latency = max(0.0, float(metrics.get("latency_ms", 0.0) or 0.0))
            summary["total_latency_ms"] += latency

            provider = str(metrics.get("provider", "unknown"))
            provider_summary = summary["by_provider"].setdefault(
                provider,
                {"requests": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0.0},
            )
            provider_summary["requests"] += 1
            provider_summary["input_tokens"] += max(0, int(metrics.get("input_tokens", 0) or 0))
            provider_summary["output_tokens"] += max(0, int(metrics.get("output_tokens", 0) or 0))
            provider_summary["latency_ms"] += latency

            task = metrics.get("task")
            if task:
                summary["by_task"][str(task)] = summary["by_task"].get(str(task), 0) + 1
            route = metrics.get("route")
            if isinstance(route, dict) and route.get("fallback_from"):
                summary["fallback_count"] += 1

        summary["sessions"] = len(session_ids)
        if summary["request_count"]:
            summary["average_latency_ms"] = round(
                summary["total_latency_ms"] / summary["request_count"], 2
            )
        summary["total_latency_ms"] = round(summary["total_latency_ms"], 2)
        for provider_summary in summary["by_provider"].values():
            provider_summary["latency_ms"] = round(provider_summary["latency_ms"], 2)
        return summary

    @staticmethod
    def _validate_session_limit(limit: int, *, maximum: int) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= maximum:
            raise SessionStoreError(f"Session result limit must be between 1 and {maximum}.")
        return limit

    @staticmethod
    def _session_overview_from_row(row: sqlite3.Row) -> dict[str, Any]:
        preview = SQLiteSessionStore._redact_session_text(row["preview"] or "")
        if len(preview) > 160:
            preview = preview[:157] + "..."
        return {
            "session_id": row["session_id"],
            "workspace": row["workspace"],
            "model": row["model"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": int(row["message_count"]),
            "preview": preview,
        }

    def list_sessions(self, workspace: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """List recent sessions and bounded latest-user-prompt previews for one workspace."""
        self._validate_session_limit(limit, maximum=100)
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT
                    s.session_id,
                    s.workspace,
                    s.model,
                    s.created_at,
                    s.updated_at,
                    COUNT(m.sequence) AS message_count,
                    (
                        SELECT json_extract(latest.message_json, '$.content')
                        FROM messages AS latest
                        WHERE latest.session_id = s.session_id
                          AND json_extract(latest.message_json, '$.role') = 'user'
                          AND json_type(latest.message_json, '$.content') = 'text'
                        ORDER BY latest.sequence DESC
                        LIMIT 1
                    ) AS preview
                FROM sessions AS s
                LEFT JOIN messages AS m ON m.session_id = s.session_id
                WHERE s.workspace = ?
                GROUP BY s.session_id
                ORDER BY s.updated_at DESC, s.rowid DESC
                LIMIT ?
                """,
                (workspace, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise SessionStoreError("Workspace sessions could not be listed.") from exc
        finally:
            connection.close()
        return [self._session_overview_from_row(row) for row in rows]


    @staticmethod
    def _redact_session_text(value: str) -> str:
        """Keep previews readable while masking common credentials and terminal controls."""
        printable = "".join(character if character.isprintable() else " " for character in value)
        printable = _SECRET_ASSIGNMENT.sub(r"\1=[REDACTED]", printable)
        return _SECRET_TOKEN.sub("[REDACTED]", printable)


    def get_session_overview(
        self,
        session_id: str,
        *,
        workspace: str,
    ) -> dict[str, Any] | None:
        """Return bounded session metadata only when it belongs to the requested workspace."""
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT
                    s.session_id,
                    s.workspace,
                    s.model,
                    s.created_at,
                    s.updated_at,
                    COUNT(m.sequence) AS message_count,
                    (
                        SELECT json_extract(latest.message_json, '$.content')
                        FROM messages AS latest
                        WHERE latest.session_id = s.session_id
                          AND json_extract(latest.message_json, '$.role') = 'user'
                          AND json_type(latest.message_json, '$.content') = 'text'
                        ORDER BY latest.sequence DESC
                        LIMIT 1
                    ) AS preview
                FROM sessions AS s
                LEFT JOIN messages AS m ON m.session_id = s.session_id
                WHERE s.session_id = ? AND s.workspace = ?
                GROUP BY s.session_id
                """,
                (session_id, workspace),
            ).fetchone()
        except sqlite3.Error as exc:
            raise SessionStoreError("Session summary could not be loaded.") from exc
        finally:
            connection.close()
        return self._session_overview_from_row(row) if row is not None else None

    def search_sessions(
        self,
        workspace: str,
        query: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search literal user-message text within one workspace, returning bounded excerpts."""
        self._validate_session_limit(limit, maximum=50)
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise SessionStoreError("Session search query must contain 1–500 characters.")
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT
                    m.session_id,
                    m.sequence,
                    m.created_at,
                    instr(json_extract(m.message_json, '$.content'), ?) AS match_index,
                    substr(
                        json_extract(m.message_json, '$.content'),
                        max(1, instr(json_extract(m.message_json, '$.content'), ?) - 80),
                        200
                    ) AS excerpt
                FROM messages AS m
                INNER JOIN sessions AS s ON s.session_id = m.session_id
                WHERE s.workspace = ?
                  AND json_extract(m.message_json, '$.role') = 'user'
                  AND json_type(m.message_json, '$.content') = 'text'
                  AND instr(json_extract(m.message_json, '$.content'), ?) > 0
                ORDER BY m.created_at DESC, m.rowid DESC
                LIMIT ?
                """,
                (query, query, workspace, query, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise SessionStoreError("Session history search failed.") from exc
        finally:
            connection.close()

        results: list[dict[str, Any]] = []
        for row in rows:
            excerpt = self._redact_session_text(row["excerpt"] or "")
            match_index = int(row["match_index"])
            if match_index > 81:
                excerpt = "..." + excerpt
            if len(excerpt) >= 200:
                excerpt = excerpt[:197] + "..."
            results.append(
                {
                    "session_id": row["session_id"],
                    "sequence": int(row["sequence"]),
                    "created_at": row["created_at"],
                    "excerpt": excerpt,
                }
            )
        return results
