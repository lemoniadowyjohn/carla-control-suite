# Thesis RQ tables (C19)

| RQ | metric | value | status | note |
|---|---|---|---|---|
| RQ1 | local_lane_width_gap | 0.0415 | BOUNDED | LOCAL manual-footprint comparison; directly comparable lane geometry, maps agree [footprint=hull] |
| RQ1 | local_curvature_gap | 0.2192 | BOUNDED | LOCAL manual-footprint comparison; range-sensitive histogram-L1, treat as a bounded structural signal, not a precise scalar [footprint=hull] |
| RQ1 | local_curvature_wasserstein_gap | 0.0747 | BOUNDED | LOCAL manual-footprint comparison; Wasserstein distance over absolute-curvature distributions, normalized by 0.2 1/m; range-robust companion to histogram-L1 [footprint=hull] |
| RQ1 | local_road_length_ratio_auto_over_manual | 2.692 | BOUNDED | LOCAL manual-footprint ratio; measures road-network completeness inside Grid0828's area [footprint=hull] -- hull is tighter/preferred, bbox kept in local_registration.json for comparison (hull materially lowers this ratio vs. the legacy bbox footprint) |
| RQ1 | local_junction_ratio_auto_over_manual | 3.782 | BOUNDED | LOCAL manual-footprint ratio; measures junction/detail completeness inside Grid0828's area [footprint=hull] |
| RQ1 | local_road_count_ratio_auto_over_manual | 3.565 | BOUNDED | LOCAL manual-footprint ratio; separates structural completeness from whole-map scope [footprint=hull] |
| RQ1 | local_auto_footprint_kept_fraction | 0.1096 | BOUNDED | manual-footprint crop kept 3539 / 32297 auto roads; whole-map stats are scope context [footprint=hull] |
| RQ1 | whole_map_construction_layers_excluded_from_local_gap | True | BOUNDED | traffic lights are a construction layer, not road-network structure, and are excluded from the LOCAL structural gap because Grid0828 does not model traffic lights at all (0 in the manual map) -- there is nothing in-footprint to compare against, independent of croppability. Reported at whole-map level as a construction/modeling-choice artifact. |
| RQ1 | whole_map_road_type_coverage_gap_context | 0.0 | BOUNDED | whole-map context only; manual road types are a subset of auto's |
| RQ1 | local_building_density_gap | 0.4139 | BOUNDED | LOCAL manual-footprint building density comparison (C26): buildings recovered via outline cornerGlobal absolute positions and cropped in-footprint -- no longer excluded [footprint=hull] |
| RQ1 | local_frechet_distance_median_m | 35.258309336315136 | BOUNDED | Thesis future-work #14, recomputed against the current local-registration methodology: mean=55.27961477346578m p90=128.01454419021908m over 895 matched road pairs (spacing=5.0m, threshold=50.0m); ~30-50x smaller than the delivered thesis's uncropped whole-network SE(2) number on every statistic -- see THESIS_ITEM14_FRECHET_DISTANCE_RECOMPUTED.md [footprint=hull] |
| RQ2 | perceptual_gap | — | DEFERRED | paired capture not executed -- needs a live CARLA server (currently blocked by a livelock, see C20_TIER1_PROBE_20260821) or the C16 UE cook (blocked on a human operator) |
| RQ3/RQ5 | gnn_latent_cosine_distance | 1.153711485862732 | AUTHORITATIVE | 5-seed ensemble (seeds=[42, 43, 44, 45, 46]) trained on the UNION of both maps' tiles (resolves C18's OOD one-sided-training caveat); cosine_distance 95% bootstrap CI=[1.0803263425827025, 1.2475571155548095], cosine_similarity 95% CI=[-0.24446440041065215, -0.08032630681991577] (excludes zero/no-gap) |
| RQ3 | miou_auto_train_manual_eval | — | DEFERRED | needs C17 paired captures (blocked -- see RQ2) |
| RQ5 | real_unlabeled_shift_metrics | — | DEFERRED | no real-world Ingolstadt dataset available on this machine (independent of the CARLA blocker) |
| RQ3 | domain_adaptation_coral_mmd | — | DEFERRED | needs C17 paired captures (blocked -- see RQ2) |
| RQ4 | natural_dr_present | False | AUTHORITATIVE | Osm2Odr(pinned OSM) is STRUCTURALLY deterministic (identical roads/junctions/length every run) but BYTE-non-deterministic (serialization ordering/IDs/metadata vary). Re-running yields the SAME map -> natural DR is ABSENT. |
| RQ4 | structurally_deterministic | True | AUTHORITATIVE | 3 runs, 3 distinct sha256 (byte-non-deterministic serialization, structure identical) |
| RQ4 | explicit_dr_wired | True | AUTHORITATIVE | apply_n produces 5 distinct variants; deterministic given a seed, varies across seeds |

Counts by status: {'BOUNDED': 11, 'DEFERRED': 4, 'AUTHORITATIVE': 4}
