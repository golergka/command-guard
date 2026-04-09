# command-guard

Configurable guardrails for Claude Code - block commands, protect files, enforce workflows.

## Overview

`command-guard` is a Claude Code plugin that provides configurable guardrails for blocking or warning about tool usage. It ships with **no default rules** - all configuration comes from your project's config file.

## Installation

Add the GitHub repo as a plugin marketplace, then install:

```bash
claude plugin marketplace add golergka/command-guard
claude plugin install command-guard@golergka-command-guard
```

For local development/testing:

```bash
claude --plugin-dir /path/to/command-guard
```

## Plugins

This repository contains multiple independent plugins. Install only what you need:

| Plugin | Description | Install command |
| ------ | ----------- | --------------- |
| `command-guard` | Configurable rules to block or warn about tool usage | `claude plugin install command-guard@golergka-command-guard` |
| `commit-guard` | Prevents Claude from finishing with uncommitted changes | `claude plugin install commit-guard@golergka-command-guard` |

---

# command-guard

## Configuration

Create `.claude/command-guard.json` in your project root:

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
      "message": "Patch files should not be edited directly. Use pnpm patch workflow.",
      "severity": "error"
    },
    {
      "match": "tool_name",
      "pattern": "mcp__betterstack__",
      "message": "Consider using better-stack-logs agent for context isolation.",
      "severity": "warning"
    }
  ],
  "safePatterns": ["git\\s+checkout\\s+-b\\s"]
}
```

If no config file exists, all tool uses are allowed (empty rules = no blocking).

## Rule Schema

| Field            | Required | Type                                          | Description                   |
| ---------------- | -------- | --------------------------------------------- | ----------------------------- |
| `match`          | Yes      | `"command"` \| `"file_path"` \| `"tool_name"` | What to match against         |
| `pattern`        | Yes      | string (regex)                                | Pattern to match              |
| `message`        | Yes      | string                                        | Message shown when triggered  |
| `severity`       | Yes      | `"error"` \| `"warning"`                      | error=block, warning=reminder |
| `case_sensitive` | No       | boolean                                       | Default: false                |

## Match Types

### `command`

Matches against Bash command content. Commands are:

- Split on chain operators (`&&`, `||`, `;`, `|`)
- Normalized (absolute paths like `/usr/bin/git` become `git`)
- Stripped of quoted strings to avoid false positives

### `file_path`

Matches against file paths in Edit and Write tool calls.

### `tool_name`

Matches against the tool name. Useful for MCP tools like `mcp__betterstack__telemetry_query`.

## Severity Levels

### `error`

Blocks the tool use entirely. The user sees a block message and the tool doesn't execute.

```
BLOCKED: git reset --hard destroys all uncommitted changes permanently. Use 'git stash' first.

Context: git reset --hard HEAD~1

To override, add a comment: # OVERRIDE: <reason>
```

### `warning`

Shows a reminder after the tool completes (PostToolUse). Doesn't block execution.

## Safe Patterns

The `safePatterns` array contains regex patterns that bypass blocking rules. This is useful for allowing safe variants of otherwise dangerous commands:

```json
{
  "safePatterns": [
    "git\\s+checkout\\s+-b\\s",
    "git\\s+restore\\s+--staged",
    "git\\s+push\\s+--force-with-lease"
  ]
}
```

## Override Mechanism

Any blocked command can be overridden by adding a comment with explicit reasoning:

```bash
git reset --hard  # OVERRIDE: cleaning up failed rebase state
```

The reason must be at least 5 characters. Override usage is logged to stderr.

## Examples

### Block Destructive Git Commands

```json
{
  "rules": [
    {
      "match": "command",
      "pattern": "git\\s+reset\\s+--hard",
      "message": "git reset --hard destroys all uncommitted changes. Use 'git stash' first.",
      "severity": "error"
    },
    {
      "match": "command",
      "pattern": "git\\s+push\\s+(\\S+\\s+)*(-f|--force)(?!-with-lease)",
      "message": "git push --force overwrites remote history. Use --force-with-lease for safer force push.",
      "severity": "error"
    }
  ],
  "safePatterns": ["git\\s+push\\s+--force-with-lease"]
}
```

### Enforce Workflow Skills

```json
{
  "rules": [
    {
      "match": "command",
      "pattern": "^prettier\\s+(?!--help)",
      "message": "Use /automated-checks skill for formatting, linting, and type checking.",
      "severity": "error"
    },
    {
      "match": "command",
      "pattern": "git\\s+commit\\s+",
      "message": "Make sure you have used /git-commits skill for proper conventional commits.",
      "severity": "warning"
    }
  ]
}
```

### Protect Generated Files

```json
{
  "rules": [
    {
      "match": "file_path",
      "pattern": "(^|/)patches/.*\\.patch$",
      "message": "Patch files are generated by pnpm. Use pnpm patch workflow instead.",
      "severity": "error"
    },
    {
      "match": "file_path",
      "pattern": "supabase/migrations/",
      "message": "Migration files should be generated, not written directly.",
      "severity": "warning"
    }
  ]
}
```

### MCP Tool Reminders

```json
{
  "rules": [
    {
      "match": "tool_name",
      "pattern": "mcp__betterstack__",
      "message": "Consider using better-stack-logs agent for context isolation.",
      "severity": "warning"
    }
  ]
}
```

## Skill

The plugin includes a `/command-guard` skill for viewing and editing configuration. Use it to:

1. View current configuration
2. Add new rules
3. Edit existing rules
4. Add safe patterns

## How It Works

The plugin registers hooks for:

- **PreToolUse** (Bash, Edit, Write, MCP tools): Checks for `error` severity rules and blocks if matched
- **PostToolUse** (all tools): Checks for `warning` severity rules and shows reminders

---

# commit-guard

Prevents Claude from finishing a session with uncommitted changes. Uses a **Stop hook** — when Claude tries to end the conversation, the hook checks `git status` and blocks if there are uncommitted changes.

## Behavior

- If the working tree is dirty, Claude is re-prompted to commit before finishing
- Claude can acknowledge the situation by including `UNCOMMITTED_OK` in its message (e.g. when it only did research or the user told it not to commit)
- Does nothing outside of git repositories

## Development

### Setup

The repository includes `.claude/settings.json` which installs both plugins from the local directory for development:

```json
{
  "plugins": ["./", "./plugins/commit-guard/"]
}
```

### Running Tests

Tests use pytest and can be run without any Claude Code or LLM calls:

```bash
pytest tests/ -v
```

The tests cover:
- Unit tests for individual functions (rule matching, command parsing, etc.)
- Integration tests that run the script as a subprocess with sample configs

### Test Fixtures

Test fixtures are in `tests/fixtures/`. The `basic_rules.json` file contains sample rules for testing.
