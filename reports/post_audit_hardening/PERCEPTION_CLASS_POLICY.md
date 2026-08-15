# Perception Semantic Class Policy

Date: 2026-08-15

Verdict: `PERCEPTION_CLASS_POLICY_RIGHT_SIZED_GREEN`

## Finding

The original perception training and evaluation defaults used `num_classes=256`. This was safe for uint8 CARLA semantic masks, but it created a mostly-dead 256-channel segmentation head for a CARLA semantic ontology whose governed class IDs fit under `0..28`.

The labeled-sim mIoU path was already safe because absent target classes are skipped. The real issue was R8-style unlabeled evaluation: pooled-logit Fréchet distance over 256 channels includes many unused dimensions and can dilute or noise the sim-to-real shift signal.

## Fix

- Added `ultimate_pipeline/perception/semantic_classes.py`.
- Added `ultimate_pipeline/perception/carla_classes.py` compatibility API.
- Set `CARLA_SEMANTIC_MAX_CLASS_ID = 28`.
- Set `CARLA_SEMANTIC_NUM_CLASSES = 29`.
- Wired training and eval defaults to `29` instead of `256`.
- Added fail-closed label range checks for supervised train/sim-eval masks.
- Preserved explicit overrides:
  - CLI `--num-classes`
  - env/settings `UP_TRAIN_NUM_CLASSES`

The implementation does **not** remap class IDs. CARLA semantic masks store numeric IDs, so the model head must remain at least `max_label_id + 1`.

## Compatibility Note

Old checkpoints trained with a 256-channel head still require `--num-classes 256` when evaluated. New default training/eval runs use the right-sized CARLA policy.

## Tests

| Suite | Result |
| --- | --- |
| Red test | missing policy module + 256 defaults failed as expected |
| Targeted final | `88 passed, 4 warnings in 16.43s` |

## ESCALATE_TO_CLAUDE

- This is a metric-sharpening fix, not a runtime proof. R8 still needs cooked maps, fair capture, real dataset path, and experiment design.
