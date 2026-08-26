# Thesis RQ tables (C19)

| RQ | metric | value | status | note |
|---|---|---|---|---|
| RQ1 | local_lane_width_gap | 0.0415 | BOUNDED | LOCAL manual-footprint comparison; directly comparable lane geometry, maps agree |
| RQ1 | local_curvature_gap | 0.2239 | BOUNDED | LOCAL manual-footprint comparison; range-sensitive histogram-L1, treat as a bounded structural signal, not a precise scalar |
| RQ1 | local_curvature_wasserstein_gap | 0.074 | BOUNDED | LOCAL manual-footprint comparison; Wasserstein distance over absolute-curvature distributions, normalized by 0.2 1/m; range-robust companion to histogram-L1 |
| RQ1 | local_road_length_ratio_auto_over_manual | 4.5 | BOUNDED | LOCAL manual-footprint ratio; measures road-network completeness inside Grid0828's area |
| RQ1 | local_junction_ratio_auto_over_manual | 6.05 | BOUNDED | LOCAL manual-footprint ratio; measures junction/detail completeness inside Grid0828's area |
| RQ1 | local_road_count_ratio_auto_over_manual | 6.122 | BOUNDED | LOCAL manual-footprint ratio; separates structural completeness from whole-map scope |
| RQ1 | local_auto_footprint_kept_fraction | 0.1882 | BOUNDED | manual-footprint crop kept 6079 / 32297 auto roads; whole-map stats are scope context |
| RQ1 | whole_map_construction_layers_excluded_from_local_gap | True | BOUNDED | buildings + traffic lights are construction layers, not road-network structure. Excluded from the LOCAL structural gap because the auto map's buildings are all attached to a single container road (not spatially distributed), so they cannot be cropped to the footprint. Note both maps DO model buildings (Grid0828 spatially; auto on a container road); traffic-lights are modeled by the auto map but not Grid0828. Reported at whole-map level as construction artifacts. |
| RQ1 | whole_map_road_type_coverage_gap_context | 0.0 | BOUNDED | whole-map context only; manual road types are a subset of auto's |
| RQ2 | perceptual_gap | — | DEFERRED | paired capture not executed -- needs a live CARLA server (currently blocked by a livelock, see C20_TIER1_PROBE_20260821) or the C16 UE cook (blocked on a human operator) |
| RQ3/RQ5 | gnn_latent_cosine_distance | 1.142302393913269 | PROTOTYPE | one-sided (auto-only) training makes the manual map OOD for the encoder -- conflates true structural gap with distribution shift; corroborates RQ1, not an independent authoritative measurement |
| RQ3 | miou_auto_train_manual_eval | — | DEFERRED | needs C17 paired captures (blocked -- see RQ2) |
| RQ5 | real_unlabeled_shift_metrics | — | DEFERRED | no real-world Ingolstadt dataset available on this machine (independent of the CARLA blocker) |
| RQ3 | domain_adaptation_coral_mmd | — | DEFERRED | needs C17 paired captures (blocked -- see RQ2) |
| RQ4 | natural_dr_present | False | AUTHORITATIVE | Osm2Odr(pinned OSM) is STRUCTURALLY deterministic (identical roads/junctions/length every run) but BYTE-non-deterministic (serialization ordering/IDs/metadata vary). Re-running yields the SAME map -> natural DR is ABSENT. |
| RQ4 | structurally_deterministic | True | AUTHORITATIVE | 3 runs, 3 distinct sha256 (byte-non-deterministic serialization, structure identical) |
| RQ4 | explicit_dr_wired | True | AUTHORITATIVE | apply_n produces 5 distinct variants; deterministic given a seed, varies across seeds |

Counts by status: {'BOUNDED': 9, 'DEFERRED': 4, 'PROTOTYPE': 1, 'AUTHORITATIVE': 3}
