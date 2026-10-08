# GAP-036 Implementation Scout — Read-Only Scope Report

**Date**: 2026-10-08
**Task**: Scoping only for GAP-036 (`PRODUCTION_MAP_QUALITY_CONTRACT.yaml` — declarative quality
contract with no executing consumer).
**Agent role**: READ-ONLY. No code was implemented. No code, gap register, or pending-policy file
was edited. This report file is the only artifact written.
**No policy recommendation is made and no option is selected.** Steps 4 and 5 present two
independent scopes for a human decision.

---

## Step 1 — The YAML file itself

**Path**: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\PRODUCTION_MAP_QUALITY_CONTRACT.yaml`
— repo root, **181 lines** (note: `GAP036_POLICY_PROPOSAL.md:13` says "172 lines"; that count is
stale, and the same proposal's own reference table is inconsistent about which files reference it).

### SURPRISE #1 — Option B was already partially executed before this scout

`git log --oneline -- PRODUCTION_MAP_QUALITY_CONTRACT.yaml` returns exactly **one** commit:

```
0f9f827c docs(GAP-036): mark PRODUCTION_MAP_QUALITY_CONTRACT.yaml as non-normative reference
```

That commit already added a **8-line `NON-NORMATIVE REFERENCE DOCUMENTATION` banner** at
`PRODUCTION_MAP_QUALITY_CONTRACT.yaml:1-8`, which explicitly redirects readers to the real
enforcement authorities:

```
1: # =====================================================================
2: # NON-NORMATIVE REFERENCE DOCUMENTATION
3: # =====================================================================
4: # This file is a historical reference architecture and is NOT executed
5: # or enforced by the Python runtime pipeline. Actual gate enforcement
6: # is governed by ultimate_pipeline/quality/map_acceptance.py and
7: # ultimate_pipeline/contracts/stage_contracts.py.
8: # =====================================================================
```

Its own commit body (quoted verbatim from `runs100.json:20920`) states the scope limit explicitly:

> "GAP-036's own status field and the remaining 7-of-9 referencing docs (archived reports under
> `docs/archive/`) are intentionally left for a separate pass -- this commit covers only the 3 files
> edited in this round."

So **the file itself is already disclaimed**. Any remaining Option B work is about the *referring*
documents, not the YAML. This materially shrinks Step 5's scope (see below) and is not reflected in
`GAP036_POLICY_PROPOSAL.md:72` ("Total: 10 distinct references across 9 files"), which predates it.

### SURPRISE #2 — the residual doc references are fewer than the register claims

`GAP036_POLICY_PROPOSAL.md:72` says 10 references / 9 files need updating. Measured now: of those,
**3 were already updated by `0f9f827c`** and **4 more live inside `docs/archive/`**. Only **4 live
(non-archived) files** still assert normativity. See Step 5.

### Confirmed: still zero executing consumers

`git grep -l "PRODUCTION_MAP_QUALITY_CONTRACT" -- '*.py'` → **zero matches** (reproduced
independently here, not taken from the register's claim at
`reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.json:651`).

A positive-form search confirms it too: every `yaml.safe_load` / `yaml.load` call in the pipeline tree
is unrelated to this file —

| File:line | What it loads |
| --- | --- |
| `ultimate_pipeline/contracts/agent_sync.py:247` | agent-sync config |
| `ultimate_pipeline/contracts/experiment_config.py:183` | experiment config |
| `ultimate_pipeline/experiments/thesis/protocol.py:55` | thesis protocol |
| `ultimate_pipeline/tools/validate_governance.py:594` | governance sync YAML |

None of these opens the contract. **GAP-036's core factual claim is confirmed accurate.**

### Rule inventory

Counting scheme, stated explicitly because "rule count" is definition-sensitive:

| # | Rule group | Location | Count |
| --- | --- | --- | --- |
| R1 | `schema` identifier | `:21` | 1 |
| R2 | `status_vocabulary.values` | `:28-34` | 6 |
| R3 | `waiver_schema.required_fields` | `:39-46` | 7 |
| R4 | `waiver_schema.rule` (no anonymous suppression) | `:47-48` | 1 |
| R5 | `profiles.research_release.required_gates` | `:59-74` | 12 |
| R6 | `profiles.production_candidate.required_gates` | `:85-120` | 24 |
| R7 | `profiles.runtime_certified.required_gates` | `:131-138` | 5 (29 implied; see note) |
| R8 | profile policy knobs (`allows_waived`, `allows_incomplete`, `fails_closed_on` × 3 profiles) | `:75-77, 123-125, 139-142` | 9 |
| R9 | profile `current_status` / `current_status_reason` | `:143-149` | 2 |
| R10 | `visual_and_cooked_map_certificate.offline_fields` | `:156-164` | 7 |
| R11 | `visual_and_cooked_map_certificate.live_fields` | `:165-167` | 2 |
| R12 | certificate `current_status` / `current_status_reason` | `:168-174` | 2 |
| R13 | `do_not_duplicate` (prose policy acknowledgement) | `:176-181` | 1 |

**Totals**: **6** status values, **7** waiver fields, **29** unique required-gate names
(12 + 12 new + 5), **9** certificate field names, **9** per-profile policy booleans/lists,
**1** schema id, **4** declared current-status fields, **1** prose block.

> Note on R7: `runtime_certified` says "everything from `production_candidate`, plus:" (`:132`) but
> then lists only 5. A strict YAML reader sees a 5-element list; a reader honoring the comment sees
> 29. **This ambiguity is itself a contract defect** an executing consumer must resolve.

> Note on R5/R6: `production_candidate` says "everything from `research_release`, plus:" (`:86`) and
> does in fact contain all 12 `research_release` names, so 24 = 12 + 12 genuinely new. Verified
> gate-by-gate.

### SURPRISE #3 — the YAML's own GAP-006 claim is stale

The YAML asserts at `:108-110` that `semantic_overlap_geometric` is "currently dead code (see
GAP-006), not the currently-wired co-attachment heuristic". That is **no longer true**:
`ultimate_pipeline/quality/quality_gate_manager.py:120-137` now runs **both** implementations,
records a `semantic_overlap_comparison` report, and **fails the gate on the polygon result**
(`:134-137`). The YAML is stale in the optimistic direction.

---

## Step 2 — Per-rule: what an executing consumer must check, and whether it already exists

Legend: **REAL** = a non-trivial implementation exists somewhere; **WIRED** = also reachable from a
pipeline gate path; **PARTIAL** = implemented but not gated, or gated only under a different name;
**NONE** = no implementation found in any `.py`.

### R2 — status vocabulary (6 values)

A consumer must guarantee every validator result coerces to exactly one of these, and that
`SKIPPED` can never become `PASS` (`:24-27`).

**Already enforced, strongly.** `ultimate_pipeline/contracts/stage_contracts.py:46-67` defines
`QualityStatus` with exactly these six members. Three independent fail-closed converters exist:
`from_legacy_bool` (`:79-81`), `from_skipped_mandatory` → `INCOMPLETE` (`:84-86`),
`from_missing_external` → `BLOCKED_EXTERNAL` (`:89-91`). `_coerce_status` (`:329-349`) maps unknown
strings/objects to `INCOMPLETE`. `normalize_gate_result` (`:604-672`) is the single verdict authority
and is consumed by `QualityGateManager._finalize_gate`
(`ultimate_pipeline/quality/quality_gate_manager.py:58-65`) — whose comment at `:59-60` explicitly
forbids the historical `rep.get("ok", True)` fail-open. **This rule needs no new enforcement logic;
it needs only that a new consumer route results through `normalize_gate_result`.**

One vocabulary mismatch to note: `GATE_STATUS_SYNONYMS` (`stage_contracts.py:566-586`) maps
`"skipped"`/`"skip"` → `NOT_RUN` (`:580-581`), which is the correct reading of the YAML's intent.

### R3/R4 — waiver schema (7 fields + no-anonymous-suppression rule)

A consumer must reject any `WAIVED` status whose record lacks any of `identifier`, `gate_id`,
`exact_issue`, `owner`, `evidence`, `rationale`, `expiration_or_review_trigger`, and must block a
profile when a `FAIL`/`INCOMPLETE` has no matching record (`:47-48`).

**PARTIAL — the *mechanism* exists, the *schema* does not.**

- Mechanism, fully built and **actually wired**: `production_gate_waiver_allowed`
  (`stage_contracts.py:301-326`) enforces exact-name, non-blank justification and resolves
  `GateClass` fail-closed. Its one production caller is
  `ultimate_pipeline/quality/map_acceptance.py:1052-1054`.
- Mechanism, **built but zero production callers**: `governed_waiver_allowed` (`:265-298`),
  `promote_aggregate_detailed` (`:352-517`), `promote_aggregate` (`:520-559`).
  `git grep "promote_aggregate" -- ':!*/tests/*'` confirms **no non-test production module calls
  `promote_aggregate`**; it is exercised only by `tests/unit/test_stage_contracts_aggregate.py`.
- **The 7-field schema itself is nowhere in code.** `grep` for `expiration_or_review_trigger` and
  `exact_issue` returns zero `.py` matches. The only waiver payload in production is the single
  free-text string `component_reachability_waiver` (`map_acceptance.py:577`, consumed `:1050-1051`),
  which satisfies **1 of the 7** fields (`rationale`) and no schema validation.

`WARNING_REGISTRY` (`stage_contracts.py:128`) holds only **2** entries (`:679-701`) — neither is a
waiver record. **A consumer must add a waiver-record loader/validator; this is genuinely new code.**

### R5/R6/R7 — 29 required-gate names

A consumer must resolve each name to a real check, normalize its result, and apply the profile's
fail-closed policy. Resolution status per name:

| YAML gate name | Resolution | Existing implementation evidence |
| --- | --- | --- |
| `xodr_xml_integrity` | REAL+WIRED | `quality_gate_manager.py:77-85` → `check_xml_integrity.XMLIntegrityChecker`; wired `quality_gates.py:163` |
| `carla_structural_compatibility` | REAL+WIRED | `quality_gate_manager.py:160-184` → `check_carla_opendrive_compat.StrictCarlaOpendriveGate`; `quality_gates.py:165`; `measure_candidate_acceptance.py:189-193` |
| `component_reachability` | REAL+WIRED | `map_acceptance.py` (`component_reachability_summary`, `topology_certification`); `measure_candidate_acceptance.py:209-217`; waiver gate `map_acceptance.py:1044-1078` |
| `junction_integrity` | REAL+WIRED | `quality_gate_manager.py:292-305` → `check_junction_integrity.JunctionIntegrityGate`; `quality_gates.py:164`; `measure_candidate_acceptance.py:110-113` |
| `lane_link_targets_exist` | REAL+WIRED | `check_lane_link_targets_exist.py`; `quality_gates.py:176-181`; advisory-only in stage `stage_08_integrity.py:606-635` |
| `lane_width_continuity` | REAL+WIRED | `quality_gate_manager.py:309-320`; `measure_candidate_acceptance.py:115-118` |
| `lane_geometry_continuity` | REAL+WIRED | `quality_gate_manager.py:322-333`; `measure_candidate_acceptance.py:120-123` |
| `lane_section_successors` | REAL+WIRED | `check_lane_section_successors.py`; `measure_candidate_acceptance.py:78-81`; `stage_08_integrity.py:591-601` |
| `elevation_continuity` | REAL+WIRED | `quality_gate_manager.py:202-288`; `measure_candidate_acceptance.py:100-103` |
| `elevation_smoothness` | REAL+WIRED | `quality_gate_manager.py:87-96`; `measure_candidate_acceptance.py:135-139` |
| `elevation_seams` | REAL+WIRED | `quality_gate_manager.py:392-403`; `measure_candidate_acceptance.py:95-98` |
| `dem_full_coverage` | REAL+WIRED | `check_dem_full_coverage.py`; `stage_05_geometry.py:425`; `measure_candidate_acceptance.py:195-200` |
| `map_registry_identity` | REAL, **NOT GATED** | `ultimate_pipeline/carla_tools/map_registry.py:935 verify_pinned_map`, `PINNED_MAP_REGISTRY` at `:702`. Callers are **root-level scripts only** (`certify_ingolstadt.py:31,350`; `gap026_generate_artifacts.py:12,17`; `gap026_oracle.py:33,295`; `scripts/cook_full_grid_tiles.py:56,65`) — **never from `QualityGateManager`, `quality_gates.run_quality_gates`, or `build_map_acceptance`** |
| `collision_mesh` | REAL+WIRED | `quality_gate_manager.py:139-158`; `measure_candidate_acceptance.py:167-171` |
| `external_validator` | REAL, PARTIAL | Three distinct producers, none mapped: libOpenDRIVE `quality_gates.py:185-217` (`external_libopendrive`); `xodr_strict_validator.py` via `quality_gate_manager.py:440-449`; preflight loadability via `stage_08_integrity.py:943-1007`. The YAML (`:117`) names two of these as if they were one gate |
| `deterministic_provenance` | REAL, **NOT GATED** | `ultimate_pipeline/quality/check_determinism.py:146 check_determinism` + `compute_structural_hash` `:36`; tested `tests/unit/test_c9_tail_gate_controls.py:209-227`. **Absent from `QualityGateManager` and from `run_gates()`** — reachable only via its own CLI |
| `semantic_overlap_geometric` | REAL+WIRED | `quality_gate_manager.py:120-137`; polygon impl `ultimate_pipeline/quality/semantic_overlap.py PolygonChecker`. **Contradicts the YAML's own GAP-006 "dead code" note at `:108-110`** |
| `connector_boundary_offset` | REAL, NOT in profile path | `quality_gate_manager.py:357-379 gate_junction_connector_boundary_alignment` (`check_geometric_continuity(gate_junction_connectors=True)`); test `tests/unit/test_junction_connector_boundary_gate.py`. Docstring `:360-366` explicitly says this exists so "a production-candidate certifier can require zero unresolved offsets" — i.e. **built for Option A and waiting for it** |
| `elevation_structure_separation` | REAL, NOT in profile path | `quality_gate_manager.py:405-436 gate_structure_elevation_plausibility` → `check_structure_elevation_plausibility` |
| `lane_count_provenance` | PARTIAL, weak | `enrichment/lane_generator.py` (2 refs) and `quality/check_lane_count_changes.py`; `map_acceptance.py:657-686` treats lane-count *changes* as a soft warning only, not per-lane provenance as the YAML (`:99-101`) demands |
| `connector_pose_validation` | **NONE** | zero `.py` matches (YAML `:91-92` admits "does not exist yet", GAP-004) |
| `lane_link_direction_validity` | **NONE** | zero `.py` matches (YAML `:96`, GAP-011) |
| `osm_correspondence_confidence` | **NONE** | no confidence-scoring gate. Related-but-different: `enrichment/osm_meta_index.py`, `signals/turn_lanes_writer.py`, `quality/semantic_completeness.py` (YAML `:111-114`, GAP-005). `docs/architecture/TARGET_PIPELINE_STAGE_GRAPH.md:81-83` independently confirms "this doesn't exist as a stage at all" |
| `crosswalk_signal_sign_geometric_validity` | **NONE** | only `quality/semantic_completeness.py` mentions crosswalks; no geometric-validity gate (YAML `:115`) |
| `visual_cooked_map_certificate` | **NONE** as a gate | no consumer; see R10-R12 |
| `carla_world_loads` | **NONE** (as this gate) | runtime-blocked; YAML `:143-149` declares `BLOCKED_EXTERNAL` |
| `carla_ego_spawns_on_valid_surface` | PARTIAL | `stage_08_integrity.py:344-428 _step8c_spawn_validation` checks spawn-point count, not "ego rests on valid surface"; and it is gated behind `ENABLE_SPAWN_VALIDATION_STEP8` (`:879`) |
| `carla_waypoint_graph_matches_visible_roads` | **NONE** | runtime-blocked |
| `carla_no_detached_road_slabs_live` | **NONE** (live) | offline analogue exists; see R10 |
| `visual_cooked_map_certificate_live_fields` | **NONE** | see R11 |

**Subtotal: 16 REAL+WIRED, 5 REAL-but-not-gated/not-in-path, 2 PARTIAL, 8 NONE.**
(18 + 4 = 22 have *something*; 8 need new check code; 9 have zero.)

### R8 — per-profile policy (9 knobs)

| Profile | `allows_waived` | `allows_incomplete` | `fails_closed_on` | Already modelled? |
| --- | --- | --- | --- | --- |
| `research_release` | `true` (`:75`) | `true` (`:76`) | `[FAIL]` (`:77`) | NO — no profile concept exists anywhere |
| `production_candidate` | `true` (`:123`) | `false` (`:124`) | `[FAIL, INCOMPLETE, NOT_RUN]` (`:125`) | NO |
| `runtime_certified` | `false` (`:139`) | `false` (`:141`) | `[FAIL, INCOMPLETE, NOT_RUN, BLOCKED_EXTERNAL]` (`:142`) | NO |

The closest existing machinery is `QualityStatus` severity ordering in `_worst_of`
(`stage_contracts.py:233-262`), which ranks `FAIL > INCOMPLETE > BLOCKED_EXTERNAL > WAIVED > NOT_RUN >
PASS` (`:239-246`). Note this ordering **conflicts with the YAML's per-profile `fails_closed_on` in
one place**: `_worst_of` treats `BLOCKED_EXTERNAL` (severity 3) as *less* severe than `INCOMPLETE`
(4), but `runtime_certified` (`:142`) blocks on all four and `research_release` (`:77`) blocks on
`FAIL` only. A consumer needs per-profile severity sets, not the single global ladder. Genuinely
new logic.

`GateClass` (`stage_contracts.py:158-166`) and `NON_WAIVABLE_CLASSES` (`:168-174`) give a *second*,
partially-overlapping policy axis that the YAML does not know about.

### R9/R12 — declared `current_status` / reasons (4 fields)

These are **observations about the world**, not rules a consumer enforces: `runtime_certified` is
`BLOCKED_EXTERNAL` (`:143`) and the certificate is `INCOMPLETE` (`:168`). A consumer's only job is to
*reproduce* these truthfully rather than assert them. No new checking code; note that hardcoding them
would defeat the purpose.

### R10/R11 — certificate fields (7 offline + 2 live)

**NONE of these 9 is enforced as a gate.** What exists is loose tooling, all reached only through
Phase J (`ultimate_pipeline/tools/phase_j_osm2world_blender.py`), never from `main_pipeline.py` —
matching the YAML's own admission at `:152-155` and GAP-013.

| Certificate field | YAML claim (`:157-167`) | Verified reality |
| --- | --- | --- |
| `no_detached_road_slabs` | real, smoke-scale | `enrichment/detached_slab_check.py`; driven at `tools/phase_j_osm2world_blender.py:20` ("J8 detached-slab validation") |
| `no_road_terrain_penetration` | real, smoke-scale | same file/driver |
| `no_floating_roads` | "same mechanism as above" | `floating_slab_check` exists — but as a **function** at `enrichment/detached_slab_check.py:184`, **not** a `floating_slab_check.py` file. The YAML's file-name reference is imprecise |
| `collision_surface_follows_drivable_surface` | real, AABB-approx | `enrichment/collision_lod_policy.py` exists |
| `building_transforms_sane` | partial, via coordinate control | `enrichment/coordinate_control.py` exists |
| `no_malformed_junction_patches` | partial (degenerate faces only) | consistent with `check_junction_integrity` scope; no dedicated certificate check |
| `no_severe_z_fighting` | **NOT IMPLEMENTED** (GAP-027) | **Confirmed accurate.** Only `ultimate_pipeline/tiling/tile_fbx_generator.py` mentions z-fighting, and that is tile export, not this gate |
| `ego_vehicle_rests_on_valid_surface` | NOT_RUN | no implementation; runtime-blocked |
| `waypoint_graph_corresponds_to_visible_roads` | NOT_RUN | no implementation; runtime-blocked |

**SURPRISE #4**: the YAML cites `floating_slab_check` as if a module; it is a function inside
`detached_slab_check.py`. Minor, but a doc-accuracy data point.

---

## Step 3 — Where an enforcing consumer would plug in

### The low-friction insertion point

**`build_map_acceptance()` — `ultimate_pipeline/quality/map_acceptance.py:568-578`.**

```python
568: def build_map_acceptance(
569:     reports: Dict[str, Any],
570:     *,
571:     run_id: str | None = None,
572:     final_xodr_path: str | None = None,
573:     osm_source_path: str | None = None,
574:     out_dir: str | None = None,
575:     require_enrichment: bool = False,
576:     require_component_reachability: bool = False,
577:     component_reachability_waiver: str | None = None,
578: ) -> Dict[str, object]:
```

This is the best candidate because:

1. **The data is already there.** `reports` is a `Dict[str, Any]` already keyed by gate name and
   already populated by both callers — `scripts/measure_candidate_acceptance.py:66-219`
   (`run_gates`) and the pipeline. The 16 WIRED gates above need **no new measurement**, only a
   profile layer over keys that already exist.
2. **The xodr path is already there**: `final_xodr_path` (`:572`), hashed at `:587-589`.
3. **The out_dir is already there**: `:574`, matching `_run_id_from_out_dir(out_dir)` at `:584-585`.
4. **The hard/soft split is already there**: `hard_fail_reasons: List[Dict[str,str]]` (`:579`),
   `soft_warnings` (`:580`), and the terminal verdict `valid_for_experiments = len(hard_fail_reasons) == 0`
   (`:1080`). A profile verdict slots in as a `hard_fail_reasons` contributor.
5. **Both real consumers already route here.** `measure_candidate_acceptance.py:247-254` calls it with
   `require_enrichment` / `require_component_reachability` — i.e. today's *de facto* profile knobs are
   already two argparse booleans (`:227-232`), exactly the seam Option A would generalize.

### Required inputs, itemized

| Input | Available? | Evidence / gap |
| --- | --- | --- |
| xodr path | **Yes** | `map_acceptance.py:572` (`final_xodr_path`), `:587-589` |
| `reports` dict (per-gate results) | **Yes** | `map_acceptance.py:569`; keys `elevation_seams` `:591`, `elevation_continuity` `:610`, `dem_coverage` `:622`, `geometric_continuity` `:634`, `lane_section_successors` `:644`, `lane_count_changes` `:657`, `lane_connectivity` `:688`, `component_reachability` `:1013-1078` |
| `out_dir` (for waiver-record persistence) | **Yes** | `:574` |
| `run_id` | **Yes** | `:571`, defaulted `:584-585` |
| DEM path | **NO — must be added** | `build_map_acceptance` takes no DEM arg, yet `dem_full_coverage` (YAML `:73`, `:107`) needs one. `measure_candidate_acceptance.py:226` has `--dem`; default at `:57` |
| tile manifests | **NOT NEEDED** | Verified: no YAML gate consumes tile data. Explicitly *not* required, contrary to what "tile manifests" might suggest |
| live CARLA handles | **NO — by design** | `runtime_certified` is `BLOCKED_EXTERNAL` per YAML `:143-149`; consumer only needs to emit that status correctly |

### The pipeline-side insertion point

**A new `_stage_gate` block in `MainPipeline.run()` between the artifact freeze and tiling**, i.e.
immediately after `self._publish_final_artifact_authority(...)` at
`ultimate_pipeline/main_pipeline.py:2391-2397` and before `# 9) 🧩 Tiling` at `:2444-2446`. At that
point `final_out` is frozen (`main_pipeline.py:2385-2390` states the freeze semantics explicitly) and
`origin_report` / `seam_report` are in scope from `:2225` and `:2366-2370`.

### Registration patterns to copy (verbatim precedents)

**(a) `_stage_gate` — the canonical stage-gate registration.**
`ultimate_pipeline/main_pipeline.py:3323-3349`. Signature `self._stage_gate(stage, name, fn)`; it
lazily constructs a `CumulativeGateRunner` (`:3333-3338`, class at
`ultimate_pipeline/contracts/gate_runner.py:19`), runs `fn()`, writes
`<out_dir>/qa_stage_reports/{stage}__{name}.json` (`:3340-3346`), and is **tally-all / fail-at-end**
(`:3330`, `:3338` via `runner.run`). Final raise happens in `_finalize_gates()` (`:3351-3365`).
Live call sites to imitate: `main_pipeline.py:2424`, `:2437`, `:2455-2458`, `:2366-2370`;
`pipeline_stages/stage_08_integrity.py:1022-1026`.

**(b) `QualityGateManager` gate-method template** —
`ultimate_pipeline/quality/quality_gate_manager.py:202-220` (a clean 19-line example) or
`:392-403`. Required sequence per gate:
- `_require_path(xodr_path, gate_name)` type guard — `:67-73`
- lazy import of the `check_*` module — `:205-207`
- `_persist_optional(rep, stage or "<name>")` — `:42-56`
- `_finalize_gate(name, rep)` → `normalize_gate_result` — `:58-65`
- return the raw `rep` dict so the caller can aggregate

**(c) `_try(label, fn)` — mandatory for the post-pipeline sweep.**
`ultimate_pipeline/quality/quality_gates.py:149-161`, used at `:163-171`. Its docstring/comment at
`:155-160` warns of the exact trap: on crash it must record under the **bare** label, "so a crashed
gate [isn't] invisible to the hard drivability check even though a cleanly-failed one is caught."

> **Blocking-set trap (important).** A new gate name is **silently non-blocking** unless added to
> `DRIVABILITY_GATES` (`quality_gates.py:26-34`) or `BLOCKING_GATE_NAMES` (`:51`). This is not
> hypothetical — the comment at `:36-40` records it as NEW-341, a real bug where `xml_parse` /
> `quality_gate_manager_import` were returned but never intersected into `DRIVABILITY_GATES`. Any
> Option A implementation must update these frozensets, and a test must assert set membership.

**(d) Waiver + classification registration.**
`stage_contracts.py:179-208` (`GATE_CLASS_REGISTRY`) and `:131-145` (`register_warning`, which
**raises on a duplicate code with a different definition** — `:135-142`).

**(e) Aggregation.** `stage_contracts.py:352-517` (`promote_aggregate_detailed`) already accepts
`child_names` for strict label→position binding (`:415-430`, raising on length mismatch `:417-419`
and duplicates `:423-430`) and `enforce_taxonomy=True` for NEW-210 production mode (`:449-455`).

### The two hard problems an implementer must solve

**Problem 1 — gate-name aliasing is required, and the registry does not cover most names.**
Producer keys diverge from YAML names in at least 8 places:

| YAML name | Actual producer key | Evidence |
| --- | --- | --- |
| `xodr_xml_integrity` | `xml_integrity` | `quality_gate_manager.py:83,85`; `quality_gates.py:163` |
| `carla_structural_compatibility` | `carla_opendrive_compat` | `quality_gate_manager.py:180,184` |
| `lane_link_targets_exist` | `lane_link_targets` | `quality_gates.py:179,181` |
| `lane_geometry_continuity` | `geometry_continuity` | `stage_contracts.py:206` |
| `lane_width_continuity` | `lane_width` | `stage_contracts.py:205` |
| `elevation_continuity` / `elevation_smoothness` | `elevation_quality` (both) | `stage_contracts.py:207` |
| `dem_full_coverage` | `dem_coverage` | `measure_candidate_acceptance.py:197` |
| `external_validator` | `external_libopendrive` | `quality_gates.py:200` |

**Problem 2 — a waiver-policy contradiction the contract does not resolve.**
`GATE_CLASS_REGISTRY` (`stage_contracts.py:179-208`) classifies only **12 of the 29** YAML gate
names, and 4 of those 12 only via aliasing (2 ambiguously: both elevation gates map to one
`elevation_quality` key). The remaining **17 are unregistered**, and
`production_gate_waiver_allowed` **fails closed** on unregistered names (`stage_contracts.py:318-320`
→ `classify_gate` returns `None` at `:219` → returns `False` at `:320`).

But `production_candidate` declares `allows_waived: true` (YAML `:123`). So under
`enforce_taxonomy=True`, **17 of that profile's 24 required gates become structurally unwaivable** —
including `connector_boundary_offset` and `elevation_structure_separation`, both of which exist and
were built specifically to serve this profile. Meanwhile `runtime_certified` declares
`allows_waived: false` (`:139`) and **none** of its 5 gate names is registered as
`GateClass.RUNTIME_DEPENDENT` (`:200-202`); they get the right answer only by accidental fail-closed.
An implementer must extend the registry or accept a narrower waiver surface than the YAML promises.
**This is a real design decision, not a mechanical gap, and it is precisely why GAP-036 needs a
human policy call.**

---

## Step 4 — Option A code estimate (real executing consumer)

### Component breakdown

| # | Component | Est. lines | Confidence |
| --- | --- | --- | --- |
| 1 | `ultimate_pipeline/contracts/quality_contract.py` (new): YAML load, schema-id check, fail-closed parse, dataclasses for Profile/Certificate | 180–260 | Med |
| 2 | Gate-name alias table (YAML name → producer key → `GateClass`) + loader | 50–90 data + ~30 loader | Med |
| 3 | `GATE_CLASS_REGISTRY` extension: classify the 17 unregistered names | 20–40 | High |
| 4 | Profile evaluator: resolve required gates → `_coerce_status`/`normalize_gate_result` → `promote_aggregate_detailed(enforce_taxonomy=True)` → apply `fails_closed_on` / `allows_waived` / `allows_incomplete` | 120–200 | Med |
| 5 | Waiver-record store: validate the 7 `required_fields`, persist next to evidence, reject anonymous suppression (`R4`) | 90–140 | Med |
| 6 | Wire into `build_map_acceptance()`: new kwargs + `profile_verdict` in the `map_acceptance_v1` payload (`:1088+`) | 50–90 | High |
| 7 | CLI surface: `--acceptance-profile` on `scripts/measure_candidate_acceptance.py` (argparse `:222-233`) + pipeline entrypoint/settings | 40–70 | High |
| 8 | `QualityGateManager` methods for the ~4 real-but-unregistered gates (determinism, connector-boundary, structure-elevation, certificate fields) | 150–250 | Med |
| 9 | **New gates for the 8 `NONE` names** (connector_pose_validation, lane_link_direction_validity, osm_correspondence_confidence, crosswalk_signal_sign_geometric_validity, no_severe_z_fighting, + runtime ones) | **400–900** | **Low** |
| 10 | `visual_and_cooked_map_certificate` aggregator (7 offline fields from loose Phase J tools) | 120–200 | Low |
| 11 | `runtime_certified` live-field emitters that correctly report `BLOCKED_EXTERNAL` (actual CARLA work is GAP-017, out of scope) | 30–60 | Med |
| | **Subtotal, components 1–8 + 11 (policy/profile layer only)** | **730–1,140** | |
| | **Subtotal, all 11 (full Option A)** | **1,250–2,260** | |

### Total estimate

- **Full Option A: ~1,250–2,260 lines** of production code.
- **Policy/profile layer only** (components 1–8 + 11; missing gates reported `NOT_RUN` rather than
  implemented): **~730–1,140 lines**.

`GAP036_POLICY_PROPOSAL.md:90` estimated ~1,650 lines / ~11 days. My independent range brackets it,
but I would weight it differently: the proposal folds ~400 lines of "visual certificate" into a flat
total and does not surface the alias-table problem (component 2) or the waiver-policy contradiction
(Problem 2) as separate line items.

### Honest uncertainty

1. **Component 9 dominates the spread and I did not measure it.** I read the *absence* of these gates
   (via repo-wide `git grep`) but did not read the problem domains (junction pose validity,
   turn-lane correspondence scoring, z-fighting detection). 400 vs 900 is a genuine order-of-magnitude
   guess.
2. **Scope boundary is undefined.** The YAML itself delegates its missing gates to other GAP ids
   (GAP-004 `:91`, GAP-002 `:93`, GAP-011 `:96`, GAP-001/019 `:99`, GAP-009/010 `:106`, GAP-005 `:111`,
   GAP-006 `:108`, GAP-027 `:159`, GAP-013 `:153`). **If those are meant to be implemented under their
   own GAPs, Option A is only the policy layer (~730–1,140 lines) and does not need component 9 at
   all.** This single scope question moves the estimate by ~800 lines.
3. **Not read, so cost unverified**: `check_geometric_continuity`, `map_registry.verify_pinned_map`,
   `check_dem_full_coverage`, `semantic_overlap.py`, `topology_certification.py`,
   `contracts/gate_runner.py`, and `submission/infrastructure/` (a full mirror tree — if it must be
   kept in sync, every estimate above roughly **doubles** for changed files; I did not determine
   whether that mirror is generated or hand-maintained).
4. **Component 1 line count assumes PyYAML is available.** It is used in-tree
   (`agent_sync.py:247`), but I did not verify it is a declared dependency.

### Tests

Estimated **3–5 new test files, ~40–62 new test functions, ~600–1,100 test lines.**

| File | Tests | Coverage |
| --- | --- | --- |
| `tests/unit/test_quality_contract_profile_enforcement.py` (new) | 20–28 | schema parse fail-closed; all 3 profiles resolve; `fails_closed_on` per profile; `allows_waived` / `allows_incomplete`; `NOT_RUN` vs `BLOCKED_EXTERNAL` not conflated; **no-SKIPPED-as-PASS regression**; alias-table completeness (every one of the 29 names resolves to a real producer key) |
| `tests/unit/test_quality_contract_waiver_records.py` (new) | 10–16 | all 7 `required_fields` enforced; missing-field rejection; anonymous-suppression rejection; expiry/review-trigger; non-waivable class rejected; unknown gate name fails closed |
| `ultimate_pipeline/tests/unit/test_quality_contract_gate_classes.py` (new) | 6–10 | all 29 names classify (no `None`); `NON_WAIVABLE_CLASSES` membership correct |
| `tests/unit/test_map_acceptance.py` (**extend**, exists) | 5–8 | `profile_verdict` propagates into `hard_fail_reasons` / `valid_for_experiments` |
| `tests/unit/test_quality_gates_blocking_set.py` (new, small) | 3–5 | every profile-required gate name is in `DRIVABILITY_GATES`/`BLOCKING_GATE_NAMES` (`quality_gates.py:26-51`) — direct NEW-341 regression guard |

**Test-file placement rationale** (measured, not guessed): `tests/unit/` holds 256 files and owns the
acceptance-layer tests — `test_map_acceptance.py`, `test_measure_candidate_acceptance_drivability_gates.py`,
`test_measure_candidate_acceptance_junction_integrity.py`, `test_stage_contracts_aggregate.py`,
`test_c9_tail_gate_controls.py` — so profile/acceptance tests belong there.
`ultimate_pipeline/tests/unit/` holds 166 files and owns contract-vocabulary tests —
`test_waiver_taxonomy.py` is the direct precedent for the gate-class file, and
`test_stage_contracts_aggregate.py` covers `promote_aggregate`.

---

## Step 5 — Option B scope (formally deprecate / relabel as non-normative)

### Search method

Repo-wide `grep` for the literal string `PRODUCTION_MAP_QUALITY_CONTRACT` → **76 matches across 19
distinct files** (hand-tallied per file and cross-checked to sum to 76). Separately, all 40 YAML rule
keys were `git grep`'d against `*.py *.ps1 *.sh *.yml *.yaml` (Step 2 table) — **no rule key appears in
any non-documentation, non-archive `.py` file under a name that implies contract-driven control.**
The only `.py` hits for rule keys are `ultimate_pipeline/contracts/stage_contracts.py` (the
`GATE_CLASS_REGISTRY`, which is a *separate* taxonomy) and tests.

### Classification: real enforcement claims vs mere mentions

**Category 1 — ALREADY disclaimed. No further work (3 files, 4 lines).**
Done by commit `0f9f827c`.

| File:line | Text |
| --- | --- |
| `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:1-8` | `NON-NORMATIVE REFERENCE DOCUMENTATION` banner |
| `docs/index.md:32` | "(historical reference) the unified acceptance-profile contract (not executed by runtime)" |
| `docs/architecture/TARGET_PIPELINE_STAGE_GRAPH.md:89` | `# Note: Non-normative historical reference` |
| *(partial)* `docs/index.md:65` | **still residual** — lists the YAML bare, next to `MAP_QUALITY_GAP_REGISTER.json`, with no qualifier. Counts in Category 2 below. |

**Category 2 — REAL ENFORCEMENT CLAIMS that need a normativity note (8 files).**

*Live (non-archived) — 4 files, 10 lines:*

| File:line | Claim |
| --- | --- |
| `GAP026_POLICY_PROPOSAL.md:41` | "It must be emitted as `WAIVED`-eligible ... per `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:waiver_schema`" |
| `GAP026_POLICY_PROPOSAL.md:58` | "**Per** `...:waiver_schema`, a `WAIVED` status **requires**: `identifier, gate_id, ...`" |
| `GAP026_POLICY_PROPOSAL.md:76` | "in addition to **the existing** `...:production_candidate` gates" |
| `GAP026_POLICY_PROPOSAL.md:91` | "**add** `junction_lanelink_pose_continuity` **to** `...:production_candidate.required_gates`" — instructs editing the YAML as live config |
| `GAP026_ROOT_CAUSE.md:197` | "`BLOCKED_EXTERNAL` **per** `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:runtime_certified`" — treats a self-declared status as fact |
| `GAP037_POLICY_PROPOSAL.md:13` | "The waiver model (defined in `...:waiver_schema` and **implemented in** `stage_contracts.py`)" — second clause is now true via `map_acceptance.py:1052`; first implies the YAML defines it |
| `GAP037_POLICY_PROPOSAL.md:105` | lists "`PRODUCTION_MAP_QUALITY_CONTRACT.yaml` gate lists" as live material to reconcile |
| `GAP037_POLICY_PROPOSAL.md:168` | "the waiver record schema (`...:waiver_schema`) **should be extended** with optional `gate_class`" — prescribes editing a non-executing artifact |
| `docs/index.md:65` | residual bare listing (see Category 1 note) |

*Archived under `docs/archive/root_reports_pre_20260912/` — 4 files, 9 lines:*

| File:line | Claim |
| --- | --- |
| `PRODUCTION_MAP_TASK_GRAPH.json:365` | task title: "**Wire** `PRODUCTION_MAP_QUALITY_CONTRACT.yaml`'s `production_candidate` profile **into** `scripts/measure_candidate_acceptance.py` **as a real, selectable acceptance profile**" — the single clearest enforcement claim in the repo |
| `PRODUCTION_MAP_TASK_GRAPH.json:46` | `affected_files` lists the YAML |
| `PRODUCTION_MAP_TASK_GRAPH.json:356` | "...or `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` **gets an explicit `WAIVED` entry with rationale**" |
| `PRODUCTION_MAP_TASK_GRAPH.json:373` | `evidence` field points at the YAML |
| `DOCS_INFORMATION_ARCHITECTURE.md:18` | "`PRODUCTION_MAP_QUALITY_CONTRACT.yaml` ... **now serves this role**" |
| `DOCS_INFORMATION_ARCHITECTURE.md:49` | same claim, inside a diagram |
| `CLAUDE_PRODUCTION_MAP_AUDIT.md:150` | "`PRODUCTION_MAP_QUALITY_CONTRACT.yaml` **unifies** the existing, extensive quality-gate system" |
| `CLAUDE_PRODUCTION_MAP_AUDIT.md:250` | "into **fail-closed profiles per** `PRODUCTION_MAP_QUALITY_CONTRACT.yaml`" |
| `MAP_QUALITY_GAP_REGISTER.json:155` | "`VISUAL_AND_COOKED_MAP_CERTIFICATE` (see `...`) **cannot currently be issued**" |

> **UNCERTAIN — archive mutability.** I found **no governance rule** that declares
> `docs/archive/` immutable. `docs/index.md:80-83` lists only `../submission/` as "Frozen (do not
> edit)". A *stale* hygiene report asserts the opposite (`REPORT_REPO_HYGIENE_ROUND3.md:30`:
> "`docs/archive/`: Does not exist"), which shows the archive directory postdates that report and has
> no policy of record. So the 4 archived files are **listed but not recommended for edit** — I cannot
> determine from the repo whether editing them is permitted or desirable. `0f9f827c`'s own commit
> message called them "the remaining 7-of-9 referencing docs (archived reports under `docs/archive/`)
> ... intentionally left", implying the author considered them out of that pass's scope.

**Category 3 — MERE MENTIONS or already-states-the-opposite. No change (10 files).**
Disclaiming these would be redundant at best and self-contradicting at worst.

| File:line | Why no change |
| --- | --- |
| `GAP036_POLICY_PROPOSAL.md` (11 refs: `1, 13, 29, 58, 62-67, 70, 111`) | This **is** the document proving there is no consumer (`:19`, `:29`, `:46`, `:52`). Its `:58-70` table is the enumeration of the offenders. |
| `reports/v5_incremental_closure/20260929T160422Z/PRODUCTION_QUALITY_CONTRACT_MATRIX.json:28` + 22 `"caller": "see ... consumers"` rows | `:28` literally states "**has NO EXECUTING CONSUMER in the repository**" |
| `reports/v5_incremental_closure/.../FINAL_SUMMARY.md:50` | "has no executing consumer" |
| `reports/v5_incremental_closure/.../FINAL_GAP_MATRIX.json:38` | "has no executing consumer" |
| `reports/production_readiness/20261007T000000Z_GAP_STATUS_AUDIT/AUDIT_REPORT.md:43, 47, 51` | `:43` "GAP-036 (open) — ... has no executing consumer"; `:47` zero `.py` matches. **(`:38` "Waiver semantics per `...` schema" is a normative-flavored mention → borderline; include in the 4 live files if a strict pass is wanted.)** |
| `reports/final_gap_closure/20260930T142358Z/ACTUAL_GATE_EXECUTION_MATRIX.json:13` | already says "NON-NORMATIVE reference; **not an execution authority**" |
| `reports/production_readiness/.../MASTER_GAP_REGISTER.md:44, 73` | the GAP-036 row itself already reads "declarative quality contract with no executing consumer" |
| `reports/production_readiness/.../MASTER_GAP_REGISTER.json:649-651, 989` | GAP-036 entry: "nothing in the Python codebase loads, parses, or enforces it", "returns **ZERO** matches" |
| `reports/production_readiness/.../MASTER_GAP_REGISTER.json:94` | GAP-0xx residual risk: "**Not wired into** ... `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` — deliberately out of scope" — already accurate |
| `runs100.json:20847, 20920, 21832` | API/git transcript log; `20920` is the `0f9f827c` commit body, which **already records the non-normative resolution**. Editing a transcript would falsify it. |
| *(self)* `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:21` | `schema: PRODUCTION_MAP_QUALITY_CONTRACT/v1` — self-reference, already covered by `:1-8` |

### Option B counts

| Metric | Count |
| --- | --- |
| Distinct files referencing the filename (whole repo) | **19** |
| Distinct files referencing it **as if enforced** (Category 2) | **8** — 4 live + 4 archived |
| — of which **live / non-archived** (the actionable set) | **4** (`GAP026_POLICY_PROPOSAL.md`, `GAP026_ROOT_CAUSE.md`, `GAP037_POLICY_PROPOSAL.md`, `docs/index.md`) |
| — of which **archived, mutability undetermined** | **4** |
| Total lines needing a normativity note | **19** (10 live + 9 archived) |
| Already disclaimed by `0f9f827c` | 3 files / 4 lines |
| Mere mentions, no change | **10** files |
| **Renames required** | **0** — the file is already self-disclaimed at `:1-8`; a rename is not needed for honesty, only for discoverability |

This is materially smaller than `GAP036_POLICY_PROPOSAL.md:72` ("10 distinct references across 9
files ... ~200 lines changed across 11 files, ~4 engineering hours"), because that estimate predates
`0f9f827c` and does not separate the archive from live docs.

---

## Cross-cutting surprises (consolidated)

1. **`0f9f827c` already did the file-level part of Option B.** The YAML has carried a
   `NON-NORMATIVE` banner since that commit. Any Option B scope estimate written before it over-counts.
2. **The YAML is stale in the *optimistic* direction**: its GAP-006 "semantic_overlap is dead code"
   note (`:108-110`) is contradicted by `quality_gate_manager.py:120-137`, which now fails on the
   real polygon result.
3. **`connector_boundary_offset` and `elevation_structure_separation` were built for Option A and are
   already waiting.** `quality_gate_manager.py:357-379` docstring `:360-366` says the split exists so
   "a production-candidate certifier can require zero unresolved offsets". Neither is in any profile
   path today — this is the clearest evidence of what an eventual consumer should call.
4. **The waiver *mechanism* is largely built; the waiver *schema* is entirely absent.**
   `production_gate_waiver_allowed` is wired (`map_acceptance.py:1052`), but all 7 YAML
   `required_fields` exist in no code path, and `promote_aggregate` has **zero** non-test callers.
5. **A hard design contradiction sits inside Option A** (Problem 2, Step 3): 17 of 24
   `production_candidate` gates are unregistered in `GATE_CLASS_REGISTRY` and therefore
   structurally unwaivable, contradicting `allows_waived: true` (YAML `:123`). This cannot be
   resolved mechanically and is why GAP-036 warrants a human decision.
6. **Two YAML ambiguities a loader must resolve**: `runtime_certified` says "everything from
   `production_candidate`, plus:" then lists 5 (`:131-138`); and `floating_slab_check` is cited as a
   module but is a function at `detached_slab_check.py:184`.
7. **The `BLOCKING_GATE_NAMES` trap is real and precedented** (NEW-341, `quality_gates.py:36-40`): a
   new gate that is not added to `DRIVABILITY_GATES`/`BLOCKING_GATE_NAMES` fails *open*.
8. **`no_severe_z_fighting` is the only YAML claim fully confirmed as unimplemented** — the single
   honest gap statement in the file (`:159`).

---

## Method / integrity notes

- Commands run: read-only `git log`/`git status`/`git grep`/`git ls-files`, plus `Read`/`Grep`/`Glob`.
  **No mutating git command was issued. No file outside this report was written or edited.**
- Working tree was already dirty from a concurrent agent (`git status` shows modified
  `stage_07_lanes.py`, `main_pipeline.py`, `RQ1_FULL_DETERMINISM_MATRIX.json`, several test files, and
  untracked scratch scripts such as `check_commits.py`, `parse_runs.py`). **Those files were not
  touched and none of the findings above depend on them** — every cited file:line was read from a
  file not in the modified set. Worth flagging that the working tree was not clean at scout time.
- 76 grep matches were hand-tallied per file; per-file counts sum to 76, cross-checked.
- Not read (so costs unverified): `check_geometric_continuity`, `map_registry.verify_pinned_map`
  body, `check_dem_full_coverage`, `semantic_overlap.py`, `topology_certification.py`,
  `contracts/gate_runner.py`, `check_determinism.py` body, all of
  `submission/infrastructure/` (mirror tree), and whether `docs/archive/` is governance-immutable.