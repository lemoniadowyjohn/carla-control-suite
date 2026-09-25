# Known Limitations

- RQ3 has no valid paired generated/manual Ingolstadt capture because the live CARLA RPC/runtime boundary has not yet been closed on the governed source-build path.
- RQ5(a) has no generated-train/manual-test transfer result and depends on valid RQ3 datasets.
- RQ5(b) has no appropriate labeled real-world Ingolstadt dataset and remains deferred.
- GAP-026 is a real map-quality concern on the current promoted map: lane-link continuity requires generator-level remediation and governed regeneration before the map is treated as final for live RQ3/RQ5 routes. Do not close it by relaxing tolerances or patching the promoted XODR in place.
- UE4 editor/compiler readiness is separate from CarlaUE4 project compilation, custom-map import, cook/package, and runtime RPC. None of those later gates may inherit PASS from the engine build alone.
- Current Large Map staging/cook tooling is still being hardened for strict final-release semantics. Probe/incremental staging evidence must not be relabeled as a complete CARLA import/cook result.
- RQ2 current measurements are local, registered comparisons; they do not by themselves prove improved whole-map quality over the thesis. If the automatic map pin changes after a generator repair, current RQ2 evidence must be rebound/recomputed for that pin.
- RQ1 timestamp normalization identifies the observed difference in committed fixtures, but exhaustive byte-source isolation and complete OSM-to-final repeated-run coverage remain bounded.
- RQ4's leak-free five-seed extension is supported by passing leakage audits, but durable preservation/retrieval of the large training artifacts/checkpoints should remain explicit rather than inferred from one local workspace.
- Large `run_*.xodr` artifacts are intentionally not required for portable CI.
- GitHub currently defaults to historical `main`; active engineering authority is `integration/production-large-map-20260918` until the governance migration is explicitly completed.
- A clean remote branch does not prove local worktrees are clean. Follow `docs/engineering/WORKTREE_HYGIENE.md` before integration, retirement, or deletion of any worktree.
