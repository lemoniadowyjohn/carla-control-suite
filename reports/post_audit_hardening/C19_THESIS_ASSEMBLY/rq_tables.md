# Thesis RQ tables (C19)

| RQ | metric | value | status | note |
|---|---|---|---|---|
| RQ1 | lane_width_gap | 0.0415145202899021 | BOUNDED | genuine, small -- directly comparable, maps agree |
| RQ1 | curvature_gap | 0.09311717328016497 | BOUNDED | real (fixed 2026-08-21, was a 1.0 measurement artifact); range-sensitive histogram-L1, treat as 'moderate' not a precise scalar |
| RQ1 | road_length_gap | 1.0 | BOUNDED | construction/scope artifact (full OSM extraction vs curated subset), not domain gap |
| RQ1 | traffic_light_density_gap | 1.0 | BOUNDED | construction artifact |
| RQ1 | building_density_gap | 0.7950785267578812 | BOUNDED | construction artifact |
| RQ1 | road_type_coverage_gap | 0.0 | BOUNDED | manual road types are a subset of auto's |
| RQ2 | perceptual_gap | — | DEFERRED | paired capture not executed -- needs a live CARLA server (currently blocked by a livelock, see C20_TIER1_PROBE_20260821) or the C16 UE cook (blocked on a human operator) |
| RQ3/RQ5 | gnn_latent_cosine_distance | 1.142302393913269 | PROTOTYPE | one-sided (auto-only) training makes the manual map OOD for the encoder -- conflates true structural gap with distribution shift; corroborates RQ1, not an independent authoritative measurement |
| RQ3 | miou_auto_train_manual_eval | — | DEFERRED | needs C17 paired captures (blocked -- see RQ2) |
| RQ5 | real_unlabeled_shift_metrics | — | DEFERRED | no real-world Ingolstadt dataset available on this machine (independent of the CARLA blocker) |
| RQ3 | domain_adaptation_coral_mmd | — | DEFERRED | needs C17 paired captures (blocked -- see RQ2) |
| RQ4 | natural_dr_present | False | AUTHORITATIVE | Osm2Odr(pinned OSM) is STRUCTURALLY deterministic (identical roads/junctions/length every run) but BYTE-non-deterministic (serialization ordering/IDs/metadata vary). Re-running yields the SAME map -> natural DR is ABSENT. |
| RQ4 | structurally_deterministic | True | AUTHORITATIVE | 3 runs, 3 distinct sha256 (byte-non-deterministic serialization, structure identical) |
| RQ4 | explicit_dr_wired | True | AUTHORITATIVE | apply_n produces 5 distinct variants; deterministic given a seed, varies across seeds |

Counts by status: {'BOUNDED': 6, 'DEFERRED': 4, 'PROTOTYPE': 1, 'AUTHORITATIVE': 3}
