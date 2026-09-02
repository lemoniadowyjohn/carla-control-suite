# WS1.4/WS1.5 — Fresh canonical regen, audit, and map-of-record promotion

2026-09-02. Part of the "Close and harden remaining gaps" plan (Workstream 1: map-quality
hardening). Supersedes the C30 baseline (2026-08-27,
`reports/post_audit_hardening/C30_VISUAL_GEOMETRY_AUDIT/`), which is now ~1 week and dozens of
bug-fix commits stale.

## What happened

1. Ran `python scripts/regen_map_of_record.py` (`PERCEPTION_RELEASE` profile) end to end,
   producing `campaigns/ingolstadt_cooked_perception_v1/regen/20260902T151513Z/`.
2. Live regen surfaced a real bug: `_find_final_xodr()` never matched C10 map-hygiene's
   `08h*.xodr` output filenames (only `08_final*`/`*DROP_BAD_LINKS*`), so the emitted candidate
   silently discarded island quarantine, degenerate-lane repair, and z-seam repair despite
   hygiene genuinely running. Fixed in `scripts/regen_map_of_record.py::_find_final_xodr()`
   (commit `1121e7c1`). This means **every governed regen since stage_08_hygiene.py was wired in
   on 2026-08-19 shipped without hygiene corrections**, including the pin superseded by this one.
3. Re-derived a hygiene-corrected candidate from the same run and found a second real bug:
   `map_hygiene.py::quarantine_island_roads()` deleted quarantined `<road>` elements but left
   `<junction><connection>` entries referencing them dangling — `JunctionIntegrityGate` flagged 28
   issues (14 `missing_incoming_road` + 14 `missing_connecting_road`), all pointing at the 30 just-
   quarantined road ids. Undetected because `_measure_acceptance()`'s gate set never runs
   `JunctionIntegrityGate`. Fixed in `ultimate_pipeline/quality/map_hygiene.py` (commit
   `bbf32d3d`): drops dangling connections, removes junctions left with zero connections.
4. Re-ran the full C10 hygiene chain (quarantine -> degenerate-lane repair -> z-seam repair) with
   both fixes applied, rebased to the local frame, measured acceptance, and emitted
   `ingolstadt_perception_map_of_record_20260902_junctionfix.xodr` as the new candidate.
   `valid_for_experiments=True`, zero hard-fail reasons.
5. Promoted this candidate to `auto_map_of_record` in
   `ultimate_pipeline/carla_tools/map_registry.py::PINNED_MAP_REGISTRY`, following the same
   pattern as the 2026-08-26 C29 promotion. The prior C29 pin is kept as a separate,
   non-`auto`-aliased registry entry (`auto_map_of_record_c29_superseded`) purely so
   `validate_thesis_claim_provenance.py`'s single-hop `supersedes_sha256` lookup can still resolve
   historical claims that cite either the C29 sha or the original pre-C29 sha two hops back.

## Before / after (C30 baseline vs. this candidate)

| Metric | C30 baseline (2026-08-27) | This candidate (2026-09-02) |
|---|---|---|
| Source file | `..._20260819_160350_C29_BUILDING_PATCH.xodr` | `..._20260902_junctionfix.xodr` |
| Road count | 32,297 | 32,267 (30 quarantined as islands) |
| Road-level connected components (`structure_scanner.py`) | 10 | **1** |
| Road-level islands (`ISLAND_MIN_SIZE=20`) | 9 components / 30 roads | **0** |
| `JunctionIntegrityGate` issues | not run by C30's tooling | **0** (was 28 on the first, pre-junction-fix hygiene attempt this session) |
| `check_planview_internal_seams`: position seams | 0 | 0 |
| `check_planview_internal_seams`: heading-only kinks | 82 | 82 (unchanged — deferred, see C31/C33) |
| `check_geometric_continuity` (road-link boundaries) | not directly comparable (C30 used a bespoke ad-hoc script; `link_gap_issue_count=18720` on a different, more granular metric) | `ok=True` |
| `check_elevation_continuity` | not directly comparable (C30's `elevation_issue_count=77503` is a different, per-sample metric) | `ok=True`, 0 boundary issues |
| Lane-level component reachability (`map_acceptance.py`) | not measured by C30 | 35 components, largest_fraction=0.9967, 27 isolated lane components (soft warning, below the 0.95 hard-fail threshold) |
| Buildings enriched | populated (per C30) | 5,682 |
| Traffic/functional signals enriched | populated (per C30) | 21,163 |
| `map_acceptance.json`: `valid_for_experiments` | not measured by C30 (predates the hardened gate) | **True**, 0 hard-fail reasons |

Caveat: several C30 metrics (elevation_issue_count, junction_issue_count, link_gap_issue_count)
came from a bespoke, uncommitted audit script operating at a different granularity than the
committed gate checkers (`check_elevation_continuity`, `JunctionIntegrityGate`,
`check_geometric_continuity`) used here — they are not apples-to-apples counts, only the
island/component and heading-kink numbers are directly comparable across both audits.

## WS1.5 — perception-readiness confirmation

`_measure_acceptance()`'s `require_enrichment=True` check passed on this candidate specifically
(not the stale comparison doc): `buildings_count=5682`, `functional_signals_count=21163`,
`traffic_light_object_count=21163`, `dem_coverage_ratio=1.0`. `require_component_reachability=True`
(WS1.1's hardening) also passed: `largest_component_fraction=0.996734`, above the hard-fail
threshold, 27 isolated lane components logged as a soft warning only.

## Known open items, unchanged by this promotion

- **82 heading-only planView kinks**: root cause confirmed (C31/C33), a fix exists but is not
  safe to adopt yet (`ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING` + companion recompute flag still
  leaves 410 residual position seams on this same map). Deferred per explicit user decision.
- **27 isolated lane-level components**: distinct connectivity model from the road-level graph
  (`map_acceptance.py::component_reachability_summary` is lane-section-level via junction
  `<connection>` elements, not road-level) — soft warning, not a hard fail, not investigated
  further this pass.

## Verification

- New tests: `tests/unit/test_regen_find_final_xodr_hygiene.py` (4 tests, RED-verified against
  the pre-fix glob), `tests/unit/test_map_hygiene.py` (+3 tests for the junction-cleanup fix,
  RED-verified against the pre-fix code via `git stash`).
- Both fixes independently re-verified against the real regen artifact (not just synthetic unit
  tests): re-ran `quarantine_island_roads()` and the full 8H chain against
  `20260902T151513Z`'s actual pre-hygiene output, confirmed `JunctionIntegrityGate` issue count
  28 -> 0.
- Full suite: 5580 passed, 1 pre-existing known flake
  (`test_find_broken_roads_json_mode_emits_parseable_report`), 79 skipped (CARLA-gated).
- Registry promotion re-verified: `test_map_registry_pinning.py`,
  `test_map_registry_verify_pinned_map.py`, `test_validate_thesis_claim_provenance.py`,
  `test_planview_internal_seams_heading_only.py` all green against the new pin and the
  chain-link entry.
