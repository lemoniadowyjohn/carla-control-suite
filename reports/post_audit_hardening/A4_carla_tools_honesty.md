# CODEX A4 (MED) — carla_tools honesty hardening (mock fallbacks must fail loud)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1
MODEL: Codex 5.x MID. Independent of A1/A2/A3.

## Problem
- `ultimate_pipeline/carla_tools/fixed_traffic_manager.py` returns a silent `MockTM` (no-op `spawn_vehicles`/
  `spawn_pedestrians`) when CARLA is unavailable → mock results can be mistaken for real evidence
  (lines ~18, 52, 251-267).
- `ultimate_pipeline/carla_tools/sensor_rig.py:147` — rotation extraction is a placeholder (calibration precision).

## Goal
Mock fallbacks may exist only in EXPLICIT dev mode; under strict/thesis mode they must FAIL LOUD so mocked output
can never enter evidence. Resolve or explicitly document the rotation-extraction placeholder.

## Steps
1. In `fixed_traffic_manager.py`: when CARLA is unavailable, RAISE (fail-closed) if `UP_THESIS_STRICT` /
   strict/release mode is set; keep the graceful `MockTM` ONLY when an explicit dev/allow-mock flag is set.
   Ensure the mock path prints/records an unmissable "MOCK — not real evidence" marker.
2. `sensor_rig.py:147`: implement the exact rotation extraction if tractable; otherwise convert the placeholder
   into a clear, tested limitation (raise/log under strict) and document it.
3. Tests: strict mode + no CARLA → raises; dev mode + explicit flag → returns MockTM with the marker; rotation
   path behaves as specified.

## Boundaries
- Do NOT change dev-mode behavior silently; the only new hard failure is under strict/thesis mode.
- No gate-logic changes.

## Deliverables / git
tests/unit/test_carla_tools_honesty_*.py; short report reports/post_audit_hardening/A4_CARLA_TOOLS_HARDENING.md.
Atomic commits; push; local==remote; full suite green.
Verdict: CARLA_TOOLS_HARDENED_GREEN | PARTIAL | BLOCKED_NEEDS_DECISION.
