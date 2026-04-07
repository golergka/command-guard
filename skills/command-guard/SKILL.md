---
name: command-guard
description: Add, view, edit, and remove command-guard rules
---

Manages the command-guard configuration at `.claude/command-guard.json`.

## Quick Reference

### Rule Schema

| Field            | Required | Type                                          | Description                   |
| ---------------- | -------- | --------------------------------------------- | ----------------------------- |
| `match`          | Yes      | `"command"` \| `"file_path"` \| `"tool_name"` | What to match against         |
| `pattern`        | Yes      | string (regex)                                | Pattern to match              |
| `message`        | Yes      | string                                        | Message shown when triggered  |
| `severity`       | Yes      | `"error"` \| `"warning"`                      | error=block, warning=reminder |
| `case_sensitive` | No       | boolean                                       | Default: false                |

### Match Types

- **command**: Bash command content. Commands are split on `&&`, `||`, `;`, `|` and normalized (absolute paths stripped, quoted strings removed).
- **file_path**: File paths in Edit and Write tool calls.
- **tool_name**: The tool name string. Useful for MCP tools like `mcp__server__method`.

### Severity

- **error**: Blocks the tool use entirely (PreToolUse, exit code 2). Can be overridden with `# OVERRIDE: <reason>` (5+ chars).
- **warning**: Shows a reminder after the tool completes (PostToolUse). Does not block.

### Safe Patterns

The `safePatterns` array contains regex patterns that bypass all blocking rules. Use for safe variants of otherwise dangerous commands.

## Instructions

When the user invokes this skill:

1. Read `.claude/command-guard.json` if it exists. If it doesn't, create it with `{"rules": [], "safePatterns": []}`.

2. **Interpret the user's request in natural language.** The user may say things like:
   - "Block git reset --hard" → `match: "command"`, `severity: "error"`
   - "Warn me when editing migration files" → `match: "file_path"`, `severity: "warning"`
   - "Don't let me use the betterstack MCP tool" → `match: "tool_name"`, `severity: "error"`
   - "Never do that again" (after a tool use) → infer from conversation context what to block
   - "Show me current rules" → list rules
   - "Remove the rule about git reset" → find and remove it

3. **Determine the rule fields:**
   - Choose `match` type based on what the user wants to guard against (a shell command, a file path, or a tool name).
   - Write the `pattern` as a regex. Use `\\s+` for whitespace, escape special regex characters, and anchor with `^`/`$` only when appropriate.
   - Write a clear, actionable `message` that explains *why* it's blocked/warned and suggests an alternative if possible.
   - Default to `severity: "error"` (block) unless the user explicitly asks for a warning/reminder.

4. **Show the proposed rule as JSON** and ask the user to confirm before writing. For example:
   ```
   I'll add this rule:
   {
     "match": "command",
     "pattern": "git\\s+reset\\s+--hard",
     "message": "git reset --hard destroys uncommitted changes. Use git stash first.",
     "severity": "error"
   }
   ```

5. **After confirmation**, read the current file, add the rule to the `rules` array (or the pattern to `safePatterns`), and write it back.

6. For **listing rules**: show each rule with a short summary (index, match type, pattern, severity).

7. For **removing or editing rules**: identify the rule by index or pattern match, show what will change, confirm, then write.
