# MIRROR DRIFT INVENTORY (read-only)

- Generated: read-only byte-compare of `ultimate_pipeline/` (canonical) vs `submission/infrastructure/ultimate_pipeline/` (mirror).
- Scope: `.py` files present in BOTH trees; `__pycache__/` and `test_*` excluded.
- Method: byte-compare (exact). No mirrored file was modified.
- Drift guard: tests/phase_q/test_duplicate_module_drift.py CRITICAL_MIRRORED_FILES (load-path-critical set).

## Summary

- total pairs: **531**
- identical: **498**
- drifted: **33**
- guarded (on CRITICAL_MIRRORED_FILES): **6** (of which drifted: **0**)
- unguarded-drifted: **33**

## Per-file status

| path | status | canonical bytes | mirror bytes | size equal | guarded |
|---|---|---|---|---|---|
| __init__.py | DRIFT | 228 | 1428 | False | False |
| analysis/correlator.py | identical | 940 | 940 | True | False |
| analysis/cross_city.py | identical | 2608 | 2608 | True | False |
| analysis/domain_gap_statistics.py | identical | 1964 | 1964 | True | False |
| analysis/lane_debugger.py | identical | 331 | 331 | True | False |
| analysis/pipeline_output_summary.py | identical | 12733 | 12733 | True | False |
| augmentation/realism_augmentor.py | identical | 10070 | 10070 | True | False |
| bootstrap_repo_root.py | DRIFT | 335 | 752 | False | False |
| carla_tools/__init__.py | DRIFT | 362 | 835 | False | False |
| carla_tools/actor_stream_manager.py | identical | 8640 | 8640 | True | False |
| carla_tools/carla_final_check.py | identical | 15704 | 15704 | True | False |
| carla_tools/carla_final_test.py | identical | 13869 | 13869 | True | False |
| carla_tools/carla_probe_port.py | identical | 211 | 211 | True | False |
| carla_tools/carla_readiness.py | identical | 9707 | 9707 | True | False |
| carla_tools/carla_recovery.py | identical | 12030 | 12030 | True | False |
| carla_tools/carla_server.py | identical | 8134 | 8134 | True | False |
| carla_tools/carla_sim_consolidated.py | identical | 18270 | 18270 | True | False |
| carla_tools/check_opendrive_determinism.py | identical | 3843 | 3843 | True | False |
| carla_tools/evaluate_generated_map.py | identical | 9658 | 9658 | True | False |
| carla_tools/fixed_traffic_manager.py | identical | 9162 | 9162 | True | False |
| carla_tools/local_perception_runner.py | identical | 25693 | 25693 | True | False |
| carla_tools/map_identity_guard.py | identical | 2564 | 2564 | True | True |
| carla_tools/map_loader.py | identical | 949 | 949 | True | False |
| carla_tools/map_registry.py | identical | 14443 | 14443 | True | False |
| carla_tools/mesh_streamer.py | identical | 4032 | 4032 | True | False |
| carla_tools/perception_runner_hpc.py | identical | 3885 | 3885 | True | False |
| carla_tools/perception_runner_local.py | identical | 561 | 561 | True | False |
| carla_tools/qa_tile_spawn_probe.py | identical | 9646 | 9646 | True | False |
| carla_tools/reload_ready_for_sensors.py | identical | 4830 | 4830 | True | False |
| carla_tools/road_defect_detector.py | identical | 8697 | 8697 | True | False |
| carla_tools/runtime_enrichments.py | identical | 14809 | 14809 | True | False |
| carla_tools/safe_spawn_ego.py | identical | 4131 | 4131 | True | False |
| carla_tools/screenshot_generator.py | identical | 7616 | 7616 | True | False |
| carla_tools/sensor_rig.py | identical | 7139 | 7139 | True | False |
| carla_tools/spawn_enrichments.py | identical | 14118 | 14118 | True | False |
| carla_tools/spawn_hardening.py | identical | 825 | 825 | True | False |
| carla_tools/spawn_recovery.py | identical | 4149 | 4149 | True | False |
| carla_tools/spawn_validator.py | identical | 1969 | 1969 | True | False |
| carla_tools/thesis_sensor_rig.py | identical | 72965 | 72965 | True | False |
| carla_tools/tile_qa_suite.py | identical | 7541 | 7541 | True | False |
| carla_tools/tile_streamer.py | identical | 13719 | 13719 | True | False |
| carla_tools/tile_world_runner.py | identical | 5445 | 5445 | True | False |
| carla_tools/vehicle_manager/__init__.py | identical | 266 | 266 | True | False |
| carla_tools/vehicle_manager/cache.py | identical | 2721 | 2721 | True | False |
| carla_tools/vehicle_manager/core.py | identical | 7377 | 7377 | True | False |
| carla_tools/vehicle_manager/spawner.py | identical | 4669 | 4669 | True | False |
| carla_tools/vehicle_manager/validator.py | identical | 1500 | 1500 | True | False |
| carla_tools/vehicle_manager/vehicle_manager.py | identical | 7390 | 7390 | True | False |
| carla_tools/weather_controller.py | identical | 3701 | 3701 | True | False |
| cli.py | DRIFT | 21526 | 15734 | False | False |
| config/paths.py | identical | 253 | 253 | True | False |
| config/runtime.py | identical | 812 | 812 | True | False |
| config/settings.py | DRIFT | 88816 | 79131 | False | False |
| config/thesis_contract.py | identical | 14376 | 14376 | True | False |
| contracts/__init__.py | DRIFT | 1300 | 1087 | False | False |
| contracts/agent_sync.py | DRIFT | 11143 | 14114 | False | False |
| contracts/artifacts.py | identical | 11031 | 11031 | True | False |
| contracts/experiment_config.py | identical | 6640 | 6640 | True | False |
| core/carla_opendrive_loader.py | identical | 18329 | 18329 | True | True |
| core/carla_preflight.py | identical | 11500 | 11500 | True | False |
| core/carla_utils.py | identical | 21179 | 21179 | True | False |
| core/crash_classifier.py | identical | 4108 | 4108 | True | False |
| core/determinism.py | identical | 646 | 646 | True | False |
| core/file_utils.py | identical | 1004 | 1004 | True | False |
| core/georef_utils.py | identical | 1917 | 1917 | True | False |
| core/odr_io.py | identical | 10384 | 10384 | True | False |
| core/opendrive_gen_diagnostic.py | identical | 7993 | 7993 | True | True |
| core/repair_diff.py | identical | 1389 | 1389 | True | False |
| core/return_codes.py | identical | 299 | 299 | True | False |
| core/run_manifest.py | identical | 4422 | 4422 | True | False |
| core/s_invariants.py | identical | 9656 | 9656 | True | False |
| core/tile_failure_monitor.py | identical | 2726 | 2726 | True | False |
| core/validation_report.py | identical | 4658 | 4658 | True | False |
| core/xodr_hash_gate.py | identical | 3384 | 3384 | True | True |
| core/xodr_lightener.py | identical | 2320 | 2320 | True | False |
| core/xodr_sanitizer.py | DRIFT | 17380 | 15953 | False | False |
| core/xodr_statistics.py | identical | 9029 | 9029 | True | False |
| database/db_manager.py | identical | 9632 | 9632 | True | False |
| database/run_archiver.py | identical | 2898 | 2898 | True | False |
| db/sensor_logger.py | identical | 3307 | 3307 | True | False |
| debug/carla_crash_fixtures.py | identical | 3055 | 3055 | True | False |
| debug/check_lanes_and_stats.py | identical | 1064 | 1064 | True | False |
| debug/check_s_invariants.py | identical | 3556 | 3556 | True | False |
| debug/compare_xodr.py | identical | 432 | 432 | True | False |
| debug/failure_bundle.py | identical | 3434 | 3434 | True | False |
| debug/single_road_extractor.py | identical | 2618 | 2618 | True | False |
| dem/dem_auto_downloader.py | identical | 8654 | 8654 | True | False |
| dem/dem_diagnostics.py | identical | 2945 | 2945 | True | False |
| determinism/__init__.py | identical | 68 | 68 | True | False |
| determinism/stage_digest.py | identical | 2313 | 2313 | True | False |
| diagnostics/autopilot_check.py | identical | 3633 | 3633 | True | False |
| diagnostics/autopilot_test.py | identical | 3715 | 3715 | True | False |
| diagnostics/carla_quick_load.py | identical | 6704 | 6704 | True | False |
| diagnostics/check_carla_session.py | identical | 1316 | 1316 | True | False |
| diagnostics/continuity_diff_anim.py | identical | 1331 | 1331 | True | False |
| diagnostics/continuity_heatmap.py | identical | 2717 | 2717 | True | False |
| diagnostics/continuity_metrics.py | identical | 1701 | 1701 | True | False |
| diagnostics/continuity_summary.py | identical | 5440 | 5440 | True | False |
| diagnostics/dataset_quick_audit.py | identical | 2601 | 2601 | True | False |
| diagnostics/elevation_summary.py | identical | 4203 | 4203 | True | False |
| diagnostics/lane_debugger.py | identical | 1160 | 1160 | True | False |
| diagnostics/mesh_checker.py | identical | 1893 | 1893 | True | False |
| diagnostics/pipeline_diagnostics.py | identical | 1274 | 1274 | True | False |
| diagnostics/system_integrity_checker.py | identical | 6201 | 6201 | True | False |
| diagnostics/tile_forensics.py | identical | 7203 | 7203 | True | False |
| diagnostics/validate_manual_maps.py | identical | 6451 | 6451 | True | False |
| diagnostics/xodr_cropper.py | identical | 1412 | 1412 | True | False |
| diagnostics/xodr_cropper_gps.py | identical | 19080 | 19080 | True | False |
| domain_gap/adaptation/__init__.py | identical | 60 | 60 | True | False |
| domain_gap/adaptation/adaptation_runner.py | identical | 1751 | 1751 | True | False |
| domain_gap/adaptation/coral.py | identical | 1143 | 1143 | True | False |
| domain_gap/adaptation/mmd.py | identical | 684 | 684 | True | False |
| domain_gap/connectivity_gap.py | identical | 19296 | 19296 | True | False |
| domain_gap/curvature_gap.py | identical | 6540 | 6540 | True | False |
| domain_gap/deterministic_alignment.py | identical | 6990 | 6990 | True | False |
| domain_gap/domain_gap_aggregator.py | identical | 8716 | 8716 | True | False |
| domain_gap/domain_gap_prep.py | identical | 4774 | 4774 | True | False |
| domain_gap/domain_gap_stats.py | identical | 14808 | 14808 | True | False |
| domain_gap/elevation_gap.py | identical | 14201 | 14201 | True | False |
| domain_gap/experiment_logger.py | identical | 4954 | 4954 | True | False |
| domain_gap/fast_eval.py | identical | 6323 | 6323 | True | False |
| domain_gap/feature_gap.py | identical | 4943 | 4943 | True | False |
| domain_gap/gap_analyzer.py | identical | 6922 | 6922 | True | False |
| domain_gap/geo_alignment.py | DRIFT | 33899 | 33159 | False | False |
| domain_gap/geometry_gap.py | identical | 9823 | 9823 | True | False |
| domain_gap/intersection_classifier.py | identical | 3833 | 3833 | True | False |
| domain_gap/intersection_gap.py | identical | 3916 | 3916 | True | False |
| domain_gap/junction_complexity_gap.py | identical | 3931 | 3931 | True | False |
| domain_gap/manual_vs_auto_comparator.py | identical | 2278 | 2278 | True | False |
| domain_gap/map_stats_osm.py | identical | 6016 | 6016 | True | False |
| domain_gap/map_stats_xodr.py | identical | 6840 | 6840 | True | False |
| domain_gap/object_density_gap.py | identical | 4549 | 4549 | True | False |
| domain_gap/osm_loader.py | identical | 3793 | 3793 | True | False |
| domain_gap/per_tile_gap.py | identical | 4195 | 4195 | True | False |
| domain_gap/perception_gap.py | identical | 8423 | 8423 | True | False |
| domain_gap/perception_gap_feature_proxy.py | identical | 2955 | 2955 | True | False |
| domain_gap/perception_plots.py | identical | 5650 | 5650 | True | False |
| domain_gap/qms.py | identical | 2955 | 2955 | True | False |
| domain_gap/report_aggregator.py | identical | 5324 | 5324 | True | False |
| domain_gap/report_writer.py | identical | 1028 | 1028 | True | False |
| domain_gap/road_classification_gap.py | identical | 4537 | 4537 | True | False |
| domain_gap/run_alignment_and_matching.py | identical | 7684 | 7684 | True | False |
| domain_gap/run_domain_gap_sweep.py | identical | 5353 | 5353 | True | False |
| domain_gap/run_gap_ablation_experiment.py | identical | 3837 | 3837 | True | False |
| domain_gap/semantic_gap.py | identical | 4220 | 4220 | True | False |
| domain_gap/structural_gap.py | identical | 3665 | 3665 | True | False |
| domain_gap/tests/__init__.py | identical | 28 | 28 | True | False |
| domain_gap/tile_gap_evaluator.py | identical | 8401 | 8401 | True | False |
| domain_gap/tile_gap_heatmap.py | identical | 4388 | 4388 | True | False |
| domain_gap/tile_grid_meta.py | identical | 6591 | 6591 | True | False |
| domain_gap/tile_matcher.py | identical | 18516 | 18516 | True | False |
| domain_gap/tile_perception_gap.py | identical | 3846 | 3846 | True | False |
| domain_gap/tile_reporter.py | identical | 988 | 988 | True | False |
| domain_gap/topology_gap.py | identical | 2200 | 2200 | True | False |
| domain_gap/validator.py | identical | 717 | 717 | True | False |
| domain_gap_cli.py | identical | 1382 | 1382 | True | False |
| domain_gap_gnn/__init__.py | identical | 130 | 130 | True | False |
| domain_gap_gnn/collapse_check.py | identical | 4136 | 4136 | True | False |
| domain_gap_gnn/graph_builder.py | identical | 7185 | 7185 | True | False |
| domain_gap_gnn/infer_tile_gaps.py | identical | 2759 | 2759 | True | False |
| domain_gap_gnn/latent_gap_metrics.py | identical | 5526 | 5526 | True | False |
| domain_gap_gnn/latent_gap_runner.py | identical | 5477 | 5477 | True | False |
| domain_gap_gnn/latent_gap_utils.py | identical | 2120 | 2120 | True | False |
| domain_gap_gnn/map_encoder.py | identical | 2994 | 2994 | True | False |
| domain_gap_gnn/map_tile_dataset.py | identical | 3252 | 3252 | True | False |
| domain_gap_gnn/run_ksweep.py | identical | 9751 | 9751 | True | False |
| domain_gap_gnn/train_map_encoder.py | identical | 6195 | 6195 | True | False |
| elevation/elevation_seam_fixer.py | DRIFT | 8770 | 289 | False | False |
| enrichment/blender_runner.py | DRIFT | 17309 | 18042 | False | False |
| enrichment/building_extruder.py | identical | 4603 | 4603 | True | False |
| enrichment/elevation_importer.py | DRIFT | 68182 | 66224 | False | False |
| enrichment/elevation_link_offset_solver.py | identical | 9360 | 9360 | True | False |
| enrichment/lane_generator.py | identical | 6955 | 6955 | True | False |
| enrichment/object_injector.py | DRIFT | 10990 | 5020 | False | False |
| enrichment/osm2world_runner.py | DRIFT | 33841 | 33614 | False | False |
| enrichment/osm_meta_index.py | identical | 3319 | 3319 | True | False |
| enrichment/osm_polygon_loader.py | identical | 9218 | 9218 | True | False |
| enrichment/realism.py | identical | 5700 | 5700 | True | False |
| enrichment/regulatory_sign_writer.py | identical | 3918 | 3918 | True | False |
| enrichment/sidewalk_builder.py | identical | 7122 | 7122 | True | False |
| enrichment/speed_limit_writer.py | identical | 3638 | 3638 | True | False |
| enrichment/street_furniture_rules.py | identical | 907 | 907 | True | False |
| enrichment/traffic_light_infer.py | identical | 7886 | 7886 | True | False |
| enrichment/turn_lanes_writer.py | identical | 2277 | 2277 | True | False |
| entrypoints.py | DRIFT | 1523 | 1053 | False | False |
| experiments/__init__.py | identical | 927 | 927 | True | False |
| experiments/evaluator.py | identical | 5788 | 5788 | True | False |
| experiments/experiment_schema.py | identical | 781 | 781 | True | False |
| experiments/registry.py | identical | 13913 | 13913 | True | False |
| experiments/rl_fuzzer.py | identical | 2679 | 2679 | True | False |
| experiments/runner.py | identical | 1975 | 1975 | True | False |
| experiments/thesis/__init__.py | identical | 77 | 77 | True | False |
| experiments/thesis/core_algorithms.py | identical | 3533 | 3533 | True | False |
| experiments/thesis/domain_adaptation.py | identical | 314 | 314 | True | False |
| experiments/thesis/exp_carla_import_repeatability.py | identical | 7569 | 7569 | True | False |
| experiments/thesis/exp_domain_gap_manual_vs_auto.py | identical | 5975 | 5975 | True | False |
| experiments/thesis/exp_manual_vs_manual_structural.py | identical | 6172 | 6172 | True | False |
| experiments/thesis/exp_natural_domain_randomization.py | identical | 3883 | 3883 | True | False |
| experiments/thesis/exp_osm_to_xodr_determinism.py | identical | 3587 | 3587 | True | False |
| experiments/thesis/experiment_auto_vs_auto.py | identical | 7127 | 7127 | True | False |
| experiments/thesis/manual_refs.py | identical | 2752 | 2752 | True | False |
| experiments/thesis/perception_preflight.py | identical | 7602 | 7602 | True | False |
| experiments/thesis/protocol.py | identical | 14253 | 14253 | True | False |
| experiments/thesis/run_all_experiments.py | identical | 17667 | 17667 | True | False |
| experiments/thesis/run_perception_capture_pair.py | identical | 14476 | 14476 | True | False |
| experiments/thesis/run_structural_domain_gap_batch.py | identical | 7750 | 7750 | True | False |
| experiments/thesis/run_thesis_experiments.py | identical | 12558 | 12558 | True | False |
| experiments/thesis/run_thesis_oneweek.py | identical | 8685 | 8685 | True | False |
| experiments/thesis/run_vision_domain_gap.py | identical | 8390 | 8390 | True | False |
| experiments/trainer.py | identical | 1891 | 1891 | True | False |
| experiments/unified_runner.py | identical | 9035 | 9035 | True | False |
| fixes/__init__.py | identical | 123 | 123 | True | False |
| fixes/fix_missing_lane_successors.py | identical | 8987 | 8987 | True | False |
| geometry/crosssection_repair.py | identical | 2176 | 2176 | True | False |
| geometry/elevation_smoother.py | identical | 1369 | 1369 | True | False |
| geometry/geometry_math.py | DRIFT | 6226 | 3897 | False | False |
| geometry/geometry_validator.py | identical | 9546 | 9546 | True | False |
| geometry/lane_seam_checker.py | identical | 4710 | 4710 | True | False |
| geometry/lane_width_clamp.py | identical | 613 | 613 | True | False |
| geometry/laneoffset_normalizer.py | identical | 6428 | 6428 | True | False |
| geometry/laneoffset_smoother.py | identical | 1758 | 1758 | True | False |
| geometry/lanesection_boundary_fixer.py | identical | 2036 | 2036 | True | False |
| geometry/mesh_continuity_repairer.py | identical | 17243 | 17243 | True | False |
| geometry/planview_smoother.py | DRIFT | 18831 | 13514 | False | False |
| geometry/quarantine_bad_roads.py | identical | 8612 | 8612 | True | False |
| hpc/build_yolo_dataset.py | identical | 6953 | 6953 | True | False |
| hpc/carla_server_launcher.py | identical | 2100 | 2100 | True | False |
| hpc/dataset_builder.py | identical | 1362 | 1362 | True | False |
| hpc/experiment_orchestrator.py | identical | 4352 | 4352 | True | False |
| hpc/hpc_experiments_dashboard.py | identical | 3356 | 3356 | True | False |
| hpc/hpc_experiments_plan.py | identical | 2590 | 2590 | True | False |
| hpc/hpc_load_opendrive_batch.py | identical | 5611 | 5611 | True | False |
| hpc/hpc_preflight.py | identical | 1676 | 1676 | True | False |
| hpc/hpc_training_launcher.py | identical | 5183 | 5183 | True | False |
| hpc/perception_runner_hpc.py | identical | 449 | 449 | True | False |
| hpc/run_core_experiments.py | identical | 1956 | 1956 | True | False |
| hpc/run_thesis_hpc_analysis.py | identical | 3677 | 3677 | True | False |
| hpc/run_train.py | identical | 419 | 419 | True | False |
| hpc/spawn_manager.py | identical | 2931 | 2931 | True | False |
| hpc/train_yolo.py | identical | 4355 | 4355 | True | False |
| hpc/yolo_backend.py | identical | 1997 | 1997 | True | False |
| inventory_processor.py | identical | 13878 | 13878 | True | False |
| lanes/lane_repair.py | identical | 4827 | 4827 | True | False |
| lanes/lanelink_builder.py | identical | 7404 | 7404 | True | False |
| lanes/markings_builder.py | identical | 11388 | 11388 | True | False |
| llm/llm_check.py | identical | 2750 | 2750 | True | False |
| llm/llm_client.py | identical | 2427 | 2427 | True | False |
| llm/llm_domain_gap_reviewer.py | identical | 2497 | 2497 | True | False |
| llm/llm_quality_gate.py | identical | 2756 | 2756 | True | False |
| llm/llm_safety_assistant.py | identical | 2561 | 2561 | True | False |
| llm/llm_xodr_checker.py | identical | 3174 | 3174 | True | False |
| llm/ollama_bootstrap.py | identical | 2221 | 2221 | True | False |
| llm/xodr_llm_checker.py | identical | 9624 | 9624 | True | False |
| main_pipeline.py | DRIFT | 143725 | 138955 | False | False |
| map_fixes/__init__.py | identical | 24 | 24 | True | False |
| map_fixes/xodr_junction_links.py | identical | 11117 | 11117 | True | False |
| ml/lane_gnn_refiner.py | identical | 759 | 759 | True | False |
| optional/carla_api.py | identical | 1089 | 1089 | True | False |
| osm/osm_downloader.py | identical | 12116 | 12116 | True | False |
| osm/osm_to_xodr.py | identical | 5208 | 5208 | True | False |
| osm/osm_to_xodr_wrapper.py | identical | 11597 | 11597 | True | False |
| perception/__init__.py | identical | 0 | 0 | True | False |
| perception/dataset_generator.py | identical | 20440 | 20440 | True | False |
| perception/eval_real_unlabeled.py | identical | 7220 | 7220 | True | False |
| perception/eval_sim_labeled.py | identical | 7614 | 7614 | True | False |
| perception/min_train_segmentation.py | identical | 3910 | 3910 | True | False |
| perception/perception_api.py | identical | 7610 | 7610 | True | False |
| perception/perception_metrics.py | identical | 5171 | 5171 | True | False |
| perception/perception_metrics_exporter.py | identical | 9102 | 9102 | True | False |
| perception/perception_metrics_simple.py | identical | 3080 | 3080 | True | False |
| perception/perception_runner_local_aug.py | identical | 20669 | 20669 | True | False |
| perception/record_route.py | identical | 74161 | 74161 | True | False |
| perception/record_route_fixed.py | identical | 125071 | 125071 | True | False |
| perception/rig_verifier.py | identical | 981 | 981 | True | False |
| perception/run_capture_end2end.py | identical | 13074 | 13074 | True | False |
| perception/run_training.py | identical | 3881 | 3881 | True | False |
| perception/segmentation_dataset_generator_queues.py | identical | 10867 | 10867 | True | False |
| perception/train_launcher.py | identical | 7063 | 7063 | True | False |
| perception_smoke.py | identical | 5645 | 5645 | True | False |
| pipeline_stages/__init__.py | identical | 58 | 58 | True | False |
| pipeline_stages/stage_00_preflight_carla.py | identical | 5520 | 5520 | True | False |
| pipeline_stages/stage_01_sanitize.py | identical | 1569 | 1569 | True | False |
| pipeline_stages/stage_02_topology_semantics.py | identical | 8069 | 8069 | True | False |
| pipeline_stages/stage_03_topology_repair.py | identical | 4135 | 4135 | True | False |
| pipeline_stages/stage_04_enrichment.py | DRIFT | 11652 | 11650 | False | False |
| pipeline_stages/stage_05_geometry.py | DRIFT | 44292 | 42514 | False | False |
| pipeline_stages/stage_06_links.py | DRIFT | 29284 | 13947 | False | False |
| pipeline_stages/stage_07_lanes.py | identical | 8933 | 8933 | True | False |
| pipeline_stages/stage_08_final_integrity.py | DRIFT | 29932 | 29527 | False | False |
| pipeline_stages/stage_08_integrity.py | DRIFT | 36200 | 35795 | False | False |
| pipeline_stages/stage_09_tiling.py | DRIFT | 22186 | 20708 | False | False |
| pipeline_stages/stage_10_tile_qa.py | identical | 36235 | 36235 | True | False |
| pipeline_stages/stage_11_12_sim_domain.py | identical | 9692 | 9692 | True | False |
| pipeline_stages/stage_11_simulation.py | identical | 3620 | 3620 | True | False |
| pipeline_stages/stage_12_domain_gap.py | identical | 7003 | 7003 | True | False |
| pipeline_stages/stage_14_finalization.py | identical | 19830 | 19830 | True | False |
| quality/__init__.py | identical | 277 | 277 | True | False |
| quality/autofix_postprune_elevation.py | identical | 6640 | 6640 | True | False |
| quality/carla_pruner.py | identical | 18783 | 18783 | True | False |
| quality/check_carla_import_s.py | identical | 6002 | 6002 | True | False |
| quality/check_carla_opendrive_compat.py | identical | 14989 | 14989 | True | True |
| quality/check_dem_coverage.py | identical | 15348 | 15348 | True | False |
| quality/check_dem_full_coverage.py | identical | 7905 | 7905 | True | False |
| quality/check_determinism.py | identical | 9537 | 9537 | True | False |
| quality/check_drivability_smoke.py | identical | 10674 | 10674 | True | False |
| quality/check_elevation_continuity.py | identical | 7153 | 7153 | True | False |
| quality/check_elevation_missing_and_cliffs.py | identical | 8085 | 8085 | True | False |
| quality/check_elevation_profile.py | identical | 6089 | 6089 | True | False |
| quality/check_elevation_seams.py | identical | 6055 | 6055 | True | False |
| quality/check_elevation_smoothness.py | identical | 1887 | 1887 | True | False |
| quality/check_external_libopendrive.py | identical | 4735 | 4735 | True | False |
| quality/check_geometric_continuity.py | DRIFT | 27694 | 26756 | False | False |
| quality/check_junction_integrity.py | identical | 5289 | 5289 | True | False |
| quality/check_lane_connectivity.py | identical | 15122 | 15122 | True | False |
| quality/check_lane_geometry_continuity.py | identical | 7170 | 7170 | True | False |
| quality/check_lane_link_targets_exist.py | identical | 11253 | 11253 | True | False |
| quality/check_lane_section_successors.py | identical | 5627 | 5627 | True | False |
| quality/check_lane_width_continuity.py | identical | 5170 | 5170 | True | False |
| quality/check_origin_sanity.py | identical | 2427 | 2427 | True | False |
| quality/check_physics_feasibility.py | identical | 2394 | 2394 | True | False |
| quality/check_post_tiling_integrity.py | identical | 4963 | 4963 | True | False |
| quality/check_randomness_entropy.py | identical | 1428 | 1428 | True | False |
| quality/check_semantic_overlap.py | identical | 1533 | 1533 | True | False |
| quality/check_xml_integrity.py | identical | 1397 | 1397 | True | False |
| quality/check_xodr_schema.py | identical | 2261 | 2261 | True | False |
| quality/collision_mesh.py | identical | 2891 | 2891 | True | False |
| quality/entropy.py | identical | 427 | 427 | True | False |
| quality/lane_width_invariants.py | identical | 6948 | 6948 | True | False |
| quality/map_acceptance.py | identical | 7153 | 7153 | True | False |
| quality/pipeline_health_summary.py | identical | 12403 | 12403 | True | False |
| quality/quality_gate_manager.py | identical | 14981 | 14981 | True | False |
| quality/quality_gates.py | identical | 8048 | 8048 | True | False |
| quality/quarantine_bad_roads.py | identical | 4816 | 4816 | True | False |
| quality/road_classification_gap.py | identical | 2105 | 2105 | True | False |
| quality/road_link_endpoint_errors.py | identical | 23447 | 23447 | True | False |
| quality/semantic_overlap.py | identical | 316 | 316 | True | False |
| quality/xodr_junction_ref_cleanup.py | identical | 3028 | 3028 | True | False |
| quality/xodr_strict_validator.py | identical | 24710 | 24710 | True | False |
| reports/_generated/__init__.py | identical | 88 | 88 | True | False |
| reports/report_generator.py | identical | 1471 | 1471 | True | False |
| run_determinism_audit.py | identical | 64493 | 64493 | True | False |
| run_full_domain_gap.py | identical | 322270 | 322270 | True | False |
| run_full_test.py | DRIFT | 10179 | 9972 | False | False |
| run_generalization_experiments.py | identical | 20241 | 20241 | True | False |
| run_pipeline.py | identical | 2339 | 2339 | True | False |
| run_quality_gates.py | identical | 2367 | 2367 | True | False |
| scenarios/auto_scenario_generator.py | identical | 1955 | 1955 | True | False |
| scenarios/sweeps.py | identical | 764 | 764 | True | False |
| semantics/__init__.py | identical | 105 | 105 | True | False |
| semantics/semantic_mapper.py | identical | 10403 | 10403 | True | False |
| sensors/attach_sensors_safe.py | identical | 10073 | 10073 | True | False |
| sensors/calibration_sanity_check.py | identical | 7581 | 7581 | True | False |
| sensors/dominik_sensor_setup.py | identical | 23118 | 23118 | True | False |
| sensors/recorder.py | identical | 35434 | 35434 | True | False |
| sensors/rig_transforms.py | identical | 1728 | 1728 | True | False |
| sensors/sensor_visualizer.py | identical | 13972 | 13972 | True | False |
| sensors/sweep_calib_setups.py | identical | 20712 | 20712 | True | False |
| sensors/transform_conventions.py | identical | 6163 | 6163 | True | False |
| settings.py | identical | 176 | 176 | True | False |
| sitecustomize.py | identical | 934 | 934 | True | False |
| system_integrity_checker.py | identical | 5683 | 5683 | True | False |
| tests/conftest.py | identical | 795 | 795 | True | False |
| thesis/generate_curvature_distribution_figure.py | identical | 6020 | 6020 | True | False |
| thesis/generate_figures.py | identical | 1212 | 1212 | True | False |
| thesis/make_figure_pack.py | identical | 3671 | 3671 | True | False |
| tile_validation/carla_load_and_spawn_worker.py | identical | 3803 | 3803 | True | False |
| tile_validation/carla_tile_tester.py | identical | 7919 | 7919 | True | False |
| tile_validation/geometry_seam_checker.py | identical | 4561 | 4561 | True | False |
| tile_validation/lane_seam_checker.py | identical | 11203 | 11203 | True | False |
| tile_validation/qa_tile_spawn_probe.py | identical | 9074 | 9074 | True | False |
| tile_validation/qa_tile_stress_tester.py | identical | 7834 | 7834 | True | False |
| tile_validation/seam_repair.py | identical | 3352 | 3352 | True | False |
| tile_validation/step10_tile_qa_supervisor.py | identical | 10870 | 10870 | True | False |
| tile_validation/step10_tile_qa_worker.py | identical | 6315 | 6315 | True | False |
| tile_validation/tile_stress_tester.py | identical | 11521 | 11521 | True | False |
| tile_validation/tile_visibility.py | identical | 8544 | 8544 | True | False |
| tiling/seam_artifacts.py | identical | 5956 | 5956 | True | False |
| tiling/stream_tiles.py | identical | 2819 | 2819 | True | False |
| tiling/tile_adjacency.py | identical | 4248 | 4248 | True | False |
| tiling/tile_auto_forensics.py | identical | 1511 | 1511 | True | False |
| tiling/tile_extractor.py | DRIFT | 18887 | 16029 | False | False |
| tiling/tile_matcher.py | identical | 1611 | 1611 | True | False |
| tiling/tile_metadata.py | identical | 13384 | 13384 | True | False |
| tiling/tile_validator.py | identical | 4519 | 4519 | True | False |
| tools/artifact_integrity_check.py | identical | 5911 | 5911 | True | False |
| tools/artifact_locator.py | identical | 2394 | 2394 | True | False |
| tools/assert_carla_invariants.py | identical | 9678 | 9678 | True | False |
| tools/audit_thesis_topic_contract.py | identical | 9711 | 9711 | True | False |
| tools/build_ledger_salvage_index.py | identical | 5199 | 5199 | True | False |
| tools/calib_sanity_check.py | identical | 4484 | 4484 | True | False |
| tools/calibrate_sensors_in_carla.py | identical | 23014 | 23014 | True | False |
| tools/capture_perception_pair_safe.py | identical | 8372 | 8372 | True | False |
| tools/capture_rgb_200frames.py | identical | 12944 | 12944 | True | False |
| tools/carla_preflight.py | identical | 9158 | 9158 | True | False |
| tools/carla_probe.py | identical | 9957 | 9957 | True | False |
| tools/carla_probe_map.py | identical | 8954 | 8954 | True | False |
| tools/carla_probe_port.py | identical | 3190 | 3190 | True | False |
| tools/carla_screenshot_once.py | identical | 5242 | 5242 | True | False |
| tools/carla_smoke_suite.py | identical | 11595 | 11595 | True | False |
| tools/carla_visual_smoke_gate.py | identical | 14180 | 14180 | True | False |
| tools/check_osm2world_stack.py | identical | 11334 | 11334 | True | False |
| tools/check_osm_to_carla_determinism.py | identical | 17609 | 17609 | True | False |
| tools/check_seams.py | identical | 3751 | 3751 | True | False |
| tools/check_sensor_rig.py | identical | 1633 | 1633 | True | False |
| tools/check_tile_alignment.py | identical | 4733 | 4733 | True | False |
| tools/compare_runs_determinism.py | identical | 6453 | 6453 | True | False |
| tools/compute_missing_run11_metrics.py | identical | 10171 | 10171 | True | False |
| tools/compute_perception_gap.py | identical | 3435 | 3435 | True | False |
| tools/coordinate_system_artifact.py | identical | 10270 | 10270 | True | False |
| tools/determinism_classify.py | identical | 3559 | 3559 | True | False |
| tools/diagnose_pipeline.py | identical | 3428 | 3428 | True | False |
| tools/diagnostic_carla_probe.py | identical | 4436 | 4436 | True | False |
| tools/drivability_probe.py | identical | 725 | 725 | True | False |
| tools/env_check_carla.py | identical | 1453 | 1453 | True | False |
| tools/evaluate_tiling.py | identical | 27722 | 27722 | True | False |
| tools/export_thesis_tables.py | identical | 6664 | 6664 | True | False |
| tools/extract_elevation_stats.py | identical | 19892 | 19892 | True | False |
| tools/final_map_readiness_gate.py | identical | 16535 | 16535 | True | False |
| tools/find_duplicate_files.py | identical | 2480 | 2480 | True | False |
| tools/generate_enrichments_json.py | identical | 16107 | 16107 | True | False |
| tools/generate_n_runs.py | identical | 18029 | 18029 | True | False |
| tools/hash_tree.py | identical | 7745 | 7745 | True | False |
| tools/junction_connector_rebuild.py | DRIFT | 19150 | 196 | False | False |
| tools/list_entrypoints.py | identical | 213 | 213 | True | False |
| tools/load_final_into_carla.py | identical | 1013 | 1013 | True | True |
| tools/map_only_probe.py | identical | 16925 | 16925 | True | False |
| tools/osm_stats.py | identical | 11329 | 11329 | True | False |
| tools/ost_run_protocol_adapter.py | identical | 11353 | 11353 | True | False |
| tools/pack_thesis_run.py | identical | 12231 | 12231 | True | False |
| tools/path_utils.py | identical | 2267 | 2267 | True | False |
| tools/perception_artifacts.py | identical | 7568 | 7568 | True | False |
| tools/post_run_carla_sanity.py | identical | 9242 | 9242 | True | False |
| tools/preflight_xodr_loadability.py | identical | 13221 | 13221 | True | False |
| tools/preload_map.py | identical | 6805 | 6805 | True | False |
| tools/print_run_paths.py | identical | 1550 | 1550 | True | False |
| tools/probe_carla.py | identical | 6620 | 6620 | True | False |
| tools/project_tools.py | identical | 2940 | 2940 | True | False |
| tools/reconcile_run11_authority.py | identical | 13005 | 13005 | True | False |
| tools/repair_drop_invalid_lane_link_targets.py | identical | 3373 | 3373 | True | False |
| tools/repair_lane_widths.py | identical | 520 | 520 | True | False |
| tools/run_arm.py | identical | 352 | 352 | True | False |
| tools/run_auto_xodr_record.py | identical | 4799 | 4799 | True | False |
| tools/run_experiments.py | identical | 20881 | 20881 | True | False |
| tools/run_full_perception_collect.py | identical | 15638 | 15638 | True | False |
| tools/run_gnn_pipeline.py | identical | 6913 | 6913 | True | False |
| tools/run_offline_gaps_from_pair.py | identical | 17211 | 17211 | True | False |
| tools/run_perception_pair.py | identical | 91591 | 91591 | True | False |
| tools/run_perception_retry.py | identical | 8714 | 8714 | True | False |
| tools/run_perception_safe.py | identical | 277141 | 277141 | True | False |
| tools/run_scenariorunner_once.py | identical | 3942 | 3942 | True | False |
| tools/run_scenarios_batch.py | identical | 4931 | 4931 | True | False |
| tools/run_thesis_experiments.py | identical | 11611 | 11611 | True | False |
| tools/run_thesis_final_experiments.py | DRIFT | 54159 | 54201 | False | False |
| tools/run_tile_perception_sweep.py | identical | 8101 | 8101 | True | False |
| tools/run_tile_qa_controller.py | identical | 350 | 350 | True | False |
| tools/select_and_view_tile.py | identical | 2279 | 2279 | True | False |
| tools/smoke_check_all.py | identical | 31350 | 31350 | True | False |
| tools/smoke_check_spawn.py | identical | 5884 | 5884 | True | False |
| tools/smoke_load_xodr.py | identical | 19225 | 19225 | True | False |
| tools/smoke_osm2world.py | identical | 4514 | 4514 | True | False |
| tools/spawn_sanity_objects.py | identical | 10750 | 10750 | True | False |
| tools/spawn_thesis_rig.py | identical | 9064 | 9064 | True | False |
| tools/stage_gate_regression.py | identical | 1512 | 1512 | True | False |
| tools/start_carla_load_xodr.py | identical | 2784 | 2784 | True | False |
| tools/stream_subprocess.py | identical | 2945 | 2945 | True | False |
| tools/sweep_calib_setups.py | identical | 20291 | 20291 | True | False |
| tools/system_metrics_monitor.py | identical | 2354 | 2354 | True | False |
| tools/thesis_orchestrator.py | identical | 6178 | 6178 | True | False |
| tools/thesis_protocol_postprocess.py | identical | 6424 | 6424 | True | False |
| tools/thesis_qa_bundle.py | identical | 5699 | 5699 | True | False |
| tools/tile_manual_xodr_windows.py | identical | 13265 | 13265 | True | False |
| tools/tile_qa_batch.py | identical | 9134 | 9134 | True | False |
| tools/tile_validate_one.py | identical | 2736 | 2736 | True | False |
| tools/tile_worker.py | identical | 18703 | 18703 | True | False |
| tools/validate_artifacts.py | identical | 5263 | 5263 | True | False |
| tools/validate_governance.py | identical | 26001 | 26001 | True | False |
| tools/validate_thesis_claim_provenance.py | identical | 4177 | 4177 | True | False |
| tools/validate_thesis_run.py | identical | 53115 | 53115 | True | False |
| tools/verify_final_xodr.py | identical | 6896 | 6896 | True | False |
| tools/visual_check_calib_setup.py | identical | 16390 | 16390 | True | False |
| tools/write_manifest.py | identical | 3063 | 3063 | True | False |
| tools/xodr_carla_hardener.py | identical | 19551 | 19551 | True | False |
| tools/xodr_compare_gate.py | identical | 9290 | 9290 | True | False |
| tools/xodr_coordinate_report.py | identical | 3023 | 3023 | True | False |
| tools/xodr_structural_summary.py | identical | 4457 | 4457 | True | False |
| topology/junction_connector_rebuild.py | DRIFT | 34689 | 31346 | False | False |
| topology/missing_junction_link_repair.py | identical | 4947 | 4947 | True | False |
| topology/road_removal.py | identical | 305 | 305 | True | False |
| topology/roundabout_rebuilder.py | identical | 5978 | 5978 | True | False |
| topology/roundabout_reconstructor.py | identical | 27676 | 27676 | True | False |
| topology/semantic_verifier.py | identical | 4875 | 4875 | True | False |
| topology/structure_prune_legacy.py | identical | 6552 | 6552 | True | False |
| topology/structure_scanner.py | identical | 25506 | 25506 | True | False |
| topology/sumo_repair.py | identical | 6760 | 6760 | True | False |
| topology/topology_linter.py | identical | 15662 | 15662 | True | False |
| topology/topology_repair.py | DRIFT | 40398 | 3563 | False | False |
| usercustomize.py | identical | 727 | 727 | True | False |
| utils/__init__.py | identical | 0 | 0 | True | False |
| utils/bootstrap.py | identical | 1029 | 1029 | True | False |
| utils/carla_server.py | identical | 3770 | 3770 | True | False |
| utils/console_encoding.py | identical | 4108 | 4108 | True | False |
| utils/environment_snapshot.py | identical | 653 | 653 | True | False |
| utils/file_hashing.py | identical | 4335 | 4335 | True | False |
| utils/finalize_run_pack.py | identical | 2198 | 2198 | True | False |
| utils/hashing.py | identical | 458 | 458 | True | False |
| utils/logging.py | identical | 109 | 109 | True | False |
| utils/map_fingerprint.py | identical | 1307 | 1307 | True | False |
| utils/optional_imports.py | identical | 533 | 533 | True | False |
| utils/output_discovery.py | identical | 904 | 904 | True | False |
| utils/paths.py | identical | 1901 | 1901 | True | False |
| utils/run_provenance.py | identical | 6381 | 6381 | True | False |
| utils/timestamped_print.py | identical | 2727 | 2727 | True | False |
| utils/utf8_console.py | identical | 299 | 299 | True | False |
| utils/xodr_subset.py | identical | 490 | 490 | True | False |
| visualization/animated_diff.py | identical | 2940 | 2940 | True | False |
| visualization/augmentation_preview.py | identical | 2394 | 2394 | True | False |
| visualization/city_drift_field.py | identical | 2103 | 2103 | True | False |
| visualization/city_map_diff.py | identical | 2382 | 2382 | True | False |
| visualization/cross_section_visualizer.py | identical | 5677 | 5677 | True | False |
| visualization/curvature_drift_plot.py | identical | 1533 | 1533 | True | False |
| visualization/elevation_heatmap.py | identical | 1645 | 1645 | True | False |
| visualization/heatmap_generator.py | identical | 7746 | 7746 | True | False |
| visualization/heatmap_plotter.py | identical | 2515 | 2515 | True | False |
| visualization/iou_histogram.py | identical | 329 | 329 | True | False |
| visualization/lane_overlay.py | identical | 5753 | 5753 | True | False |
| visualization/map_diff.py | DRIFT | 7980 | 7948 | False | False |
| visualization/map_plotter.py | DRIFT | 9706 | 9247 | False | False |
| visualization/osm_overlay.py | identical | 3823 | 3823 | True | False |
| visualization/spawn_heatmap.py | identical | 1905 | 1905 | True | False |
| visualization/thesis_figures.py | identical | 8229 | 8229 | True | False |
| visualization/tile_gap_heatmap.py | identical | 3512 | 3512 | True | False |

## DECISION NEEDED (Claude)

Facts only - no reconciliation performed. Drifted paths grouped by top-level dir:

### __init__.py/
- `__init__.py` (canonical 228 B vs mirror 1428 B, guarded=False)

### bootstrap_repo_root.py/
- `bootstrap_repo_root.py` (canonical 335 B vs mirror 752 B, guarded=False)

### carla_tools/
- `carla_tools/__init__.py` (canonical 362 B vs mirror 835 B, guarded=False)

### cli.py/
- `cli.py` (canonical 21526 B vs mirror 15734 B, guarded=False)

### config/
- `config/settings.py` (canonical 88816 B vs mirror 79131 B, guarded=False)

### contracts/
- `contracts/__init__.py` (canonical 1300 B vs mirror 1087 B, guarded=False)
- `contracts/agent_sync.py` (canonical 11143 B vs mirror 14114 B, guarded=False)

### core/
- `core/xodr_sanitizer.py` (canonical 17380 B vs mirror 15953 B, guarded=False)

### domain_gap/
- `domain_gap/geo_alignment.py` (canonical 33899 B vs mirror 33159 B, guarded=False)

### elevation/
- `elevation/elevation_seam_fixer.py` (canonical 8770 B vs mirror 289 B, guarded=False)

### enrichment/
- `enrichment/blender_runner.py` (canonical 17309 B vs mirror 18042 B, guarded=False)
- `enrichment/elevation_importer.py` (canonical 68182 B vs mirror 66224 B, guarded=False)
- `enrichment/object_injector.py` (canonical 10990 B vs mirror 5020 B, guarded=False)
- `enrichment/osm2world_runner.py` (canonical 33841 B vs mirror 33614 B, guarded=False)

### entrypoints.py/
- `entrypoints.py` (canonical 1523 B vs mirror 1053 B, guarded=False)

### geometry/
- `geometry/geometry_math.py` (canonical 6226 B vs mirror 3897 B, guarded=False)
- `geometry/planview_smoother.py` (canonical 18831 B vs mirror 13514 B, guarded=False)

### main_pipeline.py/
- `main_pipeline.py` (canonical 143725 B vs mirror 138955 B, guarded=False)

### pipeline_stages/
- `pipeline_stages/stage_04_enrichment.py` (canonical 11652 B vs mirror 11650 B, guarded=False)
- `pipeline_stages/stage_05_geometry.py` (canonical 44292 B vs mirror 42514 B, guarded=False)
- `pipeline_stages/stage_06_links.py` (canonical 29284 B vs mirror 13947 B, guarded=False)
- `pipeline_stages/stage_08_final_integrity.py` (canonical 29932 B vs mirror 29527 B, guarded=False)
- `pipeline_stages/stage_08_integrity.py` (canonical 36200 B vs mirror 35795 B, guarded=False)
- `pipeline_stages/stage_09_tiling.py` (canonical 22186 B vs mirror 20708 B, guarded=False)

### quality/
- `quality/check_geometric_continuity.py` (canonical 27694 B vs mirror 26756 B, guarded=False)

### run_full_test.py/
- `run_full_test.py` (canonical 10179 B vs mirror 9972 B, guarded=False)

### tiling/
- `tiling/tile_extractor.py` (canonical 18887 B vs mirror 16029 B, guarded=False)

### tools/
- `tools/junction_connector_rebuild.py` (canonical 19150 B vs mirror 196 B, guarded=False)
- `tools/run_thesis_final_experiments.py` (canonical 54159 B vs mirror 54201 B, guarded=False)

### topology/
- `topology/junction_connector_rebuild.py` (canonical 34689 B vs mirror 31346 B, guarded=False)
- `topology/topology_repair.py` (canonical 40398 B vs mirror 3563 B, guarded=False)

### visualization/
- `visualization/map_diff.py` (canonical 7980 B vs mirror 7948 B, guarded=False)
- `visualization/map_plotter.py` (canonical 9706 B vs mirror 9247 B, guarded=False)
