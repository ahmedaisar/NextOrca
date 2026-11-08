from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class ToolValidationError(ValueError):
    """Tool name or arguments do not match the registered contract."""


class ToolExecutionError(RuntimeError):
    """A registered tool failed during execution."""


ToolHandler = Callable[[dict[str, Any]], str]
PrepareHandler = Callable[[dict[str, Any]], "PreparedToolOperation"]


@dataclass(frozen=True)
class PreparedToolOperation:
    """A validated, previewable operation whose captured state is applied on approval."""

    preview: str
    execute: Callable[[], str]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    read_only: bool = True
    prepare_handler: PrepareHandler | None = None

    def as_provider_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _matches_schema_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return False


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Validate the small JSON Schema subset used by built-in and custom tools."""
    if schema.get("type") != "object":
        raise ToolValidationError("Tool parameter schema must describe an object.")
    if not isinstance(arguments, dict):
        raise ToolValidationError("Tool arguments must be a JSON object.")

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ToolValidationError("Tool parameter schema is invalid.")

    missing = [name for name in required if name not in arguments]
    if missing:
        raise ToolValidationError("Missing required arguments: " + ", ".join(missing))

    if schema.get("additionalProperties", False) is False:
        unknown = set(arguments) - set(properties)
        if unknown:
            raise ToolValidationError(
                "Unsupported arguments: " + ", ".join(sorted(str(x) for x in unknown))
            )

    for name, value in arguments.items():
        definition = properties.get(name)
        if definition is None:
            continue
        expected = definition.get("type")
        if isinstance(expected, list):
            valid = any(_matches_schema_type(value, item) for item in expected)
        else:
            valid = isinstance(expected, str) and _matches_schema_type(value, expected)
        if not valid:
            raise ToolValidationError(f"Argument '{name}' must have type {expected}.")
        if isinstance(value, str):
            if len(value) > int(definition.get("maxLength", 100_000)):
                raise ToolValidationError(f"Argument '{name}' is too long.")
            if "minLength" in definition and len(value) < int(definition["minLength"]):
                raise ToolValidationError(f"Argument '{name}' is too short.")
            if "enum" in definition and value not in definition["enum"]:
                raise ToolValidationError(f"Argument '{name}' has an unsupported value.")
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and "minimum" in definition
            and value < int(definition["minimum"])
        ):
            raise ToolValidationError(f"Argument '{name}' is below its minimum.")


class ToolRegistry:
    """Version-one tool registry with strict argument validation."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or not spec.name.replace("_", "").isalnum():
            raise ToolValidationError("Tool names must be non-empty alphanumeric identifiers.")
        if spec.name in self._tools:
            raise ToolValidationError(f"Tool '{spec.name}' is already registered.")
        self._tools[spec.name] = spec

    def unregister(self, name: str) -> None:
        """Remove a temporary tool from the registry if it exists."""
        self._tools.pop(name, None)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolValidationError(f"Tool '{name}' is not registered.") from exc

    def provider_tools(self) -> list[dict[str, Any]]:
        return [spec.as_provider_tool() for spec in self._tools.values()]

    @staticmethod
    def prepare(spec: ToolSpec, arguments: dict[str, Any]) -> PreparedToolOperation | None:
        validate_arguments(spec.parameters, arguments)
        if spec.prepare_handler is None:
            return None
        return spec.prepare_handler(arguments)

    @staticmethod
    def execute_prepared(prepared: PreparedToolOperation) -> str:
        try:
            result = prepared.execute()
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(
                f"Prepared tool operation failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(result, str):
            raise ToolExecutionError("Prepared tool operation returned a non-text result.")
        return result

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        spec = self.get(name)
        validate_arguments(spec.parameters, arguments)
        if spec.prepare_handler is not None:
            prepared = spec.prepare_handler(arguments)
            return self.execute_prepared(prepared)
        try:
            result = spec.handler(arguments)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"Tool '{name}' failed: {type(exc).__name__}") from exc
        if not isinstance(result, str):
            raise ToolExecutionError(f"Tool '{name}' returned a non-text result.")
        return result
