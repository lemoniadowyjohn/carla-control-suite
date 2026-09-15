# OC-2 Topology Component Hardening — Evidence Pack

Branch: `fix/topology-component-hardening-v1-20260915`
Worktree: `F:\carla-control-suite-worktrees\oc2-topology-component-hardening-v1-20260915`
Base SHA: `6f76f37f` — commit message `chore: commit another densest-tile FBX generation probe iteration`
FINAL SHA (HEAD): `22442c9afc6679fff537dd829800fd9597daafa0`
Source authority: `reports/production_readiness/20260915T203000Z_COMPREHENSIVE_GAP_AUDIT/TOPOLOGY_COMPONENT_AUDIT.json`
head_sha pinned by audit: `540b5c5f12b10ff1f1add6fa51cc2c5cabea2c2a`

RESULT: **READY_FOR_REVIEW**

## Scope

| Item | Audit token | Status |
|---|---|---|
| D1 | `map_connectivity` | DONE |
| D2 | `literal_vs_recovered_topology` | DONE |
| D3 | `junction_connectors` | DONE |
| D4 | `roundabout_reconstructor` (fail-closed default) | DONE |
| D5 | `quality_gates` | DONE |
| — | `validator_purity` | OUT_OF_SCOPE (separate architecture refactor; not requested) |

## Commits (new only, no amend/rebase/force-push)

1. `6132d89d` oc2-d1: component classifier for island quarantine (preserve UNKNOWN/INTENTIONAL)
2. `ccf43dc2` oc2-d5: QualityStatus governed-waiver vocabulary (additive, keeps ReleaseProfile TypeAlias)
3. `3706a93c` oc2-d2: literal-spec reachability + topology certification (SPEC gate, governed waiver)
4. `deb4b930` oc2-d3: junction connector association classification (fail-closed ambiguous skip, direct-line heading guard)
5. `22442c9a` oc2-d4: roundabout reconstruction fail-closed default (no SETTINGS key == disabled)

Note on ordering: commits were landed in the order D1 -> D5 -> D2 -> D3 -> D4; the branch contains all five additively on top of `6f76f37f`.

## Files changed (13, +1990 / -27)

Production:
- `ultimate_pipeline/topology/component_classifier.py` (new) — D1
- `ultimate_pipeline/quality/map_hygiene.py` — D1 (classify_components in quarantine_island_roads)
- `ultimate_pipeline/contracts/stage_contracts.py` — D5 (QualityStatus, WARNING_REGISTRY, governed_waiver_allowed)
- `ultimate_pipeline/quality/map_acceptance.py` — D2 (literal summary, waiver, new metrics)
- `ultimate_pipeline/quality/topology_certification.py` (new) — D2
- `ultimate_pipeline/topology/junction_connector_classifier.py` (new) — D3
- `ultimate_pipeline/tools/junction_connector_snap.py` — D3 (skip_ambiguous fail-closed + counters)
- `ultimate_pipeline/topology/junction_connector_rebuild.py` — D3 (ConnectorValidator.CLASSIFICATION_* + classify, direct-line heading guard)
- `ultimate_pipeline/topology/roundabout_reconstructor.py` — D4 (default True -> False)

Tests (new)/regression:
- `tests/unit/test_component_classifier.py` (new) — D1
- `tests/unit/test_topology_certification.py` (new) — D2
- `tests/unit/test_junction_connector_classifier.py` (new) — D3
- `tests/topology/test_roundabout_reconstructor.py` (extended) — D4 regression

## Gate vocabulary (D5)

`SPEC_TOPOLOGY` / `RECOVERY_DIAGNOSTIC` semantics per audit:
- Production certification uses the LITERAL spec graph only
- Recovery diagnostics are diagnostic-only (never PASS producers)
- Missing evidence -> INCOMPLETE (fail-closed)
- Mandatory FAIL to aggregate PASS requires explicit governed waiver (downgrades to WAIVED)

## Test sweeps (all green)

- `tests/unit`: 1877 passed, 3 skipped (captured in `test_sweep_tests_unit.txt`)
- `tests/topology tests/quality tests/domain_gap tests/opendrive_geometry tests/roadrunner tests/carla_tools tests/phase_q` + root-level r13/crosswalk/stage_i tests: 2774 passed, 78 skipped (captured in `test_sweep_rest.txt`)
- Total: 4651 passed, 81 skipped, 0 failures

## Merge coordination flags

- Concurrent large-map branch (`37c40d18`) carries its OWN `QualityStatus`, roundabout `False` default, `ConnectorValidator.CLASSIFICATION_*` + `classify`, plus `test_audit_remaining.py`/`test_warning_taxonomy.py`/`test_quality_status.py` and copied OC-1 content. Dedupe identical surfaces at merge; none of those files exist at OC-2 baseline and none are created here.
- OC-1 delivered separately on `fix/geometry-crs-dem-correctness-v1-20260915` @ `395a5133...`.
- Frozen twin `submission/infrastructure/ultimate_pipeline/quality/map_acceptance.py` untouched (different API).

## Notes

- No CARLA/Unreal run, no map-of-record pins regenerated, no `submission/` edits.
- Baseline branch has an active background FBX tile-probe process writing timestamped `reports/production_readiness/20260915T2*_TILE_BASED_FBX_GENERATION_PROBE/` dirs; those are byproducts of the base branch's own flow and are left untracked. Evidence pack `git add` is explicit (no `-A`).