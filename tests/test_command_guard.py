"""
Tests for command_guard.py

Run with: pytest tests/ -v
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

# Add the scripts directory to the path so we can import the module
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from command_guard import (
    check_rules,
    has_override,
    is_safe_pattern,
    load_config,
    normalize_command,
    split_compound_commands,
    strip_quoted_strings,
)


# =============================================================================
# Unit Tests
# =============================================================================


class TestStripQuotedStrings:
    """Tests for strip_quoted_strings function."""

    def test_removes_single_quoted_strings(self):
        assert strip_quoted_strings("echo 'hello world'") == 'echo ""'

    def test_removes_double_quoted_strings(self):
        assert strip_quoted_strings('echo "hello world"') == 'echo ""'

    def test_removes_ansi_c_quoted_strings(self):
        assert strip_quoted_strings("echo $'hello\\nworld'") == 'echo ""'

    def test_removes_heredoc_content(self):
        command = """cat <<EOF
git reset --hard
dangerous command
EOF"""
        result = strip_quoted_strings(command)
        assert "git reset --hard" not in result
        assert "dangerous command" not in result

    def test_removes_heredoc_with_single_quotes(self):
        command = """cat <<'EOF'
secret data
EOF"""
        result = strip_quoted_strings(command)
        assert "secret data" not in result

    def test_removes_heredoc_with_double_quotes(self):
        command = '''cat <<"EOF"
secret data
EOF'''
        result = strip_quoted_strings(command)
        assert "secret data" not in result

    def test_handles_heredoc_with_delimiter_in_content(self):
        """Test that delimiter word in content doesn't prematurely end heredoc."""
        command = """cat <<EOF
This documentation mentions EOF in the text.
But the heredoc continues.
EOF"""
        result = strip_quoted_strings(command)
        # The heredoc should be stripped entirely
        assert "documentation" not in result
        assert "continues" not in result

    def test_handles_tab_stripping_heredoc(self):
        """Test <<- syntax (tab-stripping heredoc)."""
        command = "cat <<-EOF\n\tindented content\nEOF"
        result = strip_quoted_strings(command)
        assert "indented content" not in result

    def test_preserves_command_outside_quotes(self):
        command = "echo 'ignore this' && git reset --hard"
        result = strip_quoted_strings(command)
        assert "git reset --hard" in result


class TestSplitCompoundCommands:
    """Tests for split_compound_commands function."""

    def test_splits_and_operator(self):
        result = split_compound_commands("cmd1 && cmd2")
        assert "cmd1" in result
        assert "cmd2" in result

    def test_splits_or_operator(self):
        result = split_compound_commands("cmd1 || cmd2")
        assert "cmd1" in result
        assert "cmd2" in result

    def test_splits_semicolon(self):
        result = split_compound_commands("cmd1; cmd2")
        assert "cmd1" in result
        assert "cmd2" in result

    def test_splits_pipe(self):
        result = split_compound_commands("cmd1 | cmd2")
        assert "cmd1" in result
        assert "cmd2" in result

    def test_extracts_dollar_paren_substitution(self):
        result = split_compound_commands("echo $(dangerous)")
        assert "dangerous" in result

    def test_extracts_backtick_substitution(self):
        result = split_compound_commands("echo `dangerous`")
        assert "dangerous" in result

    def test_handles_multiple_operators(self):
        result = split_compound_commands("cmd1 && cmd2 || cmd3; cmd4")
        assert "cmd1" in result
        assert "cmd2" in result
        assert "cmd3" in result
        assert "cmd4" in result


class TestNormalizeCommand:
    """Tests for normalize_command function."""

    def test_normalizes_absolute_git_path(self):
        assert normalize_command("/usr/bin/git status") == "git status"
        assert normalize_command("/bin/git status") == "git status"

    def test_normalizes_absolute_rm_path(self):
        assert normalize_command("/bin/rm -rf /tmp") == "rm -rf /tmp"
        assert normalize_command("/usr/bin/rm -rf /tmp") == "rm -rf /tmp"

    def test_preserves_regular_commands(self):
        assert normalize_command("git status") == "git status"
        assert normalize_command("rm -rf /tmp") == "rm -rf /tmp"


class TestIsSafePattern:
    """Tests for is_safe_pattern function."""

    def test_matches_safe_pattern(self):
        safe_patterns = [r"git\s+checkout\s+-b\s"]
        assert is_safe_pattern("git checkout -b feature", safe_patterns)

    def test_no_match_unsafe_command(self):
        safe_patterns = [r"git\s+checkout\s+-b\s"]
        assert not is_safe_pattern("git checkout main", safe_patterns)

    def test_empty_patterns_returns_false(self):
        assert not is_safe_pattern("any command", [])


class TestCheckRules:
    """Tests for check_rules function."""

    @pytest.fixture
    def sample_rules(self):
        return [
            {
                "match": "command",
                "pattern": r"git\s+reset\s+--hard",
                "severity": "error",
                "message": "Blocked: git reset --hard",
            },
            {
                "match": "command",
                "pattern": r"rm\s+-rf",
                "severity": "warning",
                "message": "Warning: rm -rf",
            },
            {
                "match": "file_path",
                "pattern": r"\.env$",
                "severity": "error",
                "message": "Cannot modify .env",
            },
            {
                "match": "tool_name",
                "pattern": r"^mcp__dangerous__",
                "severity": "error",
                "message": "Dangerous MCP tool",
            },
        ]

    def test_matches_command_error(self, sample_rules):
        matched, message = check_rules("git reset --hard", "command", "error", sample_rules)
        assert matched
        assert "git reset --hard" in message

    def test_matches_command_warning(self, sample_rules):
        matched, message = check_rules("rm -rf /tmp", "command", "warning", sample_rules)
        assert matched
        assert "rm -rf" in message

    def test_no_match_different_severity(self, sample_rules):
        # git reset --hard is error, not warning
        matched, _ = check_rules("git reset --hard", "command", "warning", sample_rules)
        assert not matched

    def test_matches_file_path(self, sample_rules):
        matched, message = check_rules("/path/to/.env", "file_path", "error", sample_rules)
        assert matched
        assert ".env" in message

    def test_matches_tool_name(self, sample_rules):
        matched, message = check_rules("mcp__dangerous__tool", "tool_name", "error", sample_rules)
        assert matched
        assert "Dangerous MCP" in message

    def test_no_match_when_value_doesnt_match(self, sample_rules):
        matched, _ = check_rules("git status", "command", "error", sample_rules)
        assert not matched

    def test_case_insensitive_by_default(self, sample_rules):
        matched, _ = check_rules("GIT RESET --HARD", "command", "error", sample_rules)
        assert matched


class TestHasOverride:
    """Tests for has_override function."""

    def test_valid_override(self, capsys):
        assert has_override("git reset --hard  # OVERRIDE: cleaning up failed rebase")
        captured = capsys.readouterr()
        assert "OVERRIDE accepted" in captured.err

    def test_override_with_colon(self, capsys):
        assert has_override("cmd # OVERRIDE: reason here")

    def test_override_too_short_reason(self):
        assert not has_override("cmd # OVERRIDE: abc")  # Less than 5 chars

    def test_no_override_comment(self):
        assert not has_override("git reset --hard")

    def test_override_without_reason(self):
        assert not has_override("cmd # OVERRIDE:")

    def test_override_case_sensitive(self):
        # OVERRIDE must be uppercase
        assert not has_override("cmd # override: reason here")


# =============================================================================
# Integration Tests (script execution)
# =============================================================================


class TestScriptIntegration:
    """Integration tests that run the script as a subprocess."""

    @pytest.fixture
    def script_path(self):
        return str(Path(__file__).parent.parent / "scripts" / "command_guard.py")

    @pytest.fixture
    def fixtures_dir(self):
        return Path(__file__).parent / "fixtures"

    def run_script(
        self, script_path: str, hook_input: Dict[str, Any], project_dir: str
    ) -> subprocess.CompletedProcess:
        """Run the script with given input and return the result."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = project_dir

        return subprocess.run(
            [sys.executable, script_path],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            env=env,
        )

    def test_blocked_command_returns_exit_2(self, script_path, fixtures_dir):
        """Test that blocked commands return exit code 2."""
        project_dir = str(fixtures_dir.parent)
        # Create a temporary config
        config_dir = fixtures_dir.parent / ".claude"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "command-guard.json"

        # Copy our test config
        with open(fixtures_dir / "basic_rules.json") as f:
            config = json.load(f)
        with open(config_file, "w") as f:
            json.dump(config, f)

        try:
            hook_input = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git reset --hard"},
            }

            result = self.run_script(script_path, hook_input, project_dir)

            assert result.returncode == 2
            assert "BLOCKED" in result.stderr
        finally:
            config_file.unlink(missing_ok=True)
            config_dir.rmdir()

    def test_allowed_command_returns_exit_0(self, script_path, fixtures_dir):
        """Test that allowed commands return exit code 0."""
        project_dir = str(fixtures_dir.parent)
        config_dir = fixtures_dir.parent / ".claude"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "command-guard.json"

        with open(fixtures_dir / "basic_rules.json") as f:
            config = json.load(f)
        with open(config_file, "w") as f:
            json.dump(config, f)

        try:
            hook_input = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
            }

            result = self.run_script(script_path, hook_input, project_dir)

            assert result.returncode == 0
        finally:
            config_file.unlink(missing_ok=True)
            config_dir.rmdir()

    def test_override_allows_blocked_command(self, script_path, fixtures_dir):
        """Test that OVERRIDE comment allows blocked commands."""
        project_dir = str(fixtures_dir.parent)
        config_dir = fixtures_dir.parent / ".claude"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "command-guard.json"

        with open(fixtures_dir / "basic_rules.json") as f:
            config = json.load(f)
        with open(config_file, "w") as f:
            json.dump(config, f)

        try:
            hook_input = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": "git reset --hard  # OVERRIDE: cleaning up failed rebase"
                },
            }

            result = self.run_script(script_path, hook_input, project_dir)

            assert result.returncode == 0
            assert "OVERRIDE accepted" in result.stderr
        finally:
            config_file.unlink(missing_ok=True)
            config_dir.rmdir()

    def test_safe_pattern_allows_otherwise_blocked(self, script_path, fixtures_dir):
        """Test that safe patterns allow otherwise blocked commands."""
        project_dir = str(fixtures_dir.parent)
        config_dir = fixtures_dir.parent / ".claude"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "command-guard.json"

        with open(fixtures_dir / "basic_rules.json") as f:
            config = json.load(f)
        with open(config_file, "w") as f:
            json.dump(config, f)

        try:
            # rm -rf node_modules is a safe pattern in our test config
            hook_input = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf node_modules"},
            }

            result = self.run_script(script_path, hook_input, project_dir)

            # Should not be blocked (rm -rf is warning, safe pattern exempts it anyway)
            assert result.returncode == 0
        finally:
            config_file.unlink(missing_ok=True)
            config_dir.rmdir()

    def test_tool_name_error_blocks_mcp_tools(self, script_path, fixtures_dir):
        """Test that tool_name rules with error severity block MCP tools."""
        project_dir = str(fixtures_dir.parent)
        config_dir = fixtures_dir.parent / ".claude"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "command-guard.json"

        with open(fixtures_dir / "basic_rules.json") as f:
            config = json.load(f)
        with open(config_file, "w") as f:
            json.dump(config, f)

        try:
            hook_input = {
                "hook_event_name": "PreToolUse",
                "tool_name": "mcp__dangerous__delete_all",
                "tool_input": {},
            }

            result = self.run_script(script_path, hook_input, project_dir)

            assert result.returncode == 2
            assert "BLOCKED" in result.stderr
            assert "Dangerous MCP" in result.stderr
        finally:
            config_file.unlink(missing_ok=True)
            config_dir.rmdir()

    def test_file_path_error_blocks_edit(self, script_path, fixtures_dir):
        """Test that file_path rules block Edit tool."""
        project_dir = str(fixtures_dir.parent)
        config_dir = fixtures_dir.parent / ".claude"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "command-guard.json"

        with open(fixtures_dir / "basic_rules.json") as f:
            config = json.load(f)
        with open(config_file, "w") as f:
            json.dump(config, f)

        try:
            hook_input = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": "/project/.env"},
            }

            result = self.run_script(script_path, hook_input, project_dir)

            assert result.returncode == 2
            assert "BLOCKED" in result.stderr
            assert ".env" in result.stderr
        finally:
            config_file.unlink(missing_ok=True)
            config_dir.rmdir()

    def test_no_config_allows_everything(self, script_path, tmp_path):
        """Test that missing config allows all commands."""
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard"},
        }

        result = self.run_script(script_path, hook_input, str(tmp_path))

        assert result.returncode == 0

    def test_warning_on_post_tool_use(self, script_path, fixtures_dir):
        """Test that warnings are shown in PostToolUse."""
        project_dir = str(fixtures_dir.parent)
        config_dir = fixtures_dir.parent / ".claude"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "command-guard.json"

        with open(fixtures_dir / "basic_rules.json") as f:
            config = json.load(f)
        with open(config_file, "w") as f:
            json.dump(config, f)

        try:
            hook_input = {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /tmp/test"},
            }

            result = self.run_script(script_path, hook_input, project_dir)

            assert result.returncode == 0
            # Check for JSON warning output
            output = json.loads(result.stdout)
            assert output.get("decision") == "block"
            assert "rm -rf" in output.get("reason", "")
        finally:
            config_file.unlink(missing_ok=True)
            config_dir.rmdir()

    def test_compound_command_each_part_checked(self, script_path, fixtures_dir):
        """Test that compound commands have each part checked."""
        project_dir = str(fixtures_dir.parent)
        config_dir = fixtures_dir.parent / ".claude"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "command-guard.json"

        with open(fixtures_dir / "basic_rules.json") as f:
            config = json.load(f)
        with open(config_file, "w") as f:
            json.dump(config, f)

        try:
            # Dangerous command hidden after safe one
            hook_input = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "echo hello && git reset --hard"},
            }

            result = self.run_script(script_path, hook_input, project_dir)

            assert result.returncode == 2
            assert "BLOCKED" in result.stderr
        finally:
            config_file.unlink(missing_ok=True)
            config_dir.rmdir()
