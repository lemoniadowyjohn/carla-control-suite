# Thesis run bundle (C19 step 4)

## Pinned maps
- **auto_map_of_record** (auto): `69b1f52016ebdc3e643616f86161d85789624c94d48e5caf56c53004d534de6e` — campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260819_160350.xodr
- **manual_grid0828** (manual): `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c` — campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr

## Protocol snapshot
- note: `No protocol.py exists in this repo (referenced in earlier C13/C15 specs but never built) -- this snapshot captures what actually governs a run instead.`
- git_commit: `692320bab616f1f0ee27dea5c3362e8a7504e9b6`
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
- **RQ1/local_lane_width_gap** [BOUNDED]: LOCAL manual-footprint comparison; directly comparable lane geometry, maps agree
- **RQ1/local_curvature_gap** [BOUNDED]: LOCAL manual-footprint comparison; range-sensitive histogram-L1, treat as a bounded structural signal, not a precise scalar
- **RQ1/local_curvature_wasserstein_gap** [BOUNDED]: LOCAL manual-footprint comparison; Wasserstein distance over absolute-curvature distributions, normalized by 0.2 1/m; range-robust companion to histogram-L1
- **RQ1/local_road_length_ratio_auto_over_manual** [BOUNDED]: LOCAL manual-footprint ratio; measures road-network completeness inside Grid0828's area
- **RQ1/local_junction_ratio_auto_over_manual** [BOUNDED]: LOCAL manual-footprint ratio; measures junction/detail completeness inside Grid0828's area
- **RQ1/local_road_count_ratio_auto_over_manual** [BOUNDED]: LOCAL manual-footprint ratio; separates structural completeness from whole-map scope
- **RQ1/local_auto_footprint_kept_fraction** [BOUNDED]: manual-footprint crop kept 6079 / 32297 auto roads; whole-map stats are scope context
- **RQ1/whole_map_construction_layers_excluded_from_local_gap** [BOUNDED]: buildings + traffic lights are construction layers, not road-network structure. Excluded from the LOCAL structural gap because the auto map's buildings are all attached to a single container road (not spatially distributed), so they cannot be cropped to the footprint. Note both maps DO model buildings (Grid0828 spatially; auto on a container road); traffic-lights are modeled by the auto map but not Grid0828. Reported at whole-map level as construction artifacts.
- **RQ1/whole_map_road_type_coverage_gap_context** [BOUNDED]: whole-map context only; manual road types are a subset of auto's
- **RQ2/perceptual_gap** [DEFERRED]: paired capture not executed -- needs a live CARLA server (currently blocked by a livelock, see C20_TIER1_PROBE_20260821) or the C16 UE cook (blocked on a human operator)
- **RQ3/RQ5/gnn_latent_cosine_distance** [PROTOTYPE]: one-sided (auto-only) training makes the manual map OOD for the encoder -- conflates true structural gap with distribution shift; corroborates RQ1, not an independent authoritative measurement
- **RQ3/miou_auto_train_manual_eval** [DEFERRED]: needs C17 paired captures (blocked -- see RQ2)
- **RQ5/real_unlabeled_shift_metrics** [DEFERRED]: no real-world Ingolstadt dataset available on this machine (independent of the CARLA blocker)
- **RQ3/domain_adaptation_coral_mmd** [DEFERRED]: needs C17 paired captures (blocked -- see RQ2)
- **RQ4/natural_dr_present** [AUTHORITATIVE]: Osm2Odr(pinned OSM) is STRUCTURALLY deterministic (identical roads/junctions/length every run) but BYTE-non-deterministic (serialization ordering/IDs/metadata vary). Re-running yields the SAME map -> natural DR is ABSENT.
- **RQ4/structurally_deterministic** [AUTHORITATIVE]: 3 runs, 3 distinct sha256 (byte-non-deterministic serialization, structure identical)
- **RQ4/explicit_dr_wired** [AUTHORITATIVE]: apply_n produces 5 distinct variants; deterministic given a seed, varies across seeds
