from __future__ import annotations

from nextorca.context import ContextBudget, ContextLimitError


def test_context_budget_prunes_old_tool_output_but_keeps_recent_messages():
    messages = [
        {"role": "system", "content": "Keep the system policy."},
        {"role": "tool", "tool_call_id": "old-1", "content": "x" * 5_000},
        {"role": "assistant", "content": "Old summary."},
        {"role": "user", "content": "Current user request."},
        {"role": "assistant", "content": "Latest response."},
    ]
    original = messages[1]["content"]
    budget = ContextBudget(max_chars=1_500, preserve_recent_messages=2)

    compacted, report = budget.fit(messages)

    assert report.original_chars > report.final_chars
    assert report.pruned_messages == 1
    assert report.final_chars <= 1_500
    assert compacted[1]["content"].startswith("[Earlier tool output omitted")
    assert compacted[3]["content"] == "Current user request."
    assert messages[1]["content"] == original


def test_context_budget_raises_instead_of_dropping_required_user_prompt():
    messages = [
        {"role": "system", "content": "System policy."},
        {"role": "user", "content": "Important request " * 200},
    ]
    budget = ContextBudget(max_chars=1_024)
    try:
        budget.fit(messages)
    except ContextLimitError as exc:
        assert "Reduce the prompt" in str(exc)
    else:
        raise AssertionError("Expected a context budget error.")


def test_context_budget_leaves_small_conversations_unchanged():
    messages = [{"role": "user", "content": "hello"}]
    compacted, report = ContextBudget().fit(messages)
    assert compacted == messages
    assert report.pruned_messages == 0
