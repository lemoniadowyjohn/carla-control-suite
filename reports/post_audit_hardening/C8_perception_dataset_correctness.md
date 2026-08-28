# CODEX C8 (HIGH) — Perception dataset correctness (raw labels + unified layout)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: `./.venv/Scripts/python.exe` · UP_DISABLE_CARLA=1
Rules: TDD (RED→GREEN, watch it fail first); full-suite green; **EXPLICIT-PATHSPEC commit**. Model: Codex 5.x high.
**SEV-1 thesis showstopper.** Independent of C6/C7.

## Problem — the perception dataset is unreadable by its own trainer
The capture writers and the trainer/eval disagree on BOTH directory layout AND label encoding, so training runs on empty/garbage labels:

- **Capture** — `perception/dataset_generator.py` (`images_dir=dataset/"images"`, `labels_dir=dataset/"labels"`, lines 200-201) and `perception/perception_runner_local_aug.py` (lines 282-283, 427-435) save to `images/<cam>/` + `labels/<cam>/`, and for semantic they call `seg_img.convert(carla.ColorConverter.CityScapesPalette)` **before** `save_to_disk` (dataset_generator.py:412-413) → **the raw class id (R channel = 0..N) is overwritten with RGB palette colors**.
- **Trainer/eval** — `perception/min_train_segmentation.py:44-45` (`rgb/<cam>/`, `semseg_raw/<cam>/`, "uint8 class ids"), `perception/eval_sim_labeled.py:43-44,73` ("R channel encodes class ID"), `perception/class_weights.py:77` (`semseg_raw/<cam>/`) all read `rgb/` + `semseg_raw/` and expect **raw class ids in the R channel**.
- **Detection** — `dataset_generator.py` writes `_empty_yolo_label()` (empty boxes) for non-semantic mode.
- Only `experiments/thesis/run_vision_domain_gap.py:141-142` and `perception/record_route_fixed.py:763-764` reference the correct `rgb/`+`semseg_raw/` layout — the capture paths are inconsistent with the readers.

**Net:** directory mismatch (`images|labels` vs `rgb|semseg_raw`) + palette destroys labels + empty detection labels ⇒ the perception train/eval (thesis core, RQ on domain gap) trains on nothing usable.

## Steps (TDD — the save/encode/parse logic is offline-testable with synthetic arrays)
1. **RED characterization** (no CARLA server needed; simulate a CARLA semantic frame as a BGRA numpy array with R=class id):
   - assert the current save path yields a PNG whose R channel is NOT the class id (palette applied) and/or lands under `labels/` not `semseg_raw/` → fail.
   - assert `min_train_segmentation`'s Dataset finds 0 pairs given the capture's actual output dirs.
2. **Fix capture** (both `dataset_generator.py` and `perception_runner_local_aug.py`):
   - Write RGB to `rgb/<cam>/<frame>.png`; write **raw** semantic to `semseg_raw/<cam>/<frame>.png` with the R channel = class id (do NOT `convert(CityScapesPalette)` for the training label). Reuse the existing raw-id writer if present (`perception/label_quality.py::_write_png_raw_ids` / carla_classes helpers).
   - Keep the CityScapes-palette image ONLY as a separate human-viz artifact under `semseg_viz/<cam>/` (optional), never as the training label.
   - Validate ids with `perception.carla_classes.assert_label_ids_in_range` before write; fail-closed on out-of-range.
3. **Detection labels:** either produce REAL boxes (project CARLA actor 3D bboxes → 2D per the calibrated camera) or make detection an explicit, logged NO-OP that does not fabricate empty label files that downstream treats as valid. No silent empty labels.
4. **Round-trip GREEN test:** capture-save a synthetic frame → `min_train_segmentation` Dataset loads the `rgb`+`semseg_raw` pair by filename → returns a class-id tensor with values in `[0, CARLA_SEMANTIC_NUM_CLASSES)` matching the injected tags. Add a degenerate-label guard test (all-background → flagged by `label_quality.is_degenerate_label`).
5. **Unify** the two capture modules onto one shared writer so layout/encoding can't drift again.

## Boundaries
- Deterministic/offline for tests (synthetic CARLA-image-like arrays; no live server). The live capture is an operator integration step — document the exact command.
- Do NOT change the model, `num_classes`, or the calibration semantics (K_undistortion / cTv / vTl are D2 and correct). Semantic label content only.

## Deliverables / verdict
- Fixed `dataset_generator.py` + `perception_runner_local_aug.py` (shared raw-label writer, `rgb/`+`semseg_raw/`)
- `tests/unit/test_perception_dataset_roundtrip.py` (RED characterization + GREEN capture→train round-trip + degenerate guard)
- `reports/post_audit_hardening/C8_PERCEPTION_DATASET.md` (before/after: dirs written, R-channel = class id proof, Dataset pair count > 0)
- Push (explicit pathspec); local==remote; full suite green.
- **Verdict:** `PERCEPTION_DATASET_CORRECT rgb+semseg_raw raw_ids=OK detection=<real|explicit_noop>` | PARTIAL | BLOCKED.
