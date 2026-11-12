from __future__ import annotations

import pytest

from nextorca.mcp_stdio import _validate_remote_arguments
from nextorca.tool_registry import ToolExecutionError


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite_number_arguments(value):
    schema = {
        "type": "object",
        "properties": {"amount": {"type": "number", "minimum": 0, "maximum": 10}},
        "required": ["amount"],
    }

    with pytest.raises(ToolExecutionError, match="finite number"):
        _validate_remote_arguments(schema, {"amount": value}, tool_name="numbers")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite_numbers_nested_in_arrays(value):
    schema = {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "properties": {
                    "values": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["values"],
            },
        },
        "required": ["payload"],
    }

    with pytest.raises(ToolExecutionError, match="finite number"):
        _validate_remote_arguments(
            schema,
            {"payload": {"values": [1.0, value]}},
            tool_name="nested-numbers",
        )


@pytest.mark.parametrize("value", [0, 1.5, 10, 10**400])
def test_accepts_finite_numbers_at_and_within_schema_bounds(value):
    schema = {
        "type": "object",
        "properties": {
            "amount": {"type": "number", "minimum": 0, "maximum": 10**400},
        },
        "required": ["amount"],
    }

    _validate_remote_arguments(schema, {"amount": value}, tool_name="numbers")


@pytest.mark.parametrize(
    ("value", "message"),
    [(-0.1, "below its minimum"), (10.1, "exceeds its maximum")],
)
def test_finite_numbers_still_obey_schema_bounds(value, message):
    schema = {
        "type": "object",
        "properties": {"amount": {"type": "number", "minimum": 0, "maximum": 10}},
        "required": ["amount"],
    }

    with pytest.raises(ToolExecutionError, match=message):
        _validate_remote_arguments(schema, {"amount": value}, tool_name="numbers")


def test_boolean_is_not_accepted_as_a_number():
    schema = {
        "type": "object",
        "properties": {"amount": {"type": "number"}},
        "required": ["amount"],
    }

    with pytest.raises(ToolExecutionError, match="must be number"):
        _validate_remote_arguments(schema, {"amount": True}, tool_name="numbers")
