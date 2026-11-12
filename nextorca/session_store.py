from __future__ import annotations

# ruff: isort: off
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any
# ruff: isort: on


_SESSION_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"token|secret|password|passwd|authorization|private[_-]?key)"
    r"""(\s*[:=]\s*)(?:"[^"]*"|'[^']*'|(?:Bearer|Basic)\s+[^\s,;]+|[^\s,;]+)"""
)
_SESSION_BEARER_CREDENTIAL = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_SESSION_KNOWN_TOKEN = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})"
)
_SESSION_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----"
)


def _redact_session_text(value: str) -> str:
    """Mask common credential forms before session text is shown in terminal previews."""
    value = _SESSION_PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", value)
    value = _SESSION_SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        value,
    )
    value = _SESSION_BEARER_CREDENTIAL.sub(
        lambda match: f"{match.group(1)} [REDACTED]",
        value,
    )
    return _SESSION_KNOWN_TOKEN.sub("[REDACTED TOKEN]", value)


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


    def list_sessions(
        self,
        workspace: str,
        *,
        limit: int = 20,
        preview_chars: int = 160,
    ) -> list[dict[str, Any]]:
        """List recent sessions for one workspace without loading full transcripts."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("Session list limit must be between 1 and 100.")
        if (
            not isinstance(preview_chars, int)
            or isinstance(preview_chars, bool)
            or not 1 <= preview_chars <= 500
        ):
            raise ValueError("Session preview length must be between 1 and 500 characters.")

        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT s.session_id, s.model, s.created_at, s.updated_at,
                       COUNT(m.sequence) AS message_count
                FROM sessions AS s
                LEFT JOIN messages AS m ON m.session_id = s.session_id
                WHERE s.workspace = ?
                GROUP BY s.session_id
                ORDER BY s.updated_at DESC, s.created_at DESC, s.session_id DESC
                LIMIT ?
                """,
                (workspace, limit),
            ).fetchall()

            sessions: list[dict[str, Any]] = []
            for row in rows:
                latest_prompt: str | None = None
                recent_messages = connection.execute(
                    """
                    SELECT message_json
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY sequence DESC
                    LIMIT 32
                    """,
                    (row["session_id"],),
                ).fetchall()
                for message_row in recent_messages:
                    try:
                        message = json.loads(message_row["message_json"])
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise SessionStoreError(
                            "Session contains an invalid serialized message."
                        ) from exc
                    if (
                        isinstance(message, dict)
                        and message.get("role") == "user"
                        and isinstance(message.get("content"), str)
                    ):
                        latest_prompt = message["content"]
                        break

                sessions.append(
                    {
                        "session_id": row["session_id"],
                        "model": row["model"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "message_count": int(row["message_count"]),
                        "last_user_prompt": (
                            _redact_session_text(latest_prompt[:preview_chars]) if latest_prompt is not None else None
                        ),
                        "preview_truncated": (
                            latest_prompt is not None and len(latest_prompt) > preview_chars
                        ),
                    }
                )
            return sessions
        except sqlite3.Error as exc:
            raise SessionStoreError("Workspace sessions could not be listed.") from exc
        finally:
            connection.close()

    def search_sessions(
        self,
        workspace: str,
        query: str,
        *,
        limit: int = 20,
        scan_limit: int = 5_000,
        excerpt_chars: int = 240,
    ) -> list[dict[str, Any]]:
        """Search bounded user-authored text in sessions belonging to one workspace."""
        if not isinstance(query, str) or not query.strip() or len(query) > 256:
            raise ValueError("Session search query must contain 1 to 256 characters.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("Session search result limit must be between 1 and 100.")
        if (
            not isinstance(scan_limit, int)
            or isinstance(scan_limit, bool)
            or not 1 <= scan_limit <= 10_000
        ):
            raise ValueError("Session search scan limit must be between 1 and 10000.")
        if (
            not isinstance(excerpt_chars, int)
            or isinstance(excerpt_chars, bool)
            or not 40 <= excerpt_chars <= 1_000
        ):
            raise ValueError("Session search excerpt length must be between 40 and 1000 characters.")

        needle = query.strip().casefold()
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT s.session_id, m.sequence, m.created_at, m.message_json
                FROM sessions AS s
                JOIN messages AS m ON m.session_id = s.session_id
                WHERE s.workspace = ?
                ORDER BY s.updated_at DESC, m.sequence DESC
                LIMIT ?
                """,
                (workspace, scan_limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise SessionStoreError("Workspace session history could not be searched.") from exc
        finally:
            connection.close()

        matches: list[dict[str, Any]] = []
        for row in rows:
            try:
                message = json.loads(row["message_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise SessionStoreError("Session contains an invalid serialized message.") from exc
            if (
                not isinstance(message, dict)
                or message.get("role") != "user"
                or not isinstance(message.get("content"), str)
            ):
                continue

            content = message["content"]
            match_at = content.casefold().find(needle)
            if match_at < 0:
                continue
            start = max(0, match_at - excerpt_chars // 3)
            end = min(len(content), start + excerpt_chars)
            excerpt = content[start:end]
            if start:
                excerpt = "…" + excerpt
            if end < len(content):
                excerpt += "…"
            matches.append(
                {
                    "session_id": row["session_id"],
                    "sequence": int(row["sequence"]),
                    "created_at": row["created_at"],
                    "excerpt": _redact_session_text(excerpt),
                }
            )
            if len(matches) >= limit:
                break
        return matches

    def get_session_summary(
        self,
        session_id: str,
        *,
        workspace: str,
        preview_chars: int = 240,
    ) -> dict[str, Any] | None:
        """Return bounded metadata for one session only when it belongs to workspace."""
        if (
            not isinstance(preview_chars, int)
            or isinstance(preview_chars, bool)
            or not 1 <= preview_chars <= 500
        ):
            raise ValueError("Session preview length must be between 1 and 500 characters.")
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT session_id, workspace, model, created_at, updated_at
                FROM sessions
                WHERE session_id = ? AND workspace = ?
                """,
                (session_id, workspace),
            ).fetchone()
            if row is None:
                return None
            count_row = connection.execute(
                "SELECT COUNT(*) AS message_count FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            message_rows = connection.execute(
                """
                SELECT message_json
                FROM messages
                WHERE session_id = ?
                ORDER BY sequence DESC
                LIMIT 32
                """,
                (session_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise SessionStoreError("Session summary could not be loaded.") from exc
        finally:
            connection.close()

        latest_prompt: str | None = None
        for message_row in message_rows:
            try:
                message = json.loads(message_row["message_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise SessionStoreError("Session contains an invalid serialized message.") from exc
            if (
                isinstance(message, dict)
                and message.get("role") == "user"
                and isinstance(message.get("content"), str)
            ):
                latest_prompt = message["content"]
                break

        return {
            "session_id": row["session_id"],
            "model": row["model"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": int(count_row["message_count"]),
            "last_user_prompt": (
                _redact_session_text(latest_prompt[:preview_chars])
                if latest_prompt is not None
                else None
            ),
            "preview_truncated": (
                latest_prompt is not None and len(latest_prompt) > preview_chars
            ),
        }
