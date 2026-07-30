#!/usr/bin/env bash
set -e

# Portable Python launcher for Claude hooks
# Resolves: CLAUDE_HOOK_PYTHON -> repository venv -> py -3 -> python -> python3
# All stderr from interpreter resolution is silenced.

HOOK_SCRIPT="${1:?Usage: run_python_hook.sh <script.py> [args...]}"
shift

# 1. Explicit environment variable override
if [ -n "$CLAUDE_HOOK_PYTHON" ]; then
  exec "$CLAUDE_HOOK_PYTHON" "$HOOK_SCRIPT" "$@"
fi

# 2. Repository virtual environment
if [ -n "$CLAUDE_PROJECT_ROOT" ] && [ -x "$CLAUDE_PROJECT_ROOT/.venv/Scripts/python.exe" ]; then
  exec "$CLAUDE_PROJECT_ROOT/.venv/Scripts/python.exe" "$HOOK_SCRIPT" "$@"
fi

# 3. py -3 (Windows Python launcher)
PY_EXE=""
if command -v py >/dev/null 2>&1; then
  PY_EXE="py -3"
elif command -v python >/dev/null 2>&1; then
  PY_EXE="python"
elif command -v python3 >/dev/null 2>&1; then
  PY_EXE="python3"
fi

if [ -n "$PY_EXE" ]; then
  exec $PY_EXE "$HOOK_SCRIPT" "$@"
fi

echo "No usable Python interpreter found for Claude hook" >&2
exit 0
