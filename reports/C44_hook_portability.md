# C44 — Claude Hook Portability Fix

Date: 2026-07-30
Branch: fix/claude-hooks-lock-governance-20260730

## Diagnosis

GOV-HOOK-001 was previously classified FIXED_VERIFIED_FOR_LOCAL_PYTHON after adding a `command -v python3 || command -v python` fallback. However, live Claude sessions still produce:

```
python3: command not found
```

Root cause: `command -v python3` on Git Bash prints "python3: command not found" to **stderr**, which Claude captures and displays. The `||` fallback to `command -v python` works correctly, but the stderr message is still visible in the hook output.

## Fix Applied

Added `2>/dev/null` to all `command -v` invocations in 4 hooks.json files:

| File | Status |
|------|--------|
| `.../plugins/hookify/hooks/hooks.json` | Patched |
| `.../plugins/security-guidance/hooks/hooks.json` | Patched |
| `.../cache/hookify/27d2b86d72da/hooks/hooks.json` | Patched |
| `.../cache/security-guidance/27d2b86d72da/hooks/hooks.json` | Patched |

Backup files created with suffix `.bak-20260730-stderr-leak`.

## Current Command

```bash
PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"; ...
```

## Portable Launcher

Created `.claude/run_python_hook.sh` with resolution order:
1. `CLAUDE_HOOK_PYTHON` environment variable
2. `$CLAUDE_PROJECT_ROOT/.venv/Scripts/python.exe` (repository venv)
3. `py -3` (Windows Python launcher)
4. `python`
5. `python3`
6. Graceful exit with message

## Reclassification

GOV-HOOK-001 = PARTIALLY_FIXED → FIXED_PENDING_FRESH_SESSION

A new Claude process is required to verify zero `python3: command not found` messages across all hook event types.
