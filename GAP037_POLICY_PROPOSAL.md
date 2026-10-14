# GAP-037 Policy Proposal: Waiver Gate-Class Taxonomy

**Status**: Awaiting repo owner decision  
**Date**: 2026-09-29  
**Related**: GAP-036 (no executing consumer — this proposal only matters once GAP-036 is closed)  
**Depends on**: GAP-036 (no consumer exists to apply a waiver through)  
**Blocks**: Nothing directly, but waiver system cannot be structurally sound without this

---

## Executive Summary

The waiver model (defined in `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:waiver_schema` and implemented in `ultimate_pipeline/contracts/stage_contracts.py`) has **no gate-class taxonomy**. It treats all gates identically: a governed waiver can convert any `FAIL` to `WAIVED` if the gate is on the profile's `mandatory_children` allow-list.

**The risk**: A waiver could be attached to an **identity/integrity gate** (wrong artifact identity, hash mismatch, manifest tampering, corrupt artifact, schema corruption) converting a genuine integrity defect into a passing release. The V5 audit (`WAIVER_SEMANTICS_AUDIT.json`) confirmed this exposure.

---

## Evidence: V5 Waiver Semantics Audit

The V5 branch's audit (`reports/v5_incremental_closure/20260929T160422Z/WAIVER_SEMANTICS_AUDIT.json`) found:

```json
"recommended_non_waivable_categories": [
  "wrong artifact identity",
  "hash mismatch",
  "corrupt artifact",
  "missing required artifact",
  "wrong repository SHA",
  "wrong cooked package",
  "wrong runtime map",
  "manifest tampering",
  "schema corruption",
  "invalid cryptographic digest"
]
```

**Risk statement from the audit**:
> "Because production_candidate sets allows_waived: true and the contract has no classifier, a waiver could in principle be attached to an identity or integrity gate such as map_registry_identity or deterministic_provenance, converting a genuine integrity defect into a passing release."

**Mitigating facts** (from same audit):
- V5 introduced explicit fail-closed identity gates that **do not consult the contract at all**: `finalize_run_pack` (D16), strict provenance (D17), candidate identity pre-runtime gate (E24) all fail closed independently.
- `runtime_certified` profile sets `allows_waived: false`.

**Residual exposure**: "Gates that would be evaluated purely through the contract (none of which currently has an executing consumer) remain unclassified."

---

## Current Waiver Call Sites (Verified by Grep)

### 1. `ultimate_pipeline/quality/map_acceptance.py` — Component Reachability Waiver

**Lines 1050–1067** (in `build_map_acceptance()`):
```python
waiver = component_reachability_waiver
waivable = isinstance(waiver, str) and bool(waiver.strip())
if waivable and governed_waiver_allowed(
    {"component_reachability": waiver}, "component_reachability"
):
    metrics["component_reachability_waiver_applied"] = True
    metrics["component_reachability_spec_status"] = QualityStatus.WAIVED.value
    soft_warnings.append({
        "gate": "component_reachability",
        "reason": f"WAIVED by governed waiver: LITERAL_SPEC largest_component_fraction={gate_fraction} < 0.95 ... justification='{waiver}'"
    })
```

- **Gate ID**: `"component_reachability"`
- **Gate class**: **Quality deviation** (topology fragmentation ≤5% threshold) — *waivable*
- **Waiver source**: CLI flag `--require-component-reachability` + waiver string passed by caller
- **Current behavior**: Converts hard `FAIL` → `WAIVED` (soft warning), never `PASS`

### 2. `ultimate_pipeline/contracts/stage_contracts.py` — Core Waiver Logic

**`governed_waiver_allowed()` (lines 190–202)**:
```python
def governed_waiver_allowed(waivers: Optional[Dict[str, str]], child: str) -> bool:
    if not waivers:
        return False
    justification = waivers.get(child)
    return isinstance(justification, str) and bool(justification.strip())
```
- **No gate-class check** — any child name in `mandatory_children` with a non-empty justification string is waivable.

**`promote_aggregate_detailed()` (lines 228–377)**:
- Per-child conversion: `FAIL` → `WAIVED` if `waivable_fail=True` AND child in `mandatory_children` AND `governed_waiver_allowed()`
- **Lines 318–326**: The only gate-class discriminator is membership in `mandatory_children` (an allow-list, not a taxonomy)

**`promote_aggregate()` (lines 380–415)**:
- Convenience wrapper returning only aggregate `QualityStatus`
- Same logic, no gate-class awareness

### 3. Test Files (Verify Current Behavior)

- `tests/unit/test_stage_contracts_aggregate.py`: 20+ tests covering waiver precedence, single-use, positional/label mismatch, non-FAIL non-waivable
- `tests/unit/test_topology_certification.py::test_acceptance_gate_waiver_downgrades_to_waived`: Verifies component_reachability waiver path

---

## Missing: Gate-Class Taxonomy

No `gate_class` field exists on:
- Gate definitions in `QualityGateManager` (hardcoded method names)
- Gate entries in `measure_candidate_acceptance.py` (hardcoded calls)
- `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` gate lists (just string names)
- `stage_contracts.py` `mandatory_children` (just string names)
- `gate_matrix` profiles (different gate IDs entirely)

---

## Proposed Mechanism: Required `gate_class` Field

### Design

Add a **required `gate_class` field** to every gate definition in the executing consumer (wherever the gate registry lives). The waiver application logic then refuses any waiver for gates in the **non-waivable set**.

```python
# In stage_contracts.py or a new quality_contract.py
class GateClass(StrEnum):
    IDENTITY_INTEGRITY = "identity_integrity"      # Non-waivable
    STRUCTURAL_INTEGRITY = "structural_integrity"  # Non-waivable
    QUALITY_DEVIATION = "quality_deviation"        # Waivable (with governed waiver)
    HEURISTIC_ADVISORY = "heuristic_advisory"      # Always soft, never hard-fail
    RUNTIME_DEPENDENT = "runtime_dependent"        # Non-waivable (BLOCKED_EXTERNAL only)

NON_WAIVABLE_CLASSES = frozenset({
    GateClass.IDENTITY_INTEGRITY,
    GateClass.STRUCTURAL_INTEGRITY,
    GateClass.RUNTIME_DEPENDENT,
})
```

### Waiver Application Guard

In `governed_waiver_allowed()` or `promote_aggregate_detailed()`:
```python
def governed_waiver_allowed(
    waivers: Optional[Dict[str, str]],
    child: str,
    gate_class: str,  # NEW: required
) -> bool:
    if gate_class in NON_WAIVABLE_CLASSES:
        return False  # Hard refusal, regardless of justification
    # ... existing logic
```

### Gate Classification (Mapping Current Gates)

| Current Gate (QualityGateManager / measure_candidate) | Proposed Class | Rationale |
|------------------------------------------------------|----------------|-----------|
| `map_registry_identity`, `deterministic_provenance`, `artifact_fingerprint`, `map_acceptance` (SHA binding) | `IDENTITY_INTEGRITY` | Wrong artifact = wrong map; never waivable |
| `xodr_xml_integrity`, `carla_structural_compatibility`, `junction_integrity`, `lane_link_targets_exist`, `lane_section_successors`, `lane_connectivity`, `carla_opendrive_compat`, `carla_import_s`, `post_tiling_integrity` | `STRUCTURAL_INTEGRITY` | Structural defects CARLA can crash on; never waivable |
| `lane_width_continuity`, `lane_geometry_continuity`, `elevation_continuity`, `elevation_smoothness`, `elevation_missing_and_cliffs`, `elevation_seams`, `physics_feasibility`, `lane_count_provenance`, `lane_count_changes` (unexplained), `dem_full_coverage`, `origin_sanity`, `semantic_overlap`, `collision_mesh`, `randomness_entropy` | `QUALITY_DEVIATION` | Measurable deviations; waivable with governed waiver |
| `component_reachability` | `QUALITY_DEVIATION` | Already has waiver path; topology fragmentation is a quality metric |
| `connector_pose_validation`, `connector_boundary_offset`, `lane_link_direction_validity`, `elevation_structure_separation`, `osm_correspondence_confidence`, `crosswalk_signal_sign_geometric_validity` | `QUALITY_DEVIATION` | NEW gates per YAML; quality deviations |
| `carla_world_loads`, `carla_ego_spawns_on_valid_surface`, `carla_waypoint_graph_matches_visible_roads`, `carla_no_detached_road_slabs_live`, `visual_cooked_map_certificate_live_fields` | `RUNTIME_DEPENDENT` | Require live CARLA; `runtime_certified` already `allows_waived: false` |
| `visual_cooked_map_certificate` (offline fields) | `QUALITY_DEVIATION` | Offline visual checks; waivable |

---

## Backward Compatibility: Existing Waivers

**Current state**: Only one governed waiver exists in practice — `component_reachability` waiver in `map_acceptance.py` (lines 1050–1067). It is a `QUALITY_DEVIATION` gate.

**Policy for pre-existing waivers**:
1. **No migration needed for component_reachability** — it maps to `QUALITY_DEVIATION`, remains waivable.
2. **No other governed waivers exist** in the codebase (grep confirms: only `component_reachability` waiver key used in waivers dict).
3. **Future waivers** must declare `gate_class` at registration time; the waiver record schema (`PRODUCTION_MAP_QUALITY_CONTRACT.yaml:waiver_schema`) should be extended with optional `gate_class` field for auditability.

---

## Files That Would Need to Change (If Option A from GAP-036 Proceeds)

| File | Change | Lines |
|------|--------|-------|
| `ultimate_pipeline/contracts/stage_contracts.py` | Add `GateClass` enum, `NON_WAIVABLE_CLASSES`, modify `governed_waiver_allowed()` and `promote_aggregate_detailed()` to accept/require `gate_class` | ~80 lines |
| `ultimate_pipeline/quality/quality_gate_manager.py` | Add `gate_class` attribute to each `gate_*` method (or a registry dict), pass to `_finalize_gate()` | ~50 lines |
| `scripts/measure_candidate_acceptance.py` | Add `gate_class` mapping for each gate call, pass to `build_map_acceptance()` | ~60 lines |
| `ultimate_pipeline/quality/map_acceptance.py` | Accept `gate_class` per gate in `reports` dict, enforce in waiver logic | ~40 lines |
| `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` | Add `gate_class` to each gate in `required_gates` lists (if Option A from GAP-036) | ~30 lines |
| `tests/unit/test_stage_contracts_aggregate.py` | Add tests for non-waivable class refusal | ~50 lines |
| `tests/unit/test_topology_certification.py` | Verify component_reachability still waivable (QUALITY_DEVIATION) | ~10 lines |

**Total**: ~320 lines across 7 files.

---

## Dependency on GAP-036: Critical

> **GAP-037 only matters once GAP-036 is closed (no executing consumer exists to apply a waiver through).**

The waiver gate-class taxonomy **cannot be enforced** until there is an executing consumer that:
1. Reads the profile configuration (from YAML or code)
2. Runs gates and collects their `gate_class`
3. Applies waivers through `governed_waiver_allowed()` / `promote_aggregate()`

Currently:
- `QualityGateManager` runs gates but **has no profile concept** and **no waiver application** (it just fails/passes)
- `measure_candidate_acceptance.py` runs gates but **has no profile selection** and **only one hardcoded waiver** (component_reachability)
- `gate_matrix` has profiles but **different gate IDs** and **no waiver model**

**Therefore**: This proposal is **conditional on GAP-036 Option A (build real consumer)**. If GAP-036 chooses Option B (deprecate YAML), the waiver taxonomy should be designed for the **actual executing consumers** (`QualityGateManager` + `measure_candidate_acceptance.py`) directly, not for the YAML contract.

---

## Recommendation: Defer Until GAP-036 Decision, Then Implement for Actual Consumers

### Reasoning

1. **No consumer = no enforcement point** — A taxonomy in the YAML file (which has no consumer) is decorative. The taxonomy must live where waivers are actually applied.

2. **Two actual consumers exist** — `QualityGateManager` (pipeline) and `measure_candidate_acceptance.py` (standalone). They should share a common `GateClass` enum and waiver guard.

3. **Gate Matrix is a third system** — If GAP-036 Option A includes gate_matrix reconciliation, the taxonomy must cover its gate IDs too. If not, gate_matrix stays separate.

4. **Current exposure is theoretical** — The V5 audit noted "none of which currently has an executing consumer" for the contract-only gates. The only real waiver today (`component_reachability`) is correctly classified as a quality deviation.

5. **Scope creep risk** — Designing a taxonomy for a non-existent consumer invites over-engineering. Design it for the two real consumers first.

### Concrete Next Steps (After GAP-036 Decision)

**If GAP-036 → Option A (build consumer for YAML)**:
- Implement `GateClass` enum in `stage_contracts.py`
- Add `gate_class` to YAML gate lists
- Wire into new consumer's waiver application
- Estimated: +2 days on top of Option A's 11 days

**If GAP-036 → Option B (deprecate YAML)**:
- Implement `GateClass` enum in `stage_contracts.py` (shared)
- Add `gate_class` registry to `QualityGateManager` (dict: gate_name → GateClass)
- Add `gate_class` mapping to `measure_candidate_acceptance.py`
- Modify `governed_waiver_allowed()` to check `NON_WAIVABLE_CLASSES`
- Update `component_reachability` waiver path to pass `GateClass.QUALITY_DEVIATION`
- Add tests for non-waivable refusal
- Estimated: **~3 days** (standalone, no YAML dependency)

**My recommendation: Wait for GAP-036 decision, then implement for the actual consumers (Option B path for GAP-037 regardless of GAP-036 outcome).** The waiver taxonomy is a property of the *execution system*, not the reference document.

---

## Decision Required

**Repo owner: acknowledge the dependency and approve the conditional approach.**

- **If GAP-036 → Option A**: This taxonomy becomes part of that consumer's implementation.
- **If GAP-036 → Option B**: This taxonomy gets implemented directly in `QualityGateManager` + `measure_candidate_acceptance.py` (3-day task, separate branch).

**Either way**: No waiver gate-class taxonomy can be enforced until an executing consumer exists. GAP-037 is **blocked on GAP-036** by design.