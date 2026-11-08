# Local Plugins

NextOrca plugins are declarative local bundles. A plugin can contribute Agent Skills and command-backed tools without importing or executing arbitrary Python modules.

## Locations

- Project: .nextorca/plugins/<plugin-id>/
- User: ~/.nextorca/plugins/<plugin-id>/

Project plugins take precedence over user plugins with the same ID. A plugin is discovered when its directory contains plugin.json. Remove the directory to uninstall it. Plugins are loaded automatically at startup.

## Manifest

The manifest uses schema version 1:

    {
      "schema_version": 1,
      "name": "git-helper",
      "description": "Small git workflow helpers.",
      "skills": ["skills"],
      "tools": [
        {
          "name": "status",
          "description": "Show the short git status.",
          "command": ["git", "status", "--short"],
          "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": false
          },
          "timeout_seconds": 30
        }
      ]
    }

The name must match the plugin directory. Skill paths must be relative directories inside the plugin and contain normal Agent Skills. Tool names use lowercase letters, digits and underscores. The command is an argv array; use a complete token such as "{branch}" to insert a declared scalar tool argument. Placeholder values remain one argv token and are never interpreted by a shell.

Each tool's parameter schema must be an object with additionalProperties false. Supported argument types are string, integer, number and boolean. Command timeouts are limited to 1–600 seconds. Manifests are limited to 64 KB.

## Permissions and trust

Every plugin command is treated as a mutation and asks for approval in interactive mode. The approval preview includes the plugin, tool, working directory, exact argv and timeout. A plugin command runs with the same OS permissions as the user; this is not a sandbox. Only install plugins you trust.

Plugins cannot add Python imports, change the core permission policy, approve their own calls, or override system instructions. Plugin tools use the same registry validation and runtime permission path as built-in tools. One-shot mode remains read-only unless a suitable interactive approval policy is explicitly available.

## Install the example

    mkdir -p .nextorca/plugins
    cp -R examples/plugins/git-helper .nextorca/plugins/

Start NextOrca in the project. The plugin's git status tool and bundled skill become available. To remove it, delete .nextorca/plugins/git-helper.

## Troubleshooting

- A plugin is skipped: read the startup warning. Check the schema version, plugin ID/directory match, JSON syntax and relative skill paths.
- A plugin tool is not listed: check that the tool name is unique and that its command and object parameter schema are valid.
- A command is denied: approve the exact command in the terminal. In headless one-shot mode, mutating plugin tools are denied by the read-only policy.
