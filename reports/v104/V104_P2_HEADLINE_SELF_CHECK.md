# V104 P2 — Self-check of the OpenCode O1 headline finding

**Author:** OpenCode
**Date:** 2026-11-12
**Scope:** the V103-O1 directional-coverage headline finding, before anyone relies on it
**Branch:** `fix/v103-o1-osm-direction-lane-counts` (PR #39)
**Base:** `integration/production-large-map-20260918` @ `225ed15d0da6444cc257835ca777aba281553f3c`

---

## 1. Summary

| Question | Answer |
|---|---|
| Is the coordinate-frame defect real? | **YES** — reproduced by execution, on the pinned manual map. |
| Does the fix change the governed map-of-record? | **NO** — 5000/5000 projected points are bit-identical. |
| Is the headline "1.44% matched" figure correct? | **NO** — it divided a road numerator by a way denominator. **Retracted.** |
| Does a "coverage PASS" now imply adequate coverage? | **NO** — fixed: the adequacy verdict is now separate and explicit. |
| Do any frozen thesis / RQ numbers change? | **NO** — see §6. Two forward-looking caveats are stated. |

**The defect and the fix survive. The headline *percentage* was wrong, and the
"coverage PASS" framing was misleading. Both are corrected here.**

---

## 2. The coordinate-frame defect is REAL — reproduced, not asserted

The V103-O1 commit `7d21e476` claimed that `project_positioned_osm_metadata_ways`
projected the OSM source ~161 km from the map's own coordinates because it
ignored the XODR's declared CRS.

**Method.** The base implementation (`F:\v103\base`) and the fixed
implementation (`F:\v103\o1`) were run in *separate processes* against the same
pinned inputs, and their projected coordinates compared point by point.

| Map | Declared CRS | `<offset>` | Points compared | Bit-identical | Displacement (min/median/max) |
|---|---|---|---|---|---|
| Manual `Grid0828.xodr` | `+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 …` (UTM 32N) | **absent** | 5000 | **0 / 5000** | 172,092 / **172,757** / 173,654 m |
| Map-of-record `ingolstadt_perception_map_of_record_20260916_232831.xodr` | `+proj=tmerc` | **present** (832671.676, 5458671.104) | 5000 | **5000 / 5000** | 0.000 / **0.000** / 0.000 m |

Pre-fix, **0 of 800** sampled OSM points fell inside the manual map's road
bounding box (`x[678016, 682411] y[5402486, 5405403]`); post-fix, **175 of
800** do. The pre-fix projection landed at `841663, 5468125` where the map's
own frame is `680820, 5405174`.

**Verdict: confirmed.** The defect is real, the fix is correct, and the fix
is a **byte-identical no-op for the governed map-of-record** — the governed
map carries an `<offset>` element and stores local coordinates, so it takes the
unchanged branch.

The end-to-end effect on the pinned manual pair:

| | matched roads | coverage status |
|---|---|---|
| before the fix | **0** of 3057 projected ways matched | `BLOCKED_INPUT` |
| after the fix | **44** matched (38 forward, 6 reversed, 0 not-assessable) | contract `PASS` |

---

## 3. RETRACTION — the "1.44%" headline was a unit error

The V103-O1 report and the V104/V105 state files state the result as
*"44 of 3057 roads matched is 1.4%, authoritative 35/3057 = 1.14%, yet reported
PASS"*.

**That ratio is not a rate.** It divides an **XODR-road** numerator (44, 35)
by an **OSM-way** denominator (3057). The coverage report's `counts` block
mixes the two populations in one namespace:

* `matched`, `authoritative`, `forward`, `reversed`, `ambiguous`,
  `conflicting`, `not_assessable`, `fallback` — **XODR roads**
* `correspondence_exact`, `correspondence_high`, `ambiguous_correspondence`,
  `unmatched_correspondence` — **OSM ways**

Nothing in the payload stated which population 3057 belonged to, so the only
arithmetic a reader could perform was the wrong one.

### The correct statements (all measured, manual map, 993 XODR roads)

| Metric | Value | Denominator |
|---|---|---|
| OSM ways matched EXACT/HIGH | 68 / 3057 = **2.22%** | OSM ways |
| XODR roads with a match | 44 / 993 = **4.43%** | XODR roads |
| XODR roads authoritative | 35 / 993 = **3.52%** | XODR roads |

### The same measurement on the **map-of-record** (32,267 XODR roads)

| Metric | Value |
|---|---|
| OSM ways matched EXACT/HIGH | 94 / 3057 = **3.07%** |
| XODR roads with a match | 75 / 32,267 = **0.23%** |
| XODR roads authoritative | 41 / 32,267 = **0.13%** |

**The road-level coverage on the governed map is 0.23%, an order of magnitude
lower than on the manual map.** The PR's headline number came from the manual
map because the manual map is the only one whose CRS the old code got wrong;
the governed map was never affected by the defect at all.

---

## 4. Reconciliation with the earlier repository figures

The reviewer asked for the 1.4% to be squared with the earlier evidence. The
repository contains several similar-looking percentages. **They measure
different things over different populations and must not be conflated.**

| Figure | Source | Population | Denominator | What it measures |
|---|---|---|---|---|
| **0.0000%** | `reports/post_audit_hardening/OSM_META_INDEX_NAME_MATCH_FIX.md:12-13` | 32,297 XODR roads | direct-id lookup | A **bug**: `road.get("id")` vs OSM way id. Since fixed. Different mechanism (id lookup, not spatial). |
| **0.019%** (6/32,297) | `reports/post_audit_hardening/C32_ROAD_CONNECTIVITY_CHARACTERIZATION.md:57` | 32,297 XODR roads | connectivity self-links | **Road connectivity**, not OSM correspondence. An unrelated soft WARN. |
| **0.4%** | `docs/runtime/MAP_OF_RECORD.md:23`, `reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/lane_count_classification.md:14-15` | lanes | `lane_count_source` tag coverage | **Lane provenance tags**, not correspondence. "the 'explained' classification is structurally almost-unreachable". |
| **1.14% / 1.44%** | V103-O1 headline (this report) | — | — | **RETRACTED** — mixed units. |
| **2.22% / 4.43% / 3.52%** | this report (corrected) | 3057 OSM ways / 993 XODR roads | stated | OSM↔XODR correspondence on the manual map. |
| **3.07% / 0.23% / 0.13%** | this report | 3057 OSM ways / 32,267 XODR roads | stated | The same on the **map-of-record**. |

**The 0.4% and the 1.14% are not the same quantity and neither is a
contradiction of the other.** The 0.4% says the *lane provenance tag* is
almost absent from the governed map, so the "explained" lane-transition
classification is structurally unreachable. That is the same underlying
reality as the 0.13% authoritative road coverage: **OSM enrichment barely
reaches this map.** The two independently corroborate each other.

The **0.0000%** and **0.019%** figures are over a *different population*
(32,297 roads — the map-of-record's road count at the time those reports
were written; the current pinned map has 32,267) and measure *id-lookup
matching* and *connectivity* respectively. They are not earlier versions of
this number.

### The existing test that asserts a nonzero match

Three tests assert a nonzero correspondence, and **all three are synthetic**:

* `tests/unit/test_osm_xodr_correspondence.py:105` — `eligible_road_count == 1`
* `tests/unit/test_positioned_osm_metadata.py:112` — `eligible_road_count == 1`
* `tests/unit/test_stage07_structural_osm_metadata.py:41` — `eligible_road_count == 1`

They build a one-road fixture and assert one match. They are **not** a
nonzero-match assertion about the real map, and they do not conflict with
the corrected rates. There is **no test in the repository that asserts a
nonzero correspondence rate on a real map** — which is precisely why a
1.44% rate could be reported as `PASS` without a test failing.

---

## 5. The fix — "coverage PASS" can no longer be read as "coverage is adequate"

The defect was not only a wrong percentage in a report; the *payload itself*
had no way to express "the coverage is low". Two changes were made.

### 5.1 Both populations are stated, and every rate has a matching denominator

`directional_coverage_report` now emits:

```json
"population": {
  "xodr_road_count": 993,
  "osm_way_count": 3057,
  "xodr_road_count_note": "denominator of matched_road_rate_percent and authoritative_road_rate_percent",
  "osm_way_count_note": "denominator of matched_way_rate_percent; NOT a road denominator"
},
"rates": {
  "matched_road_rate_percent": 4.431,
  "authoritative_road_rate_percent": 3.5247,
  "matched_way_rate_percent": 2.2244,
  "matched_road_count": 44,
  "authoritative_road_count": 35,
  "matched_way_count": 68
}
```

When the road population is unknown the road-level rate is `null` — never a
number computed against the wrong denominator.

### 5.2 The adequacy verdict is separate from the contract verdict

The frozen V103-O1 contract (dispatch item 5) defines the status as
*"missing OSM source is BLOCKED_INPUT; zero matched roads cannot be PASS for
release-required directionality"*. That is a **contract** verdict — does
authoritative directional evidence exist — and it is unchanged.

The **adequacy** verdict — is the coverage good enough — is now a separate
block:

```json
"coverage_qualification": {
  "status": "UNDECLARED_THRESHOLD",
  "reason": "no_declared_minimum_authoritative_rate",
  "minimum_authoritative_rate_percent": null,
  "note": "the coverage status above is the CONTRACT verdict … a PASS here must not be read as 'the coverage is adequate'."
}
```

A caller that *does* declare a minimum gets `MEETS_MINIMUM` / `BELOW_MINIMUM`
with the measured rate in the reason. **No threshold is declared by this
change** — declaring one is a scientific-policy decision for the owner, and
inventing a number here would be exactly the fabrication the project rules
forbid.

### 5.3 Tests

* `tests/unit/test_v104_p2_coverage_honesty.py` — **9 tests** (new API).
* `tests/unit/test_v104_p2_coverage_behaviour.py` — **3 tests** using only the
  **pre-existing** API, so they fail on the old code because the old code is
  wrong, not because the signature changed.

**Fail-before / pass-after, executed:**

| Suite | pre-fix (`0ff73b30`) | post-fix |
|---|---|---|
| `test_v104_p2_coverage_behaviour.py` (behavioural) | **3 failed** (`KeyError: 'population'`, `KeyError: 'coverage_qualification'`) | **3 passed** |
| `test_v104_p2_coverage_honesty.py` (new API) | **9 failed** (`TypeError: unexpected keyword argument`) | **9 passed** |

Full O1-related suite: **89 passed** (91 after adding the 3 behavioural
tests; both counts executed).

---

## 6. Do any frozen thesis or RQ numbers change? — **NO**

Three independent measurements, all on the pinned map-of-record
(`370abbbbb365d5e9…`, 32,267 roads):

1. **Projection is bit-identical.** 5000/5000 projected points identical
   (displacement 0.000 m). The governed map takes the unchanged branch.
2. **The correspondence result is identical.** Base code and O1 code produce
   *the same* match classes (`EXACT 5, HIGH 89, AMBIGUOUS 1524, UNMATCHED
   1439`), the *same* 75 eligible roads, and the *same* road-id set
   (0 differences either way). The O1 change adds orientation-conflict
   detection, which fires on 0 roads of this map.
3. **The lane output is identical.** `LaneGenerator._directional_turn_patterns`
   produces **byte-identical** output for all 32,267 roads: **0 roads
   differ**.

**Therefore: no frozen thesis number, no RQ number, and no map-of-record
byte changes.** The pinned map is not regenerated by this PR and must not be.

### Two forward-looking caveats (stated so they are not discovered later)

1. **A future regeneration under the O1 branch would differ from the pinned
   map for 60 roads** (0.186% of 32,267). Breakdown: 18 differ in total lane
   *count*, 8 differ only by a left/right *side swap*, 11 differ only in
   *provenance source*, 23 differ only in *confidence*. All 60 carry an OSM
   correspondence. The changes are the intended corrections (one-way roads no
   longer gain a phantom counterflow lane; a reversed reference swaps the
   carriageway). **The pinned map-of-record was not produced by this
   repository's stage-07 lane path** — it matches neither the base nor the
   O1 resolution for 38 of the 60 roads, and only 5 of the 60 carry any
   `osm:*` provenance in the pinned map (and that provenance is
   `osm_access_restriction_v1`, not lane-count provenance). So the pinned
   artifact is not reproducible from either branch, and the O1 branch does
   not rewrite frozen pinned-map lane content for these roads.

2. **The production map-of-record's own historical coverage report has the
   same defect at a larger scale.**
   `reports/rq1_trial_runs/run_01/20261007_214826_524342/structural_osm_lane_correspondence.json`
   records `"status": "PASS"` with `eligible_road_count: 83` out of 32,267
   roads — a **0.26%** road-level coverage reported as PASS. (The 83 vs the
   75 measured today is a historical input difference: that run's
   match-class counts are `EXACT 4, HIGH 98, AMBIGUOUS 1515, UNMATCHED 1440`,
   while both the base and O1 code reproduce `EXACT 5, HIGH 89, AMBIGUOUS
   1524, UNMATCHED 1439` today. The base code produces the *same* result as
   the O1 code, so the difference is in the run's inputs, not in this PR.)
   That historical artifact is **frozen** and is not rewritten here; the
   defect is recorded in `reports/continuous_closure/v105/ISSUE_REGISTRY.json`.

---

## 7. What is still true, and what is withdrawn

**Stands (verified by execution):**

* The coordinate-frame defect in `project_positioned_osm_metadata_ways` is
  real and is fixed.
* The fix is a **no-op for the governed map-of-record** (5000/5000 identical).
* The manual map's correspondence went from 0 matches to 44.
* The O1 direction/lane semantics are correct and change 60 roads on a future
  regeneration (0.186%).

**Withdrawn:**

* *"44 of 3057 roads matched is 1.4%"* — a mixed-unit ratio, not a rate.
* *"authoritative 35/3057 = 1.14%"* — same error.
* Any implication that a `coverage PASS` in
  `OSM_XODR_DIRECTION_COVERAGE_REALMAP.json` means the coverage is adequate.

**Added (this commit):** population-aware rates, an explicit separate adequacy
verdict, and 12 tests that pin both.

---

## 8. Reproduction commands

```powershell
# the three measurements behind this report
py C:\Users\admin\AppData\Local\Temp\opencode\_v104_p2_decisive.py   # projection bit-identity
py C:\Users\admin\AppData\Local\Temp\opencode\_v104_p2_mor.py         # both map arms
py C:\Users\admin\AppData\Local\Temp\opencode\_v104_p2_counts.py      # lane-count delta
py C:\Users\admin\AppData\Local\Temp\opencode\_v104_p2_pinned.py      # pinned-map comparison

# the tests
py -m pytest tests/unit/test_v104_p2_coverage_honesty.py tests/unit/test_v104_p2_coverage_behaviour.py -q
py -m pytest tests/unit/test_v103_o1_osm_direction.py tests/unit/test_v104_pr39_review_fixes.py `
  tests/unit/test_v104_safe_xml_boundary.py tests/unit/test_stage07_structural_osm_metadata.py `
  tests/unit/test_v104_p2_coverage_honesty.py tests/unit/test_v104_p2_coverage_behaviour.py -q
```

---

## 9. The honest position

The **defect** and the **fix** in PR #39 stand: a real coordinate-frame bug,
a correct fix, and a no-op on the governed map. The **number** attached to it
was wrong, and the **"coverage PASS"** framing overstated what had been
measured. Both are corrected.

The corrected, honest measurement is that **OSM directional enrichment
reaches 0.23% of the governed map-of-record's roads (41 of 32,267
authoritative)**. That is a **low** number, and it is stated as such. It is
consistent with the repository's own long-standing 0.4% lane-provenance
finding, and it means OSM-derived directionality is **not** a material
contributor to the current map-of-record. Any thesis or RQ claim that leans on
OSM directional enrichment as a significant input should be re-examined on
that basis.

**No release-readiness claim is made or implied by this report.**
