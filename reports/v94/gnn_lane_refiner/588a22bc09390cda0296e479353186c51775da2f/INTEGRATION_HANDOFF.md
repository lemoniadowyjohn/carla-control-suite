# V94 integration handoff

Repository: `lemoniadowyjohn/carla-control-suite`
Production base: `integration/production-large-map-20260918`, `225ed15d0da6444cc257835ca777aba281553f3c`.
Topic branch: `fix/v94-lane-gnn-failclosed-20261112`.
Implementation source commit: `588a22bc09390cda0296e479353186c51775da2f`. Code/test commits: `30cad8a408ebef489b38bdf9d34c4af5dc02223c` and `588a22bc09390cda0296e479353186c51775da2f`.
PR: https://github.com/lemoniadowyjohn/carla-control-suite/pull/31 (draft).

Changed code: `ultimate_pipeline/ml/lane_gnn_refiner.py`; new tests `tests/unit/test_lane_gnn_refiner_fail_closed_v94.py`. Reports under this directory are evidence only. Dependency footprint: Python stdlib + pytest for tests; no CARLA, torch, or numpy needed for disabled path. No shared `main_pipeline.py`, terminal authority or quality-gate file changed.

Entrypoint call graph: caller (currently none confirmed in main pipeline) -> `LaneGNNRefiner.run_inplace` -> validate threshold/device -> [no model: immutable DISABLED receipt] | [model supplied: LaneRefinementBlocked]. No XML writer, checkpoint loader, publish or gate sink is reachable. Importability itself must never be construed as operational ML.

Compatibility: previous `run_inplace` returned `None` and printed for both paths. New unconfigured path returns a false receipt; configured path raises, potentially breaking callers that silently ignored the stub. Audit any dynamic/reflection callers before integrating. No default production stage is enabled; do not make GNN a mandatory gate until a real implementation exists.

Integration order: 1. Independent review and full repo regression on exact PR HEAD. 2. Locate all runtime entrypoints, including dynamic imports and flags. 3. Serialize any future main-pipeline hook with release-gate owner, before structure freeze and final acceptance. 4. Add approved training artifact + safety projection + before/after mandatory gates + atomic rollback. 5. Held-out evaluation, actual CARLA runs, operator approval. No merge authorized by this handoff.

Rollback: revert the topic-branch commits through a normal reviewable revert; do not hard reset or force push. Reverting removes the safe boundary and restores dangerous silent success, so disable all ML use until replacement verified. Operator actions: supply licensed labeled data, checkpoint, hardware/runtime scope, independent reviewers and full-suite access.

Final verdict: **REQUIRES_CHANGES**, GNN feature **BLOCKED_DATA**; isolated disabled-mode source behavior verified only.
