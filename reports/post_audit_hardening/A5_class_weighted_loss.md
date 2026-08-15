# CODEX A5 (MED) — Class-weighted segmentation loss (fix imbalance bias)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1
Rules: TDD; full-suite green; EXPLICIT-PATHSPEC commit. Model: Codex 5.x mid.

## Problem (genuinely missing)
`ultimate_pipeline/perception/min_train_segmentation.py:92` uses plain `torch.nn.CrossEntropyLoss()` — no class
weights. CARLA semantic classes are heavily imbalanced (road/building/vegetation dominate; pedestrians, poles,
traffic signs/lights are rare — and the perception-critical ones). Unweighted CE makes the model underlearn the
rare classes, so mIoU is biased toward easy classes and the perception result understates rare-class performance.

## Goal
Compute per-class weights from the training-set label frequency and pass them to the loss, so rare classes are
learned. Offline-testable weight computation; opt-out flag to preserve current behavior for comparison.

## Steps
1. Add a helper (e.g. `perception/class_weights.py`): `compute_class_weights(label_id_counts, num_classes=CARLA_SEMANTIC_NUM_CLASSES,
   scheme="median_frequency")` returning a torch.FloatTensor[num_classes]. Support median-frequency balancing
   (weight_c = median(freq)/freq_c) and inverse-frequency; absent classes → weight 0 (or a documented floor).
2. Add a dataset-scan that accumulates per-class pixel counts from the `semseg_raw/` masks (uses
   `np.bincount(minlength=num_classes)`); reuse `perception.carla_classes.assert_label_ids_in_range`.
3. Wire into `min_train_segmentation.py`: build weights from the scanned dataset, pass
   `CrossEntropyLoss(weight=weights)`; add `--no-class-weights` to opt out (default: weighted).
4. TDD (offline, synthetic): median-frequency weights give RARE classes higher weight than COMMON ones; a uniform
   distribution → ~equal weights; empty/absent class → weight 0; bincount counts correctly.

## Boundaries
- Do NOT change the model architecture or num_classes. Weighting is opt-out, not silent.
- Deterministic, offline tests (no CARLA, no real dataset — synthetic count vectors).

## Deliverables / verdict
`perception/class_weights.py` + tests + wiring; report reports/post_audit_hardening/A5_CLASS_WEIGHTED_LOSS.md.
Push (explicit pathspec); local==remote; suite green. Verdict: CLASS_WEIGHTS_GREEN | PARTIAL | BLOCKED.

## Execution Report

Date: 2026-08-15

Verdict: `CLASS_WEIGHTS_GREEN`

The segmentation trainers now use class-weighted `CrossEntropyLoss` by default. This reduces the training bias toward dominant CARLA semantic classes while preserving an explicit `--no-class-weights` opt-out for ablation/comparison runs.

Changes:
- Added `ultimate_pipeline/perception/class_weights.py`.
- Implemented median-frequency balancing and inverse-frequency balancing.
- Added class-id pixel counting from raw semantic PNG masks under `semseg_raw/<camera>/`.
- Wired `min_train_segmentation.py` to scan labels, build weights, pass them into `CrossEntropyLoss`, and record counts/weights in `metrics.json`.
- Wired `train_launcher.py` to use the same default weighted loss and opt-out flags.

Tests:

```text
Red: ModuleNotFoundError: No module named 'ultimate_pipeline.perception.class_weights'
Targeted: 6 passed in 4.68s
Compatibility: 10 passed, 3 warnings in 4.67s
Full suite: 727 passed, 49 warnings in 162.41s
```

ESCALATE_TO_CLAUDE:
- Weighted CE reduces imbalance bias but does not replace experiment-design choices: convergence epochs, train/val/test splits, and baselines still need methodology approval.
