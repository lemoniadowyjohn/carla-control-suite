# GAP-026 Root Cause — Independent Lane-Link Pose Continuity Forensics

**Map:** `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr`  
**Pin:** `verify_pinned_map("auto_map_of_record")` → SHA256 `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`, 149,799,632 bytes, frame `rebased-to-local (dx=832671.676 dy=5458671.104)`, registry fingerprint `4f5ba958...a534`.  
**Signal (validated):** 23,529 laneLinks checked, 2,992 failed (12.72%), 832 > 3 m, max 14.0 m. Independent oracle (kernel + `opendrive_geometry`) reproduces 2,992/2,992 with 0 m delta. Reference coincidence intact for 98.5% (807/832 >3 m have ref ≤ 0.25 m).  
**Verdict:** `MAP_DEFECT_CONFIRMED` (checker validated, see `GAP026_METHOD_VALIDATION.json`).

---

## 1. What the checker actually does (and does not do)

`ultimate_pipeline/lanes/lanelink_builder.py:199` `sanitize_junction_lane_links`:

- Reads each `<junction><connection>` with `incomingRoad`, `connectingRoad`, `contactPoint`.
- `incoming` always at **end** (`at_start=False`), `connecting` at **start** if `contactPoint=start` else **end** (`at_start = contactPoint != "end"`).
- Reference pose: `sorted(planView/geometry by s)`, `pose_at_s(geoms[0],0)` for start, `endpoint(geoms[-1])` for end — via `ultimate_pipeline/geometry/opendrive_geometry_kernel.py`.
- Lane center: side by sign (`left` if id>0 else `right`), `preceding = sum(width/@a where |id|<|target|)` over `type=driving` sorted by `abs(id)`, `lateral = (preceding + width/2)*sign`, world = `ref + lateral * (-sin, cos)`. No `laneOffset`, no `b/c/d`, no `sOffset`.
- Heading continuity: `heading_target = connecting_heading + (0 if at_start else π)`, angular = wrapped difference to `incoming_heading`, threshold 12°.
- Position continuity: Euclidean `hypot(lane_center_src, lane_center_tgt)`, threshold 0.25 m.

**Audited semantics (independent oracle `gap026_oracle.py:lane_center_oracle`):**

| Semantic | Checker | Oracle | Map truth | Bias? |
|---|---|---|---|---|
| `planView` endpoint | `endpoint(geoms[-1])` | Both kernel + `opendrive_geometry` primitives (line/arc/paramPoly3/poly3/spiral) | Road length = sum geometry lengths (verified) | **None** — kernel vs OG delta 0 m |
| Heading/tangent | `Pose.heading` with π flip at end | Same via both authorities (atan2 for poly, integrated for spiral) | Connector `paramPoly3` headings verified | **None** |
| `contactPoint` | `at_start = contact != "end"` | Same, reversal test shows 0/832 >3 m would pass if flipped | All >3 m are `contactPoint=start` | **None** |
| `laneSection s` | First/last section | Same + `ds = target_s - section_s - sOffset` evaluated | All 53,639 widths have `sOffset=0` | **None triggered** (0 non-zero) |
| `laneOffset` | Ignored | Evaluated `a+b*ds+c*ds²+d*ds³` at `s=length or 0` | All 32,267 `laneOffset` have `a=b=c=d=0` (full scan) | **None triggered** |
| Lane width poly | `@a` only | Evaluated full `a+b*ds+...` | All 53,639 widths have `b=c=d=0` | **None triggered** |
| Left/right sign | `sign = +1 left / -1 right` with `(-sin, cos)` | Same | Interleaving `0/41,944` side-sections | **None** (82/2,991 sign-flip fix, not systematic) |
| Lane center offset | `preceding + width/2` over driving only | Also tested `all lane types` + `edge` | Drift vs all-types Δ=0, vs edge Δ huge (12,424 fails) | **None** — center is correct |
| Connection orientation | `+π` at end | Same | — | **None** |
| `from/to` mapping | Direct read | Same | — | **None** |

**Conclusion:** For this pin, every simplification the checker makes is numerically inert (all polynomials zero, no interleaving, no tapered widths). The oracle that includes every omitted term reproduces the production result exactly (2992/2992). The checker is **not** `CHECKER_INVALID` or `CHECKER_PARTIALLY_BIASED` for this map.

---

## 2. Stratification

| Bucket (m) | Count | % checked | % failed | Representative (deterministic first sorted) |
|---|---|---|---|---|
| 0.25–0.5 | 1,721 | 7.31 | 57.52 | j12/c3 −1→−1 0.25 m 0° (inc 47383 → con 54435, width 3.0 vs 3.5) |
| 0.5–1 | 146 | 0.62 | 4.88 | j39/c1 −2→−2 0.75 m 0° |
| 1–3 | 292 | 1.24 | 9.76 | j5/c1 −1→−1 2.607 m 96.31° |
| 3–5 | 686 | 2.92 | 22.93 | j1/c3 −2→−1 3.5 m 0° (inc 42486 → con 52027, outer→inner mispairing, ref 0.0 m) |
| 5–10 | 123 | 0.52 | 4.11 | j8/c2 −3→−1 7.0 m 0° |
| >10 | 23 | 0.10 | 0.77 | j411/c15 −4→−1 10.5 m 0° (inc 47036 → con 69337) |
| heading_only (≤0.25, >12°) | 1 | 0.00 | 0.03 | j3125/c4 −1→−1 0.143 m 175.31° |

**Angular among failures (15% >12°):** 0–12° 2,541 (84.93%), 12–30° 99, 30–60° 99, 60–90° 60, 90–120° 57, >120° 136. The angular tail is concentrated in `1–3 m` (heading kinks) and the solitary heading-only case; the `>3 m` tail is predominantly lateral (multiples of 3.5 m) with 0° heading, not angular.

Both authorities reconstruct every representative sample identically (see `GAP026_METHOD_VALIDATION.json:representative_samples` — each lists `both_authorities_agree: true`). Manual reconstruction via `gap026_oracle.py` using kernel and `opendrive_geometry` primitives yields identical world poses (Δ < 1e-9 m) because endpoint geometry for these roads is `line` (incoming) + `paramPoly3` (connector) with `pRange=normalized` — both kernels handle `pRange` correctly.

---

## 3. Near-threshold population (0.25–0.5 m, N=1,721) — mechanism

**Not** any of the hypothesized checker biases:

- **Half-lane-width bias:** Tested `center` vs `edge` (outer edge) — `edge` would fail 12,424 vs. center 2,991, and `0/1,721` near-threshold center fails would pass as edge. **Ruled out.**
- **laneOffset omission:** All 32,267 laneOffsets are `0`. Oracle inclusion changes distance by 0 for every link. **Ruled out.**
- **contactPoint reversal:** Flipping `contactPoint` fixes `0/832` >3 m and `0/1,721` near-threshold. **Ruled out.**
- **Lane sign:** Flipping lateral sign fixes 82/2,991 (2.7%), not systematic, and none in near-threshold equal-ordering bucket (1,713/1,721 are `|from|==|to|` inner→inner). **Ruled out.**
- **Width-at-end evaluation:** 0/53,639 widths have non-zero `b/c/d` or `sOffset`. **Ruled out.**
- **Reference-vs-lane-center confusion:** Checker correctly compares lane-center to lane-center. Comparing reference-to-reference would pass 2,947/2,991 (98.5%) — this would hide the defect, not create it. **Ruled out** as bias; it is the correct metric.

**Identified mechanism:** **Width tier mismatch.**

- `wdiff` distribution for `0.25–0.5` bucket: `0.50 m` → 1,489 cases (86.5%), `0.25 m` → 161, `0.75 m` → 60, `0.00 m` → 10.
- `lateral_diff` for same bucket: `0.25 m` → 1,490 (86.6%). Since `lateral = width/2`, `wdiff 0.50 → lateral 0.25`.
- Deterministic example: `j12/c3 47383→54435` (also `j472/c3 50620→71157` etc.) — incoming driving lane width `3.000` (or `3.0`) vs. connecting driving lane width `3.500`. Both are `type=driving`, `|id|=1` inner lanes, so `preceding=0`, `lateral_src=1.50`, `lateral_tgt=1.75`, `Δlateral=0.25` → exactly threshold. `ref_dist` for these links is `0.0` (reference coincidence), so the failure is purely lane-width continuity, not geometry.

**Why the width mismatch exists:** `ultimate_pipeline/enrichment/lane_width_policy.py` + `LaneGenerator._road_type_width` assign non-junction (incoming) roads a type-dependent width (RAST06 / `HIGHWAY_DEFAULT_WIDTH_M` + OSM `width` / `lanes` divisor). Incoming roads carry `type=town`/`highway=secondary` etc., yielding `3.0`, `3.25`, `3.5`, `3.75` (distribution: 3.5 25,761 / 3.25 6,952 / 3.0 1,375 / 3.75 176). **Connector roads** are `junction != -1`; `LaneGenerator.ensure_lanes` for connectors (`_is_connector`) unconditionally creates **one** right driving lane with `target_driving_width_m(..., fallback) → 3.5 m` (verified: 23,407/23,407 connector driving lanes are `3.500`). No type-aware width inheritance is applied to connectors.

The width mismatch is therefore a **map defect** at the lane-width policy boundary, not a checker artifact. It is `MIXED_POPULATION` only in the sense that the near-threshold tail (86.5% width-mismatch) and the severe tail (>3 m) have different mechanisms but both are genuine.

**Other near-threshold sub-populations:** `67/1,721` have `incoming lane count != connecting lane count`; `8` are `outer→inner` with large lateral but still fall in `0.25–0.5` due to heading cancellation (rare, not systematic). The remaining `1,713` are `equal` ordering (`|from|==|to|`), confirming inner→inner width mismatch is dominant.

---

## 4. Severe tail (>3 m, N=832) — clustering and traversability

| Dimension | Observation (validated) |
|---|---|
| **Distinct junctions** | 491 distinct `junction_id` of ~3,561 total (≈13.8% of all junctions) — widely dispersed, not clustered to a single junction. Top junctions have ≤10 failures each (`3255:10, 411:10`); no single junction dominates. |
| **Distinct roads** | 628 distinct `incomingRoad` (regular, `junction=-1`), 756 distinct `connectingRoad` (junction-internal), 1,384 distinct roads total. Each failure consumes 2 roads; sharing is limited (many roads appear in 1–2 failures). |
| **Generator stage / source** | `incomingRoad`: always `junction=-1` (Stage 3/7 regular roads, lane count from OSM via `driving_lane_counts`, width from `lane_width_policy`). `connectingRoad`: always `junction != -1` (Stage 3 `junction_connector_rebuild` + Stage 7 `LaneGenerator` connector branch). Geometry: incoming endpoint `line` (832/832), connecting at contact `paramPoly3` 723 / `line` 109 (85% curved `paramPoly3` with `pRange=normalized`, length ~3–17 m). Road class for incoming: all `type=town` (OSM town roads) in this sample — distribution matches the overall pin's non-junction road class bias. |
| **Traversability** | **832/832 are `type=driving` laneLinks** (both `from` and `to` lanes are `driving`, not sidewalk/border). Verified per-link by inspecting final `laneSection` at interface. These are **actually traversable driving lane links** — a vehicle transiting the junction would experience a visible lateral jump (CARLA's lane-following would snap). Not a sidewalk/board defect that could be ignored. |
| **Connection direction** | `contactPoint=start` for **832/832** (100%). No `contactPoint=end` among severe failures. This is not a `contactPoint` bug (reversal fixes 0), but a structural pattern: the severe `paramPoly3` connectors are all oriented with `start` glued to incoming `end`; their `start` heading is already aligned (angular among >3 m tail: 0–12° for 2541 of the overall 2992, and the 14.0 m max case has 0°). |
| **Junction type** | `type=default` for **832/832**. No `roundabout` or `virtual` type among severe failures (despite pipeline support for roundabout reconstruction — `roundabout_reconstructor`). The defect is in ordinary intersections, not roundabouts. |
| **Geometry primitive** | Incoming: `line` endpoint (832/832) suggests the last planView segment after smoothing is a short `line` (e.g., `0.687 m` in the `j1/c3` example). Connecting: `paramPoly3` 723, `line` 109 at the contact — the paramPoly3 connectors are the curved junction curves; their reference endpoints are **coincident** with incoming refs (ref ≤0.25 for 807/832). The 25 with `ref >0.25` are the only genuine geometry discontinuities; the 807 with `ref ≤0.25` are pure laneLink mispairings (reference already good). |
| **Road class** | `incomingRoad` class `town` (832/832 in gt3 sample; overall non-junction distribution includes `town` majority plus `secondary` etc., but the gt3 subset happens to be town). No highway/motorway among severe; these are urban grid roads. |
| **Lateral signature** | Multiples of 3.5 m: `3.5` → 361, `7.0` → 77, `10.5` → 18, `14.0` → 1 (j3470). The lateral difference for >3 m is 85% `≥3.1 m` (704/832 have `incoming lane count != connecting lane count`, 677 `outer→inner`). Example maxima: `j3470/c0 from=-5 to=-1` (inc 49561 `len=94.6 m, 5 driving lanes` → con 69981 `len=3.64 m, 1 lane`) → `Δlateral = (5.25+1.75?)` Wait math: `inc -5` lateral = `(4*3.5 +1.75)=15.75` to right, `con -1` lateral = `1.75` → Δ=14.0 m exactly. Reference gap is `0.0`. |

**Reference vs. lane-center test:** 807/832 (97%) have `reference distance ≤0.25 m` (confirmed via `hypot(incoming_ref, connecting_ref)`). If the checker had compared reference-to-reference, only `25` would fail — **this would hide 97% of the severe tail**. The checker is correct to compare lane centers.

**Angular discontinuity for >3 m:** Largely **not** angular — the maxima (14.0, 10.5) have `0°` heading continuity. The angular failures (136 `>120°`, 57 `90–120°`) are concentrated in the `1–3 m` bucket where reference headings diverge despite small lateral, often on short connectors (`length 3–5 m`) where `paramPoly3` tangent is sensitive.

---

## 5. Earliest responsible generator stage

### 5.1 Width mismatch (0.25–0.5 m)

**Earliest stage:** `stage_07_lanes.py:_step7_lanes_sidewalks` → `LaneGenerator.ensure_lanes` + `lane_width_policy.target_driving_width_m` + `LaneRepair.standardize` / `LaneWidthClamp`.

- **Evidence:** `LaneGenerator._is_connector` branch (line 584–601) creates **exactly one** right driving lane for every `junction != -1` road with `target_driving_width_m(..., fallback=3.5)` — no highway-type or OSM-width inheritance. Non-junction roads go through `driving_lane_counts` + `_road_type_width` (RAST06 + OSM `width`/`lanes` divisor) yielding 3.0/3.25/3.5/3.75. The two width regimes never meet.
- **Why earlier:** The lane count and width decisions are made in Stage 7, before `LaneOffsetSmoother`/`CrossSectionRepair`. Once written, width is baked into `<lane><width a=...>`. No later stage re-harmonizes cross-junction width (there is no `width continuity across junction` repair — `LaneRepair.enforce_width_continuity` only handles `laneSection` boundaries along a single road, not across `predecessor/successor` junctions).
- **Canonical stage for repair:** Stage 7 lane-width policy itself. Patching the final XODR `<width a=...>` directly would be non-canonical (bypasses provenance `lane_count_source`/`userData` vectors and the `lane_provenance_report.json`). The canonical fix is to make the connector width decision inherit from its incident incoming/outgoing roads (or from a junction-level cross-section characteristic).

### 5.2 Lane-count mispairing / laneLink outer→inner (≥3.5 m)

**Earliest stage is split:**

1. **Connector synthesis:** `stage_03_topology_repair` + `ultimate_pipeline/topology/junction_connector_rebuild.py:rebuild_displaced_junction_connectors_on_root` (Stage 3) and `LaneGenerator` connector lane creation (Stage 7). Connectors are synthesized as **single-lane** roads regardless of how many lanes the incoming road carries. For a 5-lane incoming (e.g., `49561` with `5` driving lanes), a single connector cannot host 5 laneLinks. The correct topology would be **N connectors** (or one connector with N lanes) — the current pipeline builds one connector with one lane. This is the same gap identified in prior memory `component_reachability: 27 isolated lane components, every isolated lane is outermost driving lane, laneLink set always covers `from=-1..-(n-1)` but never `from=-n`` — outermost lane left unwired or miswired.

2. **LaneLink mapping:** `ultimate_pipeline/lanes/lanelink_builder.py:regenerate_lane_links` / `match_by_direction` (Stage 8 `lanelink_builder`, currently **disabled** via `ENABLE_LANELINK_REGEN=0`). The existing laneLinks in the pin were **not** created by the current `match_by_direction` (which would correctly pair inner→inner and leave outer unmatched). They were inherited from the initial OSM→XODR conversion (SUMO/jsnap) which appears to pair **outer→inner** when counts mismatch (evidence: `from=-5 to=-1` — outer to inner). The fact that `LaneLinkBuilder.sanitize` now detects this proves the mapping was never validated until GAP-026.

   - **Evidence that `match_by_direction` would NOT produce the observed mispairings:** Re-running `match_by_direction` on the sample `j1/c3` (inc: `-1,-2` driving, `-3 sidewalk`; con: `-1` driving) would produce **one** pair `-1→-1` only, leaving `-2` unmatched. The observed link `-2→-1` is the opposite (outer→inner). This is signature of a different, index-agnostic mapper.
   - **Canonical repair stage for laneLinks:** `stage_08_integrity.py` / `LaneLinkBuilder.regenerate_lane_links` is the canonical stage for laneLink topology (documented in `docs/hardening/01_stage_mutation_matrix.md: | **8** LaneLinks + Markings | ... LaneLink regen ... | lanes_out`). However, merely regenerating with `match_by_direction` would leave outer lanes isolated (correct but reduces connectivity). The **earlier** connector count must be fixed first, else regeneration trades a 14 m mispairing for a 27-component isolation — the prior gap's `component_reachability` already flagged this as `zero valid connector candidates`.

**Therefore the earliest responsible stage is the connector generation that fixes `junction != -1` roads to single-lane**, which precedes laneLink generation. Fixing laneLinks alone in Stage 8 without fixing connector lanes in Stage 3/7 would replace a pose discontinuity with a reachability gap (both are defects, but the laneLink pose is the more severe simulation artifact).

---

## 6. Generator-level repair design (no direct XODR coordinate patch)

### 6.1 Principle

Do **not** patch final XODR coordinates directly (e.g., edit `<geometry x=... y=... hdg=...>` or `<laneLink from=... to=...>` in place). The canonical stage for each transformation is:

- **Width:** Stage 7 lane-width policy.
- **Connector planView:** Stage 3/5 geometry (`junction_connector_rebuild`, `opendrive_geometry_kernel`).
- **Lane topology:** Stage 7 `LaneGenerator`.
- **LaneLink mapping:** Stage 8 `LaneLinkBuilder`.

A corrected map must be **regenerated from governed inputs** (OSM + DEM + governed settings) via `main_pipeline.py` in an isolated worktree, then compared against the old pin for the required receipt metrics (see `GAP026_POLICY_PROPOSAL.md §7`).

### 6.2 Repair A — Width harmonization (eliminates 0.25–0.5 m tail)

**File:** `ultimate_pipeline/enrichment/lane_width_policy.py` + `ultimate_pipeline/pipeline_stages/stage_07_lanes.py`

- Extend `target_driving_width_m` decision for connectors: instead of `fallback=3.5`, derive `connector_width` as the **median (or incoming-road) driving width** of its incident `incomingRoad`/`outgoingRoad` at the junction interface. If the incident road's final laneSection has `n` driving lanes each `w_i`, the consistent lane width for the connector is the **lane-specific width** (`w` of the matched lane), not a single scalar. Simplest: inherit `width a` of the matched `from` lane (`inc -1 → con -1` inherits `inc -1` width). This makes `Δlateral` zero for inner→inner.

- **Algorithm:**
  1. After `LaneGenerator.ensure_lanes` + `LaneRepair.standardize` have written non-connector roads, build a map `road_id → lane_widths_by_lane_id` at `endpoint LaneSection`.
  2. For each `junction != -1` road, look up its `connection`'s `incomingRoad` and candidate `outgoingRoad` (via `_find_incoming_anchor` / `_find_outgoing_anchor` already in `junction_connector_rebuild.py`), read the matched lane's width, and write the connector lane's `<width a=...>` to that value (preserve `b=c=d=0, sOffset=0` convention).
  3. Re-run `LaneOffsetSmoother`/`CrossSectionRepair` if needed (no laneOffset change, but ensures continuity).

- **Validation:** Re-run `sanitize_junction_lane_links` on the regenerated candidate; the `0.25–0.5` bucket should drop from 1,721 to `~0` (residual < 10 due to `3.25→3.5` cases that will also be harmonized). `reference distance` unchanged.

### 6.3 Repair B — Connector lane-count synthesis (eliminates ≥3.5 m tail)

**Files:** `ultimate_pipeline/topology/junction_connector_rebuild.py` + `ultimate_pipeline/enrichment/lane_generator.py` + `ultimate_pipeline/lanes/lanelink_builder.py`

Two-phase:

**Phase B1 — Connector lane count:**
- Modify `LaneGenerator._is_connector` handling to **not** hardcode one lane. Instead, for each junction connector, set its driving lane count equal to the **minimum** of its incident roads' driving lane counts on the side that participates in the connection (typically `right` for driving). If the incident incoming has `n` lanes on `right` and the outgoing has `m` lanes, the connector should have `min(n,m)` lanes (or `n` if the junction is a merge/diverge — this requires junction-type awareness; `min` is the safe conservative choice that avoids over-provisioning).

- Write `n` driving lanes (`id=-1..-n`) on the connector's `right` side, each with inherited width as in Repair A. Preserve `center` lane `0` and add `sidewalk` if `ENABLE_SIDEWALKS` adds them to the incident roads (currently connectors have no sidewalk — need to mirror incident sidewalk lane if present for cross-section consistency).

- Geometry: The connector's `planView` length and curvature must accommodate `n` parallel lanes of width `w`. The current `paramPoly3`/`line` geometry is reference-line only and does not depend on lane count; no planView change is required for lane-count alone (lane cross-section is independent of planView). However if connectors are lengthened for multi-lane storage, `junction_connector_rebuild`'s `start_gap_threshold` logic must still hold (reference still at 0.0).

**Phase B2 — LaneLink regeneration (geometry-aware):**

- Enable `ENABLE_LANELINK_REGEN` (currently `0`) in the governed settings for a candidate run, and replace `match_by_direction` (pure `|id|` ordering) with a **geometry-aware** matcher that:
  1. Computes lane-center world poses for every `from` (incoming end) and `to` (connector at contact) candidate using the same kernel as the checker (`lane_center_oracle`).
  2. Solves a minimum-weight bipartite matching (Hungarian) where cost = Euclidean lane-center distance + `λ * angular discontinuity` (`λ ≈ 2.0 m/rad` to penalize heading), restricted to `same sign` (left/right) and `type=driving`.
  3. Only creates `laneLink` entries where `cost < 0.50 m` (warning) or `< 0.25 m` (pass) — otherwise leaves the lane **unlinked** and records `isolated_component` for `component_reachability`. This replaces the current `zip(inner_first)` heuristic.

- This matcher will naturally produce **inner→inner** pairings at zero cost and leave outer lanes unmatched when the connector has fewer lanes than the incoming — which is correct. After Phase B1, the connector will have enough lanes that no lane is left unmatched in the common case.

- **Gate:** The matcher must be behind a flag `UP_ENABLE_GEOMETRY_AWARE_LANELINK` (default off) until validated against the full map (see `PRODUCTION_MAP_TASK_GRAPH.json` expectation that `sanitize` be wired before regen is changed).

### 6.4 Validation of repairs

- Regenerate the map in an isolated worktree (`git worktree add --detach` per L4 rules), starting from `stage_03_topology_repair` through `stage_08_integrity`, with exactly one writer.
- Compare candidate vs. old pin:
  - `roads: 32267 → ?` (connector lane count changes may add lanes but not roads; connector road count stays 22,589 but lane topology changes).
  - `junctions: 3561 unchanged` (no junction creation).
  - `lanes: ~?` (increase due to multi-lane connectors: estimate `+ (avg incident lanes -1) * num_connectors ≈ + ~5k`).
  - `structural fingerprint` (`registry_fingerprint`): must change (expected, content change).
  - `RQ2 metrics`: road length / junction / lane count ratios must remain within `~2.7–3.8×` hull bounds (connector changes do not affect road length).
  - `lane-link failure distribution`: `>3 m` should go `832 → 0–25` (25 genuine geometry gaps remain if not fixed), `0.25–0.5` should go `1721 → 0–50`, overall `12.7% → <2%`.
  - `static CARLA gates`: `StrictCarlaOpendriveGate` must remain `PASS` (laneLinks with fewer than before are still valid OpenDRIVE).
  - `final receipt`: `final_artifact_receipt.json` via `resolve_final_artifact_receipt` must verify `bytes`/`sha256` of the new candidate.

- **No coordinate patch:** The only acceptable direct XODR edit is the one performed by `junction_connector_rebuild` itself (which already does a governed planView replacement via `canonical_endpoint` / `validate`). That stage is canonical for geometry; editing laneLinks without regeneration is not.

---

## 7. Risk & Rollback

- **Lane count increase** amplifies `component_reachability` risk: more lanes → more waypoints → CARLA waypoint graph must be revalidated live (currently `BLOCKED_EXTERNAL` per `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:runtime_certified`). Do not claim runtime-certified until live `carla_ego_spawns_on_valid_surface` passes on the new candidate.
- **Width harmonization** changes drivable width statistics used by `check_lane_width_continuity` and `lane_width_policy_report.json`; the gate `lane_width_continuity` must be re-run and is expected to remain `PASS` (widths remain positive, no sudden jumps along a single road).
- **Rollback:** If either repair increases `start_gap_over_threshold_after` in `junction_connector_rebuild`'s report, revert per that module's atomic commit (it already deep-copies the road and validates). The candidate is rejected and the old pin remains authoritative.

---

*Evidence: `GAP026_METHOD_VALIDATION.json` (oracle match 2992/2992, both kernels), `GAP026_FAILURE_POPULATION.csv` (stratification), `ultimate_pipeline/geometry/opendrive_geometry_kernel.py:71` + `opendrive_geometry/primitives.py:19` for geometry authorities, `lanelink_builder.py:199` for checker, `lane_generator.py:584` for connector single-lane hardcode, `junction_connector_rebuild.py:563` for connector planView canonical stage.*
