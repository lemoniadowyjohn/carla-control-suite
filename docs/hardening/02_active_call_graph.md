# Active Call Graph

```
__main__  ──>  main()  ──>  MainPipeline().run()
                              │
                              └── _run_internal()
                                    │
                                    ├── [PRELUDE]
                                    │   ├── RunArchiver.archive_old_runs()
                                    │   ├── [if !INPUT_XODR.exists] OSM→XODR bootstrap
                                    │   ├── _maybe_preanchor_input_xodr()   {opt-in}
                                    │   ├── Database._validate_schema()
                                    │   ├── write settings_snapshot.json
                                    │   ├── enforce_determinism()   {if DETERMINISTIC_MODE}
                                    │   ├── ensure_osm_exists()
                                    │   ├── _dem_precheck()
                                    │   ├── CARLA preflight → _connect_carla()  {if reachable}
                                    │   │
                                    ├──★ STAGE 1:  _step1_sanitize(sanitized)
                                    │   │             └── XODRSanitizer.sanitize_xodr()
                                    │   │             └── self.qgate.gate_xml_integrity()
                                    │   │
                                    ├── [optional] _gps_qa_crop()  {if !thesis_strict && ENABLE_GPS_QA_CROP}
                                    │   │
                                    ├──★ STAGE 2:  _step2_topology_semantics()
                                    │   │             ├── handle_georeference()  {always}
                                    │   │             ├── write_georeference_provenance()
                                    │   │             ├── _write_crs_comparability()
                                    │   │             ├── repair_missing_junction_links()  {always}
                                    │   │             ├── TopologyLinter.run()  {always}
                                    │   │             ├── SUMORepair.repair()  {if ENABLE_SUMO_REPAIR}
                                    │   │             ├── StructureScanner.analyze()  {always}
                                    │   │             ├── prune()  {if ENABLE_AGGRESSIVE_STRUCTURE_PRUNE}
                                    │   │             └── SemanticVerifier.analyze_xodr()  {always}
                                    │   │
                                    ├──★ STAGE 3:  _step3_topology_repair()
                                    │   │             ├── TopologyRepair.run()  {always}
                                    │   │             ├── [if ENABLE_CARLA_TEST_EARLY] CARLA load test
                                    │   │             └── _stage_gate("junction_integrity")
                                    │   │
                                    ├──★ STAGE 4:  _step4_enrichment()
                                    │   │             ├── RoundaboutReconstructor  {if ENABLE_ROUNDABOUT_RECONSTRUCTION}
                                    │   │             ├── RoundaboutRebuilder.tag_roundabouts()  {always}
                                    │   │             ├── TrafficLightInferer  {if ENABLE_TRAFFIC_LIGHTS}
                                    │   │             ├── Buildings  {if ENABLE_BUILDINGS}
                                    │   │             ├── RealismModule.enrich()  {if ENABLE_REALISM}
                                    │   │             ├── OSM meta: speed limits, turn lanes, signs  {always}
                                    │   │             └── OSM2WorldRunner.run()  {if enabled}
                                    │   │
                                    ├──★ STAGE 5+6 (MERGED): _step5_geometry_elevation_continuity()
                                    │   │   │
                                    │   │   ├── [SUB 6 FIRST] _step6_planview_continuity()
                                    │   │   │   ├── PlanViewSmoother  {full if unsafe_planview_mutations_enabled}
                                    │   │   │   │   ├── smooth_heading_jumps          ← GATED
                                    │   │   │   │   ├── merge_small_geometries        ← GATED
                                    │   │   │   │   ├── merge_short_segments          ← GATED
                                    │   │   │   │   ├── clamp_curvature               ← ALWAYS
                                    │   │   │   │   └── recompute_s_values            ← ALWAYS
                                    │   │   │   └── MeshContinuityRepairer.run()     ← ALWAYS
                                    │   │   │   └── _stage_gate("geometric_continuity")
                                    │   │   │
                                    │   │   ├── [opt] rebuild_displaced_junction_connectors()
                                    │   │   ├── Freeze geometry (geometryFrozen="true")  ← ALWAYS
                                    │   │   │
                                    │   │   └── [SUB 5 SECOND] _step5_dem_and_geometry()
                                    │   │       ├── DEM download/expand  {if ENABLE_DEM_AUTO_DOWNLOAD}
                                    │   │       ├── check_dem_full_coverage()
                                    │   │       ├── ElevationImporter.apply_dem()
                                    │   │       ├── ElevationSmoother.smooth()
                                    │   │       ├── PlanViewSmoother.clamp_curvature()
                                    │   │       └── GeometryValidator.validate()
                                    │   │
                                    ├──★ STAGE 7:  _step7_lanes_sidewalks()
                                    │   │             └── [delegated to stage_07_lanes.py]
                                    │   │
                                    ├──★ STAGE 8:  _step8_markings_and_integrity()
                                    │   │             ├── Remove illegal id=0 driving lanes
                                    │   │             ├── Add missing <link> nodes
                                    │   │             ├── LaneLinkBuilder.regenerate()  {if unsafe_lanelink_regen_enabled}
                                    │   │             ├── LaneLinkBuilder.sanitize_junction_lane_links()  {always}
                                    │   │             ├── MarkingBuilder.add_basic_markings()  {always}
                                    │   │             └── repair_and_assert_lane_section_successors() {always}
                                    │   │
                                    │   ├── _stage_gate("origin_sanity")
                                    │   ├── _stage_gate("elevation_seams")
                                    │   ├── build_map_acceptance()
                                    │   ├── write_map_content_fingerprint()
                                    │   ├── _step8d_preflight_validation()
                                    │   ├── _write_determinism_fingerprint()
                                    │   ├── run_junction_link_integrity_gate()
                                    │   └── _step8f_optional_carla_elevation_validation()
                                    │
                                    ├──★ STAGE 9:  _step9_tiling()  {if ENABLE_TILING}
                                    │   │             ├── TileExtractor.tile()
                                    │   │             ├── S-invariant fix  {if ENABLE_LANESECTION_FIX}
                                    │   │             └── Subprocess tile_qa_batch  {if enabled}
                                    │   │
                                    ├──★ STAGE 10:  _step10_tile_qa()  {skip if DISABLE_TILE_QA_ON_WINDOWS}
                                    │   │
                                    ├──★ STAGE 10C/D/E: _step10c_road_perception_screenshots()
                                    │   │
                                    ├──★ STAGE 11:  _step11_simulation()  {if interactive}
                                    │   │
                                    ├──★ STAGE 12:  _step12_domain_gap()
                                    │   │
                                    ├──★ QUALITY GATES: _run_quality_gates_wrapper()
                                    │   │
                                    ├──★ FINAL SUMMARY: _final_summary_and_llm()
                                    │   │
                                    └──★ RUN SUMMARY: _write_run_summary()
```

## Key: Conditional stage gates

Labels in `{curly braces}` indicate the condition. All 4 unsafe planView mutations and LaneLink regeneration require **both** explicit opt-in AND `RELEASE_PROFILE=debug` (or other unsafe-permitting profile).
