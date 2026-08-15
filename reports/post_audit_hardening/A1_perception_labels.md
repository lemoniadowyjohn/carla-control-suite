# CODEX A1 (HIGH) — Fix perception label generation (empty YOLO labels block training)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1 for tests
MODEL: Codex 5.x HIGH.  Independent of A2/A3/A4 and the E-series map work (different files).

## Problem (self-documented in-code)
The perception dataset generators write EMPTY YOLO label placeholders → supervised training is blocked:
- `ultimate_pipeline/perception/segmentation_dataset_generator_queues.py:15`
- `ultimate_pipeline/perception/perception_runner_local_aug.py:21`
- `ultimate_pipeline/perception/dataset_generator.py:408`
(Do NOT touch `perception/record_route.py` "placeholder" code — that is validation that *rejects* placeholder
paths; it is correct and must stay.)

## Goal
Emit REAL labels: derive 2D bounding boxes + class IDs from CARLA semantic segmentation + actor bounding boxes at
capture time, written in the existing YOLO (and/or segmentation) layout — so a supervised trainer has non-empty,
correctly-classed labels.

## Steps
1. Trace the capture path: where each generator writes labels; the class taxonomy already used elsewhere
   (semantics/semantic_mapper.py, perception_metrics). Confirm the exact YOLO format + directory layout expected
   by the trainer (perception/run_training.py / train_launcher.py).
2. Implement label extraction: 2D bbox from actor 3D bbox projected via the camera intrinsics/extrinsics (reuse
   sensors/transform_conventions.py, rig_transforms.py) OR from semantic+instance segmentation masks; map CARLA
   semantic tags → the project class IDs.
3. Wire it into the three generators, replacing the empty-placeholder writes. Keep the file layout identical.
4. OFFLINE tests (no CARLA): feed a synthetic semantic image + a synthetic actor list (with known 3D bboxes +
   a known camera transform) and assert the written labels are non-empty, correctly formatted, correctly classed,
   and pixel-plausible. An all-empty output MUST fail a test.

## Boundaries
- Do NOT fabricate/synthesize fake labels to "pass" — labels must derive from real inputs; empty output fails.
- Do NOT change the trainer or the class taxonomy without ESCALATE_TO_CLAUDE.
- End-to-end validation on a live CARLA capture is a SEPARATE runtime step (out of scope here).

## Deliverables / git
New tests under tests/unit/ (or tests/perception/); report reports/post_audit_hardening/A1_PERCEPTION_LABELS.md
listing classes covered + any gaps. Atomic commits; push; local==remote; full suite stays green.
Report: baseline vs final; ESCALATE_TO_CLAUDE. Verdict: LABELS_REAL_GREEN | PARTIAL | BLOCKED_NEEDS_DECISION.
