import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "proxy_security.py"
SPEC = importlib.util.spec_from_file_location("proxy_security", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("authorization", "api_key", "expected", "result"),
    [
        ("Bearer local-secret", "", "local-secret", True),
        ("", "local-secret", "local-secret", True),
        ("Bearer wrong", "local-secret", "local-secret", False),
        ("", "", "local-secret", False),
        ("Bearer local-secret", "", "", False),
    ],
)
def test_authorization(authorization, api_key, expected, result):
    assert MODULE.authorization_matches(authorization, api_key, expected) is result


def test_content_length_valid():
    assert MODULE.parse_content_length("1024", 2048) == 1024


@pytest.mark.parametrize(
    ("value", "limit", "status"),
    [
        (None, 100, 411),
        ("not-a-number", 100, 411),
        ("0", 100, 400),
        ("-1", 100, 400),
        ("101", 100, 413),
    ],
)
def test_content_length_rejected(value, limit, status):
    with pytest.raises(MODULE.RequestValidationError) as caught:
        MODULE.parse_content_length(value, limit)
    assert caught.value.status_code == status
