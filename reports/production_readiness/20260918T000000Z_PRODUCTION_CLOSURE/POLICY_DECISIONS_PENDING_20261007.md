# Policy Decisions Pending — 2026-10-07

Five gaps are blocked on human policy decisions, not code fixes. This document records the exact decision needed, concrete options with evidence-based effort estimates, and the consequence of no decision.

---

## GAP-036: PRODUCTION_MAP_QUALITY_CONTRACT.yaml Has No Executing Consumer

**Decision needed**: Whether to build a real executing consumer for the YAML contract or formally deprecate/relabel it as non-normative reference documentation.

### Option A: Build a Real Executing Consumer

| Integration Point | Scope | Effort |
|-------------------|-------|--------|
| YAML loader (`ultimate_pipeline/contracts/quality_contract.py`) | Parse/validate YAML at startup | ~200 lines, 1 day |
| Profile selection CLI flag | `--acceptance-profile {research_release,production_candidate,runtime_certified}` on `measure_candidate_acceptance.py` and pipeline entrypoint | ~100 lines, 0.5 day |
| Gate name mapping | Map YAML gate names (`xodr_xml_integrity`, `carla_structural_compatibility`, etc.) to actual gate implementations in `QualityGateManager` / `measure_candidate_acceptance.py` | ~300 lines, 2 days |
| Waiver integration | Wire `waiver_schema` → `governed_waiver_allowed()` + `promote_aggregate()`; store waiver records alongside gate evidence | ~200 lines, 1.5 days |
| Profile policy enforcement | Implement `allows_waived`, `allows_incomplete`, `fails_closed_on` per profile in aggregation logic | ~150 lines, 1 day |
| Visual certificate | Wire `visual_and_cooked_map_certificate` offline/live fields into `QualityGateManager` and CARLA runtime gates | ~400 lines, 3 days (depends on GAP-017 CARLA runtime) |
| Tests | Contract conformance: profile selection, gate mapping, waiver application, fail-closed behavior | ~300 lines, 2 days |

**Subtotal**: ~1,650 lines, **~11 engineering days** (single engineer, no parallelization).

**Critical dependency**: The RoadRunner `gate_matrix` subsystem (`ultimate_pipeline/roadrunner/gate_matrix.py`) is a **second complete gate system** with different profiles (`structural_release`, `visual_build`, `governed_map_release`, `debug`, `scenario_augmentation`) and different gate IDs (`source_integrity`, `semantic_diff`, `mesh_xodr_alignment`, `artifact_hashes`, `artifact_transaction`, `capability_probe`, `map_identity`). Building a consumer for the YAML contract without reconciling `gate_matrix` repeats the same mistake — creating a third decorative layer. Any Option A **must** either (a) subsume `gate_matrix` into the YAML contract, or (b) explicitly partition: YAML = map-quality gates; `gate_matrix` = RoadRunner artifact gates. Reconciliation adds **~3–4 weeks**.

### Option B: Formally Deprecate/Relabel as Non-Normative Documentation

| Action | Files | Effort |
|--------|-------|--------|
| Rename file | `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` → `PRODUCTION_MAP_QUALITY_CONTRACT_REFERENCE.yaml` | 1 commit |
| Add header disclaimer | `# NON-NORMATIVE REFERENCE DOCUMENT — No executing consumer exists. See GAP-036.` | 5 lines |
| Update 9 referencing files | Replace normative language ("the contract requires", "wire the contract") with reference language ("the reference document describes") | ~2 hours |
| Update GAP-026 docs | `GAP026_ROOT_CAUSE.md:197`, `GAP026_POLICY_PROPOSAL.md:41,58,76,91` | ~1 hour |
| Add cross-link | Point to `scripts/measure_candidate_acceptance.py` and `QualityGateManager` as actual executing consumers | 10 lines |

**Total**: ~200 lines across 11 files, **~4 engineering hours**.

### If No Decision Is Ever Made

**Repo stays safe in its current state.** Two real executing consumers already exist and work:
- `scripts/measure_candidate_acceptance.py` — 22 hardcoded gates, CLI flags, produces acceptance evidence
- `ultimate_pipeline/quality/quality_gate_manager.py` — 19 hardcoded gate methods, used by `MainPipeline.run()`

The YAML contract is purely decorative. No gate execution, waiver, or profile logic depends on it. The only degradation is **documentation drift**: 10 references across 9 files (8 in `docs/`, 2 in root GAP docs) continue to treat the YAML as normative, misleading future contributors. GAP-037 remains blocked because no consumer exists to apply a waiver through.

---

## GAP-037: Waiver Gate-Class Taxonomy Missing

**Decision needed**: Whether to add a gate-class taxonomy (the V5 branch's `recommended_non_waivable_categories` list) to prevent waivers on identity/integrity gates, and if so, whether to attach it to the YAML contract (GAP-036 Option A) or the actual executing consumers (GAP-036 Option B path).

### Option A: Add Taxonomy to YAML Contract (Requires GAP-036 Option A)

| File | Change | Effort |
|------|--------|--------|
| `ultimate_pipeline/contracts/stage_contracts.py` | Add `GateClass` enum, `NON_WAIVABLE_CLASSES`, modify `governed_waiver_allowed()` and `promote_aggregate_detailed()` | ~80 lines |
| `ultimate_pipeline/quality/quality_gate_manager.py` | Add `gate_class` attribute to each gate method (or registry dict), pass to `_finalize_gate()` | ~50 lines |
| `scripts/measure_candidate_acceptance.py` | Add `gate_class` mapping for each gate call, pass to `build_map_acceptance()` | ~60 lines |
| `ultimate_pipeline/quality/map_acceptance.py` | Accept `gate_class` per gate in `reports` dict, enforce in waiver logic | ~40 lines |
| `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` | Add `gate_class` to each gate in `required_gates` lists | ~30 lines |
| Tests | Add tests for non-waivable class refusal | ~50–60 lines |

**Total**: ~320 lines across 7 files, **~2 days** (on top of GAP-036 Option A's 11 days).

### Option B: Add Taxonomy Directly to Actual Executing Consumers (Works Regardless of GAP-036)

| File | Change | Effort |
|------|--------|--------|
| `ultimate_pipeline/contracts/stage_contracts.py` | Add `GateClass` enum, `NON_WAIVABLE_CLASSES`, modify `governed_waiver_allowed()` to check class | ~80 lines |
| `ultimate_pipeline/quality/quality_gate_manager.py` | Add `gate_class` registry dict (gate_name → GateClass), pass to `_finalize_gate()` | ~50 lines |
| `scripts/measure_candidate_acceptance.py` | Add `gate_class` mapping for each gate call, pass to `build_map_acceptance()` | ~60 lines |
| `ultimate_pipeline/quality/map_acceptance.py` | Accept `gate_class` per gate, enforce in `component_reachability` waiver path | ~40 lines |
| Tests | Verify `component_reachability` (QUALITY_DEVIATION) still waivable; add non-waivable refusal tests | ~60 lines |

**Total**: ~300 lines across 5 files, **~3 days** (standalone, no YAML dependency).

### Gate Classification Mapping (from GAP-037 proposal, verified against current code)

| Gate Class | Gates | Non-Waivable? |
|------------|-------|---------------|
| `IDENTITY_INTEGRITY` | `map_registry_identity`, `deterministic_provenance`, `artifact_fingerprint`, `map_acceptance` (SHA binding) | Yes |
| `STRUCTURAL_INTEGRITY` | `xodr_xml_integrity`, `carla_structural_compatibility`, `junction_integrity`, `lane_link_targets_exist`, `lane_section_successors`, `lane_connectivity`, `carla_opendrive_compat`, `carla_import_s`, `post_tiling_integrity` | Yes |
| `QUALITY_DEVIATION` | `lane_width_continuity`, `lane_geometry_continuity`, `elevation_continuity`, `elevation_smoothness`, `elevation_missing_and_cliffs`, `elevation_seams`, `physics_feasibility`, `lane_count_provenance`, `lane_count_changes`, `dem_full_coverage`, `origin_sanity`, `semantic_overlap`, `collision_mesh`, `randomness_entropy`, `component_reachability` | No (waivable with governed waiver) |
| `RUNTIME_DEPENDENT` | `carla_world_loads`, `carla_ego_spawns_on_valid_surface`, `carla_waypoint_graph_matches_visible_roads`, `carla_no_detached_road_slabs_live`, `visual_cooked_map_certificate_live_fields` | Yes (runtime_certified already `allows_waived: false`) |

### If No Decision Is Ever Made

**Repo stays safe in its current state.** The only governed waiver that exists today is `component_reachability` in `map_acceptance.py:1050–1067`, which is correctly a `QUALITY_DEVIATION` gate. No waivers exist for identity/integrity gates. The V5 audit's risk statement ("a waiver could in principle be attached to an identity or integrity gate") is **theoretical** — it requires an executing consumer that uses the waiver schema. Since GAP-036 has no consumer, the risk is latent.

**However**: If GAP-036 chooses Option A (build consumer) without this taxonomy, the risk becomes real immediately. The taxonomy must be designed for the *execution system*, not the reference document.

---

## GAP-038: Two Real Tested Modules Unwired (Fail-Closed Commandlet Execution, Package-Identity Binding)

**Decision needed**: Whether to wire the two new contract modules (`carla_0916_import_process_contract.py`, `carla_0916_large_map_contract.py`) into the real subprocess call sites for CARLA import/cook, or defer wiring indefinitely.

### Modules Added by `hardening/final-gap-closure-20260930` (Merged 2026-09-30)

1. **`carla_0916_import_process_contract.py`** (315 lines, 21 tests) — `run_mandatory_process()` and `run_import_sequence()`: fail-closed execution wrapper for every mandatory Unreal commandlet/import/cook child process. Enforces receipt + hash-bound output verification on both Windows and POSIX. Raises `ImportProcessError` on any mandatory failure so callers cannot proceed downstream.

2. **`carla_0916_large_map_contract.py`** (416 lines, 26 tests) — `PackageIdentity`, `resolve_package_identity()`, `resolve_material_config()`, `derive_decal_seed()`, `generate_deterministic_decals()`, `parse_tilesinfo()`/`format_tilesinfo()`: canonical package identity resolution, material config binding, deterministic decal generation, locale-independent TilesInfo float schema.

**Independent verification (2026-09-30)**: Repo-wide grep (excluding the modules and their own tests) returns **ZERO callers** for either module. The branch's own `MODULE_JUSTIFICATION.json` admits: "no canonical import/cook execution owner exists; scattered unchecked subprocess.run/call sites."

### Option A: Wire Into Real Call Sites

**Real call sites to modify (identified by grep for `subprocess.Popen`, `subprocess.run` with UE4Editor/ImportAssets/cook):**

| Call Site | Current Code | Required Change |
|-----------|--------------|-----------------|
| `tools/carla_import_supervision.py::run_supervised()` (line 296) | `subprocess.Popen(command, cwd=cwd, stdout=out_fh, stderr=err_fh)` + manual classification | Replace with `run_mandatory_process()` or `run_import_sequence()`; map classification to `ImportProcessResult.status` |
| `tools/stage_large_map_import_package.py` | Stages package but **does not invoke UE4** (line 13: "It does NOT invoke make import or any UE4/UE5 process") | Add invocation path using `run_import_sequence()` with steps for `ImportAssets` and `cook` commandlets |
| Any `scripts/*.py` launching UE4Editor-Cmd.exe -run=ImportAssets/cook | Various ad-hoc `subprocess.run`/`Popen` calls | Replace with contract calls |

**Effort estimate**: 
- Discovery: enumerate all UE4 commandlet launch points (~0.5 day)
- Modify `carla_import_supervision.py` to use `run_import_sequence()` for mandatory steps (~1 day)
- Add UE4 invocation to `stage_large_map_import_package.py` or a new driver script (~1 day)
- Wire `PackageIdentity`/`resolve_material_config()` into the import/cook pipeline (where material config is loaded) (~1 day)
- Wire `derive_decal_seed()`/`generate_deterministic_decals()` into decal generation path (~0.5 day)
- Wire `parse_tilesinfo()`/`format_tilesinfo()` into TilesInfo consumers (~0.5 day)
- End-to-end test with real CARLA import/cook (depends on GAP-017) (~1 day)

**Total**: **~5–6 engineering days** (plus CARLA runtime availability for validation).

### Option B: Defer/Document as Reference Implementations

| Action | Effort |
|--------|--------|
| Add module-level docstring disclaimer: "Reference implementation — not wired into any execution path. See GAP-038." | 5 lines × 2 files |
| Update `MODULE_JUSTIFICATION.json` to reflect current status honestly | 10 lines |
| Update any misleading commit messages / FINAL_VERDICT.md claims | ~1 hour |

**Total**: **~2 engineering hours**.

### If No Decision Is Ever Made

**Repo stays safe in its current state.** The modules are real, tested, and correct in isolation (21 + 26 tests pass). No regression was introduced — the underlying gaps they were meant to close (unchecked `subprocess.call()` return values on POSIX, unbound package identity, non-deterministic decals, ambiguous TilesInfo schema) **remain functionally open in the real pipeline** exactly as they were before the modules were added. The only degradation is **false confidence risk**: a reader trusting the branch's commit messages ("every mandatory import/cook child process now runs through a single fail-closed contract") or `FINAL_VERDICT.md`'s undifferentiated "PASS with tests" line would incorrectly believe these are closed.

---

## GAP-039: 5 Perception Fixes Never Implemented + 1 Dead Gate (NEW-291)

**Decision needed**: What priority/scheduling to assign to the 5 never-implemented perception fixes and the SHA-pin configuration for NEW-291.

### Items (Independent Verification 2026-10-01 via Blob-SHA Comparison)

| Item | Claimed Fix | Actual State | Target File |
|------|-------------|--------------|-------------|
| NEW-274 | Atomic capture_writer.py commit (temp-rename) | **Never implemented** — file byte-identical to pre-commit base | `ultimate_pipeline/perception/capture_writer.py` |
| NEW-275 | perception_api.py docs clarification | **Never implemented** — file byte-identical | `ultimate_pipeline/perception/perception_api.py` |
| NEW-276 | label_quality.py any/unlabeled/learnable split | **Never implemented** — file byte-identical | `ultimate_pipeline/perception/label_quality.py` |
| NEW-277 | train_launcher.py DATASET_ACCEPTANCE enforcement | **Never implemented** — file byte-identical | `ultimate_pipeline/perception/train_launcher.py` |
| NEW-288 | THESIS_STRICT degraded-sensor disable | **Already exists** (pre-dates branch) — `local_perception_runner.py:369–373` enforces `allow_degraded=False` when `THESIS_STRICT=True` | `ultimate_pipeline/carla_tools/local_perception_runner.py` |
| NEW-291 | SHA256 pin validation for manual XODR refs | **Implemented but dead** — `manual_refs.py:55–63` computes hash and compares to `manual_xodr_sha256_pin`, but `MANUAL_INGOLSTADT_REFS` has **no pin values set** for Grid0821 or Grid0828 | `ultimate_pipeline/experiments/thesis/manual_refs.py` |

### Option A: Implement All 5 Missing Fixes + Fix NEW-291

| Item | Scope | Effort |
|------|-------|--------|
| NEW-274 | Add atomic write via temp file + rename in `save_capture_frame()` | ~0.5 day |
| NEW-275 | Add docstring/comments clarifying dual call style in `perception_api.py` | ~0.5 day |
| NEW-276 | Add `any/unlabeled/learnable` fraction computation to `label_quality.py` (extend `label_stats()`) | ~1 day |
| NEW-277 | Add `DATASET_ACCEPTANCE` gate enforcement in `train_launcher.py` (fail if dataset quality below threshold) | ~1.5 days |
| NEW-288 | **Already done** — verify `THESIS_STRICT` path in `local_perception_runner.py` | 0 days |
| NEW-291 | Compute SHA256 of current approved manual XODR files, populate `manual_xodr_sha256_pin` in `MANUAL_INGOLSTADT_REFS` | ~1 hour |

**Total**: **~3.5–4.5 engineering days** (NEW-277 is the largest unknown; depends on what "DATASET_ACCEPTANCE enforcement" means precisely).

### Option B: Fix Only NEW-291 (Highest Impact / Lowest Effort)

| Action | Effort |
|--------|--------|
| Run `sha256_file()` on the two current manual XODR files (Grid0821.xodr, manual_ingolstadt_grid0828.xodr) | 5 minutes |
| Populate `manual_xodr_sha256_pin` in `MANUAL_INGOLSTADT_REFS` dict | 5 minutes |
| Test `resolve_manual_town()` rejects a corrupted file | ~0.5 day |

**Total**: **~0.5 engineering days**.

### Option C: Defer All as Technical Debt

| Action | Effort |
|--------|--------|
| Add comment in GAP register / docs acknowledging the 5 items were claimed but not implemented | ~0.5 hour |

**Total**: **~0.5 engineering hours**.

### If No Decision Is Ever Made

**Repo stays safe in its current state.** None of these 6 gaps cause active harm — no regression, nothing was broken. The only degradation is **technical debt and documentation-accuracy risk**: if the original "NEW-271..292 all fixed" framing is ever cited without this correction, a reader would incorrectly believe:
- Atomic capture-writer commits exist (NEW-274)
- Perception API docs are clarified (NEW-275)
- Label quality reports any/unlabeled/learnable fractions (NEW-276)
- Training enforces DATASET_ACCEPTANCE (NEW-277)
- SHA-pinned manual-reference validation is active (NEW-291)

None of these currently do anything. NEW-291 is the only one with implemented-but-inert code; the other 5 have zero trace in the codebase.

---

## GAP-026: Junction Lane-Link Pose Continuity Dead Signal on Promoted Map-of-Record

**Decision needed**: How to handle the validated but ungated `sanitize_junction_lane_links` signal on the currently-promoted map-of-record (SHA256 `370abbbb...c8c8`, 149,799,632 bytes). The checker found 2,992 of 23,529 laneLinks (12.7%) fail pose-continuity at its own tolerance (0.25 m / 12°), including 832 links with >3 m discontinuity (max 14 m). **AGENTS.md explicitly states: "GAP-026 cannot be 'fixed' by raising tolerance" — so that is not an option.** The decision must address: (1) whether the checker's tolerance/methodology needs review before concluding the map is broken (the 74% near-threshold cluster at median 0.125 m suggests possible systematic half-width bias), and (2) whether/how to wire this signal into a hard gate without immediately failing the currently-promoted `valid_for_experiments=true` map.

### Real Candidate Fixes (from GAP-026 entry, GAP026_ROOT_CAUSE.md, GAP026_POLICY_PROPOSAL.md)

| Option | Scope | Files | Effort Estimate (Grounded in Code) |
|--------|-------|-------|-----------------------------------|
| **Option A: Width Harmonization Only (eliminates 0.25–0.5 m tail)** | Fix connector lane-width policy to inherit width from incident incoming/outgoing roads instead of hardcoded 3.5 m fallback. 1,721 near-threshold failures (57.5% of all failures) are 86.5% width-mismatch (incoming 3.0 m vs connector 3.5 m). | `ultimate_pipeline/enrichment/lane_width_policy.py`<br>`ultimate_pipeline/pipeline_stages/stage_07_lanes.py`<br>`ultimate_pipeline/enrichment/lane_generator.py` (connector branch) | ~3 days:<br>- Extend `target_driving_width_m()` for connectors: derive from incident road's matched lane width (~150 lines)<br>- Build `road_id → lane_widths_by_lane_id` map at endpoint LaneSection after Stage 7 standardization (~80 lines)<br>- Write connector `<width a=...>` to matched lane width, preserve `b=c=d=0` (~60 lines)<br>- Re-run `LaneOffsetSmoother`/`CrossSectionRepair` (~40 lines)<br>- Governed regeneration + validation run (~1 day) |
| **Option B: Connector Lane-Count Synthesis + Geometry-Aware LaneLink Regen (eliminates ≥3.5 m tail)** | Fix connector generation to synthesize N lanes matching incident roads (not hardcoded 1 lane), then enable geometry-aware laneLink regeneration (Hungarian matching on lane-center poses) behind a flag. 832 >3 m failures are 85% lane-count mispairing (outer→inner, multiples of 3.5 m). | `ultimate_pipeline/topology/junction_connector_rebuild.py`<br>`ultimate_pipeline/enrichment/lane_generator.py`<br>`ultimate_pipeline/lanes/lanelink_builder.py`<br>`ultimate_pipeline/pipeline_stages/stage_08_integrity.py` | ~10–12 days:<br>- Phase B1: Modify `LaneGenerator._is_connector` to set driving lane count = min(incident incoming/outgoing right-side lanes); write N lanes with inherited widths (~2 days, ~300 lines)<br>- Phase B2: Replace `match_by_direction` with geometry-aware Hungarian matcher (lane-center poses from kernel, cost = Euclidean + λ·angular, same-sign driving-only, threshold 0.25/0.50 m) (~4 days, ~400 lines)<br>- Add `UP_ENABLE_GEOMETRY_AWARE_LANELINK` flag, wire into Stage 8 (~1 day)<br>- Governed regeneration in isolated worktree + full validation (RQ2 metrics, structural fingerprint, CARLA static gates, lane-link distribution) (~3–5 days, depends on GAP-017 for live gates) |
| **Option C: Wire Checker as Soft Gate First (per GAP026_POLICY_PROPOSAL.md rollout)** | Wire `sanitize_junction_lane_links` into `measure_candidate_acceptance.py` and `map_acceptance.py` to emit FAIL/WAIVED/PASS per proposed thresholds (hard >0.50 m, warning 0.25–0.50 m, population caps >2% >0.50 m or >0.5% >3 m) without blocking `valid_for_experiments`. Collect one full-map evidence run. | `scripts/measure_candidate_acceptance.py`<br>`ultimate_pipeline/quality/map_acceptance.py`<br>`ultimate_pipeline/quality/quality_gate_manager.py`<br>`ultimate_pipeline/contracts/stage_contracts.py` (waiver schema) | ~4 days:<br>- Add `junction_lanelink_pose_continuity` gate method to `QualityGateManager` (~100 lines)<br>- Wire into `measure_candidate_acceptance.py` CLI/profile selection (~80 lines)<br>- Implement population-cap logic in `map_acceptance.py:hard_fail_reasons` (~100 lines)<br>- Waiver schema integration for warning band (0.25–0.50 m) per `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:waiver_schema` (~120 lines)<br>- Test with current promoted map (expects FAIL on population caps, WAIVED on warning band) (~1 day) |
| **Option D: Full Hard Gate + Governed Regeneration (Options A+B+C combined)** | Execute all repairs (width harmonization + connector lane-count + geometry-aware laneLink regen), then promote soft gate to hard gate in `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:production_candidate.required_gates` with `fails_closed_on: [FAIL]`. | All files above + `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` | ~17–19 days (Options A+B+C sequential, plus promotion step). **Requires human sign-off on the regenerated map's receipt metrics vs. old pin** (roads/junctions/lanes counts, structural fingerprint, RQ2 ratios, lane-link distribution, final receipt). |

### If No Decision Is Ever Made

**Repo stays safe in its current state.** The checker (`sanitize_junction_lane_links`) is wired in `stage_08_integrity.py:560` and writes `junction_lanelink_sanity.json` on every real run — it is **measured but not gating**. The currently-promoted map-of-record remains `valid_for_experiments=true`. No regression is introduced.

**However, three degradations persist indefinitely:**

1. **Latent map-quality question**: The promoted map — used by RQ2 structural-gap metrics, RQ4 GNN training tiles, and all other real-data audits — has a computed, ignored signal showing 12.7% lane-link pose discontinuities, 3.5% >3 m (832 links), up to 14 m. A vehicle following these lane links in live CARLA (once GAP-017 unblocks RQ3/RQ5a) would visibly jump at severe-tail junctions.

2. **Checker-before-map risk uninvestigated**: The 74% near-threshold cluster (1,721 links at 0.25–0.5 m, median 0.125 m) is dominated by a documented width-tier mismatch (incoming 3.0 m vs connector 3.5 m fallback). This is a **map defect at the lane-width policy boundary**, not a checker artifact (oracle validated: width mismatch is the mechanism). But without a decision, the systematic half-width bias hypothesis is neither confirmed nor ruled out as a checker methodology issue.

3. **Governance precedent**: A real, geometrically-validated quality signal on the promoted map-of-record remains dead code. Future contributors have no pattern for "measured but not gating — needs human decision." The GAP register correctly characterizes this as `open -- real finding, needs a human policy decision before any fix is dispatched` (status since 2026-09-24).

---

## Summary Table

| Gap | Decision Type | Recommended Path (Evidence-Based) | Cost If Deferred |
|-----|---------------|-----------------------------------|------------------|
| GAP-026 | **Map Quality**: gate wiring + repair scope | **Option C first (soft gate, 4d)** to collect evidence; then **Option A (3d)** for width harmonization; **Option B (10–12d)** only if soft gate confirms severe tail is not checker artifact. Do not raise tolerance (AGENTS.md). | Latent map-quality question on promoted map; checker-before-map risk uninvestigated; governance precedent for dead signals |
| GAP-036 | **Architecture**: build vs deprecate | **Option B (deprecate)** — 4h vs 11d+3wk; two real consumers exist; YAML is decorative | Docs drift (misleading references); GAP-037 stays blocked |
| GAP-037 | **Design**: taxonomy location | **Option B (actual consumers)** — 3d standalone; works regardless of GAP-036; taxonomy belongs where waivers are applied | Latent risk if GAP-036 Option A chosen without taxonomy |
| GAP-038 | **Integration**: wire vs defer | **Option A (wire)** — 5–6d bounded task; modules are real and tested; underlying gaps remain open in pipeline | False confidence; real subprocess/identity gaps stay open |
| GAP-039 | **Scheduling**: priority | **Option B (NEW-291 only)** — 0.5d for real gate activation; other 5 are quality improvements, not safety | Technical debt; no active harm |

---

**Prepared**: 2026-10-07  
**Scope**: Synthesis only — no code changes, no gap register edits, no decisions made.  
**Sources**: `GAP026_ROOT_CAUSE.md`, `GAP026_POLICY_PROPOSAL.md`, `GAP026_METHOD_VALIDATION.json`, `MASTER_GAP_REGISTER.json` (GAP-026, GAP-038, GAP-039 entries), `GAP036_POLICY_PROPOSAL.md`, `GAP037_POLICY_PROPOSAL.md`, `AUDIT_REPORT.md` (2026-10-07), independent grep/blob-SHA verification of call sites and implementation status.