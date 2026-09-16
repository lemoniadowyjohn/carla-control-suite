# Declared predecessor/successor link-rate gap — investigation and fix

Date: 2026-09-16

## Trigger

`reports/production_readiness/20260915T101724Z_FRESH_DOMAIN_GAP_REGEN/full_report.json`
(`connectivity_gap`) showed `predecessor_valid_rate`/`successor_valid_rate`/
`road_lane_link_valid_rate` all at 1.0 for both maps (link *validity* is fine), but the
*declared*-link rate — whether a `<road><link><predecessor>`/`<successor>` element is present at
all — was auto ~0.29 vs. manual ~0.94, a large unexplained gap, noted in
`docs/research/THESIS_TO_CURRENT_PROGRESS.md` as "mostly absent on junction-connector roads."
This investigation determines why, with direct evidence rather than assumption.

## Conclusion: REAL BUG, FIXED (not a legitimate spec difference)

The gap was caused entirely by `ultimate_pipeline/tools/xodr_carla_hardener.py`'s
`_fix_connectivity()`, which unconditionally deleted the road-level `<link>` element from every
junction-connector road (`road.junction != "-1"`) — regardless of whether that link was valid —
under an undocumented, un-cited comment: "Junction connectors should not have road-level links."

That premise is directly contradicted by two independent, real data sources inspected in this
investigation (see `evidence.json` for exact counts):

1. **The manual/RoadRunner-authored reference map** (`Grid0828.xodr`): 725/725 (100%) of its
   junction-connector roads declare `<link><predecessor>` and `<successor>`, referencing the
   incoming/outgoing road by id with a `contactPoint`. Junction-connector roads are in fact the
   roads *most* likely to carry a declared link in the manual reference (100%, vs. 76-88% for
   ordinary roads) — the opposite of what the hardener's premise implies.
2. **This pipeline's own OSM-based generator**, on the current pin
   (`ingolstadt_perception_map_of_record_20260905_202847.xodr`, sha256 `2ca342d8ae4bee39…`):
   22,589/22,589 (100%) of junction-connector roads already have a correct, fully valid
   `<link>` *before* the hardener runs. The hardener's `JUNCTION_LINK_REMOVED` finding count on the
   fresh run (22,589) matches the junction-connector road count on the pin exactly — it stripped
   every single one.

Both maps' declared links, where present, were also already 100% *valid*
(`predecessor_valid_rate`/`successor_valid_rate` = 1.0) — so the hardener was not cleaning up
dangling or malformed references. It was deleting correct, spec-consistent topology data wholesale.

### Why the two link mechanisms are not redundant

A junction's `<connection>` element (with its `<laneLink>` children) exists to let a junction
**disambiguate which of several alternative connecting roads** to use for a given
incoming-road + turn, at the lane level. It is not a substitute for the connecting road's own
`<link><predecessor>/<successor>`, which is what lets a consumer that walks the network
**road-by-road** (CARLA's `Waypoint::GetNext()`/`GetPrevious()`, and this pipeline's own
lane-continuity phases such as `phase_g4_lane_continuity.py`) cross a junction connector without
needing junction-aware special-casing. Both the manual reference and this project's own generator
independently converge on populating both — strong evidence this is the correct, expected
OpenDRIVE convention for this map class, not an optional redundancy.

## Fix

`ultimate_pipeline/tools/xodr_carla_hardener.py::_fix_connectivity()`:
- Removed the unconditional `JUNCTION_LINK_REMOVED` block that deleted every junction-connector
  road's `<link>` regardless of validity.
- The pre-existing junction-membership check (`_validate_junction_connector`, confirming the
  connector appears in its junction's `<connection>` list) is unchanged.
- The pre-existing "remove link if target road doesn't exist" validation (previously applied only
  to non-junction roads) now applies uniformly to **all** roads, including junction connectors —
  so a connector road with a genuinely dangling link reference is still correctly repaired
  (`ROAD_LINK_REMOVED`), just no longer unconditionally.

Tests (`tests/unit/test_xodr_carla_hardener.py`):
- Replaced `test_fix_connectivity_junction_connector_road_link_removed` (asserted the old, now
  reverted, incorrect behavior) with:
  - `test_fix_connectivity_junction_connector_valid_road_link_preserved` — a connector road with a
    valid `<link>` pointing at existing roads is left untouched.
  - `test_fix_connectivity_junction_connector_dangling_road_link_removed` — a connector road with a
    `<link>` pointing at a nonexistent road is still repaired.

`docs/research/THESIS_TO_CURRENT_PROGRESS.md` updated in place (search "2026-09-16 update").

## Before/after (real measurement, current pin, no mocks)

`ultimate_pipeline.domain_gap.connectivity_gap.ConnectivityGap.compute()` against
`campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr`:

| metric | before fix | after fix | manual |
|---|---|---|---|
| auto predecessor_declared_rate | 0.2898 | 0.9898 | 0.9355 |
| auto successor_declared_rate | 0.2898 | 0.9899 | 0.9678 |
| gap (auto − manual) predecessor_declared_rate | −0.6458 | **+0.0543** | — |
| gap (auto − manual) successor_declared_rate | −0.6779 | **+0.0221** | — |
| predecessor_valid_rate / successor_valid_rate (both maps) | 1.0 | 1.0 | 1.0 |

The gap closes from ~65-68 percentage points to ~2-5 points (auto now slightly *exceeds* manual,
consistent with manual's own non-junction roads being only 76-88% linked vs. auto's 96.6%).

Full raw numbers and direct per-map junction-connector sampling counts: `evidence.json` in this
directory.

## Test suite

Targeted: `pytest tests/unit/test_xodr_carla_hardener.py` — 35 passed.
Full bare `pytest` suite run on this branch before pushing — see the branch's commit message /
handback report for pass/fail counts.

## Scope note

This is a `campaigns/` + `ultimate_pipeline/` + `tests/` + `docs/` change only.
`submission/infrastructure/` was intentionally **not** touched — it carries its own mirrored copy
of `xodr_carla_hardener.py` with the same old behavior, but per
`docs/.../project_mirror_sync_policy_correction_20260828` syncing into `submission/infrastructure/`
outside the 6 CRITICAL_MIRRORED_FILES is out of scope for this branch.
