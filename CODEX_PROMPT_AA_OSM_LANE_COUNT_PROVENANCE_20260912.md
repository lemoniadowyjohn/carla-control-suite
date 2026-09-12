# Codex — PROMPT AA: connect OSM lane-count provenance to lane-successor repairs

## Context

Direct answer to "is lane predecessor/successor resolution informed by OSM": **no, still not**,
even after this session's W (`feature/lane-successor-hardening-v1-20260912`) made it geometry-aware
and fixed a dangling-reference bug. Re-verified fresh: grepped W's own changed files for "osm"/"OSM"
-- zero matches in `check_lane_section_successors.py`, `fix_missing_lane_successors.py`, or the new
`check_lane_link_targets_exist.py` detector.

Found the reason this gap still exists: the OSM-provenance machinery it would connect to is real but
**completely unmerged and currently inert**, spanning two separate, never-integrated branches:

1. `feature/lane-count-from-osm-v1-20260907` -- `LaneGenerator.ensure_lanes()` maps OSM
   `lanes:forward`/`lanes:backward`/`lanes` tags onto newly-generated driving lanes (only for roads
   that have no driving lanes yet), writing a `<userData><vector key="lane_count_source"
   value="osm:..."/></userData>` provenance tag per lane. Per its own report
   (`LANE_COUNT_FROM_OSM_REPORT.md`): focused fixtures pass, full verification incomplete in its
   sparse worktree, no map-of-record work done.
2. `feature/lane-count-change-gate-v1-20260908` -- `ultimate_pipeline/quality/check_lane_count_
   changes.py::check_lane_count_changes()`, a real, well-written, advisory-only checker that reads
   those SAME `lane_count_source` tags at every road-to-road link boundary and classifies the
   boundary as `NO_CHANGE` / `OSM_EXPLAINED_CHANGE` / `UNEXPLAINED_CHANGE`.

Verified directly: the current pinned map-of-record has **zero** `lane_count_source` tags anywhere
(`grep -c` returns 0). So even if you ran `check_lane_count_changes.py` against it today, every
single lane-count-change boundary would classify as `UNEXPLAINED_CHANGE` -- the OSM-explained
category is currently unreachable on real data, not because it's broken, but because nothing in the
live pipeline ever writes the provenance tags it depends on.

## PROMPT AA

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/osm-lane-count-provenance-v1-<date>.

TASK 1 (verify both source branches are still sound before merging anything): re-run whatever
focused tests exist on feature/lane-count-from-osm-v1-20260907 and feature/lane-count-change-gate-v1-20260908
in isolation first, against the current pinned map-of-record where applicable. Report pass/fail
honestly -- these branches are from 2026-09-07/08, verify they still apply cleanly and their claims
still hold before building on them, don't assume.

TASK 2: port LaneGenerator.ensure_lanes()'s OSM lane-count-provenance tagging into the current main
pipeline lineage (fix/post-audit-phase-e-junctions-roundabouts-20260803, NOT the isolated branch it
was built on) at whichever enrichment/geometry stage actually generates new driving lanes for roads
that don't have them yet -- find the real live call site, don't assume stage_04_enrichment.py without
checking. Confirm scope stays narrow (only newly-generated lanes get tagged, per the original design
-- do not retroactively tag existing/pre-existing lanes with a fabricated OSM source).

TASK 3: port check_lane_count_changes.py into the same lineage, wire it as an advisory report step
(it already says "advisory": true, "does not repair lane links" in its own claim_boundary -- keep
that framing, do not make it a hard gate).

TASK 4 (the actual connection, this session's real ask): in check_lane_section_successors.py's
_choose_best_target/geometry-aware fallback (from W, feature/lane-successor-hardening-v1-20260912 --
merge that branch in first or reproduce its exact function), when a boundary's lane-count change is
classified OSM_EXPLAINED_CHANGE by check_lane_count_changes, surface that as additional confidence
metadata on the repair decision (a "repair_basis" field or equivalent -- does not need to change
which target gets chosen, geometry already validated correctly, just make the OSM confirmation
visible when it exists). Do not let an UNEXPLAINED_CHANGE classification block or weaken an
otherwise-correct geometry-based repair -- OSM data being absent is not evidence the repair is wrong.

TASK 5: run against the pinned map-of-record and report the REAL number: after Task 2's narrow
tagging runs on a fresh regen (if one is practical in your environment; if not, say so explicitly
and report what you can from a copy of the pinned map instead), how many lane-count-change boundaries
now have real OSM provenance data at all, and of those, how many are OSM_EXPLAINED_CHANGE vs
UNEXPLAINED_CHANGE. This is the number that determines whether this connection is meaningful in
practice or still mostly inert due to narrow tagging scope -- report it honestly either way, do not
oversell a small number.

End with:
TASK_1_SOURCE_BRANCHES_STILL_SOUND: PASS | FAIL (per branch)
TASK_2_PROVENANCE_TAGGING_PORTED: PASS | FAIL -- <live call site>
TASK_3_CHECKER_WIRED: PASS | FAIL -- advisory, not a hard gate
TASK_4_REPAIR_BASIS_SURFACED: PASS | FAIL
TASK_5_REAL_COVERAGE: <tagged_lane_count_change_boundaries> / <total_lane_count_change_boundaries>, <OSM_EXPLAINED count>
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
```
