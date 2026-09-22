# Master Gap Register — Production Closure 20260918

Machine-readable version: `MASTER_GAP_REGISTER.json`. This file is kept in sync at each update.

| ID | Severity | Subsystem | Status | Owner |
|---|---|---|---|---|
| GAP-001 | P0 | large_map_package.py copy semantics | **fixed** | direct (coordinator) |
| GAP-002 | P0 | tile_fbx_generator.py roundtrip status | **fixed** | direct (coordinator) |
| GAP-003 | P0 | main_pipeline.py artifact-authority ordering | **fixed** | a0fc461e58ef06e59 |
| GAP-004 | P1 | geometry_math.py legacy divergence | **fixed** | afed7bcc6adcb5bd9 |
| GAP-005 | P1 | check_lane_count_changes.py classification | **fixed** | ab5d110e2573e658b |
| GAP-006 | P0 | xodr_junction_links.py _geom_end LIVE bug | **fixed** | afed7bcc6adcb5bd9 (found during F) |
| GAP-007 | P2 | xodr_carla_hardener.py dead broken code | **fixed** | afed7bcc6adcb5bd9 (found during F) |
| GAP-008 | P1 | two independent geometry-authority packages | deferred | afed7bcc6adcb5bd9 (found during F) |
| GAP-009 | P1 | stage_09_tiling.py post-freeze mutation path | deferred | a0fc461e58ef06e59 (found during C) |
| GAP-010 | P0 | RQ4 GNN train/eval content leakage (FAIL) | **open** | unknown (discovered 2026-09-22) |
| GAP-011 | P1 | integration debt, 09-18..09-22 parallel-agent work | in_progress | direct (coordinator) |

Totals: 11 tracked, 8 fixed, 1 in progress, 2 deferred, 1 open, 0 blocked_external.

**Update 2026-09-22**: GAP-005 (`e2befc36`) merged (`f5333f3a`) and pushed to
`origin/integration/production-large-map-20260918`. Two new findings surfaced by a
2026-09-22 survey of work that accumulated 2026-09-18..09-21 outside this thread's
direct supervision (OpenCode, Codex, and continued autonomous execution of this
same master program by other sessions/agents):

- **GAP-010 (P0, open, top priority)**: `reports/production_readiness/20260919_RQ4_GNN_PROVENANCE/LEAKAGE_AUDIT.json`
  reports `status: "FAIL"` — the RQ4 eval reference file `manual_grid0821.xodr`
  hash-matches content already in the training set. Must be root-caused and fixed
  before any RQ4 GNN number is trusted.
- **GAP-011 (P1, in progress)**: real, tested, but unintegrated work is sitting across
  (a) a WIP checkpoint branch `fix/xodr-validator-convergence-v1-20260921` containing
  5 legitimate report-backed packages (Semantic Organizer Hardening, RQ3 Paired-Capture
  Contract, RQ4 GNN Provenance, Map Registry Integrity, XODR Validator Convergence)
  mixed with an unreviewed OC-26 change and some scratch files, (b) 10 unpushed
  OpenCode branches (OC-35..OC-43 + VAP), and (c) 2 unpushed Codex branches overlapping
  already-shipped P0-C scope. None of it is lost, none of it is merged.

See `MASTER_GAP_REGISTER.json` for full detail per issue (proof, affected files, consequence,
fixing commit, regression test, evidence artifact, residual risk). Updated after every subagent
handback per this program's integration discipline (Section 33).

## Two genuinely new, previously-untracked findings this round

- **GAP-006** (P0, live bug): `xodr_junction_links.py::_geom_end` silently returned a road segment's
  *start* pose for arc/spiral/poly3 endpoints instead of the true endpoint — wired into the live
  junction-connector matching path. Found opportunistically during the geometry-consolidation audit,
  not part of the original scope. Fixed and tested.
- **GAP-008** (P1, architectural, deferred deliberately): two independent, actively-maintained
  "canonical" OpenDRIVE geometry packages exist with no shared imports (~30 vs ~8 active callers).
  A new cross-oracle test proves they agree numerically (17/17 cases, 1e-6..1e-9) but nothing prevents
  future drift since they don't share code. Recommend a dedicated follow-up to pick one authority.
