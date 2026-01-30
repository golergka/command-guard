---
name: command-guard
description: View and edit command-guard configuration
---

Opens or creates the command-guard configuration file at `.claude/command-guard.json`.

## Configuration Location

`.claude/command-guard.json` in your project root.

## Configuration Format

```json
{
  "rules": [
    {
      "match": "command",
      "pattern": "git\\s+reset\\s+--hard",
      "message": "git reset --hard destroys uncommitted changes. Use git stash first.",
      "severity": "error"
    },
    {
      "match": "file_path",
      "pattern": "patches/.*\\.patch$",
      "message": "Patch files should not be edited directly.",
      "severity": "error"
    },
    {
      "match": "tool_name",
      "pattern": "mcp__betterstack__",
      "message": "Consider using better-stack-logs agent instead.",
      "severity": "warning"
    }
  ],
  "safePatterns": ["git\\s+checkout\\s+-b\\s"]
}
```

## Rule Schema

| Field            | Required | Type                                          | Description                   |
| ---------------- | -------- | --------------------------------------------- | ----------------------------- |
| `match`          | Yes      | `"command"` \| `"file_path"` \| `"tool_name"` | What to match against         |
| `pattern`        | Yes      | string (regex)                                | Pattern to match              |
| `message`        | Yes      | string                                        | Message shown when triggered  |
| `severity`       | Yes      | `"error"` \| `"warning"`                      | error=block, warning=reminder |
| `case_sensitive` | No       | boolean                                       | Default: false                |

## Match Types

- **command**: Matches Bash command content (after splitting compound commands)
- **file_path**: Matches Edit/Write file paths
- **tool_name**: Matches tool name (useful for MCP tools)

## Severity Levels

- **error**: Blocks the tool use entirely (exit code 2)
- **warning**: Shows a reminder after tool completes (PostToolUse)

## Safe Patterns

The `safePatterns` array contains regex patterns that bypass blocking rules. Useful for allowing safe variants of otherwise dangerous commands.

## Override Mechanism

Any blocked command can be overridden by adding a comment:

```bash
git reset --hard  # OVERRIDE: cleaning up failed rebase state
```

The reason must be at least 5 characters.

## Instructions

When user invokes this skill:

1. Read `.claude/command-guard.json` if it exists
2. If it doesn't exist, create it with an empty rules array: `{"rules": [], "safePatterns": []}`
3. Show the current configuration to the user
4. Help them add, edit, or remove rules as requested
