import pytest

from scripts.agent_protocol import (
    ToolCallParseError,
    build_anthropic_content,
    openai_to_anthropic_response,
    parse_tool_calls,
)


def test_plain_text_is_preserved():
    assert parse_tool_calls("hello") == ("hello", [])


def test_valid_tool_call_is_converted():
    rest, calls = parse_tool_calls(
        'Before <tool_call>{"name":"Read","arguments":{"path":"a"}}</tool_call> After'
    )
    assert rest == "Before  After"
    assert calls[0]["name"] == "Read"
    assert calls[0]["input"] == {"path": "a"}
    assert calls[0]["type"] == "tool_use"


def test_malformed_json_is_not_silently_dropped():
    with pytest.raises(ToolCallParseError, match="Malformed JSON"):
        parse_tool_calls("<tool_call>{broken}</tool_call>")


@pytest.mark.parametrize(
    "payload",
    ["[]", '{"arguments":{}}', '{"name":"Read","arguments":"bad"}'],
)
def test_invalid_tool_call_envelope_is_rejected(payload):
    with pytest.raises(ToolCallParseError):
        parse_tool_calls(f"<tool_call>{payload}</tool_call>")


def test_content_stop_reason_reflects_tool_call():
    content, reason = build_anthropic_content(
        '<tool_call>{"name":"Grep","arguments":{"pattern":"TODO"}}</tool_call>'
    )
    assert content[0]["type"] == "tool_use"
    assert reason == "tool_use"


def test_local_response_preserves_usage_and_model():
    result = openai_to_anthropic_response({
        "model": "local-test",
        "choices": [{"message": {"content": "Done"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5},
    })
    assert result["model"] == "local-test"
    assert result["content"] == [{"type": "text", "text": "Done"}]
    assert result["usage"] == {"input_tokens": 12, "output_tokens": 5}


def test_missing_provider_choice_is_rejected():
    with pytest.raises(ValueError, match="missing choices"):
        openai_to_anthropic_response({})
