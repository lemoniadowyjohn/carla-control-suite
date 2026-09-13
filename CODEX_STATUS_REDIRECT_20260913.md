# Status check + redirect (2026-09-13)

Checked progress on PROMPT BB and PROMPT CC. Findings and a request below.

## PROMPT BB (structure-elevation CRS blocker) — confirmed in progress, keep going

Found real work on `feature/structure-elevation-crs-blocker-v1-20260913`
(commit `7a42365f`, "fix(elevation): preserve local XODR CRS provenance" —
`dem_crs_contract.py`, `elevation_importer.py`, `structure_classifier.py`,
`opendrive_geometry_kernel.py`, `stage_05_geometry.py` + tests, 293 lines).
This is unpushed as of this check. **No concerns with the approach from a
skim — please keep going and push when it's ready**, including your own
verification against the pinned map (`campaigns/ingolstadt_cooked_perception_v1/
candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`,
sha256 `2ca342d8...`), not just synthetic fixtures.

## PROMPT CC (roundabout-v2 real-map validation) — not started, please pick up next

No branch, worktree, or commit anywhere matches this prompt yet. This is
still open — please prioritize it once BB is pushed.

## One process note: please don't keep growing a second full integration branch

`integration/production-map-quality-v1-20260912` (and its `feature/*-f195-*`
predecessors) has grown into a second, independent consolidation of most of
the same 31-branch backlog that's already been merged, tested, and pushed as
`integration/session-batch1-20260912` (HEAD `f8b395f8` as of this note). The
two branches now diverge (neither is an ancestor of the other) and cover a
lot of the same files, which creates real reconciliation risk for no benefit
— e.g. `integration/production-map-quality-v1-20260912` is missing 3 bug
fixes already verified and merged on the other side (`46e1cacd` OSM
way-direction computation for the turn-classification audit, `af858d6d`
asymmetric road-polygon buffering in `semantic_overlap.py`, `f8b395f8`
unit-aware speed-limit comparison in `speed_limit_writer.py`).

**Request**: once BB and CC are ready, please base/rebase them onto
`integration/session-batch1-20260912` rather than continuing to extend
`integration/production-map-quality-v1-20260912` as a parallel "final"
candidate. If there's something genuinely unique in that branch beyond
BB/CC's own scope that isn't already in `integration/session-batch1-20260912`,
flag it explicitly rather than folding it in silently — happy to look at it
directly. (One good independent cross-check from that branch, for what it's
worth: `0593e4ce` found and fixed the same parampoly3-connector-rebuild
fixture bug already fixed on `integration/session-batch1-20260912` at
`5bca810d` — same root cause, found independently ~16h later. Nice
confirmation that one was real.)
