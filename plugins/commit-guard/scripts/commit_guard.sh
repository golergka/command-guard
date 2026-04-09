#!/usr/bin/env bash
# Stop hook: block Claude from finishing with uncommitted changes.
#
# If the working tree is dirty and the last assistant message does not
# contain UNCOMMITTED_OK, the hook returns decision:block so Claude
# is re-prompted to commit first.

INPUT=$(cat)
LAST_MSG=$(echo "$INPUT" | jq -r '.last_assistant_message // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // "."')

cd "$CWD" || exit 0

# Only act inside a git repo
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# Clean tree — nothing to do
if git diff --quiet HEAD 2>/dev/null && [ -z "$(git status --porcelain 2>/dev/null)" ]; then
  exit 0
fi

# Dirty tree — allow if explicitly acknowledged
if echo "$LAST_MSG" | grep -qF 'UNCOMMITTED_OK'; then
  exit 0
fi

cat <<'EOF'
{
  "decision": "block",
  "reason": "UNCOMMITTED CHANGES DETECTED. You MUST commit your work before finishing. Run git status, stage your changes, and commit. If there is a genuine reason not to commit (e.g. you only did research, or the user told you not to), include UNCOMMITTED_OK in your message."
}
EOF
