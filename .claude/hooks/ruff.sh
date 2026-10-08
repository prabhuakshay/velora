#!/usr/bin/env bash
# Claude Code PostToolUse hook, wired up in .claude/settings.json for Write|Edit.
# Runs after Claude writes or edits a file so Python code is formatted and linted
# immediately, instead of piling up ruff failures for the pre-commit hooks to reject.

# The hook receives the tool call as JSON on stdin; pull out the edited file's path.
f=$(python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))")

# Only Python files that still exist; anything else is a no-op.
[[ "$f" == *.py && -f "$f" ]] || exit 0

uv run ruff format --quiet "$f"

# Exit code 2 makes Claude Code feed stderr back to Claude, so it sees the
# lint errors ruff couldn't auto-fix and corrects them in its next edit.
out=$(uv run ruff check --fix --output-format concise "$f") || { echo "$out" >&2; exit 2; }
