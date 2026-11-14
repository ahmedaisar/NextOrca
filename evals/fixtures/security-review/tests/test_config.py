import ast
from pathlib import Path


def test_parser_uses_literal_eval_and_does_not_call_eval():
    source = Path("config.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "literal_eval" in source
    assert "eval" not in calls
