import pytest

from scripts.agent_protocol import (
    ToolCallParseError,
    build_anthropic_content,
    openai_to_anthropic_response,
    parse_tool_calls,
)


def test_parse_text_without_tool_call():
    assert parse_tool_calls("hello") == ("hello", [])


def test_parse_valid_tool_call():
    text = 'Before <tool_call>{"name":"Read","arguments":{"file_path":"a.py"}}</tool_call> After'
    remaining, calls = parse_tool_calls(text)
    assert remaining == "Before  After"
    assert calls[0]["type"] == "tool_use"
    assert calls[0]["name"] == "Read"
    assert calls[0]["input"] == {"file_path": "a.py"}
    assert calls[0]["id"].startswith("toolu_")


def test_parse_rejects_malformed_json():
    with pytest.raises(ToolCallParseError, match="Malformed JSON"):
        parse_tool_calls("<tool_call>{bad json}</tool_call>")


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        '{"arguments":{}}',
        '{"name":"Read","arguments":"not-an-object"}',
    ],
)
def test_parse_rejects_invalid_envelopes(payload):
    with pytest.raises(ToolCallParseError):
        parse_tool_calls(f"<tool_call>{payload}</tool_call>")


def test_build_anthropic_content_and_stop_reason():
    content, reason = build_anthropic_content(
        '<tool_call>{"name":"Grep","arguments":{"pattern":"TODO"}}</tool_call>'
    )
    assert reason == "tool_use"
    assert content[0]["type"] == "tool_use"


def test_openai_response_preserves_usage_and_text():
    result = openai_to_anthropic_response(
        {
            "model": "local-test",
            "choices": [{"message": {"content": "Done"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        }
    )
    assert result["model"] == "local-test"
    assert result["content"] == [{"type": "text", "text": "Done"}]
    assert result["usage"] == {"input_tokens": 12, "output_tokens": 5}


def test_openai_response_rejects_missing_choice():
    with pytest.raises(ValueError, match="missing choices"):
        openai_to_anthropic_response({})
