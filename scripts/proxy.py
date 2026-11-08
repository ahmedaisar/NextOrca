#!/usr/bin/env python3
"""Hybrid Anthropic-compatible proxy with local-model routing and cloud fallback.

Local inference is intentionally non-streaming for now. Requests requiring streaming
are transparently escalated to the configured remote provider until a native local
Anthropic SSE adapter is available.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from agent_protocol import (
    ToolCallParseError,
    openai_to_anthropic_response,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

LLAMA_SERVER = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080").rstrip("/")
OPENROUTER_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api").rstrip("/")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.environ.get("NEXTORCA_PROXY_PORT", "9091"))
LOCAL_MODELS = {"claude-haiku-4-5-20251001"}
REMOTE_FALLBACK_MODEL = os.environ.get("NEXTORCA_REMOTE_MODEL", "qwen/qwen3-coder-next")
MAX_LOCAL_TURNS = int(os.environ.get("NEXTORCA_MAX_LOCAL_TURNS", "10"))
MAX_REQUEST_BYTES = int(os.environ.get("NEXTORCA_MAX_REQUEST_BYTES", str(2 * 1024 * 1024)))
MAX_CONCURRENT_REQUESTS = int(os.environ.get("NEXTORCA_MAX_CONCURRENT_REQUESTS", "4"))
REQUEST_TIMEOUT = float(os.environ.get("NEXTORCA_REQUEST_TIMEOUT_SECONDS", "300"))

TOKEN_FILE = PROJECT_ROOT / ".claude" / "proxy-token"
try:
    PROXY_TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip()
except OSError:
    PROXY_TOKEN = ""

if MAX_REQUEST_BYTES <= 0 or MAX_CONCURRENT_REQUESTS <= 0 or MAX_LOCAL_TURNS <= 0:
    raise ValueError("Proxy request, concurrency and turn limits must be positive.")

_local_client = httpx.Client(
    timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0),
    trust_env=False,
)
_remote_client = httpx.Client(
    timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0),
    trust_env=True,
)
_request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

TRAINING_SYSTEM_PROMPT = """You are a read-only codebase exploration specialist.
Use Read, Glob, and Grep for repository discovery. Avoid destructive commands.
For each tool call, emit a JSON object inside <tool_call></tool_call> tags:
<tool_call>
{"name": "<tool-name>", "arguments": {}}
</tool_call>
Tool results are provided inside <tool_response></tool_response> tags."""


def convert_anthropic_to_openai(body: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": TRAINING_SYSTEM_PROMPT}
    ]
    for message in body.get("messages", []):
        role = message.get("role")
        content = message.get("content", "")
        if role not in {"user", "assistant"}:
            continue
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue

        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                parts.append(str(block.get("text", "")))
            elif block_type == "tool_use":
                payload = {
                    "name": block.get("name", ""),
                    "arguments": block.get("input", {}),
                }
                parts.append(f"<tool_call>\n{json.dumps(payload)}\n</tool_call>")
            elif block_type == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, list):
                    result_content = " ".join(
                        str(part.get("text", ""))
                        for part in result_content
                        if isinstance(part, dict) and part.get("type") == "text"
                    )
                parts.append(f"<tool_response>\n{result_content}\n</tool_response>")
        messages.append({"role": role, "content": "\n".join(parts)})

    return {
        "model": "loco-operator-4b",
        "messages": messages,
        "max_tokens": min(int(body.get("max_tokens", 4096)), 8192),
        "temperature": float(body.get("temperature", 0.0)),
        "stream": False,
    }


def _json_error(
    handler: BaseHTTPRequestHandler,
    status: int,
    message: str,
    extra_headers: dict[str, str] | None = None,
) -> None:
    payload = json.dumps(
        {"type": "error", "error": {"type": "proxy_error", "message": message}}
    ).encode()
    handler.close_connection = True
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    for name, value in (extra_headers or {}).items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(payload)


def _forward_headers(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_KEY}",
    }
    # Never forward the local proxy token or a caller-supplied credential upstream.
    for name in ("anthropic-version", "anthropic-beta"):
        value = handler.headers.get(name)
        if value:
            headers[name] = value
    return headers


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "NextOrcaProxy/0.2"
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(30.0)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[proxy] {format % args}")

    def do_GET(self) -> None:
        if self.path in ("/health", "/healthz"):
            payload = json.dumps(
                {
                    "status": "ok",
                    "local_ready": bool(LLAMA_SERVER),
                    "remote_configured": bool(OPENROUTER_KEY),
                    "proxy_auth_configured": bool(PROXY_TOKEN),
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        _json_error(self, 404, "Not found")

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/v1/messages":
            _json_error(self, 404, "Not found")
            return
        if not PROXY_TOKEN:
            _json_error(self, 503, "Local proxy authentication is not configured; run setup.")
            return

        authorization = self.headers.get("Authorization", "")
        scheme, separator, candidate = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator:
            candidate = self.headers.get("x-api-key", "")
        if not candidate or not hmac.compare_digest(candidate, PROXY_TOKEN):
            _json_error(self, 401, "Unauthorized")
            return

        if self.headers.get("Transfer-Encoding"):
            _json_error(self, 400, "Transfer-encoded requests are not supported.")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            _json_error(self, 411, "A valid Content-Length header is required.")
            return
        if length < 1:
            _json_error(self, 400, "Request body must not be empty.")
            return
        if length > MAX_REQUEST_BYTES:
            _json_error(self, 413, "Request body exceeds the configured size limit.")
            return
        if not _request_slots.acquire(blocking=False):
            _json_error(
                self, 503, "Proxy is busy; retry the request.",
                extra_headers={"Retry-After": "2"},
            )
            return

        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                _json_error(self, 400, "Incomplete request body.")
                return
            try:
                body = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                _json_error(self, 400, "Request body must be valid JSON.")
                return
            if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
                _json_error(self, 400, "Request must be a JSON object with a messages array.")
                return

            model = str(body.get("model", ""))
            messages = body["messages"]
            turn = sum(
                1 for message in messages
                if isinstance(message, dict) and message.get("role") == "assistant"
            )
            is_stream = bool(body.get("stream", False))
            use_local = model in LOCAL_MODELS and turn < MAX_LOCAL_TURNS and not is_stream
            print(
                f"[proxy] model={model} turn={turn} local={use_local} "
                f"stream={is_stream} messages={len(messages)}"
            )

            if use_local:
                self._handle_local(body, is_stream)
            else:
                if model in LOCAL_MODELS and (turn >= MAX_LOCAL_TURNS or is_stream):
                    reason = "local turn limit reached" if turn >= MAX_LOCAL_TURNS else "local streaming unavailable"
                    print(f"[proxy] escalating to remote: {reason}")
                    body = dict(body)
                    body["model"] = REMOTE_FALLBACK_MODEL
                    raw = json.dumps(body).encode()
                self._handle_remote(raw, is_stream)
        except (BrokenPipeError, ConnectionResetError):
            print("[proxy] client disconnected")
        except Exception as exc:
            print(f"[proxy] request failed: {type(exc).__name__}")
            if not self.wfile.closed:
                _json_error(self, 500, "Proxy request failed.")
        finally:
            _request_slots.release()

    def _handle_remote(self, raw: bytes, is_stream: bool) -> None:
        if not OPENROUTER_KEY:
            _json_error(self, 503, "Remote provider is not configured.")
            return
        url = f"{OPENROUTER_URL}/v1/messages"
        if is_stream:
            headers_sent = False
            try:
                with _remote_client.stream(
                    "POST", url, content=raw, headers=_forward_headers(self)
                ) as response:
                    self.send_response(response.status_code)
                    for name in ("content-type", "cache-control"):
                        value = response.headers.get(name)
                        if value:
                            self.send_header(name, value)
                    self.send_header("X-Accel-Buffering", "no")
                    self.send_header("Connection", "close")
                    self.close_connection = True
                    self.end_headers()
                    headers_sent = True
                    for chunk in response.iter_raw():
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()
            except httpx.TimeoutException:
                if headers_sent:
                    print("[proxy] remote stream timed out after response started")
                else:
                    _json_error(self, 504, "Remote provider request timed out.")
            except httpx.HTTPError:
                if headers_sent:
                    print("[proxy] remote stream failed after response started")
                else:
                    _json_error(self, 502, "Remote provider request failed.")
            return

        try:
            response = _remote_client.post(
                url, content=raw, headers=_forward_headers(self)
            )
            self.send_response(response.status_code)
            for name in ("content-type", "cache-control"):
                value = response.headers.get(name)
                if value:
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)
        except httpx.TimeoutException:
            _json_error(self, 504, "Remote provider request timed out.")
        except httpx.HTTPError:
            _json_error(self, 502, "Remote provider request failed.")

    def _handle_local(self, body: dict[str, Any], is_stream: bool) -> None:
        request_body = convert_anthropic_to_openai(body)
        try:
            response = _local_client.post(
                f"{LLAMA_SERVER}/v1/chat/completions",
                json=request_body,
            )
            response.raise_for_status()
            local_response = response.json()
            if "choices" not in local_response:
                error = local_response.get("error", {})
                if isinstance(error, dict) and error.get("type") == "exceed_context_size_error":
                    fallback = dict(body)
                    fallback["model"] = REMOTE_FALLBACK_MODEL
                    self._handle_remote(json.dumps(fallback).encode(), is_stream)
                    return
                raise ValueError("Local provider returned an invalid response.")

            converted = openai_to_anthropic_response(local_response)
            payload = json.dumps(converted).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except ToolCallParseError:
            _json_error(self, 502, "Local model returned an invalid tool-call envelope.")
        except httpx.TimeoutException:
            _json_error(self, 504, "Local model request timed out.")
        except httpx.HTTPError:
            _json_error(self, 502, "Local model request failed.")
        except (ValueError, KeyError, TypeError):
            _json_error(self, 502, "Local model returned an invalid response.")


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32


if __name__ == "__main__":
    if not PROXY_TOKEN:
        raise SystemExit("Local proxy token missing. Run scripts/setup.sh before starting the proxy.")
    if not OPENROUTER_KEY:
        print("WARNING: OPENROUTER_API_KEY not set; remote fallback is unavailable.")
    server = ProxyServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler)
    print(f"Proxy listening on http://{LISTEN_HOST}:{LISTEN_PORT}")
    print(f"Local: llama-server at {LLAMA_SERVER} (turns < {MAX_LOCAL_TURNS}, non-streaming)")
    print(f"Remote: OpenRouter {REMOTE_FALLBACK_MODEL}")
    server.serve_forever()
