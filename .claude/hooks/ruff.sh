#!/usr/bin/env bash
f=$(python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))")
[[ "$f" == *.py && -f "$f" ]] || exit 0
uv run ruff format --quiet "$f"
out=$(uv run ruff check --fix --output-format concise "$f") || { echo "$out" >&2; exit 2; }
