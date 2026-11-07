# Codex — CI classification integrity, strict gate semantics and mirrored source

Baseline SHA `dfa6ffff07c38d0cc09507c52b3328900ef2d900`. Do not claim that all 30 failures arise from CARLA absence; exact run https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556 confirms nonplatform defects. Do not weaken tests to satisfy CI. Work in a separate owned worktree, coordinate any overlaps with T2b or W-F.

1. `QualityGateManager`: test `ok='yes'` conflicts with fail-closed normalization. Determine frozen contract, prefer strict bool and update obsolete truthiness test only with rationale; add negative controls `False`, `0`, `1`, `''`, `'false'`, `'yes'`, None, conflicting status, unknown keys. `from_legacy_bool` currently `bool(value)`: verify declared type checks and actual callers before changing.
2. Mirror drift: authoritative `ultimate_pipeline/core/carla_opendrive_loader.py` differs from submission mirror. Compare exact bytes/semantics, decide source of truth from dispatch, synchronize by controlled explicit copy/generation or fail-closed release gate; test drift in modified production logic. No blind mirror overwrite.
3. `StorageGate` test uses Windows volume C: on Linux. Replace implicit OS assumption in test with platform-accurate volume discovery, without relaxing unmeasurable volume semantics.
4. `tests/unit/test_single_writer_arbitration.py` exercises native Windows API on Linux. Enforce truthful Windows-only marker and require a separate actual Windows CI job; no Win32 mock presented as native validation. Work with T2b owner; 21 error tests + two related subprocess failures remain unresolved until Windows result.
5. Preserve full CI test selection, do not broad xfail/skip/ignore 30 nodeids; require CI run success on *new exact SHA*, original 30 disposition matrix and no lost tests. T2b and orchestration logic stay specialist-owned.

Collect actual check-run API; PR-event-only helper may return [] even for a push workflow. Avoid misleading 'no CI found'. Report unchanged findings, executed tests and blockers.

## Non-negotiable working contract
- Do not force-push, merge, auto-approve, auto-deploy, publish candidate b or change protected `main`/`integration`.
- No live CARLA/UE4, cooking, high-cost experiments or new model training without explicit operator authorization; synthetic-only offline work is allowed.
- The final XODR cannot be cosmetically modified; GAP-026 cannot be hidden by raising tolerance; geometry corrections only at generating source stage with provenance.
- Do not edit or overwrite historical artifacts, original V25/V26 reports, receipts, or anyone else's worktree. Use unique output directories with new run IDs and SHA256 manifests.
- Single writer per worktree and per shared Git-metadata mutation. Audit locks and actual process start identity first; if inconsistent STOP/BLOCKED.
- Every PASS must have command, exact cwd, executable/tool version, return code, collected/passed/failed/skipped/xfailed, input/output hashes, actual test nodeids, and exact commit SHA; unexecuted commands => NOT_EXECUTED.
- No false platform classification: one failing test on Linux does not establish success on Windows. Evidence for live or external runtime requires actual authorized RPC response, not an import or socket.
- If a command could alter production, invoke providers, real CARLA, or paid resources: **do not execute it** without a precise separate authorization grant.
- Never make OpenCode production changes or Codex edits to OpenCode-only test paths. See `contracts/OWNERSHIP_AND_GATES.md`.

