# GAP-036 Policy Proposal: PRODUCTION_MAP_QUALITY_CONTRACT.yaml — Normative or Decorative?

**Status**: Awaiting repo owner decision  
**Date**: 2026-09-29  
**Related**: GAP-037 (waiver gate-class taxonomy), GAP-026 (lane-link pose continuity), GAP-008 (geometry kernel consolidation)  
**Depends on**: Nothing (this is the root decision)  
**Blocks**: GAP-037 (no executing consumer exists to apply a waiver through)

---

## Executive Summary

`PRODUCTION_MAP_QUALITY_CONTRACT.yaml` (repo root, 172 lines, schema `PRODUCTION_MAP_QUALITY_CONTRACT/v1`) declares:
- A **status vocabulary** (PASS, FAIL, INCOMPLETE, NOT_RUN, BLOCKED_EXTERNAL, WAIVED)
- A **waiver schema** (7 required fields: identifier, gate_id, exact_issue, owner, evidence, rationale, expiration_or_review_trigger)
- **Three acceptance profiles** with explicit `required_gates` lists, `allows_waived`, `allows_incomplete`, `fails_closed_on` policies
- A `visual_and_cooked_map_certificate` sub-contract with offline/live fields

**The problem**: **Zero executing consumer** in the Python codebase reads this file. It is purely decorative — a well-specified contract that no code enforces.

---

## Evidence: No Executing Consumer Exists

### 1. `scripts/measure_candidate_acceptance.py` (the primary standalone acceptance runner)
- Runs 22 quality gates (lines 68–193) with hardcoded calls
- Has its **own** CLI flags: `--require-enrichment`, `--require-component-reachability`
- Calls `build_map_acceptance()` with those flags (lines 247–254)
- **Never reads** `PRODUCTION_MAP_QUALITY_CONTRACT.yaml`
- **Never selects** a profile (`research_release` / `production_candidate` / `runtime_certified`)

### 2. `ultimate_pipeline/quality/quality_gate_manager.py` (QualityGateManager)
- Central registry used by `MainPipeline.run()` (line 909)
- Has **hardcoded** gate methods: `gate_xml_integrity`, `gate_elevation_smoothness`, `gate_physics_feasibility`, `gate_randomness_entropy`, `gate_semantic_overlap`, `gate_collision_mesh`, `gate_junction_integrity`, `gate_carla_opendrive_compat`, `gate_xodr_strict_carla`, `gate_lane_width_continuity`, `gate_lane_geometry_continuity`, `gate_elevation_missing_and_cliffs`, `gate_lane_section_successors`, `gate_lane_connectivity`, `gate_length_invariant`, `gate_origin_sanity`, `gate_post_tiling_integrity`, `gate_carla_import_s`, `gate_dem_coverage`, `gate_component_reachability`
- Uses `normalize_gate_result()` from `stage_contracts.py` for verdict normalization
- **Never reads** the YAML contract's profiles or gate lists

### 3. `ultimate_pipeline/roadrunner/gate_matrix.py` (RoadRunner gate matrix)
- **Separate** profile system: `structural_release`, `visual_build`, `scenario_augmentation`, `governed_map_release`, `debug`
- **Different** gate IDs: `source_integrity`, `semantic_diff`, `mesh_xodr_alignment`, `artifact_hashes`, `visual_mesh_quality`, `artifact_transaction`, `capability_probe`, `map_identity`
- **No overlap** with the YAML contract's gate names (e.g., YAML has `xodr_xml_integrity`, `carla_structural_compatibility`, `lane_link_targets_exist`, etc.)

### 4. `tools/current_map_static_release_matrix.py`
- Reports on **historical evidence artifacts** (pinned to specific report directories)
- Uses its own status vocabulary: `PASS`, `NOT_RUN`, `STALE_OR_UNBOUND`
- **Never reads** the YAML contract

### 5. `ultimate_pipeline/quality/map_acceptance.py::build_map_acceptance()`
- Aggregates gate reports into `hard_fail_reasons` / `soft_warnings` / `metrics`
- Has **hardcoded** logic for which gates are hard-fail vs soft-warning
- Accepts `require_enrichment` / `require_component_reachability` booleans from caller
- **Never reads** the YAML contract's `fails_closed_on` or `allows_waived` policies

---

## Evidence: Real References Treating It As Normative

The following files reference `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` **as if it were the authoritative, executing contract**:

| File | Line(s) | Context |
|------|---------|---------|
| `docs/architecture/TARGET_PIPELINE_STAGE_GRAPH.md` | 89 | "PRODUCTION_MAP_QUALITY_CONTRACT.yaml" listed as quality gate authority |
| `docs/index.md` | 32, 65 | "the unified acceptance-profile contract" |
| `docs/archive/root_reports_pre_20260912/PRODUCTION_MAP_TASK_GRAPH.json` | 46, 356, 365, 373 | Tasks explicitly say "wire PRODUCTION_MAP_QUALITY_CONTRACT.yaml's production_candidate profile into scripts/measure_candidate_acceptance.py as a real, selectable acceptance profile" |
| `docs/archive/root_reports_pre_20260912/MAP_QUALITY_GAP_REGISTER.json` | 155 | "VISUAL_AND_COOKED_MAP_CERTIFICATE (see PRODUCTION_MAP_QUALITY_CONTRACT.yaml) cannot currently be issued" |
| `docs/archive/root_reports_pre_20260912/DOCS_INFORMATION_ARCHITECTURE.md` | 18, 49 | "PRODUCTION_MAP_QUALITY_CONTRACT.yaml (repo root, per this audit's explicit required-output list) now serves this role" |
| `docs/archive/root_reports_pre_20260912/CLAUDE_PRODUCTION_MAP_AUDIT.md` | 150, 250 | "PRODUCTION_MAP_QUALITY_CONTRACT.yaml unifies the existing, extensive quality-gate system" / "into fail-closed profiles per PRODUCTION_MAP_QUALITY_CONTRACT.yaml" |
| `GAP026_ROOT_CAUSE.md` | 197 | References `runtime_certified` profile as if it were enforceable |
| `GAP026_POLICY_PROPOSAL.md` | 41, 58, 76, 91 | Proposes waiver emission per the YAML's `waiver_schema`, gate promotion to `production_candidate.required_gates` |
| `MASTER_GAP_REGISTER.json` | 94 | "Not wired into scripts/measure_candidate_acceptance.py or PRODUCTION_MAP_QUALITY_CONTRACT.yaml — deliberately out of scope" |

**Total: 10 distinct references across 9 files** (8 in `docs/`, 2 in root GAP docs) treating the YAML as normative.

---

## Option A: Build a Real Executing Consumer

### What It Would Need to Hook Into

| Integration Point | What Needs to Change | Effort |
|-------------------|---------------------|--------|
| **YAML loader** | Add `ultimate_pipeline/contracts/quality_contract.py` to parse/validate YAML at startup | ~200 lines, 1 day |
| **Profile selection** | CLI flag `--acceptance-profile {research_release,production_candidate,runtime_certified}` on `measure_candidate_acceptance.py` and pipeline entrypoint | ~100 lines, 0.5 day |
| **Gate name mapping** | Map YAML gate names (`xodr_xml_integrity`, `carla_structural_compatibility`, etc.) to actual gate implementations in `QualityGateManager` / `measure_candidate_acceptance.py` | ~300 lines, 2 days |
| **Waiver integration** | Wire `waiver_schema` → `governed_waiver_allowed()` + `promote_aggregate()`; store waiver records alongside gate evidence | ~200 lines, 1.5 days |
| **Profile policy enforcement** | Implement `allows_waived`, `allows_incomplete`, `fails_closed_on` per profile in the aggregation logic | ~150 lines, 1 day |
| **Visual certificate** | Wire `visual_and_cooked_map_certificate` offline/live fields into `QualityGateManager` and CARLA runtime gates | ~400 lines, 3 days (depends on GAP-017 CARLA runtime) |
| **Tests** | Contract conformance tests: profile selection, gate mapping, waiver application, fail-closed behavior | ~300 lines, 2 days |

**Total estimate**: ~1,650 lines, **~11 engineering days** (single engineer, no parallelization).

### Critical Dependency: The Gate Matrix Subsystem Is Also Disconnected

The repo's memory (GAP-011, GAP-008 audit) already flagged that the **RoadRunner `gate_matrix` subsystem** (in `ultimate_pipeline/roadrunner/gate_matrix.py`) is a **second, parallel gate system** with:
- Different profiles (`structural_release`, `visual_build`, `governed_map_release`, `debug`, `scenario_augmentation`)
- Different gate IDs (`source_integrity`, `semantic_diff`, `mesh_xodr_alignment`, `artifact_hashes`, `artifact_transaction`, `capability_probe`, `map_identity`)
- **No shared vocabulary** with the YAML contract

**Building another consumer for the YAML contract without reconciling the gate_matrix subsystem repeats the exact mistake**: creating a third decorative layer. Any Option A work **must** either:
- (a) Subsume `gate_matrix` into the YAML contract (migrate its profiles/gates), or
- (b) Explicitly partition: YAML = map-quality gates; gate_matrix = RoadRunner artifact gates — and document the boundary.

---

## Option B: Formally Deprecate/Relabel as Non-Normative Documentation

### Required Actions

| Action | Files to Change | Effort |
|--------|-----------------|--------|
| **Rename file** | `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` → `PRODUCTION_MAP_QUALITY_CONTRACT_REFERENCE.yaml` (or `.md`) | 1 commit |
| **Add header disclaimer** | New file: `# NON-NORMATIVE REFERENCE DOCUMENT — No executing consumer exists. See GAP-036.` | 5 lines |
| **Update 9 referencing files** (see table above) | Replace normative language ("the contract requires", "wire the contract") with reference language ("the reference document describes", "see REFERENCE for gate definitions") | ~2 hours |
| **Update GAP-026 docs** | `GAP026_ROOT_CAUSE.md:197`, `GAP026_POLICY_PROPOSAL.md:41,58,76,91` — remove normative references to YAML profiles | ~1 hour |
| **Add cross-link** | In new reference file, point to `scripts/measure_candidate_acceptance.py` and `QualityGateManager` as the **actual** executing consumers | 10 lines |

**Total estimate**: ~200 lines changed across 11 files, **~4 engineering hours**.

---

## Recommendation: Option B (Deprecate/Relabel)

### Reasoning

1. **No consumer exists after 3+ months** — The YAML was written in the 2026-09-06 audit window (per its header). Three audit cycles later (2026-09-18, 2026-09-23, 2026-09-29), no consumer has been built. The "wire the contract" task in `PRODUCTION_MAP_TASK_GRAPH.json` (line 365) has been open since 2026-09-12 and never acted on.

2. **Two existing consumers already exist and work** — `measure_candidate_acceptance.py` (standalone) and `QualityGateManager` (pipeline-integrated) both run gates and produce acceptance evidence. They have different gate sets and different CLI flags, but they **execute**. The YAML adds a third, unimplemented layer.

3. **Gate Matrix subsystem conflict** — The `gate_matrix` subsystem (RoadRunner) is a **second complete gate system** with its own profiles and gate IDs. Reconciling all three (YAML + measure_candidate + gate_matrix) is a **major architectural project** (estimated 3–4 weeks), not a "build a consumer" task. Option A as scoped above ignores this conflict.

4. **Waiver system (GAP-037) depends on a consumer** — The waiver gate-class taxonomy proposed in GAP-037 **cannot be applied** until a consumer exists that actually uses waivers. Since no consumer exists, GAP-037 is blocked on GAP-036 regardless.

5. **Cost of honesty is low** — Renaming the file and updating 9 references takes ~4 hours. Cost of building Option A properly (including gate_matrix reconciliation) is ~4 weeks. The repo owner can always commission Option A later with a clear scope.

### What This Does NOT Mean

- **Quality gates are not being run** — They are, via `measure_candidate_acceptance.py` and `QualityGateManager`. The gates themselves are real, tested, and produce evidence.
- **The gate definitions are wrong** — The YAML's gate list is a reasonable superset of what the existing consumers run. The problem is the **profile/policy layer** (waivers, fail-closed rules, profile selection) has no execution path.
- **The waiver schema is bad** — The waiver schema (7 required fields) is well-designed. It just has no consumer.

---

## Decision Required

**Repo owner: approve Option A or Option B.**

- **If Option A**: I will write a concrete implementation plan (separate doc) that includes gate_matrix reconciliation, with milestones and a dedicated branch.
- **If Option B**: I will execute the rename + reference updates in a single commit on `docs/gap036-037-policy-proposals-20260929`.

**My recommendation: Option B.** The YAML is a well-written specification that got ahead of implementation reality. Making it honest reference documentation unblocks GAP-037 (which can then design a waiver taxonomy for the *actual* executing consumers) and stops the docs from misleading future contributors.