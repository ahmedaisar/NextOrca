import json
import re
import uuid

import pytest


def parse_tool_calls(text: str):
    calls = []
    pattern = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)

    def replace(match):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ValueError("Malformed JSON tool call") from exc
        if not isinstance(payload, dict):
            raise ValueError("Tool call must be an object")
        name = payload.get("name")
        args = payload.get("arguments", payload.get("input", {}))
        if not isinstance(name, str) or not name.strip() or not isinstance(args, dict):
            raise ValueError("Invalid tool call name or arguments")
        calls.append(
            {
                "type": "tool_use",
                "id": f"toolu_{uuid.uuid4().hex[:24]}",
                "name": name,
                "input": args,
            }
        )
        return ""

    return pattern.sub(replace, text).strip(), calls


def test_plain_text():
    assert parse_tool_calls("hello") == ("hello", [])


def test_valid_call():
    rest, calls = parse_tool_calls(
        '<tool_call>{"name":"Read","arguments":{"path":"a"}}</tool_call>'
    )
    assert rest == ""
    assert calls[0]["name"] == "Read"
    assert calls[0]["input"] == {"path": "a"}


def test_malformed_call_is_not_silently_dropped():
    with pytest.raises(ValueError, match="Malformed"):
        parse_tool_calls("<tool_call>{broken}</tool_call>")


@pytest.mark.parametrize(
    "payload",
    ["[]", '{"arguments":{}}', '{"name":"Read","arguments":"bad"}'],
)
def test_invalid_envelope(payload):
    with pytest.raises(ValueError):
        parse_tool_calls(f"<tool_call>{payload}</tool_call>")
