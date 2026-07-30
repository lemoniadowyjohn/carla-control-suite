# P2 — Fresh-Hook Verification RUNBOOK (operator-ordered)

**Goal:** close blocker **B1** by producing the missing `FRESH_SESSION_HOOKS_PASS` evidence and flipping
`GOV-HOOK-001 → RESOLVED`. This runbook consolidates and supersedes the reading order of
`P2_fresh_claude_hook_test.md` + `P2_oneshot_commands.md` — follow it top-to-bottom.

- **Worktree:** `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main`
- **Branch:** `integration/governed-map-quality-20260729` (tip `a7e0a332` or later)
- **Model:** cheapest available Claude Code model (Haiku 4.5 → Sonnet 5 → Opus 4.8). Reasoning strength is irrelevant.
- **Mode:** read-only for the *test*; one bounded governed commit only for the ledger flip (Step 6).

---

## 0. What you're proving (and what is already true)

`GOV-HOOK-001` was: a hook manifest invoked bare `python3 <script>` → `bash: python3: command not found`.
Commit `ee8871c8` routed hooks through `.claude/run_python_hook.sh` (portable launcher, **fails open with `exit 0`**).

**Already verified green (static side), 2026-07-30 @ `a7e0a332`:**
- `.claude/run_python_hook.sh` present + tracked; resolves `CLAUDE_HOOK_PYTHON → $CLAUDE_PROJECT_ROOT/.venv/Scripts/python.exe → py -3 → python → python3`.
- Static grep for a bare `python3` hook (excluding the launcher and the `Bash(python3:*)` *permission* entry) = **NONE** in project + user settings.

**Therefore P2 is now an evidence-capture test, not a repair.** The only thing missing is proof from a **fresh process**
that live hook *events* don't error, plus the written `FCH01` artifact. Do **not** "fix" anything unless Step 4 actually fails.

## 1. Why a fresh process is mandatory

Claude Code reads hook manifests **at startup**. The P0/P3 sessions cached the *pre-*`ee8871c8` config and will keep
printing the stale `python3: command not found`. Only a **new** process loads the patched config. A fresh session is
the entire point — you cannot validate this by reasoning, only by launching clean.

## 2. Preconditions (abort if any fails)

```
[ ] All old Claude Code processes closed (especially P0/P3).
[ ] git rev-parse HEAD == origin/integration/governed-map-quality-20260729   (clean, synced)
[ ] .claude/run_python_hook.sh exists and is executable
[ ] No live writer lock:  python -c "import json;print(json.load(open('.agent_locks/writer.lock'))['status'])"  -> released/expired
```

## 3. Static probe (paste once in the fresh session)

```powershell
# ===== P2 — FRESH CLAUDE HOOK VERIFICATION (static) =====
$root = git rev-parse --show-toplevel; Set-Location $root
"session_start : $(Get-Date -Format o)"
"worktree      : $root"
"branch        : $(git branch --show-current)"
"HEAD          : $(git rev-parse HEAD)"

$manifests = @(
  ".claude/settings.local.json", ".claude/settings.json", ".claude/run_python_hook.sh",
  "$HOME/.claude/settings.json", "$HOME/.claude/settings.local.json"
) + (Get-ChildItem "$HOME/.claude/plugins" -Recurse -Filter "hooks*.json" -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty FullName)
$present = $manifests | Where-Object { Test-Path $_ }
"--- manifest sha256 (first 16) ---"
foreach ($m in $present) { "{0}  {1}" -f (Get-FileHash $m -Algorithm SHA256).Hash.Substring(0,16), $m }

"--- bare python3 in hook manifests (expect: NONE) ---"
$hits = Select-String -Path $present -Pattern "python3" -ErrorAction SilentlyContinue |
        Where-Object { $_.Line -notmatch "run_python_hook" -and $_.Line -notmatch 'Bash\(python3' }
if ($hits) { $hits | ForEach-Object { "HIT: $($_.Path): $($_.Line.Trim())" } } else { "NONE" }

"--- run_python_hook.sh probe (must NOT say 'command not found') ---"
'import sys; print("HOOK_PY_OK", sys.executable)' | Set-Content "$env:TEMP\hook_probe.py" -Encoding utf8
$env:CLAUDE_PROJECT_ROOT = $root
$probe = & bash "$root/.claude/run_python_hook.sh" "$env:TEMP/hook_probe.py" 2>&1
$probe
if ($probe -match "command not found") { "PROBE: FAIL" } elseif ($probe -match "HOOK_PY_OK") { "PROBE: PASS" } else { "PROBE: INCONCLUSIVE (bash?)" }
```

Record the three results: **manifest hashes**, **bare-python3 = NONE**, **PROBE = PASS**.

## 4. Live event test (cannot be scripted — this is the actual test)

In the **same fresh session**, trigger each hook event with a harmless operation and watch the transcript for any
`python3: command not found` / interpreter-not-found error:

| Event | Trigger |
|---|---|
| `PreToolUse:Read` + `PostToolUse:Read` | Read a small file (e.g. `README.md`) |
| `PreToolUse:Grep` + `PostToolUse:Grep` | Grep a trivial pattern |
| `PreToolUse:Bash`/`PowerShell` + `PostToolUse` | Run `echo ok` |
| `Stop` | End a turn |

Record each event's hook output verbatim, or `NONE`.

## 5. Acceptance & verdict

- **`FRESH_SESSION_HOOKS_PASS`** — ALL of: static grep = `NONE`, probe = `PASS`, live check = `NONE`,
  **and hooks still actually fired** (a silenced/disabled hook is NOT a pass).
- **`FAIL_PYTHON3_STILL_ACTIVE`** — any `python3: command not found`, or a real HIT in a hook `command`.
  → the grep names the offending manifest; repair **only** that hook to route through `.claude/run_python_hook.sh`,
  then re-run this runbook. Touch nothing else.
- **`FAIL_HOOK_DISABLED`** — hooks replaced by unconditional success / no-op. Not a pass.
- **`BLOCKED_EXTERNAL_CONFIGURATION`** — offender is outside the repo and not editable in scope.

Write the evidence:
```
reports/fresh_claude_hook_test/FCH01_hook_events.md
reports/fresh_claude_hook_test/FCH01_hook_events.json
```
Template:
```
FRESH CLAUDE HOOK VERDICT: <one of the four>
SESSION START:            <ISO>
WORKTREE:                 C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
BRANCH:                   integration/governed-map-quality-20260729
SHA:                      <git rev-parse HEAD>
MANIFEST HASHES:          <list>
STATIC python3 GREP:      NONE | <hits>
LAUNCHER PROBE:           PASS | FAIL | INCONCLUSIVE  (resolved -> <interpreter path>)
HOOK EVENTS FIRED:        Read/Grep/Bash/Stop
HOOK ERRORS:              NONE | <verbatim>
HOOKS DISABLED:           NO   (must be NO)
GOV-HOOK-001 STATUS:      RESOLVED (only on PASS) | REGRESSED | FIXED_PENDING_FRESH_SESSION
```

## 6. On PASS — flip the ledger (bounded governed commit)

This mutates a tracked file (`AGENT_TASK_LEDGER.md`), so use the canonical lock. From the worktree root:

```python
# acquire (never edit the lock by hand)
from pathlib import Path
from ultimate_pipeline.contracts.writer_lock import WriterLock
lock = WriterLock.acquire(Path('.'), branch='integration/governed-map-quality-20260729',
    head_sha=__import__('subprocess').check_output(['git','rev-parse','HEAD']).decode().strip(),
    owner='<agent> (P2 hook verify)', purpose='Flip GOV-HOOK-001 -> RESOLVED + FCH01 evidence',
    model='<model>', task_id='P2-HOOK-VERIFY', allowed_paths=['reports/**','AGENT_TASK_LEDGER.md'],
    forbidden_paths=['cities/**','**/*.xodr','manual_maps/**'])
```

Then in `AGENT_TASK_LEDGER.md` change the two rows:
```
GOV-HOOK-001 : FIXED_PENDING_FRESH_SESSION  ->  RESOLVED   (note: P2 pass, FCH01 evidence @ <SHA>)
P2           : OPEN                          ->  RESOLVED
```
Stage **only** `reports/fresh_claude_hook_test/` + `AGENT_TASK_LEDGER.md`, verify no junk
(`nul`,`vehicle.`,`.idea`,`__pycache__`,`.pyc`,`.xodr`), commit docs-only:
```
docs(hooks): P2 FRESH_SESSION_HOOKS_PASS; GOV-HOOK-001 RESOLVED (FCH01)
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
Release: `lock.release()`. Push only if instructed.

## 7. Downstream — corrected for current reality

⚠ The original P2 prompt says "on PASS → run P4". **P4 has already run** (@`a7e0a332`) and returned
`REQUIRES_BASE_CORRECTION` (see `reports/architecture_gate/AG07_verdict.md`). So:

- Passing P2 **closes B1 only**. It does **not** flip the P4 verdict on its own.
- **B2** (authoritative XODR unpinned), **B3** (no FBX / visible-road source), **B4** (cook toolchain absent on host)
  still block. Codex 5.5 stays **not authorized**.
- Correct sequence after P2 PASS: close B2→B4, then **re-run P4** (fresh Opus) for a new verdict; only an
  `AG07 = ARCHITECTURE_APPROVED_FOR_CODEX_55` unblocks P5.

**Stop after the ledger flip. Do not start P4/P5/Unreal/CARLA from the P2 session.**
