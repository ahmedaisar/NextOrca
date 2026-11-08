from __future__ import annotations

from nextorca.skills import (
    build_skill_tool,
    discover_skills,
    format_skill_catalog,
    load_skill,
)
from nextorca.tool_registry import ToolRegistry


def _write_skill(root, folder, name, description, body):
    directory = root / folder / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return directory / "SKILL.md"


def test_discovers_project_and_user_skills_with_project_precedence(tmp_path):
    workspace = tmp_path / "project"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    project_file = _write_skill(workspace, ".agents/skills", "review", "Review code", "Project rules.")
    _write_skill(home / ".nextorca" / "skills", "", "review", "User review", "User rules.")
    _write_skill(home / ".nextorca" / "skills", "", "commit", "Write commits", "Commit rules.")

    skills, errors = discover_skills(workspace, home=home)

    assert [skill.name for skill in skills] == ["review", "commit"]
    assert skills[0].file_path == project_file.resolve()
    assert any("higher-priority" in error for error in errors)
    assert "review: Review code" in format_skill_catalog(skills)


def test_load_skill_returns_body_without_frontmatter(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    _write_skill(workspace, ".claude/skills", "pytest", "Run tests", "Run pytest before finishing.")

    skills, errors = discover_skills(workspace, home=tmp_path / "empty-home")

    assert not errors
    result = load_skill(skills[0])
    assert "Run pytest before finishing." in result
    assert "description: Run tests" not in result


def test_load_skill_tool_only_loads_requested_skill(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    _write_skill(workspace, ".nextorca/skills", "docs", "Write docs", "Keep docs concise.")
    skills, _ = discover_skills(workspace, home=tmp_path / "empty-home")
    registry = ToolRegistry()
    registry.register(build_skill_tool(skills))

    result = registry.execute("LoadSkill", {"skill_name": "docs"})

    assert "Keep docs concise." in result


def test_invalid_frontmatter_is_skipped_without_aborting_discovery(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    directory = workspace / ".agents" / "skills" / "broken"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("No frontmatter", encoding="utf-8")
    _write_skill(workspace, ".agents/skills", "good", "Valid", "Good skill.")

    skills, errors = discover_skills(workspace, home=tmp_path / "empty-home")

    assert [skill.name for skill in skills] == ["good"]
    assert any("frontmatter" in error for error in errors)


def test_skill_directory_symlink_is_not_followed(tmp_path):
    workspace = tmp_path / "project"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    _write_skill(outside, "", "escape", "Outside skill", "Do not load.")
    skills_root = workspace / ".agents" / "skills"
    skills_root.mkdir(parents=True)
    (skills_root / "escape").symlink_to(outside / "escape", target_is_directory=True)

    skills, errors = discover_skills(workspace, home=tmp_path / "empty-home")

    assert skills == []
    assert errors == []
