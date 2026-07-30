# P2 — One-Paste Fresh-Hook Verification Block

> Companion to `P2_fresh_claude_hook_test.md`. Open a **FRESH Claude Code session** in `carla_-main`
> (not the P0/P3 session — hooks are read at startup, so only a new process loads the post-`ee8871c8` config)
> and paste the block below. Read-only; no source/git changes.

## One-paste command block

```powershell
# ===== P2 — FRESH CLAUDE HOOK VERIFICATION =====
$root = git rev-parse --show-toplevel; Set-Location $root
"session_start : $(Get-Date -Format o)"
"worktree      : $root"
"branch        : $(git branch --show-current)"
"HEAD          : $(git rev-parse HEAD)"

# --- active hook manifests + hashes ---
$manifests = @(
  ".claude/settings.local.json", ".claude/settings.json", ".claude/run_python_hook.sh",
  "$HOME/.claude/settings.json", "$HOME/.claude/settings.local.json"
) + (Get-ChildItem "$HOME/.claude/plugins" -Recurse -Filter "hooks*.json" -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty FullName)
$present = $manifests | Where-Object { Test-Path $_ }
"--- manifest sha256 (first 16) ---"
foreach ($m in $present) { "{0}  {1}" -f (Get-FileHash $m -Algorithm SHA256).Hash.Substring(0,16), $m }

# --- CRITICAL: any hook calling bare python3 (NOT via run_python_hook.sh, NOT a Bash(python3:*) permission) ---
"--- bare python3 in hook manifests (expect: NONE) ---"
$hits = Select-String -Path $present -Pattern "python3" -ErrorAction SilentlyContinue |
        Where-Object { $_.Line -notmatch "run_python_hook" -and $_.Line -notmatch 'Bash\(python3' }
if ($hits) { $hits | ForEach-Object { "HIT: $($_.Path): $($_.Line.Trim())" } } else { "NONE" }

# --- portable launcher probe: must resolve an interpreter, never 'python3: command not found' ---
"--- run_python_hook.sh probe ---"
'import sys; print("HOOK_PY_OK", sys.executable)' | Set-Content "$env:TEMP\hook_probe.py" -Encoding utf8
$env:CLAUDE_PROJECT_ROOT = $root
$probe = & bash "$root/.claude/run_python_hook.sh" "$env:TEMP/hook_probe.py" 2>&1
$probe
if ($probe -match "command not found") { "PROBE: FAIL" } elseif ($probe -match "HOOK_PY_OK") { "PROBE: PASS" } else { "PROBE: INCONCLUSIVE (bash?)" }
```

## Then, in the same fresh session (cannot be scripted — this is the actual test + report)

1. **Live check:** you just ran Read/Grep/Bash/PowerShell tools → scan *this session's* transcript for any
   `python3: command not found` (or interpreter-not-found) hook error. Record verbatim, or state `NONE`.
2. **Write** `reports/fresh_claude_hook_test/FCH01_hook_events.md` + `.json` with: session start, worktree, branch,
   HEAD, manifest hashes, static-grep result, launcher-probe result, per-event hook errors (or NONE).
3. **Verdict:**
   - `FRESH_SESSION_HOOKS_PASS` — only if grep=`NONE`, probe=`PASS`, live check=`NONE`, **and hooks still fired**
     (not silently disabled).
   - `FAIL_PYTHON3_STILL_ACTIVE` — any `python3: command not found`, or a real HIT in a hook `command`.
   - `FAIL_HOOK_DISABLED` — hooks replaced by unconditional success / no-op.

## Notes (why these checks)
- **Static grep is the real diagnostic.** The original bug was a hook manifest invoking bare `python3 <script>`
  (`bash: python3: command not found`); the fix routes through `.claude/run_python_hook.sh`. Two false positives
  are excluded: `run_python_hook.sh` (correct routing) and `Bash(python3:*)` (a *permission-allow* entry in
  `.claude/settings.local.json`, not a hook).
- **Fresh process is mandatory** — hooks load at startup; a cached session reports a stale failure.

## On result
- `FRESH_SESSION_HOOKS_PASS` → flip `GOV-HOOK-001 → RESOLVED` in `AGENT_TASK_LEDGER.md`, then run **P4** (fresh Opus).
- `FAIL_PYTHON3_STILL_ACTIVE` → the grep names the offending manifest; repair *only* that hook to route through
  `.claude/run_python_hook.sh`, then re-run this block.
