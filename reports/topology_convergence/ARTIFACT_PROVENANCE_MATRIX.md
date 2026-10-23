# Artifact Provenance Matrix

Generated: 2026-10-11

## Artifacts

| experiment_id | artifact_path | artifact_sha256 | size_bytes | description |
|--------------|---------------|-----------------|------------|-------------|
| A | campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr | 370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8 | 149,799,632 | Authoritative map-of-record (pinned) |
| B | reports/rq1_trial_runs_x2_verify/run_01/20261008_024449_086823/07_lanes_20261008_024449_086823.xodr | 2a188b372ed369a17464c87c1f6932841249f52e51ba8ef049d3b6ce2ab5dccb | 125,001,202 | RQ1 run-01 Stage-7 BEFORE artifact |
| C | reports/gap048/07_lanes_GAP048_AFTER.xodr | 0e3eb2f2c93c3ee60b76dfdf3fe2a644501ecaf1ae69eb32a80e0abb29e6b960 | 125,265,882 | GAP-048 AFTER (ef3003c2 module) |
| D | reports/gap048/07_lanes_GAP048_STAGE8_SIM.xodr | d8dca1d9316e227ffe436a138bcf12df5f6049cdf4fbeb767b457f5f3a29e4c2 | 125,266,233 | GAP-048 Stage-8 simulation |
| E | C:/temp/m2_gap026_regenerated.xodr | 548ccd12d3293dc1b1d45b281fd9f05565b08d4d6a2850bda2e3ab3f7407d4a0 | ~125MB | M2 GAP026 regenerated artifact |

## Modules

| module_path | code_sha | module_sha256 | version | notes |
|------------|----------|---------------|---------|-------|
| ultimate_pipeline/enrichment/lane_successor_topology.py (ef3003c2) | ef3003c2 | b16652e1d72facc84bc19efb79517b8f363e39fee290adbd37c6a9dbda712d62 | GAP-048 strategy 3 | Source-stage through-junction repair |
| ultimate_pipeline/enrichment/lane_successor_topology.py (current) | working_tree | 7ee02c0215c05661f89c8e00ef22f29d2882a3eb4f933d5466e0f695eed30e76 | Divergent untracked | Not committed, differs from ef3003c2 |
| ultimate_pipeline/lanes/junction_lane_width_harmonizer.py (M2) | 0f3c3601 | ca6195612111a12a461919971517853b1b6ca0d7f018f54a23681e610ba89d91 | GAP-026 fix | Lane-width harmonizer |
| ultimate_pipeline/lanes/lanelink_builder.py (M2) | 0f3c3601 | b2a54e3a3e15bdf66911f8dfd2e40a2e8ab898da29e859531b00144cd22dea12 | GAP-026 fix | Regeneration + outer->inner guard |
| ultimate_pipeline/lanes/lanelink_builder.py (current) | working_tree | e7a56037ee569ee71877ad6c68a556ca39c717094d3e8affc62dbb21166af3bb | Current production | Includes Stage-8 call |
| ultimate_pipeline/pipeline_stages/stage_07_lanes.py (M2) | 0f3c3601 | 9253c3203f86c625bfcf40bf01e273d8936f29f18121b6401e4eb8017126848b | GAP-026 integration | Calls harmonizer |
| ultimate_pipeline/pipeline_stages/stage_07_lanes.py (current) | working_tree | 49b3ad1ef3df0e8eac2ca6ffebbd4c03e647890e3cfefc93815a878550726ef4 | Current production | Calls lane_successor_topology |

## Checkers / Oracles

| name | code_sha | module_sha256 | description |
|------|----------|---------------|-------------|
| production_checker | 0f3c3601 (M2) / working_tree | part of lanelink_builder | LaneLinkBuilder.sanitize_junction_lane_links |
| independent_oracle | working_tree | 7fbf4ecb3fcc8f14b7284c5a6f1fc06de1ec0f1bda1b977da2a4ec74dc961c38 | gap026_oracle.py (dual geometry authorities) |

## Experiment Results

| experiment_id | input_artifact_sha256 | code_sha | stage_range | module_sha256 | checker_sha256 | oracle_sha256 | reported_total | reported_fail | reported_repaired | reported_residual | notes |
|--------------|----------------------|----------|-------------|---------------|----------------|---------------|----------------|---------------|-------------------|-------------------|-------|
| baseline_no_regen | 370abbbb... | 68868f76 (prod) | map-of-record | e7a5603... (current) | e7a5603... | 7fbf4ec... | 23529 | 2992 | 0 | 2992 | Map-of-record, no regeneration |
| simple_regen | 370abbbb... | 68868f76 (prod) | map-of-record + regen | e7a5603... (current) | e7a5603... | 7fbf4ec... | 23403 | 2315 | 677 | 2315 | Original lanelink_builder.regenerate |
| m2_regen | 370abbbb... | 0f3c3601 | map-of-record + regen + harmonize | b2a54e3... (M2) + ca61956... | b2a54e3... | 7fbf4ec... | 23403 | 513 | 2479 | 513 | M2 lanelink_builder + harmonizer |
| gap048_ef3003c2 | 2a188b3... (Stage-7 BEFORE) | ef3003c2 | Stage-7 only | b16652e... (ef3003c2) | N/A | N/A | 10563 broken | N/A | 10180 | 376 | Strategy 3 (unambiguous only) |
| gap048_stage8_sim | 0e3eb2f... (GAP048 AFTER) | ef3003c2 | Stage-8 sim | b16652e... | N/A | N/A | 383 | N/A | 7 | 376 | Stage-8 intra-road repair |

## Key Discrepancies

| discrepancy | narrative_a (M2) | narrative_b (simple regen) | notes |
|-------------|------------------|----------------------------|-------|
| fail_after_regen | 513 | 2315 | M2 includes lane-width harmonizer + outer->inner guard |
| angle_severe_eliminated | 451 -> 0 | 451 -> 0 | Both eliminate angle severe |
| dist_severe_reduction | 832 -> 192 | 832 -> 206 | Similar reduction |
| total_reduction | 2992 -> 513 (83%) | 2992 -> 2315 (23%) | M2 fixes lane-width mismatch at junctions |

## GAP-048 Population Discrepancy

| metric | historic_report | ef3003c2_actual | discrepancy |
|--------|-----------------|-----------------|-------------|
| broken_total | 10563 | 10563 | matches |
| repaired | 10180 | 10180 | matches |
| unresolved_ambiguous | 261 | 261 | matches |
| unresolved_no_candidate | 115 | 115 | matches |
| total_unresolved | 376 | 376 | matches |

Note: M3 reported historic 10563 excluded 331 lanes - needs re-computation from frozen baseline.