# CODEX B2 — Promote calib_data.json to canonical tree + verify sensor wiring (R7)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1
MODEL: Codex 5.x MID. Independent of other prompts.

## Problem
`calib_data.json` (the thesis sensor calibration) exists in `submission/infrastructure/ultimate_pipeline/sensors/`
and sibling worktrees but NOT in the canonical `ultimate_pipeline/sensors/`. The canonical sensor rig therefore
cannot load its calibration on this branch.

## Goal
calib_data.json present + correctly consumed in the canonical tree, with a test proving the rig applies the
contract transforms exactly.

## Steps
1. Promote calib_data.json into `ultimate_pipeline/sensors/calib_data.json` (copy from the submission mirror;
   verify by sha256; do not alter values).
2. Confirm the rig loaders (carla_tools/sensor_rig.py, thesis_sensor_rig.py, sensors/attach_sensors_safe.py,
   rig_transforms.py, transform_conventions.py) resolve THIS canonical file.
3. Add an OFFLINE test (no CARLA) asserting the rig applies the contract exactly:
   - cameras: use `K_undistortion` (pinhole), IGNORE `K` and `D`; honor `image_size` width/height;
   - `cTv` is applied as vehicle→camera (NOT inverted; agent_sync ctv_inverted=false);
   - `vTl` is applied as LiDAR→vehicle and INVERTED for CARLA attachment (agent_sync vtl_inverted=true);
   - cross-check against the existing test_thesis_sensor_rig_contract.py.

## Boundaries
- Do NOT change calibration values or the contract directions. If a loader currently inverts cTv (legacy defect
  flagged in agent_sync) → ESCALATE_TO_CLAUDE, do not silently "fix".

## Deliverables / git
Canonical calib_data.json (small JSON, tracked); test under tests/; short report
reports/post_audit_hardening/B2_CALIB_PLACEMENT.md. Atomic commits; push; local==remote; suite green.
Verdict: CALIB_WIRED_GREEN | PARTIAL | BLOCKED_NEEDS_DECISION.
