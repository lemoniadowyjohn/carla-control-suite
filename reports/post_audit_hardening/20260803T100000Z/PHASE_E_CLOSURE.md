# Phase E closure evidence

- run_id: `20260803T100000Z`
- generated_at_utc: `2026-08-03T10:17:50.809368+00:00`
- producer: `ultimate_pipeline/tools/phase_e_closure_evidence.py`

## Frozen horizontal geometry

- candidate: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\campaigns\ingolstadt_cooked_perception_v1\candidate\raw_xodr_run_1_epsg32632_header_pinned.xodr`
- byte SHA-256: `ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d`
- protected geometry hash (roads length+planView+link attachments): `b0ecc5c642e17e3a8f06d9cb6f3fc535470ff9d823edd60bd5ac8c5dbb9361d6`
- connector geometry hash (junction roads): `b78b8610e6db0e32524d5510e3e3f8e2df8a7abe3740f83f969f0c8fffc07222`
- junction connection hash: `9cfa94bf5018e4fb27fd6426086a8e9994cce58006477bf994623b028697295f`
- roads: 32710, connector roads: 22816, junction connections: 22816

## Phase E test evidence

- `atomic_connector_reconstruction`: `exit=0 :: ============================== 4 passed in 0.32s ==============================`
- `connector_candidate_gate_and_path_safety`: `exit=0 :: ============================= 20 passed in 0.96s ==============================`
- `geometry_freeze`: `exit=0 :: ============================= 24 passed in 0.55s ==============================`
- `phase_e_policy`: `exit=0 :: ======================== 4 passed, 3 warnings in 0.86s ========================`

## Policies

- atomic connector reconstruction: deep-copy candidate, commit only when every mandatory check passes, revert otherwise.
- downstream invalidation: connector rebuild runs before geometry freeze and before elevation/lanes; rejected candidates are reverted.
- roundabout reconstruction: **disabled by default** in every release profile; remains disabled until its full fixture suite is committed and passes.

Phase E is closed with the evidence above; Phase F (Elevation and DEM) may proceed against the recorded frozen horizontal hash.