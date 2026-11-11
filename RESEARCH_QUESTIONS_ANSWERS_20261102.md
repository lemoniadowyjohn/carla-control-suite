# Research questions — evidence-backed answers (2026-11-02)

Branch `integration/post-pr16-final-20261102`. Every number below was **re-derived from raw artifacts in
this session**, not copied from summaries. RQ wording is from
`submission/thesis_source/Chapter1/chap1.tex:24-28`.

| RQ | Question | Status | Answer |
|---|---|---|---|
| RQ1 | Determinism of OSM → OpenDRIVE generation | **AUTHORITATIVE** (structural) / BOUNDED (bytes) | The generator is structurally deterministic: identical roads, junctions and lengths across runs on the pinned OSM. Raw bytes differ only in non-semantic serialization such as timestamps; after timestamp normalization the hash is stable, and real structural changes are still detected. Natural domain randomization does **not** occur. |
| RQ2 | Structural domain gap (auto map vs manual Grid0828) | **BOUNDED** | Inside the manual map's convex-hull footprint, lane width and curvature agree closely (lane_width_gap 0.042, curvature_gap 0.093 whole map / 0.22 local). The auto map is **2.68× denser in road length, 3.78× in junctions and 3.56× in road count**. That is a real completeness gap (full OSM extraction vs a curated hand model), not a tolerance artifact. |
| RQ3 | Perceptual domain gap (paired CARLA capture) | **DEFERRED — not measured** | No paired auto/manual capture exists, so there is no number to report. See "Path to RQ3/RQ5" below. |
| RQ4 | Structural variability / latent representation (GNN) | **AUTHORITATIVE** (leak-free) | Auto and manual maps occupy clearly separated regions of the learned latent space: **cosine distance 0.921, 95% bootstrap CI [0.845, 0.976]**. 5 seeds, union-trained on 562 tiles, CPU. The CI excludes zero for every seed. The earlier 0.643 [0.616, 0.676] had a train/eval content leak (GAP-010) and is **superseded**. The leak-free value is larger. |
| RQ5a | Generalization: train on auto-map captures, test on manual (mIoU degradation) | **DEFERRED — not measured** | Depends on the RQ3 paired captures. |
| RQ5b | Transfer to real-world data | **DEFERRED — external data** | No real-world Ingolstadt dataset is available on this machine. |

## Evidence (re-verified 2026-11-02)

**RQ1**
- `tests/unit/test_exp_osm_to_xodr_determinism_normalized.py`: 5 passed, 1 skipped (executed).
- Structural signature: `reports/post_audit_hardening/C15_RQ4_DR/C15_RQ4_DOMAIN_RANDOMIZATION.json`. The "RQ4" in the filename predates the 2026-09-06 relabel.

**RQ2**
- Source: `reports/production_readiness/20260923_RQ2_REVERIFICATION/local_registration.json`.
- Ratios recomputed from raw counts: 143606.1/53525.3 = 2.683; 450/119 = 3.782; 3536/993 = 3.561.
- Map hashes checked on disk:
  - auto map-of-record `…20260916_232831.xodr`: sha256 `370abbbb…4c8c8`, matching the registry;
  - `Grid0828.xodr`: sha256 `5eaece23…e9b0c`.

**RQ4**
- Source: `reports/production_readiness/20260924T000000Z_GAP010_RQ4_LEAKFREE_RETRAIN/aggregate_stats.json` (sha256 `89f5d2ac…`).
- Mean and CI were recomputed from the 5 per-seed values with the repo's own bootstrap (`gnn_provenance.py:784-814`, seed 0, 2000 resamples); both match exactly.
- The post-hoc leakage audit passed for all 5 checkpoints.
- Training-exclusion inputs:
  - `candidate_connectivity_repaired.xodr`: `c3dc29d3…`;
  - `cities/ingolstadt/manual_grid0821.xodr`: `69ee3498…`, present in the main checkout and deliberately gitignored.
- Fixed this session: `tools/export_thesis_tables.py` had still emitted the leaky 0.643 as AUTHORITATIVE, and the README called RQ4 "not citable". Both are corrected (`2e0b764a`, `1509c559`). The refreshed table is `reports/production_readiness/20261102T000000Z_RQ_TABLES_REFRESH/`. The historical C19 table is unchanged.

## Path to RQ3 / RQ5 (what blocks them, by class)

| Blocker | Class | Detail |
|---|---|---|
| CARLA server | **Resolved** | 2026-10-21: RPC answers (0.9.16, 15 maps), Grid0828 loads (3.85 GB VRAM), and an RGB frame was captured. GAP-017's handshake hang no longer reproduces. |
| Auto map in CARLA | **CODE done; runtime blocked** | Built and verified `tools/rq3_crop_auto_to_manual_footprint.py` (`ebe80121`). It produces a 17.7 MB crop: 3,584 roads, 450 junctions, deterministic sha256 `5a27f6ee…`, 0 dangling references. It is a pure subset of the map-of-record and covers 100% of Grid0828, with 93% of its road length inside the footprint. CARLA pilot (2026-11-03): **2 attempts failed at the RPC handshake, before the crop was loaded.** CarlaUE4 filled 5.9 of 6.1 GB VRAM at 84 °C and never answered, even when started on `OpenDriveMap`. No driver reset was logged. The identical command worked on 2026-10-21, right after a system recovery. Next: reboot, then rerun the pilot. Receipts are kept in the session scratchpad `rq3crop/`. |
| Same-place alignment | **OPERATOR data** | A paired capture needs surveyed anchors (CHAT-05: 3 fit + 2 holdout points) to place matching routes on both maps. |
| Capture writer crash | **CODE** (being fixed) | `capture_writer.py` raises a `NameError` when writing labels; it is pre-existing on production. |
| Admission | **OPERATOR** | The RQ3 gate admits evidence only with an Ed25519-signed independent review receipt. No trust root exists, so any capture can be at most "measured, NOT_ADMITTED". |
| RQ5 training | **RESOURCE** | CPU only (torch 2.9.1+cpu); the frozen budget is 3 epochs × 3 seeds × batch 4. scikit-learn 1.8.0 is available for CORAL/MMD. |
| Disk | **RESOURCE** | C: ~6.7 GB, E: 2.6 GB, F: 2.2 GB free. A paired 6-camera capture needs several GB. |
| RQ5b data | **EXTERNAL** | Needs a real-world Ingolstadt dataset. |

Smallest honest path to a first RQ3 number:
1. Write a governed, source-stage tool that crops the auto map to Grid0828's footprint. Store the output as a new artifact; never edit the map-of-record.
2. Get the anchor set from the operator.
3. Free about 10 GB of disk.
4. Run a single-camera, low-resolution paired pilot on Grid0828 and the auto crop. Only the main agent or the operator may run CARLA.
5. Report the result as `measured, NOT_ADMITTED` until an external reviewer signs a receipt.
