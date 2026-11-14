from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nextorca.codex_cli import DISABLED_CODEX_FEATURES, CodexCLIProvider
from nextorca.provider import ProviderError


def test_codex_cli_disables_workspace_tools_and_returns_structured_tool_proposals(tmp_path: Path):
    assert {"shell_tool", "unified_exec", "code_mode_host"}.issubset(DISABLED_CODEX_FEATURES)
    script = tmp_path / "fake_codex.py"
    script.write_text(
        """import json
import sys
from pathlib import Path

args = sys.argv[1:]
if args[0] != "exec" or args[-1] != "-":
    raise SystemExit(21)
def value(flag):
    return args[args.index(flag) + 1]
if value("--sandbox") != "read-only":
    raise SystemExit(22)
if value("--cd") != str(Path.cwd()):
    raise SystemExit(23)
if "--ephemeral" not in args or "--ignore-user-config" not in args or "--ignore-rules" not in args:
    raise SystemExit(24)
disabled = [args[index + 1] for index, item in enumerate(args[:-1]) if item == "--disable"]
if "shell_tool" not in disabled or "unified_exec" not in disabled or "code_mode_host" not in disabled:
    raise SystemExit(25)
schema = json.loads(Path(value("--output-schema")).read_text())
if "tool_calls" not in schema["properties"]:
    raise SystemExit(26)
request = json.loads(sys.stdin.read().split("NextOrca request JSON:\\n", 1)[1])
if request["system"] != "Follow project policy":
    raise SystemExit(27)
if request["tools"][0]["function"]["name"] != "Read":
    raise SystemExit(28)
Path(value("--output-last-message")).write_text(json.dumps({
    "content": "I will read it.",
    "tool_calls": [{"name": "Read", "arguments": {"file_path": "README.md"}}],
}))
""",
        encoding="utf-8",
    )
    provider = CodexCLIProvider(command=[sys.executable, str(script)])

    result = provider.complete(
        model="codex-test-model",
        messages=[
            {"role": "system", "content": "Follow project policy"},
            {"role": "user", "content": "Read README"},
        ],
        tools=[{"type": "function", "function": {"name": "Read", "parameters": {"type": "object"}}}],
    )

    assert result.content == "I will read it."
    assert result.tool_calls[0].name == "Read"
    assert result.tool_calls[0].arguments == {"file_path": "README.md"}


def test_codex_cli_rejects_missing_final_message_file(tmp_path: Path):
    script = tmp_path / "no_output.py"
    script.write_text("import sys\n", encoding="utf-8")
    provider = CodexCLIProvider(command=[sys.executable, str(script)])

    with pytest.raises(ProviderError, match="did not write"):
        provider.complete(model="codex-test-model", messages=[{"role": "user", "content": "hi"}], tools=[])
