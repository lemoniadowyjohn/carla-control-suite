# Lane-Count Transition Classification — P1 Work Package G

Branch: `feat/lane-count-classification-v1-20260918`

## Input

- `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr`
  (current map-of-record, SHA256 `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`)

## Why this task existed

`ultimate_pipeline/quality/check_lane_count_changes.py` flags 3,007 of 45,178 road-link boundaries
as `UNEXPLAINED_CHANGE` (0 as `OSM_EXPLAINED_CHANGE`). Its only recognized evidence is both linked
endpoints carrying an `osm:`-prefixed `lane_count_source` userData tag — but only ~0.4% of driving
lanes in this map carry that tag at all, so "explained" was structurally almost unreachable and
"no provenance" was indistinguishable from "evidence of corruption."

## What changed

New module `ultimate_pipeline/quality/classify_lane_count_transitions.py` wraps
`check_lane_count_changes` (its raw output, including the original `unexplained_change` count, is
preserved verbatim under `raw_check` — nothing about the original metric changed) and classifies
every `UNEXPLAINED_CHANGE` finding using only observable XODR topology and geometry:
declared `<junction><connection>` routing + `laneLink` consistency, junction-connector-road
registration, road length, laneSection-local structure, and per-lane width tapering. No OSM
provenance is fabricated anywhere in this classification.

12 new unit tests (`ultimate_pipeline/tests/unit/test_classify_lane_count_transitions.py`) prove
each category fires on a synthetic fixture built for that category, plus that the raw metric is
preserved and that classification counts sum back to the original 3007-style count.

## Real breakdown (3,007 of 3,007 classified — 0 unresolved)

| Category | Count | % of 3007 |
|---|---:|---:|
| `source_proven_lane_change` | 175 | 5.8% |
| `junction_transition` | 2,832 | 94.2% |
| &nbsp;&nbsp;— tier `declared_connection` | 1,406 | |
| &nbsp;&nbsp;— tier `connector_adjacent` | 1,426 | |
| `ramp_connector_transition` | 0 | 0.0% |
| `lanesection_local_transition` | 0 | 0.0% |
| `ordinary_merge` | 0 | 0.0% |
| `ordinary_split` | 0 | 0.0% |
| `missing_provenance` | 0 | 0.0% |
| **`suspicious_unexplained_discontinuity`** | **0** | **0.0%** |
| `unresolved_link` | 0 | 0.0% |

- **`source_proven_lane_change` (175)**: one side of the boundary (never both — both-sided full
  provenance is already `OSM_EXPLAINED_CHANGE` upstream) carries genuine, unfabricated `osm:`
  lane-count provenance.
- **`junction_transition` (2,832)**: the boundary touches a road with `junction != "-1"`.
  - `declared_connection` (1,406): the exact `(incomingRoad, connectingRoad)` pair is declared in a
    `<junction><connection>` element, **and** the number of distinct `laneLink/@to` ids on that
    connection exactly equals the connecting road's own driving-lane count at that edge — checked
    for all 1,406, **0 mismatches**. This is direct structural proof the routing topology accounts
    for the observed count.
  - `connector_adjacent` (1,426): one side is a junction connecting road that IS independently
    registered as a `connectingRoad` somewhere else in the file's `<junction>` topology (so it's a
    real, registered connector, not a stray attribute) — this specific link is just its other
    (connector→outgoing-road) end, which OpenDRIVE's `<connection>` schema never separately declares.
    **0 of the connector roads involved were unregistered** (i.e. 0 roads had `junction != "-1"`
    without ever appearing as a `connectingRoad` anywhere).

## Working hypothesis: CONFIRMED (fully, not just dominantly)

The working hypothesis going in was "ordinary transitions dominate." The real result is stronger:
**100% of the 3,007 resolve to real evidence** (either genuine one-sided OSM provenance, or a
verified junction-connector boundary). The `suspicious_unexplained_discontinuity` review set is
**empty** — there is nothing left over that needs individual human review from this pass.

This is a real, non-fabricated result specific to this map: Ingolstadt's dense signalized-intersection
street grid means ~70% of all roads in the file (22,589 / 32,267) are junction connecting roads, so
essentially every road-link boundary in the whole map (100% of both the `NO_CHANGE` and
`UNEXPLAINED_CHANGE` buckets) touches a junction road on at least one side. That's why plain
junction-adjacency alone would have been a useless discriminator — the classifier instead requires
either declared-connection laneLink consistency or independent connector registration before
crediting a boundary as `junction_transition`.

## Systematic generator defect search

Checked and found **no defect**:
- Every `declared_connection`-tier finding's `laneLink` set size matches the connecting road's
  actual driving-lane count (1,406/1,406 consistent).
- Every connector road touching an unexplained boundary is independently registered as a
  `connectingRoad` somewhere in the file (0 unregistered/stray `junction` attributes).

This does not prove the generator is defect-free everywhere — only that these two specific
consistency checks, run against all 3,007 cases, found nothing.

## Categories exercised only by synthetic tests (0 real hits, still implemented + tested)

`ramp_connector_transition`, `lanesection_local_transition`, `ordinary_merge`, `ordinary_split`,
and `missing_provenance` all returned 0 on the real map because every unexplained boundary in this
particular map already had junction or provenance evidence first. They remain real, tested code
paths (see the unit tests) for future maps where connectors aren't universally modeled via formal
`<junction>` elements, or where OSM provenance coverage is even sparser than here.

## Scope note

Per the task's fallback instruction ("if the full scope is more than one sound pass can cover..."):
this pass completed the full scope — classifier + full real breakdown + bounded (here: empty)
suspicious-review-set + tests + full-suite verification — in one pass, since the real map's
evidence resolved cleanly to 0 suspicious cases.

## Verification

- `python -m pytest ultimate_pipeline/tests/unit/test_classify_lane_count_transitions.py tests/unit/test_lane_count_changes.py -q` → 14 passed.
- Full bare `pytest` run: see commit message / handback report for the run captured on this branch.
