# C8 (HIGH) — Perception dataset correctness (raw labels + unified layout)

Date: 2026-08-16
Branch: fix/c8-perception-dataset-correctness (base: fix/post-audit-phase-e-junctions-roundabouts-20260803 @ 95a816ea)
Executor: Claude (Sonnet 5), TDD
Interp: `./.venv/Scripts/python.exe` · `UP_DISABLE_CARLA=1`

## Verdict

`PERCEPTION_DATASET_CORRECT rgb+semseg_raw raw_ids=OK detection=explicit_noop`

## Problem (recap)

The perception capture writers and the trainer/eval/class-weight readers disagreed on both directory
layout and label encoding:

- **Capture** — `ultimate_pipeline/perception/dataset_generator.py` (`images_dir=dataset/"images"`,
  `labels_dir=dataset/"labels"`) and `ultimate_pipeline/perception/perception_runner_local_aug.py`
  (`images/<cam>/`, `labels/<cam>/`) saved to a layout no reader consumed. For semantic mode,
  `dataset_generator.py` called `seg_img.convert(carla.ColorConverter.CityScapesPalette)` **before**
  `save_to_disk`, overwriting the raw class id (R channel) with RGB palette colors.
- **Trainer/eval** — `min_train_segmentation.py`, `eval_sim_labeled.py`, `class_weights.py` all read
  `rgb/<cam>/` + `semseg_raw/<cam>/` and expect raw class ids in the R channel (single-channel uint8
  after extraction).
- **Detection** — `dataset_generator.py` and `perception_runner_local_aug.py` both wrote
  `_empty_yolo_label()` — empty `.txt` files — for every non-semantic frame, which downstream tooling
  could mistake for "zero objects" ground truth rather than "not implemented."

Note: `ultimate_pipeline/perception/segmentation_dataset_generator_queues.py` already wrote the correct
`rgb/` + `semseg_raw/` (+ `semseg/` viz) layout using a raw-id writer (`_write_png_raw_ids`, extracts the
R channel of the BGRA sensor buffer). That module was the reference implementation this fix generalizes
into a single shared writer used by **all** capture entry points.

## Fix

### New shared writer: `ultimate_pipeline/perception/capture_writer.py`

`save_capture_frame(dataset_root, *, camera, frame, rgb_image, seg_image, label_mode, write_viz=False)`
is now the single source of truth for capture output layout/encoding:

- `rgb/<camera>/<frame:08d>.png` — RGB image, decoded directly from the BGRA raw buffer (works for both
  real `carla.Image` and duck-typed fakes; does not depend on `carla.Image.save_to_disk`).
- `semseg_raw/<camera>/<frame:08d>.png` — **training label**: single-channel uint8, pixel value == CARLA
  semantic class id. Written via the existing `_write_png_raw_ids` helper from
  `segmentation_dataset_generator_queues.py` (reused, not duplicated), which extracts the R channel
  (index 2 of BGRA) **before** any palette conversion.
- `semseg_viz/<camera>/<frame:08d>.png` — **optional**, human-viewable CityScapes-palette colorization,
  written only when `write_viz=True`. Derived independently from the raw ids; never used as a training
  label and never read by any trainer/eval/class-weight code.
- ids are validated with `assert_label_ids_in_range` (from `carla_classes.py`) **before** write; raises
  `ValueError` and writes nothing on out-of-range ids (fail-closed).
- Non-semantic (`label_mode != "semantic"`) capture is an **explicit, logged no-op** — see Detection
  section below.

### `dataset_generator.py`

- Removed `self.images_dir` / `self.labels_dir` and the inline `seg_img.convert(CityScapesPalette)` +
  `save_to_disk` sequence; the per-frame save loop now calls `save_capture_frame(...)`.
- `meta/label_schema.json` now documents the `rgb/` + `semseg_raw/` (+ `semseg_viz/`) layout for
  `label_mode="semantic"`, and an explicit `detection_status="explicit_noop"` schema for
  `label_mode="none"`.
- Removed the dead `_empty_yolo_label()` helper (no longer called anywhere in this module).
- DB logging and augmented-copy paths updated to read `img_path`/`label_path` off the
  `CaptureWriteResult` returned by the shared writer.

### `perception_runner_local_aug.py`

- This module never attached a semantic-segmentation sensor (RGB-only), so there was no palette-mangling
  bug here — but it shared the same incompatible `images/`+`labels/` layout and fabricated empty YOLO
  labels. Switched to `rgb/<camera>/` via the shared writer (`label_mode="none"`), unifying the layout
  with `dataset_generator.py` so it can no longer drift.
- Writes a `meta/label_schema.json` documenting `detection_status="explicit_noop"` for the same reason
  as `dataset_generator.py`.
- Removed the dead `_empty_yolo_label()` helper and the `labels_dir`/`lbl_path` bookkeeping.
- Per-frame `meta/frames.jsonl` entries now carry `detection_status` instead of a `label_path` pointing
  at a fabricated empty file.

### Detection labels: explicit no-op (not real boxes)

**Chosen: explicit, logged no-op** — not real projected 2D boxes.

Rationale: no 3D-actor-bbox -> 2D-camera-plane projector exists anywhere in this codebase (searched
`bounding_box|bbox|get_2d_bbox|project.*bbox` across `ultimate_pipeline/perception/*.py`; the only hit is
an unrelated distance-filter docstring comment in `record_route.py`). Building one is a real-boxes
feature addition, not a correctness fix, and the C8 spec's Boundaries section explicitly puts calibration
semantics (`K_undistortion`/`cTv`/`vTl`, i.e. exactly what a projector would need) out of scope for this
fix ("D2 and correct... Semantic label content only"). The minimal, honest, in-scope correction is to
stop fabricating empty `.txt` files that a downstream consumer could mistake for "zero objects present"
ground truth. `save_capture_frame(..., label_mode="none")` now performs and logs an explicit no-op
(`CaptureWriteResult.detection_status == "explicit_noop"`) instead. Confirmed no real consumer depended
on the previous empty-file behavior: `ultimate_pipeline/diagnostics/dataset_quick_audit.py` (the only
other reader of the legacy YOLO layout) already tolerates empty label files ("empty label file is
allowed, but we warn") and is a standalone manual diagnostic, not a trainer.

## Before / after proof

**Before (legacy `dataset_generator.py`, label_mode="semantic"):**
- Written: `<dataset>/images/<cam>/<frame>.png`, `<dataset>/labels/<cam>/<frame>.png` (CityScapes-palette
  RGB — R channel is NOT the class id after `convert()`).
- `min_train_segmentation.SegDataset(root, cam)` looks under `root/"rgb"/cam` + `root/"semseg_raw"/cam`
  → **0 pairs found** (directories don't exist) → training silently runs on nothing.

**After (this fix):**
- Written: `<dataset>/rgb/<cam>/<frame>.png`, `<dataset>/semseg_raw/<cam>/<frame>.png` (raw class ids).
- R-channel proof (from `tests/unit/test_perception_dataset_roundtrip.py::test_capture_writes_raw_class_ids_not_palette_colors`):
  a synthetic BGRA seg frame with injected class ids `{7, 10}` round-trips through `save_capture_frame`
  and the saved PNG's pixel values equal the injected ids exactly (`np.array_equal(saved, ids)` — no
  palette RGB present).
- `SegDataset(out_root, cam="front")` finds `len(ds) == 1` pair (was 0) for a single synthetic frame; the
  loaded label tensor equals the injected ids and satisfies
  `0 <= y.min() and y.max() < CARLA_SEMANTIC_NUM_CLASSES` (29).
- Degenerate-label guard: an all-background synthetic frame round-trips to a label flagged by
  `label_quality.is_degenerate_label(...) is True`, proving the persisted/read-back values are the raw
  ids (all-zero), not palette colors.
- Out-of-range ids (class id 250, outside `[0, 28]`) raise `ValueError` from `save_capture_frame` before
  anything is written (fail-closed via `assert_label_ids_in_range`).

## Operator integration step (live capture command, unchanged CLI surface)

No CLI flags changed. Example (same as before; requires a running CARLA server, hence out of scope for
offline tests):

```
./.venv/Scripts/python.exe -m ultimate_pipeline.perception.dataset_generator \
  --map-type auto --frames 2000 --out-root datasets \
  --calib calib_data.json --xodr path/to/map.xodr \
  --camera front_left_camera --fps 20 --label-mode semantic
```

Output now lands under `datasets/<dataset_name>/rgb/front_left_camera/` and
`datasets/<dataset_name>/semseg_raw/front_left_camera/`, directly consumable by:

```
./.venv/Scripts/python.exe -m ultimate_pipeline.perception.min_train_segmentation \
  --dataset datasets/<dataset_name> --camera front_left_camera
```

## Tests

Added `tests/unit/test_perception_dataset_roundtrip.py` (6 tests, all offline — synthetic BGRA numpy
buffers via a duck-typed `_FakeCarlaImage`, no live CARLA server; `carla.Image` cannot be constructed
from pure Python, confirmed during investigation):

- `test_capture_writes_raw_class_ids_not_palette_colors` — RED→GREEN: R channel of the saved training
  label equals injected class ids.
- `test_capture_does_not_land_training_label_under_labels_dir` — no `labels/` directory is produced.
- `test_min_train_segmentation_dataset_finds_pairs_from_capture_output` — round-trip:
  capture-save → `SegDataset` finds >0 pairs → loaded tensor matches injected ids, values in
  `[0, CARLA_SEMANTIC_NUM_CLASSES)`.
- `test_degenerate_all_background_capture_is_flagged` — all-background synthetic frame round-trips to a
  label flagged by `label_quality.is_degenerate_label`.
- `test_detection_mode_does_not_fabricate_silent_empty_labels` — non-semantic capture returns
  `detection_status="explicit_noop"` and writes no fabricated empty `.txt` labels.
- `test_out_of_range_ids_fail_closed` — out-of-range class ids raise `ValueError`, nothing written.

RED confirmation: before `capture_writer.py` existed, all 6 tests failed with
`ModuleNotFoundError: No module named 'ultimate_pipeline.perception.capture_writer'` (the fix this test
suite characterizes did not yet exist). After implementing `capture_writer.py` and wiring both capture
modules to it, all 6 pass.

## Full-suite result

```
UP_DISABLE_CARLA=1 ./.venv/Scripts/python.exe -m pytest -q
772 passed, 1 skipped, 0 failed, 82 warnings in 192.40s
```

No pre-existing tests broke. Targeted perception-adjacent run (24 tests: roundtrip + label_quality +
carla_classes + class_weights + perception_collect_tools) also green.

## Boundaries respected

- No changes to `num_classes`, model architecture, or calibration semantics
  (`K_undistortion`/`cTv`/`vTl` — D2, untouched).
- No live CARLA server required or used for any test; all logic is offline/synthetic-array testable.
- Detection: explicit no-op chosen over fabricating a bbox projector, which would be new functionality
  outside this correctness fix's scope (see Detection section above).

## Files changed

- `ultimate_pipeline/perception/capture_writer.py` (new — shared writer)
- `ultimate_pipeline/perception/dataset_generator.py` (wired to shared writer; removed dead
  `_empty_yolo_label`; updated docstring + `label_schema.json` content)
- `ultimate_pipeline/perception/perception_runner_local_aug.py` (wired to shared writer; removed dead
  `_empty_yolo_label`; updated docstring + `label_schema.json` content)
- `tests/unit/test_perception_dataset_roundtrip.py` (new — RED characterization + GREEN round-trip +
  degenerate guard + detection no-op + fail-closed validation)
- `reports/post_audit_hardening/C8_PERCEPTION_DATASET.md` (this report)
