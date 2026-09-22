# MTIME AUTHORITY AUDIT — 2026-09-18

**Commit SHA:** `3151c47293bdaf174abea2b17334b81005fa5e83`
**Scope:** All `.py` files under the workspace root
**Pattern:** `stat().st_mtime`, `getmtime`, reverse-mtime sorting, glob+newest selection

---

## Summary

| Risk | Count |
|------|-------|
| HIGH | 5 |
| MEDIUM | 25 |
| LOW | 15 |
| **Total** | **45** |

---

## HIGH Risk — Production/Scientific Authority

These use mtime as the **sole or primary** authority for selecting which artifact to use in production or scientific computation. No structural/ provenance guard.

| # | File | Line(s) | Function | Purpose | Risk |
|---|------|---------|----------|---------|------|
| 1 | `ultimate_pipeline\tools\ost_run_protocol_adapter.py` | 92 | `find_canonical_xodr()` | Selects "canonical" XODR as the newest `*.xodr` by mtime — no structural filter, no sibling check | **HIGH** |
| 2 | `ultimate_pipeline\config\settings.py` | 204–206 | `find_best_final_xodr()` (module-level helper) | Scans all run dirs for newest `08_final*.xodr` by mtime — pure mtime authority, no structural verification | **HIGH** |
| 3 | `ultimate_pipeline\tools\check_osm_to_carla_determinism.py` | 272–281 | `_pick_latest_runs()` | Composite mtime (`max` of child/metadata/final/tiles mtimes) used to rank which runs are "latest" for determinism audit | **HIGH** |
| 4 | `ultimate_pipeline\tools\path_utils.py` | 58 | `resolve_latest_valid_run()` | `max(meta.mtime, tiles_dir.mtime, child.mtime)` determines which run dir is "latest valid" — used by downstream consumers | **HIGH** |
| 5 | `ultimate_pipeline\run_full_domain_gap.py` | 3401 | `_find_latest_valid_run()` | Same composite-mtime pattern as path_utils — picks "latest valid run" for domain gap computation | **HIGH** |

---

## MEDIUM Risk — Production with Partial Mitigation

These use mtime as **tiebreak** among structurally-validated candidates, or in production artifact selection where structural checks partially mitigate risk.

| # | File | Line(s) | Function | Purpose | Mitigation |
|---|------|---------|----------|---------|------------|
| 6 | `ultimate_pipeline\tools\artifact_locator.py` | 116, 123 | `_newest_final_xodr()` | mtime tiebreak among repair-verified siblings; structural check (`_repaired_sibling_exists`) applied first | Structural filter first, mtime tiebreak only |
| 7 | `ultimate_pipeline\tools\export_thesis_tables.py` | 35, 38 | `_latest_final_xodr()` | Newest `08_final*_semantic.xodr` by mtime, fallback to any `08_final*.xodr` | No structural check — pure mtime |
| 8 | `ultimate_pipeline\tools\export_thesis_tables.py` | 110 | `collect_run_rows()` | `run_dirs` sorted by mtime for iteration order (not selection authority) | Iteration order only |
| 9 | `ultimate_pipeline\run_determinism_audit.py` | 450 | `_find_final_xodr()` | Newest `08_final*.xodr` by mtime | No structural check |
| 10 | `ultimate_pipeline\run_determinism_audit.py` | 627 | `_find_source_osm_file()` | Newest OSM file by mtime | No structural check |
| 11 | `ultimate_pipeline\tools\check_osm_to_carla_determinism.py` | 152 | `_find_source_osm_file()` | Newest OSM file by mtime | No structural check |
| 12 | `ultimate_pipeline\tools\compare_runs_determinism.py` | 159, 164 | `_find_final_xodr()` | Newest by mtime; documented rationale about laneSectionFixed convention | Documented, no structural guard |
| 13 | `ultimate_pipeline\tools\carla_smoke_suite.py` | 98 | `_find_xodr_in_run()` | Newest by mtime; documented rationale about laneSectionFixed | Documented, no structural guard |
| 14 | `ultimate_pipeline\domain_gap\run_alignment_and_matching.py` | 68 | `_find_latest_final_xodr()` | Newest by mtime among semantic/any final xodr | No structural check |
| 15 | `ultimate_pipeline\domain_gap\run_gap_ablation_experiment.py` | 79 | `_find_newest_final_xodr()` | Newest `08_final*.xodr` by mtime; documented convention | Documented, no structural guard |
| 16 | `ultimate_pipeline\domain_gap\run_domain_gap_sweep.py` | 25 | `_find_newest_final_xodr()` | Newest `08_final*.xodr` by mtime; documented convention | Documented, no structural guard |
| 17 | `ultimate_pipeline\experiments\thesis\run_thesis_experiments.py` | 29, 32 | `_resolve_auto_xodr()` | Newest `08_final*.xodr` by mtime; fallback `*.xodr` | No structural check |
| 18 | `ultimate_pipeline\experiments\thesis\run_all_experiments.py` | 50 | `_discover_auto_xodr()` | Newest by mtime across AUTO_XODR_GLOBS | No structural check |
| 19 | `ultimate_pipeline\experiments\thesis\run_all_experiments.py` | 105 | `_latest_pair_dir()` | Newest `pair_*` dir by mtime | No structural check |
| 20 | `ultimate_pipeline\tools\stage_gate_regression.py` | 22 | `_find_stage_xodr()` | Newest by mtime for stage gate regression | Documented rationale |
| 21 | `ultimate_pipeline\tools\run_thesis_final_experiments.py` | 350 | `_find_latest_run_dir()` | Newest run dir by mtime | No structural check |
| 22 | `ultimate_pipeline\tools\run_thesis_final_experiments.py` | 358 | `_find_final_xodr()` | Newest by mtime | No structural check |
| 23 | `ultimate_pipeline\tools\run_thesis_final_experiments.py` | 670 | `_run_single_experiment()` | Newest `*DROP_BAD_LINKS*.xodr` by mtime | No structural check |
| 24 | `ultimate_pipeline\tools\run_thesis_experiments.py` | 66–67 | `_resolve_xodr_for_mode()` | `mode == "latest"` — newest `*.xodr` by mtime | Explicit mode, documented |
| 25 | `ultimate_pipeline\tools\osm_stats.py` | 96 | `_find_osm_in_run()` | Newest OSM file by mtime | No structural check |
| 26 | `ultimate_pipeline\database\run_archiver.py` | 33 | `_list_runs()` | mtime sort for archive priority (older runs archived first) | Ordering for archival, not selection |
| 27 | `ultimate_pipeline\run_determinism_audit.py` | 995 | `_capture_run_fingerprint()` | mtime recorded as metadata in fingerprint dict (not used as authority) | Metadata only, no selection authority |
| 28 | `ultimate_pipeline\run_full_domain_gap.py` | 712 | `_pick_best_metadata_file()` | mtime as tiebreak among scored candidates | Score-primary, mtime tiebreak |
| 29 | `ultimate_pipeline\run_full_domain_gap.py` | 7220, 7236 | `main()` | Newest `08_final*.xodr` by mtime for auto xodr resolution | No structural check |
| 30 | `ultimate_pipeline\domain_gap\run_alignment_and_matching.py` | 43 | `_resolve_latest_run_dir()` | Newest run dir by mtime | No structural check |

---

## LOW Risk — UI/Convenience or Metadata Only

These use mtime for UI convenience (display ordering, log browsing) or record mtime as informational metadata.

| # | File | Line(s) | Function | Purpose |
|---|------|---------|----------|---------|
| 31 | `ultimate_pipeline\config\settings.py` | 2042 | `_resolve_tiles_dir()` | mtime sort to scan recent pipeline outputs (top 50) |
| 32 | `ultimate_pipeline\config\settings.py` | 2145, 2149 | `_resolve_manual_map_path()` | mtime tiebreak among name-scored manual maps |
| 33 | `ultimate_pipeline\config\settings.py` | 2305 | `latest_output_dir()` | Newest subdir by mtime for display |
| 34 | `ultimate_pipeline\carla_tools\map_registry.py` | 740 | `_find_latest_carla_log()` | Newest CARLA log for copying to output |
| 35 | `ultimate_pipeline\perception\train_launcher.py` | 69 | `_find_latest_dataset()` | Newest dataset dir for training |
| 36 | `ultimate_pipeline\perception\perception_api.py` | 110 | `_resolve_config_json()` | Newest JSON config for perception |
| 37 | `ultimate_pipeline\diagnostics\continuity_summary.py` | 27 | `_find_latest_run()` | Newest run for diagnostic display |
| 38 | `ultimate_pipeline\utils\output_discovery.py` | 34 | `find_latest_tiles_output()` | Newest tiles output for discovery |
| 39 | `ultimate_pipeline\tools\osm_stats.py` | 78 | `_resolve_run_dir()` | Newest run dir for OSM stats display |
| 40 | `ultimate_pipeline\tools\carla_smoke_suite.py` | 82 | `_resolve_run_dir()` | Newest run dir for smoke test |
| 41 | `ultimate_pipeline\tools\run_thesis_final_experiments.py` | 203 | `_resolve_manual_map()` | Newest manual map for thesis fallback |
| 42 | `scripts\xodr_bisect.py` | 44, 48 | `last_crash()` | Newest crash logs for bisection |
| 43 | `scripts\regen_map_of_record.py` | 275 | `_find_final_xodr()` | Newest pattern for map-of-record regen |
| 44 | `ultimate_pipeline\run_full_domain_gap.py` | 1287 | `_file_fingerprint()` | mtime recorded as metadata in fingerprint |
| 45 | `ultimate_pipeline\experiments\thesis\run_structural_domain_gap_batch.py` | 150 | `main()` | mtime comparison for stray output detection (not selection) |

---

## Key Observations

1. **Structural mitigation exists in one place only.** `artifact_locator._newest_final_xodr()` applies `_repaired_sibling_exists()` before mtime tiebreak. All other `08_final*.xodr` selection paths use pure mtime authority.

2. **The `ost_run_protocol_adapter.find_canonical_xodr()` at line 92 is the highest-risk single point.** It selects the "canonical" XODR for CARLA loading with zero structural verification — any adversarial or stale `.xodr` dropped into a run dir wins.

3. **Composite mtime patterns (`max(mtimes)`) in `path_utils.py:58` and `run_full_domain_gap.py:3401`** determine which run is "latest valid" for production domain gap computation. A touched directory could override a genuinely newer run.

4. **The `settings.py` module-level helper at line ~196** (`find_best_final_xodr`) is called during settings initialization and uses pure mtime authority across all run dirs.

5. **Convention documentation is good but inconsistent.** ~10 locations have explanatory comments about why mtime-newest is used (laneSectionFixed convention), but ~35 do not.

6. **Previous OC3 adversarial review fixed 3 of 4 mtime-based selection defects** (see `STALE_ARTIFACT_SELECTION_AUDIT.json`), but the fixes were limited to the `reports/` selection code path. The ~40 remaining production uses were not addressed.

---

## Recommendations

1. **Promote structural verification** from `artifact_locator._newest_final_xodr()` to a shared utility; apply in all `08_final*.xodr` selection paths.
2. **Replace pure-mtime run-dir selection** (HIGH-risk items 1–5) with explicit run ID / receipt provenance.
3. **Audit `ost_run_protocol_adapter.find_canonical_xodr()`** for adversarial resilience — it's the canonical CARLA loading path.
4. **Add provenance metadata** (run ID, SHA256, creation timestamp from manifest) alongside mtime in all selection tiebreaks.
5. **Standardize convention comments** across all mtime uses to clarify whether mtime is authority or tiebreak.
