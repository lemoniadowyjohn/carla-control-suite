# Thesis run bundle (C19 step 4)

## Pinned maps
- **auto_map_of_record** (auto): `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798` — campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr
- **auto_map_of_record_reproregen1_superseded** (auto): `847d41bd11d85ff468f7e9611e1914959dad3b444ba83002911f20f86fd925bb` — campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_180515.xodr
- **auto_map_of_record_round6_elevationfix_superseded** (auto): `cb85fc14420479bc5ddee432636c531df3a41377850f999960c484e530f78d46` — campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_131617.xodr
- **auto_map_of_record_round5_hygienefix_superseded** (auto): `60a363258c29b22b4abd1151ea9aa6ab19510cf89107b72f3a2892c933ca0d75` — campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260904_214501.xodr
- **auto_map_of_record_deepaudit_superseded** (auto): `e281367e5429533a25c809272de697e2a4166c042bf069f89daffbde7f638ba2` — campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260904_deepaudit.xodr
- **auto_map_of_record_junctionfix_superseded** (auto): `a5bd01be4ef480a09836cec89eb16f8a169f8f3d34527bc65e5d47707b162802` — campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260902_junctionfix.xodr
- **auto_map_of_record_c29_superseded** (auto): `744757f3f01da835269b5678eeb269cf5d534984213c551b9c475699aa73aec8` — campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260819_160350_C29_BUILDING_PATCH.xodr
- **manual_grid0828** (manual): `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c` — campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr

## Protocol snapshot
- note: `No protocol.py exists in this repo (referenced in earlier C13/C15 specs but never built) -- this snapshot captures what actually governs a run instead.`
- git_commit: `eb5dd83adc691f451796ba34ffed5e49a2800aaa`
- git_branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803`
- git_dirty: `True`
- canonical_regen_entrypoint: `scripts/regen_map_of_record.py`
- inputs_manifest: `campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json`

## Evidence reports
- [✓] reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/C14_RQ1_REPORT.md
- [✓] reports/post_audit_hardening/C15_RQ4_DR/C15_RQ4_REPORT.md
- [✓] reports/post_audit_hardening/C18_GNN_LATENT_GAP/C18_GNN_LATENT_GAP_REPORT.md
- [✓] reports/post_audit_hardening/C17_rq2_perception_capture.md
- [✓] reports/post_audit_hardening/C13_manual_map_and_registry.md
- [✓] reports/post_audit_hardening/C20_CARLA_RUNTIME_UNBLOCK.md
- [✓] reports/post_audit_hardening/C20_TIER1_PROBE_20260821/FINDINGS.md

## Claim boundaries (per RQ metric)
- **RQ1/natural_dr_present** [AUTHORITATIVE]: Osm2Odr(pinned OSM) is STRUCTURALLY deterministic (identical roads/junctions/length every run) but BYTE-non-deterministic (serialization ordering/IDs/metadata vary). Re-running yields the SAME map -> natural DR is ABSENT.
- **RQ1/structurally_deterministic** [AUTHORITATIVE]: 3 runs, 3 distinct sha256 (byte-non-deterministic serialization, structure identical)
- **RQ2/local_lane_width_gap** [BOUNDED]: LOCAL manual-footprint comparison; directly comparable lane geometry, maps agree [footprint=hull]
- **RQ2/local_curvature_gap** [BOUNDED]: LOCAL manual-footprint comparison; range-sensitive histogram-L1, treat as a bounded structural signal, not a precise scalar [footprint=hull]
- **RQ2/local_curvature_wasserstein_gap** [BOUNDED]: LOCAL manual-footprint comparison; Wasserstein distance over absolute-curvature distributions, normalized by 0.2 1/m; range-robust companion to histogram-L1 [footprint=hull]
- **RQ2/local_road_length_ratio_auto_over_manual** [BOUNDED]: LOCAL manual-footprint ratio; measures road-network completeness inside Grid0828's area [footprint=hull] -- hull is tighter/preferred, bbox kept in local_registration.json for comparison (hull materially lowers this ratio vs. the legacy bbox footprint)
- **RQ2/local_junction_ratio_auto_over_manual** [BOUNDED]: LOCAL manual-footprint ratio; measures junction/detail completeness inside Grid0828's area [footprint=hull]
- **RQ2/local_road_count_ratio_auto_over_manual** [BOUNDED]: LOCAL manual-footprint ratio; separates structural completeness from whole-map scope [footprint=hull]
- **RQ2/local_auto_footprint_kept_fraction** [BOUNDED]: manual-footprint crop kept 3539 / 32297 auto roads; whole-map stats are scope context [footprint=hull]
- **RQ2/whole_map_construction_layers_excluded_from_local_gap** [BOUNDED]: traffic lights are a construction layer, not road-network structure, and are excluded from the LOCAL structural gap because Grid0828 does not model traffic lights at all (0 in the manual map) -- there is nothing in-footprint to compare against, independent of croppability. Reported at whole-map level as a construction/modeling-choice artifact.
- **RQ2/whole_map_road_type_coverage_gap_context** [BOUNDED]: whole-map context only; manual road types are a subset of auto's
- **RQ2/local_building_density_gap** [BOUNDED]: LOCAL manual-footprint building density comparison (C26): buildings recovered via outline cornerGlobal absolute positions and cropped in-footprint -- no longer excluded [footprint=hull]
- **RQ2/local_frechet_distance_median_m** [BOUNDED]: Thesis future-work #14, recomputed against the current local-registration methodology: mean=55.27961477346578m p90=128.01454419021908m over 895 matched road pairs (spacing=5.0m, threshold=50.0m); ~30-50x smaller than the delivered thesis's uncropped whole-network SE(2) number on every statistic -- see THESIS_ITEM14_FRECHET_DISTANCE_RECOMPUTED.md [footprint=hull]
- **RQ3/perceptual_gap** [DEFERRED]: paired capture not executed -- needs a live CARLA server (currently blocked by a livelock, see C20_TIER1_PROBE_20260821) or the C16 UE cook (blocked on a human operator)
- **RQ4/gnn_latent_cosine_distance** [AUTHORITATIVE]: 5-seed ensemble (seeds=[42, 43, 44, 45, 46]) trained on the UNION of both maps' tiles (resolves C18's OOD one-sided-training caveat); cosine_distance 95% bootstrap CI=[0.616146469116211, 0.6760465860366821], cosine_similarity 95% CI=[0.32272505164146426, 0.3838535487651825] (excludes zero/no-gap)
- **RQ4/explicit_dr_wired** [AUTHORITATIVE]: apply_n produces 5 distinct variants; deterministic given a seed, varies across seeds
- **RQ5/miou_auto_train_manual_eval** [DEFERRED]: RQ5(a): needs C17 paired captures (blocked -- see RQ3)
- **RQ5/domain_adaptation_coral_mmd** [DEFERRED]: RQ5(a): needs C17 paired captures (blocked -- see RQ3)
- **RQ5/real_unlabeled_shift_metrics** [DEFERRED]: RQ5(b): no real-world Ingolstadt dataset available on this machine (independent of the CARLA blocker)
