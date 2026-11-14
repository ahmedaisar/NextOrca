from __future__ import annotations

import sys
from pathlib import Path

from nextorca.claude_code_cli import ClaudeCodeCLIProvider


def test_claude_code_cli_uses_no_tools_and_parses_structured_output(tmp_path: Path):
    script = tmp_path / "fake_claude.py"
    script.write_text(
        """import json
import sys

args = sys.argv[1:]
required = [
    "--print", "--output-format", "json", "--json-schema", "--model", "claude-test",
    "--max-turns", "1", "--no-session-persistence", "--restricted", "--tools", "",
    "--strict-mcp-config", "--setting-sources", "", "--permission-mode", "plan",
    "--system-prompt",
]
if any(item not in args for item in required):
    raise SystemExit(21)
request = json.loads(sys.stdin.read().split("NextOrca request JSON:\\n", 1)[1])
if request["system"] != "Follow project policy":
    raise SystemExit(22)
if request["tools"][0]["function"]["name"] != "Read":
    raise SystemExit(23)
print(json.dumps({
    "structured_output": {
        "content": "I will read it.",
        "tool_calls": [{"name": "Read", "arguments": {"file_path": "README.md"}}],
    },
    "usage": {"input_tokens": 20, "output_tokens": 6},
}))
""",
        encoding="utf-8",
    )
    provider = ClaudeCodeCLIProvider(command=[sys.executable, str(script)])

    result = provider.complete(
        model="claude-test",
        messages=[
            {"role": "system", "content": "Follow project policy"},
            {"role": "user", "content": "Read README"},
        ],
        tools=[{"type": "function", "function": {"name": "Read", "parameters": {"type": "object"}}}],
    )

    assert result.content == "I will read it."
    assert result.tool_calls[0].name == "Read"
    assert result.tool_calls[0].arguments == {"file_path": "README.md"}
    assert result.usage == {"input_tokens": 20, "output_tokens": 6}
