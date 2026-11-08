from __future__ import annotations

import json

from nextorca.plugins import build_plugin_tools, discover_plugins
from nextorca.skills import discover_skills
from nextorca.tool_registry import ToolRegistry
from nextorca.workspace import Workspace


def _plugin(root, name, *, command=None, skills=None):
    directory = root / name
    directory.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "name": name,
        "description": "A local test plugin.",
        "skills": skills or [],
        "tools": [
            {
                "name": "say",
                "description": "Print a supplied message.",
                "command": command or ["python", "-c", "print('plugin-ready')"],
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                "timeout_seconds": 5,
            }
        ],
    }
    (directory / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_discovers_project_plugins_before_user_plugins(tmp_path):
    workspace = tmp_path / "project"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    project_root = workspace / ".nextorca" / "plugins"
    project_root.mkdir(parents=True)
    user_root = home / ".nextorca" / "plugins"
    user_root.mkdir(parents=True)
    _plugin(project_root, "formatter")
    _plugin(user_root, "formatter")
    _plugin(user_root, "git-tools")

    plugins, errors = discover_plugins(workspace, home=home)

    assert [plugin.name for plugin in plugins] == ["formatter", "git-tools"]
    assert plugins[0].root == (project_root / "formatter").resolve()
    assert any("higher-priority" in error for error in errors)


def test_plugin_command_is_prepared_as_argv_and_runs_in_workspace(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    plugin_root = workspace / ".nextorca" / "plugins"
    plugin_root.mkdir(parents=True)
    _plugin(plugin_root, "demo")

    plugins, errors = discover_plugins(workspace, home=tmp_path / "home")

    assert not errors
    tools = build_plugin_tools(plugins[0], Workspace(workspace))
    registry = ToolRegistry()
    registry.register(tools[0])
    prepared = registry.prepare(tools[0], {})

    assert prepared is not None
    assert "Plugin: demo" in prepared.preview
    assert "python -c" in prepared.preview
    assert "plugin-ready" in registry.execute_prepared(prepared)


def test_plugin_skill_paths_are_loaded_only_from_plugin_directory(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    plugin_root = workspace / ".nextorca" / "plugins"
    plugin_root.mkdir(parents=True)
    directory = _plugin(plugin_root, "with-skills", skills=["skills"])
    skill_dir = directory / "skills" / "workflow"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: workflow\ndescription: Plugin workflow\n---\n\nPlugin skill body.",
        encoding="utf-8",
    )

    plugins, errors = discover_plugins(workspace, home=tmp_path / "home")

    assert not errors
    assert plugins[0].skill_roots == ((directory / "skills").resolve(),)


def test_invalid_plugin_manifest_fails_closed(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    root = workspace / ".nextorca" / "plugins" / "bad"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"schema_version": 99, "name": "bad", "description": "bad"}),
        encoding="utf-8",
    )

    plugins, errors = discover_plugins(workspace, home=tmp_path / "home")

    assert plugins == []
    assert any("schema_version" in error for error in errors)


def test_plugin_tool_command_placeholders_are_single_argv_values(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    root = workspace / ".nextorca" / "plugins"
    root.mkdir(parents=True)
    directory = _plugin(root, "argument")
    manifest_path = directory / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tools"][0]["command"] = ["python", "-c", "import sys; print(sys.argv[1])", "{value}"]
    manifest["tools"][0]["parameters"] = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    plugins, errors = discover_plugins(workspace, home=tmp_path / "home")
    assert not errors
    tool = build_plugin_tools(plugins[0], Workspace(workspace))[0]
    registry = ToolRegistry()
    registry.register(tool)
    prepared = registry.prepare(tool, {"value": "two words; no shell"})
    assert prepared is not None
    assert "two words; no shell" in prepared.preview
    assert "two words; no shell" in registry.execute_prepared(prepared)

def test_plugin_skills_join_the_agent_skill_catalog(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    plugin_root = workspace / ".nextorca" / "plugins"
    plugin_root.mkdir(parents=True)
    directory = _plugin(plugin_root, "skill-pack", skills=["skills"])
    skill_dir = directory / "skills" / "workflow"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: workflow\ndescription: Plugin workflow\n---\n\nUse the plugin workflow.",
        encoding="utf-8",
    )

    plugins, _ = discover_plugins(workspace, home=tmp_path / "home")
    skills, errors = discover_skills(
        workspace,
        home=tmp_path / "home",
        extra_roots=list(plugins[0].skill_roots),
    )

    assert not errors
    assert [skill.name for skill in skills] == ["workflow"]
