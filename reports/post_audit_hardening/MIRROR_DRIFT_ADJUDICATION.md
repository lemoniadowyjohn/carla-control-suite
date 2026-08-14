# Mirror-Drift Adjudication (Claude Opus 4.8, 2026-08-13)

Adjudicates the "DECISION NEEDED (Claude)" section of `MIRROR_DRIFT_INVENTORY.md`
(33 drifted pairs between `ultimate_pipeline/` and `submission/infrastructure/ultimate_pipeline/`).

## Determinant: is the submission mirror executed?

Investigated, evidence:
1. **No production code imports it.** `git grep "submission.infrastructure" -- '*.py'` (excluding `submission/`
   itself) hits only `tests/phase_q/test_duplicate_module_drift.py` (reads via `filecmp`, not import) and one
   scratch report script. No pipeline / certifier / entrypoint imports the mirror.
2. **The test suite excludes it.** `pytest.ini` → `norecursedirs = … submission …`. Never collected, never run.
3. **It is a self-contained thesis deliverable.** Own `README.md`, `ARCHITECTURE_STATUS.md`,
   `DEPRECATION_POLICY.md`, `THESIS_DELIVERABLES.md`, `docs/INSTALL.md`, etc. (565 `.py` files).

**Conclusion: `submission/infrastructure/ultimate_pipeline/` is an INERT, archived reproducibility bundle** —
a frozen snapshot, not a live execution path.

## Verdict on the 33 drifts

**LEAVE ALL 33. Do NOT reconcile. Add ZERO new drift-guard entries.**

Rationale: the divergence is *intentional frozen-snapshot* divergence, not a bug. Forcing the trees identical
would be wrong in both directions:
- syncing mirror→canonical would pull **stale/stubbed** submission code into the live pipeline (regression);
- syncing canonical→mirror would overwrite a **frozen thesis deliverable**, destroying its provenance.

The only files that must stay in sync are those a reproduction run would load. Those are the 6 on the drift
guard's `CRITICAL_MIRRORED_FILES` (`core/carla_opendrive_loader.py`, `core/xodr_hash_gate.py`,
`carla_tools/map_identity_guard.py`, `quality/check_carla_opendrive_compat.py`, `tools/load_final_into_carla.py`,
`core/opendrive_gen_diagnostic.py`) — **all currently identical and guarded**. Guard scope is correct as-is.

## Documentation caveat (not a fix)

Three mirror files are near-empty **stubs**, so the submission bundle can reproduce *certification from frozen
artifacts* but **cannot regenerate maps** for these modules:
- `elevation/elevation_seam_fixer.py`  — 289 B (canonical 8770 B)
- `tools/junction_connector_rebuild.py` — 196 B (canonical 19150 B)
- `topology/topology_repair.py`         — 3563 B (canonical 40398 B)
This is expected for a reproduce-from-frozen bundle; recorded here so no one assumes the bundle re-runs generation.

## Category summary

| Action | Count | Files |
|---|---|---|
| LEAVE + DOCUMENT (intentional divergence) | 33 | all drifted pairs in the inventory |
| SYNC (bug) | 0 | — |
| ADD DRIFT-GUARD | 0 | critical set already identical + guarded |

## Related: Escalation 1 (length-invariant docstring)

Resolved in the same cycle. `run_n_certify.py::_length_invariant_evidence` docstring was corrected to match the
(crash-safe, correct) implementation: missing/unparseable length → skipped (not in `roads_checked`); non-positive
declared length with geometry → **violation** (it trips CARLA's `s <= GetLength()` assert). Locking tests added:
`test_length_invariant_non_positive_length_with_geometry_violates`,
`test_length_invariant_negative_length_with_geometry_violates`, `test_length_invariant_missing_length_skipped`;
and opencode's degenerate case renamed to `test_length_invariant_zero_length_zero_geometry_no_violation`.
Escalation 2 (G2 anchor pins superseded candidate `80ebb00`) needs no action — it is the expected stale-anchor
state that flips only on the live-CARLA re-collection.
