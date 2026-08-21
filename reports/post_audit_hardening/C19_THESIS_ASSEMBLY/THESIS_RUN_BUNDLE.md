# Thesis run bundle (C19 step 4)

## Pinned maps
- **auto_map_of_record** (auto): `69b1f52016ebdc3e643616f86161d85789624c94d48e5caf56c53004d534de6e` — campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260819_160350.xodr
- **manual_grid0828** (manual): `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c` — campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr

## Protocol snapshot
- note: `No protocol.py exists in this repo (referenced in earlier C13/C15 specs but never built) -- this snapshot captures what actually governs a run instead.`
- git_commit: `dbe2bc977d30385eef285eb5dba3957bbdc3cdf9`
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
- **RQ1/lane_width_gap** [BOUNDED]: genuine, small -- directly comparable, maps agree
- **RQ1/curvature_gap** [BOUNDED]: real (fixed 2026-08-21, was a 1.0 measurement artifact); range-sensitive histogram-L1, treat as 'moderate' not a precise scalar
- **RQ1/road_length_gap** [BOUNDED]: construction/scope artifact (full OSM extraction vs curated subset), not domain gap
- **RQ1/traffic_light_density_gap** [BOUNDED]: construction artifact
- **RQ1/building_density_gap** [BOUNDED]: construction artifact
- **RQ1/road_type_coverage_gap** [BOUNDED]: manual road types are a subset of auto's
- **RQ2/perceptual_gap** [DEFERRED]: paired capture not executed -- needs a live CARLA server (currently blocked by a livelock, see C20_TIER1_PROBE_20260821) or the C16 UE cook (blocked on a human operator)
- **RQ3/RQ5/gnn_latent_cosine_distance** [PROTOTYPE]: one-sided (auto-only) training makes the manual map OOD for the encoder -- conflates true structural gap with distribution shift; corroborates RQ1, not an independent authoritative measurement
- **RQ3/miou_auto_train_manual_eval** [DEFERRED]: needs C17 paired captures (blocked -- see RQ2)
- **RQ5/real_unlabeled_shift_metrics** [DEFERRED]: no real-world Ingolstadt dataset available on this machine (independent of the CARLA blocker)
- **RQ3/domain_adaptation_coral_mmd** [DEFERRED]: needs C17 paired captures (blocked -- see RQ2)
- **RQ4/natural_dr_present** [AUTHORITATIVE]: Osm2Odr(pinned OSM) is STRUCTURALLY deterministic (identical roads/junctions/length every run) but BYTE-non-deterministic (serialization ordering/IDs/metadata vary). Re-running yields the SAME map -> natural DR is ABSENT.
- **RQ4/structurally_deterministic** [AUTHORITATIVE]: 3 runs, 3 distinct sha256 (byte-non-deterministic serialization, structure identical)
- **RQ4/explicit_dr_wired** [AUTHORITATIVE]: apply_n produces 5 distinct variants; deterministic given a seed, varies across seeds
