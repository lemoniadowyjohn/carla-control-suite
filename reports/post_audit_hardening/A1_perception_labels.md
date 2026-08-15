# A1 Perception Labels - Outcome

Date: 2026-08-15
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803
Executor: Codex

## Verdict

LABELS_REAL_GREEN for the thesis semantic-segmentation path.

The original A1 premise was too broad. The unused YOLO/detection `.txt` path still writes empty placeholder labels,
but the thesis training path uses semantic segmentation masks:

- `ultimate_pipeline/perception/segmentation_dataset_generator_queues.py` writes `semseg_raw/<camera>/*.png`.
- `ultimate_pipeline/perception/min_train_segmentation.py` trains `fcn_resnet50` from `semseg_raw/<camera>/*.png`.
- `ultimate_pipeline/perception/eval_sim_labeled.py` evaluates against `semseg_raw/<camera>/*.png`.

Therefore R4/R8 segmentation training is not blocked by empty YOLO labels. The remaining empty-label issue is a
detection-track cleanup item, not the thesis segmentation blocker.

## Additive Guard

Added `ultimate_pipeline/perception/label_quality.py` with offline per-frame semantic-label quality checks:

- `label_stats(raw_ids)` reports class count, non-background fraction, and dominant-class fraction.
- `is_degenerate_label(raw_ids)` flags all-background or single-class-dominated masks that would poison training.

No live CARLA run is required for these helpers.

## Tests

Added `tests/unit/test_label_quality.py`:

- Validates class counts and fractions on synthetic masks.
- Flags all-background and dominant-single-class masks as degenerate.
- Accepts diverse masks.
- Characterizes `_write_png_raw_ids` as extracting CARLA semantic class IDs from the R channel of BGRA raw data.

Targeted result:

```text
tests/unit/test_label_quality.py ..... [100%]
5 passed, 3 warnings
```

Full-suite gate:

```text
662 passed, 49 warnings in 63.88s
```

## Classes Covered

The characterization test covers the raw class-id extraction mechanism, not a fixed taxonomy mapping. Synthetic IDs
`0`, `7`, and `10` are used to prove that non-zero CARLA class IDs survive into the raw mask. The production
semantic sensor can emit the full CARLA uint8 semantic class-id range.

## Follow-Ups

- Wire `is_degenerate_label` into the live capture loop during the capture phase so bad frames are flagged or skipped
  with explicit accounting.
- Decide whether the unused YOLO/detection `.txt` path should be implemented with real detection labels or removed
  from the thesis path to avoid future confusion.
