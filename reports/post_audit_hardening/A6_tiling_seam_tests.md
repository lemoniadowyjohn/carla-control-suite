# CODEX A6 (MED) — Tiling seam-continuity tests (checkers exist, untested)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1
Rules: characterization tests (existing code); full-suite green; EXPLICIT-PATHSPEC commit. Model: Codex 5.x mid.

## Problem (premise partly off — checkers exist, not tested)
The map is tiled (`pipeline_stages/stage_09_tiling.py`, `tiling/tile_extractor.py`). Seam-continuity CHECKERS
already exist — `tile_validation/geometry_seam_checker.py::GeometrySeamChecker` ("planView endpoint continuity"),
`tile_validation/lane_seam_checker.py`, `quality/check_post_tiling_integrity.py`, `tools/check_seams.py` — but the
tiling tests cover CRS/extractor/matcher/IoU, **not seam continuity**. So the checkers themselves are unverified:
we don't know they actually catch a discontinuous seam.

## Goal
Characterize the seam checkers with synthetic tiled fixtures, incl. a NEGATIVE CONTROL proving they detect a real
seam break (not just pass everything).

## Steps
1. Read the checker APIs (GeometrySeamChecker, lane_seam_checker, check_post_tiling_integrity) — inputs (tile XODRs
   + adjacency) and what "continuous" means (endpoint position/heading match within tolerance).
2. Build tiny synthetic tiled fixtures:
   - CONTINUOUS: two adjacent tiles whose shared-edge road endpoints (position + heading) match within tolerance
     → checker reports 0 seam violations.
   - DISCONTINUOUS (negative control): inject a gap/heading-jump at the shared edge → checker FLAGS the seam.
3. Tests assert both: clean tiling passes; the injected break is detected. If a checker FAILS to detect the injected
   discontinuity → ESCALATE_TO_CLAUDE (that is a real checker defect, not a test to loosen).
4. (Optional) run the checker on a real tiled candidate if one is on disk; record the seam-violation count.

## Boundaries
- Tests + report ONLY (no checker logic change unless a real defect is found → ESCALATE). Deterministic, offline.

## Deliverables / verdict
tests/unit/test_tiling_seam_continuity.py; report reports/post_audit_hardening/A6_TILING_SEAM_TESTS.md.
Push (explicit pathspec); local==remote; suite green. Verdict: SEAM_CHECKERS_CHARACTERIZED | PARTIAL | BLOCKED.

## Execution Report

Date: 2026-08-15

Verdict: `SEAM_CHECKERS_CHARACTERIZED`

The existing seam checkers were characterized on synthetic two-tile OpenDRIVE fixtures:

- `GeometrySeamChecker` accepts a continuous line endpoint seam.
- `GeometrySeamChecker` flags a 1.0 m endpoint discontinuity as `fail`.
- `LaneSeamChecker` accepts a continuous driving-lane pair.
- `LaneSeamChecker` flags a matched 0.5 m lateral break.
- `LaneSeamChecker` flags a matched 0.2 rad heading break.

Targeted tests:

```text
tests/unit/test_tiling_seam_continuity.py .....                          [100%]
5 passed in 0.13s
```

Full suite:

```text
732 passed, 49 warnings in 163.16s
```

ESCALATE_TO_CLAUDE:
- None.
