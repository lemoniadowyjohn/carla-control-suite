# C14 (HIGH) — RQ1: structural domain gap (auto ↔ manual) on the pinned pair

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803` · Interp: `./.venv/Scripts/python.exe` · UP_DISABLE_CARLA=1
Rules: TDD for any code change; **EXPLICIT-PATHSPEC commit**; result-touching → human review; **conservative claim boundaries**. Model: high.
Plan: Phase R2. Depends on C12 (pinned auto) + C13 (pinned manual). Offline, authoritative-capable.

## RQ1
*What are the structural differences (geometry, topology, connectivity, semantics, curvature, elevation, junction
complexity, object density) between the automatically generated map and the manually modeled Grid0828 map?*

## Machinery (reuse — do NOT reimplement)
- Aggregator: `ultimate_pipeline/domain_gap/structural_gap.py`, `manual_vs_auto_comparator.py`,
  `domain_gap_aggregator.py` (A3-characterized composite).
- Per-aspect: `geometry_gap.py`, `topology_gap.py`, `connectivity_gap.py`, `semantic_gap.py`, `curvature_gap.py`,
  `elevation_gap.py`, `junction_complexity_gap.py`, `object_density_gap.py`, `intersection_gap.py`,
  `road_classification_gap.py`.
- Alignment: `geo_alignment.py` / `deterministic_alignment.py` (auto tmerc(0,0)/local ↔ manual UTM-32N).
- Batch runner: `experiments/thesis/run_structural_domain_gap_batch.py` (`run_single`, `main`).
- Prior result: `thesis_results/structural_gap_v1/run_11` (BOUNDED — has fit-metric-provenance + coverage caveats).

## Steps
1. **Align the pinned pair.** Auto is Osm2Odr-local (post-rebase, `<offset>` in header); manual is UTM-32N. Use
   `geo_alignment.py`/`deterministic_alignment.py` to bring both to a common frame + report the bbox IoU after
   reprojection and the auto↔manual road-length coverage ratio (these already exist as `coverage_context`).
2. **Compute the per-aspect gaps** via `run_structural_domain_gap_batch.run_single` on (auto=C12-pinned,
   manual=C13-pinned). Produce the composite via `domain_gap_aggregator` (∈[0,1], 0=identical, disabled/missing
   aspects excluded — already A3-tested).
3. **Carry the claim boundaries explicitly** (these are contract requirements, not optional):
   - `full_network_metrics ≠ local_registration_quality` — full-network numbers are not local registration quality.
   - Coverage context (auto vs manual road length, bbox IoU) accompanies every number.
   - **Construction-artifact caveats:** the manual map’s elevation encoding and building density differ by
     *construction method*, not domain gap — the elevation_gap and object_density_gap must be reported WITH this
     caveat (an auto map with DEM elevation vs a hand-modeled map is not a pure "domain" difference).
4. **Refresh `run_11`** (or write `structural_gap_v1/run_<new>`): recompute on the *pinned, corrected* pair with
   clean provenance (both maps’ sha256, alignment report, per-aspect + composite, caveats). Resolve the
   `fit_metric_provenance.exact_source_revision_status` = conflicting/unverified flag from the old run_11.
5. Feed the result so `tools/audit_thesis_topic_contract.py` reports RQ1 as
   `authoritative_result_available` with `coverage_context_present=true` and the claim boundary present.

## Boundaries
- Deterministic/offline (no CARLA). Do not change the gap MATH (A3-characterized) — this is a *run + provenance*
  task; if a gap module has a bug, fix via TDD with a negative control, don’t silently adjust.
- Never report a bare composite without its coverage_context + construction-artifact caveats.

## Deliverables / verdict
- `thesis_results/structural_gap_v1/run_<new>/` (per-aspect + composite + alignment + caveats + both sha256).
- `reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP.md` (the RQ1 number, with boundaries).
- Tests if any module changed; push (explicit pathspec); suite green.
- **Verdict:** `RQ1_STRUCTURAL_GAP composite=<x> auto=<sha> manual=<sha> coverage_iou=<y> status=authoritative_with_boundaries` | PARTIAL | BLOCKED.
