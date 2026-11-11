# V94 lane GNN refinement: fail-closed safety boundary

## Verified defect
On production base `225ed15d0da6444cc257835ca777aba281553f3c`, `ultimate_pipeline/ml/lane_gnn_refiner.py` (Git blob `1e25cffc053c405ca1ee810edb41a0e02b08d374`) prints "stub active" and returns `None` even when `model_path` is provided. It does not run a model, measure confidence, modify geometry or run quality gates. The actual `main_pipeline.py` has an import at line ~806, but no confirmed call to `run_inplace` in the inspected file.

Reproduced before repair: `python behavioral_control.py <verified-old-source-path>` exits 1. Exact original blob was reconstructed and Git blob identity verified; the control explicitly asserts that a configured model must be rejected rather than silently accepted.

## Minimal safety repair
- `run_inplace(root, model_path, device='cpu', confidence_thresh=0.7)` retains its positional arguments.
- No model path (`None` or empty string) yields immutable `LaneRefinementReceipt(status='DISABLED', ok=False, applied=False, release_eligible=False, quality_gates_run=False)`. It is deliberately false in a Boolean context and has JSON-compatible `to_dict()`.
- Any supplied nonempty/whitespace/PathLike/checkpoint argument raises `LaneRefinementBlocked(code='BLOCKED_MODEL_UNVALIDATED')` before any filesystem, GPU or XML work.
- Invalid threshold/device arguments raise explicit `INVALID_THRESHOLD` / `INVALID_DEVICE`.
- No checkpoint deserialization, inference, geometry correction, quality gate, or artifact publication is claimed. No change to `main_pipeline.py` or release-gate code.

## Impact and status
The prior no-op pretending to be an active refinement stage is repaired in source, and the isolated safety test cases pass. This is NOT `IMPLEMENTED_SOURCE_ONLY` for a real GNN. Overall verdict: **REQUIRES_CHANGES; actual GNN capability BLOCKED_DATA**. No operator release or merger is authorized by these results.
