#!/usr/bin/env python3
"""
Command Guard Plugin for Claude Code

Provides configurable guardrails for blocking/warning about tool usage.
No default rules - all configuration comes from project config file.

Configuration file: ${CLAUDE_PROJECT_DIR}/.claude/command-guard.json

Override mechanism:
Any blocked command can be overridden by adding a comment with explicit reasoning:
  git reset --hard  # OVERRIDE: cleaning up failed rebase state
The reason must be at least 5 characters. Override usage is logged to stderr.

Rule severity levels:
- "error": Blocks the tool use (exit code 2 in PreToolUse)
- "warning": Shows a reminder (JSON output in PostToolUse)

Rule match types:
- "command": Matches Bash command content
- "file_path": Matches Edit/Write file paths
- "tool_name": Matches tool name (for MCP tools)
"""

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# Shell operators that chain commands together
CHAIN_OPERATORS = r"&&|\|\||;|\|"

# Patterns that indicate command substitution
COMMAND_SUBSTITUTION_PATTERN = r"\$\([^)]+\)|`[^`]+`"

# Override mechanism - allows bypassing blocks with explicit reasoning
OVERRIDE_PATTERN = r"#\s*OVERRIDE:\s*(.+)$"
MIN_OVERRIDE_REASON_LENGTH = 5


def load_config() -> Optional[Dict[str, Any]]:
    """
    Load configuration from project's .claude/command-guard.json.
    Returns None if config doesn't exist (no rules = allow everything).
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not project_dir:
        return None

    config_path = os.path.join(project_dir, ".claude", "command-guard.json")
    if not os.path.exists(config_path):
        return None

    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Failed to load command-guard config: {e}", file=sys.stderr)
        return None


def has_override(command: str) -> bool:
    """
    Check if command has a valid override comment.
    Returns True if override is valid.

    Override format: # OVERRIDE: <reason>
    The reason must be at least MIN_OVERRIDE_REASON_LENGTH characters.
    """
    match = re.search(OVERRIDE_PATTERN, command)
    if not match:
        return False
    reason = match.group(1).strip()
    if len(reason) < MIN_OVERRIDE_REASON_LENGTH:
        return False
    print(f"OVERRIDE accepted for command: {command}\nReason: {reason}", file=sys.stderr)
    return True


def strip_quoted_strings(command: str) -> str:
    """
    Remove content inside quoted strings to avoid false pattern matches.
    Handles single quotes, double quotes, and heredocs.
    """
    # Remove heredoc content: <<'EOF' ... EOF or <<"EOF" ... EOF or <<EOF ... EOF
    command = re.sub(r"<<['\"]?(\w+)['\"]?.*?\1", "", command, flags=re.DOTALL)
    # Remove $'...' strings (ANSI-C quoting)
    command = re.sub(r"\$'[^']*'", '""', command)
    # Remove single-quoted strings
    command = re.sub(r"'[^']*'", '""', command)
    # Remove double-quoted strings (but keep the quotes as placeholder)
    command = re.sub(r'"[^"]*"', '""', command)
    return command


def split_compound_commands(command: str) -> List[str]:
    """
    Split a compound command into individual commands.
    Handles command chaining (&&, ||, ;, |) and command substitution ($(), ``).
    """
    commands = []

    # Extract command substitutions: $(...) and `...`
    for match in re.finditer(COMMAND_SUBSTITUTION_PATTERN, command):
        inner = match.group()
        if inner.startswith("$("):
            commands.append(inner[2:-1])
        else:
            commands.append(inner[1:-1])

    # Split on chain operators: &&, ||, ;, |
    parts = re.split(r"\s*(?:" + CHAIN_OPERATORS + r")\s*", command)
    commands.extend(parts)

    return [cmd.strip() for cmd in commands if cmd.strip()]


def normalize_command(command: str) -> str:
    """Normalize absolute paths at the start of commands to standard forms."""
    # Replace common absolute paths for git
    command = re.sub(r"^/usr/bin/git\s", "git ", command)
    command = re.sub(r"^/bin/git\s", "git ", command)
    # Replace common absolute paths for rm
    command = re.sub(r"^/bin/rm\s", "rm ", command)
    command = re.sub(r"^/usr/bin/rm\s", "rm ", command)
    return command


def is_safe_pattern(command: str, safe_patterns: List[str]) -> bool:
    """Check if command matches a known safe pattern."""
    for pattern in safe_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False


def check_rules(
    value: str, match_type: str, severity: str, rules: List[Dict[str, Any]]
) -> Tuple[bool, str]:
    """
    Check value against rules of given match_type and severity.
    Returns (matched, message).
    Patterns run case-insensitive by default; set "case_sensitive": True for exact matching.
    """
    for rule in rules:
        if rule.get("match") != match_type or rule.get("severity") != severity:
            continue

        pattern = rule.get("pattern", "")
        if not pattern:
            continue

        flags = 0 if rule.get("case_sensitive", False) else re.IGNORECASE
        if re.search(pattern, value, flags):
            return True, rule.get("message", "Rule matched")

    return False, ""


def block_with_error(context: str, message: str):
    """Block tool use with exit code 2."""
    print(
        f"BLOCKED: {message}\n\n"
        f"Context: {context}\n\n"
        f"To override, add a comment: # OVERRIDE: <reason>",
        file=sys.stderr,
    )
    sys.exit(2)


def show_warning(message: str):
    """Show warning (exit 0 with JSON)."""
    print(json.dumps({"decision": "block", "reason": message}))
    sys.exit(0)


def main():
    try:
        # Load config - if no config, allow everything
        config = load_config()
        if config is None:
            sys.exit(0)

        rules = config.get("rules", [])
        safe_patterns = config.get("safePatterns", [])

        # If no rules defined, allow everything
        if not rules:
            sys.exit(0)

        data = json.load(sys.stdin)
        hook_event = data.get("hook_event_name", "PreToolUse")
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {}) or {}

        if not isinstance(tool_input, dict):
            tool_input = {}

        if hook_event == "PreToolUse":
            # Check for ERRORS only (exit 2 to block)

            if tool_name == "Bash":
                command = tool_input.get("command", "")
                if not isinstance(command, str) or not command:
                    sys.exit(0)

                # Check override first (applies to entire compound command)
                if has_override(command):
                    sys.exit(0)

                # Split compound commands and check each
                for sub_command in split_compound_commands(command):
                    sub_command = normalize_command(sub_command)

                    # Check safe patterns
                    if is_safe_pattern(sub_command, safe_patterns):
                        continue

                    # Check errors
                    matched, message = check_rules(
                        strip_quoted_strings(sub_command), "command", "error", rules
                    )
                    if matched:
                        block_with_error(command, message)

            elif tool_name in ("Edit", "Write"):
                file_path = tool_input.get("file_path", "")
                if file_path:
                    matched, message = check_rules(file_path, "file_path", "error", rules)
                    if matched:
                        block_with_error(file_path, message)

            sys.exit(0)

        elif hook_event == "PostToolUse":
            # Check for WARNINGS only (exit 0 with JSON to show reminder)

            if tool_name == "Bash":
                command = tool_input.get("command", "")
                if isinstance(command, str) and command:
                    matched, message = check_rules(
                        strip_quoted_strings(command), "command", "warning", rules
                    )
                    if matched:
                        show_warning(message)

            elif tool_name in ("Edit", "Write"):
                file_path = tool_input.get("file_path", "")
                if file_path:
                    matched, message = check_rules(file_path, "file_path", "warning", rules)
                    if matched:
                        show_warning(message)

            else:
                # MCP tools and other tools
                matched, message = check_rules(tool_name, "tool_name", "warning", rules)
                if matched:
                    show_warning(message)

            sys.exit(0)

    except json.JSONDecodeError as e:
        # Invalid JSON - log for debugging but allow to not break things
        print(f"Warning: command_guard failed to parse JSON input: {e}", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        # Any other error - log for debugging but allow by default
        print(f"Warning: command_guard error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
