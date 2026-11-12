# V103 — OpenCode Coordination Report

**Owner:** OpenCode (O1, O2, O3, O4, O5, O6)
**Base:** `integration/production-large-map-20260918` @ `225ed15d0da6444cc257835ca777aba281553f3c`
**Date:** 2026-11-12
**Scope:** V103 prompts 01, 02, 04, 05, 09, 10. Codex retains prompts 03, 06, 07, 08 (road/lane/junction links, release acceptance, locking, CARLA/GUI/runtime) and final integration.

---

## 1. Delivery summary

| Prompt | Owner | Registry issues | Status | Branch / PR |
|---|---|---|---|---|
| 01 OSM direction, lane count, side, reference orientation | **O1** | T01, T02, T06 | **DONE** | `fix/v103-o1-osm-direction-lane-counts` @ `7d21e476` — **PR #39** |
| 02 OSM restrictions and legal movements | O2 | T04, T05 | **NOT STARTED** | — |
| 04 OSM road graph and orphan repairs | **O3** | T03, T09, R15 | **DONE** | `fix/v103-o3-osm-road-graph-orphans` @ `ee94abca` — **PR #40** |
| 05 Connector-Z, junction endpoint orientation, 3D realism | O4 | R16 | **NOT STARTED** | — |
| 09 CI security and package | **O5** | R25, R26, R27, R28, R29 | **DONE (audit + proposal; DOC_ONLY_NO_WRITE)** | `fix/v103-o5-ci-audit` @ `6f0b02a2` — **PR #41** |
| 10 Research / GNN / scientific truth | O6 | R30, R31 | **NOT STARTED** | — |

**Three of six workstreams delivered as reviewable PRs.** The other three
are named explicitly as not started, with the reasons in §5.

---

## 2. V103-O1 — OSM direction, lane counts, side and reference orientation

**PR #39** · `fix/v103-o1-osm-direction-lane-counts` @ `7d21e476` · base `225ed15d`

### T01 — a one-way road gained a phantom counterflow lane

`enrichment/lane_width_policy.py::driving_lane_counts` split a total
`lanes` tag in half with **no** `oneway` handling. A one-way road with
`lanes=2` became `(1, 1)` — a counterflow driving lane that is not on the
map.

**Fix:** new `enrichment/osm_direction.py` with `parse_oneway()`
(`yes|true|1`, `-1|reverse`, `no|false|0`, `reversible`, the implicit
one-way default of `junction=roundabout`, and explicitly undecidable for
`oneway:conditional`) and `resolve_directional_lane_counts()` (directional
tags authoritative; a **decidable** oneway puts every lane of a total
`lanes` in the legal direction; an undecidable oneway keeps the historical
split but is flagged `unsupported`; `lanes:both_ways` never added to either
direction; vehicle-specific oneway variants never change motor-traffic lane
counts).

### T02 — the OSM way orientation was discarded before lane geometry

`pipeline_stages/stage_07_lanes.py::_build_structural_osm_metadata` kept
only `association["metadata"]` (the raw OSM tags) and dropped the
`osm_direction` that `build_metadata_associations` had already resolved.
OSM's `oneway`, `turn:lanes:forward` and `cycleway:left|right` were
therefore applied to the wrong carriageway on a reversed XODR road.

**Fix:** the orientation, OSM way id, match class and confidence are
preserved under reserved non-OSM-tag keys (the raw tags are preserved
verbatim); `lane_generator._turn_patterns` and the cycleway side selection
are remapped onto the XODR carriageway when the reference line is reversed,
with the remap recorded in the lane provenance.

### T06 — coverage could report success without useful matches

New `directional_coverage_report()` counts matched / forward / reversed /
ambiguous / conflicting / not-assessable / fallback / authoritative roads.
Missing OSM source and zero matched roads are `BLOCKED_INPUT`; a set with
no authoritative road is `INCOMPLETE`. Never a release-eligible `PASS`
without authoritative matches.

### NEW FINDING (not in the registry) — the OSM was projected into the wrong coordinate frame

Found by running the correspondence against the **pinned** Ingolstadt pair,
not by reading code.

`enrichment/osm_meta_index.py::project_positioned_osm_metadata_ways` always
projected with the hardcoded bare-tmerc default (`+proj=tmerc +datum=WGS84
+units=m +no_defs` → `lon_0=0`, `k=1`) and ignored the XODR's declared CRS.
`Grid0828.xodr` declares `+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996
+x_0=500000 +y_0=0` (UTM 32N) and stores **global** coordinates with **no**
`<offset>` element.

| Projection | x | y |
|---|---|---|
| pyproj `EPSG:32632` (= the map's declared CRS) | **680 820** | **5 405 174** |
| the pipeline's hardcoded bare-tmerc | 841 663 | 5 468 125 |

Measured on the same probe point. The pipeline landed ~161 km east and
~63 km north of the map's own coordinates.

**Fix:** the projection frame is selected from the XODR header — an
`<offset>` element means the governed auto-map convention (bare tmerc minus
the offset, **unchanged**); no `<offset>` element means the coordinates are
already global in the declared CRS, so the declared CRS is used; no usable
declared CRS falls back to the previous behaviour (fail-safe, not fail-open).

**Measured effect on the pinned real pair** (OSM sha256 `b9e07465…`
verified against `INPUTS_MANIFEST.json`):

| | matched roads | forward | reversed | coverage |
|---|---|---|---|---|
| before | **0** | 0 | 0 | `BLOCKED_INPUT` |
| after | **44** | 38 | 6 | **`PASS`** |

### Verification

* **RED on the unmodified base** `225ed15d`: 4 failed
  (`oneway=yes lanes=2 → backward=1 forward=1`; reversed XODR not swapped;
  `oneway=-1` wrong side; projected x 841662.6 ≠ declared CRS 680819.7).
* **GREEN on the branch**: 43 passed.
* **No regressions**: 67 passed across the existing lane / correspondence /
  acceptance suites.
* The wider offline run reports the **identical 23 pre-existing collection
  errors** before and after (all `ModuleNotFoundError: No module named
  'torch'`), verified by running the identical command on the unmodified
  base worktree.
* **Independent review** by a different model (read-only):
  `APPROVE_WITH_MINOR`, **no blocking findings**, RED independently
  re-verified, no Codex-owned file touched. All five non-blocking findings
  were applied in the follow-up commit.

---

## 3. V103-O3 — OSM road graph and orphan repairs

**PR #40** · `fix/v103-o3-osm-road-graph-orphans` @ `ee94abca` · base `225ed15d`

### T09 — endpoint-only way adjacency missed interior-node cases

`build_osm_way_adjacency` used only `refs[0]` / `refs[-1]`. That is the
right question for an XODR road *endpoint* boundary check and it is
**unchanged**. New `build_osm_source_adjacency()` answers the other
question — "which OSM ways are traversable from one another?" — from the
source alone: adjacency comes **only** from a shared `nd` reference (no
edge is ever fabricated from an XY crossing or a shared street name), the
node's role in each way (`start`/`end`/`interior`) is recorded, topology
existence is kept separate from legal eligibility, grade separation
(bridge/tunnel/layer) is honoured, `oneway` direction is respected, and
undecidable cases are `UNRESOLVED`.

### T03 — a geometry-only orphan repair lacked OSM node proof

`topology/orphan_road_repair.py::repair_orphan_roads` snapped an orphan to
the nearest connected road endpoint using proximity, heading and Z **only**.

**Fix:** a repair now requires positive OSM graph evidence — the orphan's
OSM way and the candidate's OSM way must share an OSM node. Proximity /
heading / Z remain **necessary filters applied after** the proof: they can
veto a proven candidate, never create one. The report gains a
`source_authority` block and the residual reason `no_source_proof`.

`pipeline_stages/stage_03_topology_repair.py` now resolves the OSM source
and the road correspondence and passes them to the repair, so the pipeline
performs **source-proven** repairs. When the OSM extract is unavailable the
legacy geometry-only repair is kept (a run must not abort on a missing
extract) but the report records `source_authority.enabled = false` and the
reason — the gap is explicit, not silent.

The two existing L1/L2 geometry-only repair tests were **updated to supply
the OSM source proof** (making them stronger, not weaker) and two new tests
prove that a geometry-only repair is **refused** and that a source-proven
repair records its proof.

### R15 / OSM-04 — the six historically flagged road ids

Measured on the **current** map-of-record candidate
(`ingolstadt_perception_map_of_record_20260916_232831.xodr`, 32 267 roads,
SHA-256 `370abbbbb365d5e9…`) with the pinned, digest-verified OSM:

| Historical id | Outcome |
|---|---|
| 42367, 43405, 46369, 46698, 48129 | **`ABSENT_FROM_CURRENT_MAP`** |
| 51657 | present, and **not an orphan** (declares a road-level link) |

**None of the six can be resolved as an orphan on the current map.** The
current population is different: **326** unreachable drivable roads under
the strict definition ("drivable, declares links, registered in no junction
connection"), and **0** under the loose one ("no link element at all"). The
historical "six" therefore does not describe the current map.

Deliverables: `reports/v103/o3/ORPHAN_ROAD_SOURCE_RECONCILIATION.csv`,
`…/OSM_XODR_ROAD_GRAPH_AUDIT.json`,
`…/ORPHAN_ROAD_SOURCE_RECONCILIATION.json`, runner
`reports/v103/o3/run_orphan_reconciliation.py`.

### Verification

41 passed across the orphan / topology / road-link suites; the wider offline
run reports the identical 23 pre-existing collection errors. A **mutation
control** removes the source proof and shows the repair stops happening.

---

## 4. V103-O5 — CI forensics, supply chain and branch enforcement

**PR #41** · `fix/v103-o5-ci-audit` @ `6f0b02a2` · base `225ed15d`
**C08 `DOC_ONLY_NO_WRITE` honoured — no workflow file is modified.**

| Registry | Finding | Status |
|---|---|---|
| **R27 (P0)** | The production branch is **not protected** (`GET /branches/{b}/protection` → `404 "Branch not protected"`) and the repository has **zero rulesets** (`GET /rulesets` → `[]`) | **CONFIRMED** |
| **R26** | The `offline-release-gate` job is internally **fail-closed** (bare `needs:`, no `if: always()`, no `contains(needs.*.result,'success')`, no `!contains(...,'failure')`; `gate_exit_code` returns 0 only on PASS) — but with **no required status checks** nothing forces it to have run before a push lands | **CONFIRMED (aggregate fail-open)** |
| **R28 (P1)** | All three actions use **36-character** commit refs, not full 40-char SHAs; artifacts uploaded but never downloaded/validated; no dependency-review / SBOM / provenance job | **CONFIRMED** |
| **R25 (P1)** | `requires-python = ">=3.10"` but every CI job is hardcoded to `python-version: "3.12"`; `pip check` in only one of seven jobs; **`PyQt6` declared in no requirements file and no workflow** (the real PR #34 blocker); `pyproj==3.7.2` in `requirements.txt` only | **CONFIRMED** |
| **R29 (P1)** | The wider offline suite aborts with **23 collection errors**, all `ModuleNotFoundError: No module named 'torch'` — identical before and after the O1/O3 changes. The CI invocation is correct (`set -o pipefail`, no `--continue-on-collection-errors`, no `|| true`), but the **torch-optional suite is not partitioned**, so a runner without the `gnn` extra loses the whole collection | **CONFIRMED** |

**PR states at exact SHAs** (all six are draft and open): #31 `884f019c5`,
#32 `6b2c348b5`, #34 `aea4aea5c`, #35 `9c4c0f264`, #36 `941cace20`,
#37 `a72700bb1`.

**Failure classes NOT re-reproduced here — recorded as `NOT VERIFIED`, not
PASS**: #31 (legacy GNN expectation), #35 (readiness mock mismatch),
#36 (research contract failures). #32 and #34 are verified as described
above.

**Run history** on the production branch: current head `225ed15d0` is
green; the recent history contains **14 failures and 2 cancellations** —
the cancellations are the shape PR #32 exists to close.

**Branch protection was NOT applied** — that needs repository
administration. `BRANCH_POLICY_CHECKLIST.md` gives the owner-executable
plan including a **refusal test** that must pass before governance may be
called enforced.

**No 40-character action SHA was invented.** The proposal lists the
substitution sites and the owner resolves them.

---

## 5. Not delivered, and why

### V103-O2 — OSM restrictions and legal movements (T04, T05) — NOT STARTED

Scope: new `ultimate_pipeline/osm/restriction_*`, `legal_movement_*`,
`quality/osm_movement_gate.py`, the `AllowedMovementReport` API with
`ALLOW_SOURCE_PROVEN` / `DENY_SOURCE_PROVEN` / `UNKNOWN_NO_SOURCE` /
`AMBIGUOUS_MAPPING` / `UNSUPPORTED_CONDITIONAL` / `PHYSICAL_DISCONTINUITY`,
and a non-destructive comparison API mapping each junction connection +
laneLink to a possible OSM movement.

**Why not delivered:** O2 depends on O1's *stable* oriented correspondence
contract (`RoadOSMDirectionalAssociation` and the orientation-preserving
`structural_osm_meta` shape). O1's contract is now implemented and
reviewed, so O2 is **unblocked and ready to start** — it was simply not
reached in this session's budget. The O1 handoff to Codex states the
contract explicitly so O2 can begin against it.

**Also note:** `quality/osm_movement_gate.py` is a *gate*, and the prompt
says the reconciliation must stay advisory until Codex C2 integrates a
release-mandatory contract. O2 must therefore not touch
`quality/map_acceptance.py`, `quality/final_artifact_gates.py`,
`contracts/artifact_authority.py` or `main_pipeline.py`.

### V103-O4 — Connector-Z, junction endpoint orientation, 3D realism (R16) — NOT STARTED

**A factual correction to the workstream's assumptions:** the prompt's
source starting points **do exist** in the production base
(`ultimate_pipeline/quality/map_realism_p0_oracle.py` and
`ultimate_pipeline/topology/connector_elevation_reconciler.py` are both
present at `225ed15d`). An earlier scout reported them as absent; that
report was wrong and was caught by direct verification before any write.

The four defects the prompt lists (`at_start_contact` computed but unused;
`max(abs(l['dz_start']), abs(l['dz_end']))` able to raise `TypeError`;
mixed-grain counters; `scan_georeference` checking token presence rather
than numerical validity) are therefore **reproducible against the
production base** and O4 is fully in scope — it was not reached in this
session's budget.

**Constraint for whoever picks it up:** PR #33 (`cf24666e`) and PR #38
(`a9541949`) already carry the elevation-seam work and must be
coordinated, not rewritten. The V97 geometry lane `6d18b6c4` already
contains both, plus one additive V97 commit — when #33/#38 land, that
lane's first two commits become redundant and need a rebase.

### V103-O6 — Research / GNN / scientific truth (R30, R31) — NOT STARTED

Scope: reproduce and fix the hosted source/test-contract failures (PR #31
legacy no-op expectation, PR #36 latent-gap / report / checkpoint / RQ1),
verify checkpoint SHA-256 and canonical metadata binding before load,
secure deserialization, graph-feature dimension/mask consistency,
training/evaluation disjointness, and keep R30–R31 pending when the
campaigns cannot be executed.

**Why not delivered:** the research suites are exactly the 23 modules that
**fail to collect in this environment** (`No module named 'torch'`). R30/R31
cannot honestly be moved without the `gnn` extra installed, and O6's own
prompt requires that a missing checkpoint / unavailable campaign stay
`NOT_RUN` / `BLOCKED_INPUT` rather than be reported as a pass. Installing
torch is an environment change beyond this agent's scope.

**Unblocked by O5:** the R29 partitioning proposal (mark the 23
torch-dependent modules and ignore them **only** for the approved offline
profile) would let the non-GNN research tests run.

---

## 6. Registry closure matrix — OpenCode-owned issues

| ID | Pri | Area | Issue | Owner | Status | Evidence |
|---|---|---|---|---|---|---|
| T01 | P0 | Directionality | oneway total lane count can create phantom counterflow | O1 | **SOURCE_FIXED + TESTED** | PR #39; `test_dir01_oneway_two_lane_road_has_no_phantom_counterflow`; RED on `225ed15d` |
| T02 | P0 | OSM correspondence | osm_direction discarded before lane geometry | O1 | **SOURCE_FIXED + TESTED** | PR #39; `test_t02_stage07_preserves_osm_orientation`, `test_t02_reversed_road_puts_turn_lanes_on_the_xodr_backward_carriageway` |
| T03 | P0 | Orphan links | geometry-only orphan repair lacks OSM node proof | O3 | **SOURCE_FIXED + TESTED** | PR #40; `test_geometry_only_repair_is_refused_without_osm_source_proof` |
| T04 | P0 | Turn restrictions | OSM turn-lane/restriction comparison advisory only | O2 | **NOT STARTED** | — |
| T05 | P0 | Vehicle access | OSM access metadata not enforced in routing | O2 | **NOT STARTED** | — |
| T06 | P0 | OSM source coverage | scan may report success without useful matches | O1 | **SOURCE_FIXED + TESTED** | PR #39; `directional_coverage_report` + `TestT06` group |
| T09 | P1 | OSM road graph | endpoint-only way adjacency misses interior-node cases | O3 | **SOURCE_FIXED + TESTED** | PR #40; `test_osm01_two_ways_sharing_an_interior_node_are_adjacent` |
| R15 | P0 | OSM | six orphan drivable roads unresolved | O3 | **RE-MEASURED, POPULATION CHANGED** | PR #40; 5 ids absent, 1 not an orphan, current population 326 unreachable / 0 isolated |
| R16 | P0 | Connector-Z | historic 866 >0.5 m; oracle orientation bug | O4 | **NOT STARTED** | prompt's source files confirmed present at base |
| R25 | P0 | Environment | test runtime unsupported/undeclared | O5 | **AUDITED (P1)** | PR #41 §1.4 / §3 |
| R26 | P0 | CI | release aggregate fail-open when predecessors skipped | O5 | **AUDITED — mechanism fail-closed, policy missing** | PR #41 §1.1 |
| R27 | P0 | Governance | unprotected release branches and empty rulesets | O5 | **CONFIRMED P0 — owner action required** | PR #41 §3; `BRANCH_POLICY_CHECKLIST.md` |
| R28 | P0 | Supply chain | workflow/gh-aw supply chain incomplete | O5 | **AUDITED (P1)** | PR #41 §1.3 / §4 |
| R29 | P0 | CI | full-suite errors and skipped prerequisites | O5 | **AUDITED (P1)** | PR #41 §5 |
| R30 | P1 | ML | LaneGNNRefiner not trained/integrated | O6 | **NOT STARTED** | blocked on torch |
| R31 | P1 | Research | RQ1/RQ2/RQ4 empirical claims unverified | O6 | **NOT STARTED** | blocked on torch |
| **NEW** | **P1** | **OSM correspondence** | **OSM projected with a hardcoded bare-tmerc instead of the map's declared CRS — 0/3057 ways matched on the pinned pair** | O1 | **SOURCE_FIXED + TESTED** | PR #39; `test_projection_uses_the_declared_crs_when_the_map_has_no_offset`; real-map 0 → 44 matched |

Issues **not** owned by OpenCode (Codex C1–C4 / owner): R01, R02, R03, R04,
R05, R06, R07, R08, R09, R10, R11, R12, R13, R14, R17, R18, R19, R20, R21,
R22, R23, R24, R32, R33, T07, T08. R05 (the XML DTD / size-boundary bypass)
was independently reproduced by me against Chat 1's PR #30 source and handed
over in a separate deliverable; the fix itself is Chat 1-owned.

---

## 7. Worktrees, branches and isolation

| Worktree | Branch | Base | HEAD | Remote |
|---|---|---|---|---|
| `F:\v103\base` | `integration/production-large-map-20260918` | — | `225ed15d` | — |
| `F:\v103\o1` | `fix/v103-o1-osm-direction-lane-counts` | `225ed15d` | `7d21e476` | pushed, PR #39 |
| `F:\v103\o3` | `fix/v103-o3-osm-road-graph-orphans` | `225ed15d` | `ee94abca` | pushed, PR #40 |
| `F:\v103\o5` | `fix/v103-o5-ci-audit` | `225ed15d` | `6f0b02a2` | pushed, PR #41 |
| `F:\v103\o1_old` | `tmp/v103-o1-oldbase-red` | `225ed15d` | `225ed15d` | local only (RED proof worktree) |

Each owner works in its **own worktree on its own branch off the same
production base**, with its own Git common directory
(`F:\v103\_gitdirs\base.git`). No two writers share a path. Nothing was
force-pushed, reset, cleaned or deleted. The shared `E:\wt-v97\staging`
checkout was **not** read or modified.

---

## 8. Explicitly not claimed

* **No release readiness.** No independent certification of the integrated
  candidate exists; the three PRs are independent, unreviewed-by-a-second-
  model workstreams except O1 (which has one independent review).
* **No CARLA runtime certification.** No simulator was launched.
* **No release-mandatory gate was added or removed.** The O3 reconciliation
  is advisory; gate membership is Codex C2's decision.
* **No branch protection was applied.**
* **No workflow file was modified** (C08).
* **No 40-character action SHA, gate membership, or threshold was invented.**
* **The 23 `torch` collection errors are pre-existing**, verified identical
  on the unmodified base; they are **not** reported as a pass, and they
  still block R30/R31.
* **PR #31 / #35 / #36 CI failure classes are `NOT VERIFIED`** — they were
  not re-reproduced in this session.

## 9. Recommended next actions

1. **Codex C2** — pick up O2's scope once it accepts O1's
   `RoadOSMDirectionalAssociation` / orientation contract; the O1 handoff
   states the contract explicitly.
2. **Codex C1** — pick up O4; the prompt's source files are present at the
   production base, and PR #33/#38 coordination is required.
3. **Owner** — apply the branch-protection ruleset and run the refusal test
   (`BRANCH_POLICY_CHECKLIST.md` §3–§4). This is the only P0 that OpenCode
   can definitively hand over rather than fix.
4. **Owner** — lift C08 for the two workflow files and apply
   `CI_PATCH_PROPOSAL.diff`, resolving the 40-character SHAs.
5. **Owner / CI** — partition the 23 torch-dependent modules so the offline
   profile can run the non-GNN research tests, and install the `gnn` extra
   so R30/R31 can be executed rather than reported pending.
