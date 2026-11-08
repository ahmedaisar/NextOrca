from __future__ import annotations

import hmac


class RequestValidationError(ValueError):
    """A client request failed proxy size or framing validation."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def authorization_matches(
    authorization_header: str,
    api_key_header: str,
    expected_token: str,
) -> bool:
    """Validate a local bearer token (or legacy x-api-key) using constant-time compare."""
    if not expected_token:
        return False
    scheme, separator, candidate = authorization_header.partition(" ")
    if scheme.lower() == "bearer" and separator:
        presented = candidate.strip()
    else:
        presented = api_key_header.strip()
    return bool(presented) and hmac.compare_digest(presented, expected_token)


def parse_content_length(value: str | None, maximum_bytes: int) -> int:
    if value is None:
        raise RequestValidationError(411, "A valid Content-Length header is required.")
    try:
        length = int(value)
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(
            411, "A valid Content-Length header is required."
        ) from exc
    if length < 1:
        raise RequestValidationError(400, "Request body must not be empty.")
    if length > maximum_bytes:
        raise RequestValidationError(413, "Request body exceeds the configured size limit.")
    return length
