# Agent Skills

NextOrca supports the open Agent Skills folder convention. A skill is a directory containing a SKILL.md file with YAML frontmatter and instruction text.

## Discovery order

NextOrca scans these directories, in order:

1. <project>/.agents/skills/
2. <project>/.claude/skills/
3. <project>/.nextorca/skills/
4. ~/.nextorca/skills/

Each child directory may contain one SKILL.md. The declared skill name must match the directory name. If two skills share a name, the first discovered copy wins and a warning identifies the ignored copy.

## Frontmatter

The current parser supports simple scalar name and description fields:

    ---
    name: test-first
    description: Run focused tests before and after code changes.
    ---

The name must be lowercase and use letters, digits, dots, underscores or hyphens. The description is required and limited to 1024 characters. Skill files are limited to 64 KB. Keep frontmatter values on one line.

## Activation

The agent sees the skill name and description at session start. When a skill matches the task, it calls LoadSkill with the exact name. NextOrca then loads the instruction body into the conversation. This keeps unrelated skill bodies out of the model context.

Skills are trusted as project/user-authored guidance, but their contents are still untrusted input. They cannot change NextOrca's core instructions, grant tools, or bypass shell/file/MCP approval.

## Example

Copy examples/skills/test-first into your project:

    mkdir -p .agents/skills
    cp -R examples/skills/test-first .agents/skills/

Then start NextOrca in that project. Ask it to implement a change and it can select the test-first skill when relevant.

## Troubleshooting

- A skill is not listed: check the folder path and that the file is named exactly SKILL.md.
- A skill is skipped: read the startup warning; common causes are malformed frontmatter, a mismatched folder/name, a symlink or a file over 64 KB.
- A skill body is not loaded: ask the agent to use the skill by name or describe the task the skill covers.
