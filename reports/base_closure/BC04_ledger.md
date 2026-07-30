# BC04 — Governance Ledger

`AGENT_TASK_LEDGER.md` created at repo root with operating rules, status vocabulary, model-routing table, and rows:

| ID | Status |
|---|---|
| GOV-AUTH-001 (clean pushed base + upstream) | **RESOLVED** |
| GOV-LOCK-001 (canonical writer-lock system) | **RESOLVED** |
| GOV-SYNC-001 (agent_sync bound to canonical lock) | **RESOLVED** |
| GOV-HOOK-001 (portable Claude hooks) | **FIXED_PENDING_FRESH_SESSION** |
| P0 / P1 | **RESOLVED** |
| P3 (this closure) | **READY** |
| P2 / P4 | **OPEN** |
| P5 | **BLOCKED** (prereq P4) |
| S01 artifact transactions | **READY** |
| MAP-REPAIR | **BLOCKED** |

**Critical honesty guard:** `GOV-HOOK-001` is **NOT** RESOLVED — it flips only after P2 (fresh-session hook test)
returns `FRESH_SESSION_HOOKS_PASS`. The v4 P3 spec would set it RESOLVED "only because P2 passed"; P2 has not run,
so it correctly remains `FIXED_PENDING_FRESH_SESSION`.
