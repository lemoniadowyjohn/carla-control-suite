# Methodology gaps W2-W5 - advisor memo

Date: 2026-08-15
Scope: thesis validity risks that are not primarily code defects

## Summary

A1, A2, A3, and A4 reduced the main code-risk items: semantic labels are real, the GNN math is characterized, the
domain-gap aggregation contract is characterized, and CARLA mock evidence now fails loud. The remaining high-impact
risks are methodology and claim-scope decisions. They should be fixed in the thesis plan before interpreting live
results.

## W2 - Experiment Design

Current risk:

- Frame counts, train/validation/test splits, seeds, routes, weather conditions, and repeated-run variance are not
  pinned as a thesis protocol.
- Without that protocol, a green pipeline can still produce non-reproducible or cherry-picked results.

Decision needed:

- Number of generated frames per map.
- Train/validation/test split policy.
- Fixed route set and spawn policy.
- Number of random seeds or repeated captures.
- Whether cross-validation is required.
- Which metrics are primary vs secondary.
- Minimum evidence required before a result can be called conclusive.

Recommended protocol shape:

- Predefine one fixed capture rig from canonical `calib_data.json`.
- Use identical routes and frame budgets for auto and manual maps.
- Run at least three seeds or repeated captures if stochastic elements remain.
- Report mean, standard deviation, and confidence intervals for stochastic metrics.
- Keep a signed manifest of map sha256, calibration sha256, route IDs, seed IDs, and frame counts.

## W3 - Controls and Baselines

Current risk:

- "How much generalization is possible" has no scale without controls.
- A sim-to-real number alone is hard to interpret.

Controls to define:

- Same-domain sanity check: train on auto-map synthetic, evaluate on held-out auto-map synthetic.
- Cross-map structural check: train on auto synthetic, evaluate on manual synthetic, and the reverse if feasible.
- Real-data upper bound if labels exist: train or fine-tune on labeled real data, then evaluate on held-out real.
- Null/random baseline: untrained or randomly initialized model to bound meaningless scores.
- Majority/background baseline for segmentation masks.
- Optional domain-adaptation baseline such as CORAL/MMD if already implemented.

Minimum recommendation:

- Include same-domain synthetic sanity, cross-map synthetic, and unlabeled real-shift metrics.
- Do not claim real-world accuracy unless real labels exist.

## W4 - Claim Boundary For Unlabeled Real Evaluation

Current risk:

- `eval_real_unlabeled.py` can measure model confidence, entropy, feature/logit distribution shift, and related
  unsupervised diagnostics.
- It cannot measure real-world segmentation accuracy without labels.

Required thesis wording:

> On unlabeled real Ingolstadt data, this thesis evaluates sim-to-real domain shift and model uncertainty, not
> supervised real-world accuracy. Accuracy claims are limited to labeled synthetic or any real subset for which
> ground-truth labels are available.

Implication:

- R8 is partially answerable with unlabeled data: the project can quantify shift and uncertainty.
- R8 is not fully answerable as an accuracy/generalization claim unless real labels are acquired.

## W5 - Fairness Protocol For Auto-vs-Manual Perceptual Comparison

Current risk:

- If auto and manual maps are cooked with different visual assets, lighting, sensor rigs, routes, or capture
  settings, measured "domain gap" can reflect asset/rendering differences instead of map-structure differences.

Protocol to pin before cooking:

- Same Unreal/CARLA version.
- Same weather, time of day, rendering quality, and no-rendering settings if applicable.
- Same vehicle, sensor rig, `calib_data.json`, and camera/LiDAR transforms.
- Same routes, spawn points, frame count, FPS, and random seeds.
- Same visual asset pack and material/cooking pipeline.
- Same output schema and dataset writer.
- Same postprocessing and label-quality filtering.

Evidence to record:

- Auto map sha256 and manual map sha256.
- Cooked package identifiers and build logs.
- Calibration sha256.
- Capture manifest with route IDs, seeds, frame count, FPS, weather, and map identity.

## Bottom Line

These are not unit-test failures. They are thesis-validity controls. The highest-risk actionable code/runtime gap is
W1 manual-map loadability. W2-W5 should be resolved with the advisor before final claims are written, because they
define what the results are allowed to mean.
