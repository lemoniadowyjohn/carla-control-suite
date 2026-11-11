# LaneGNNRefiner safety contract (V94)

## Current callable interface
`LaneGNNRefiner.run_inplace(root, model_path: str | None, device='cpu', confidence_thresh=0.7) -> LaneRefinementReceipt` in the unconfigured case, or raises `LaneRefinementBlocked`. Legacy method argument order retained; return type changes from `None` to a false-valued receipt when disabled. Callers depending on `is None` require compatibility review. No known production call was identified in the inspected `main_pipeline.py`.

`LaneRefinementReceipt`: immutable; `status=DISABLED`, `ok=False`, `applied=False`, `release_eligible=False`, `quality_gates_run=False`; all model and geometry digests `null`, because neither is evaluated. `policy_version=lane-gnn-disabled-v1`. It must NEVER be accepted as an ML success or as satisfaction of a required map gate. Boolean conversion is False. `to_dict()` is JSON-serializable.

`LaneRefinementBlocked` is a RuntimeError with `code` and `reason`. `BLOCKED_MODEL_UNVALIDATED`: any configured checkpoint. `INVALID_THRESHOLD`: confidence value not a Python int/float, NaN/Inf or outside [0,1]. `INVALID_DEVICE`: not `cpu`, `cuda`, or `cuda:<nonnegative integer>`. Device syntax validation DOES NOT establish GPU readiness.

## Future *proposed* geometry-refiner interface (NOT IMPLEMENTED)
- Input: immutable OpenDRIVE artifact identity (SHA-256); graph version and feature order digest; local metric frame (origin/CRS/heading); lane nodes identified by (road, section s, signed lane id, direction), attributes for centerline/width/boundaries/elevation/slope/curvature/road class plus feature masks; directed intra-road, inter-road, lateral and junction edges. Missing values must be masked, not silently made physical zero.
- Output: bounded, calibrated correction proposals; per-lane confidence and OOD score; never direct topology edits. Graph target and threshold definitions, labels and units require approval.
- Checkpoint: architecture, feature-schema and scaler SHA-256; source code Git SHA, dataset manifest SHA-256, split/group hashes, training seed, optimizer and calibration metadata, version and allowable delta bounds. Use safe checkpoint loading (never unsafe pickle); verify every digest before inference.
- Acceptance: run before structure freeze on a copy; preserve road/lane IDs and direction, topological links, legal width, slope, curvature, elevation continuity and intersections. Run the real mandatory before/after gates on the same artifact snapshot; require strict PASS and objective improvement, else atomically discard. Recheck snapshot SHA and publish only via authoritative writer. CPU bound, optional CUDA resource/timeout/batch controls.
- Data: license-tagged manual/synthetic examples; grouped split by map/road/subgraph, deduplicate linked tiles, prevent geographic leakage. Calibrate on validation; test on held-out real maps, with confidence intervals and OOD strata.

None of these proposed future inference or training capabilities is present in this PR. No thresholds or geometry-promotion policy were altered.
