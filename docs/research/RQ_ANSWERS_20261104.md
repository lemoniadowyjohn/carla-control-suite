# Research questions — evidence-backed answers (2026-11-04)

Branch `integration/post-pr16-final-20261102`. This updates the 2026-11-02 answers: RQ1, RQ2 and RQ4
are unchanged, while the RQ3/RQ5 blockers and the map-quality caveats are current as of 2026-11-04.
Every number was re-derived from raw artifacts, not copied from summaries. RQ wording is from
`submission/thesis_source/Chapter1/chap1.tex:24-28`.

| RQ | Question | Status | Answer |
|---|---|---|---|
| RQ1 | Determinism of OSM → OpenDRIVE generation | **AUTHORITATIVE** (structural) / BOUNDED (bytes) | The generator is structurally deterministic: identical roads, junctions and lengths across runs on the pinned OSM. Raw bytes differ only in non-semantic serialization such as timestamps; after timestamp normalization the hash is stable, and real structural changes are still detected. Natural domain randomization does **not** occur. Open scope gap: the post-enrichment stage has no cheap determinism fixture. |
| RQ2 | Structural domain gap (auto map vs manual Grid0828) | **BOUNDED** | Inside the manual map's convex-hull footprint, lane width and curvature agree closely (lane_width_gap 0.042, curvature_gap 0.093 whole map / 0.22 local). The auto map is **2.68× denser in road length, 3.78× in junctions and 3.56× in road count**. That is a real completeness gap (full OSM extraction vs a curated hand model), not a tolerance artifact. |
| RQ3 | Perceptual domain gap (paired CARLA capture) | **DEFERRED — not measured** | No paired auto/manual capture exists. The code and the auto-map crop are ready; the CARLA runtime is blocked (GAP-077). See "Path to RQ3/RQ5". |
| RQ4 | Structural variability / latent representation (GNN) | **AUTHORITATIVE** (leak-free) | Auto and manual maps occupy clearly separated regions of the learned latent space: **cosine distance 0.921, 95% bootstrap CI [0.845, 0.976]**. 5 seeds, union-trained on 562 tiles, CPU; the CI excludes zero for every seed. The earlier 0.643 [0.616, 0.676] had a train/eval content leak (GAP-010) and is **superseded**. |
| RQ5a | Generalization: train on auto-map captures, test on manual (mIoU degradation) | **DEFERRED — not measured** | Depends on the RQ3 paired captures. |
| RQ5b | Transfer to real-world data | **DEFERRED — external data** | No real-world Ingolstadt dataset is available on this machine. |

## Evidence

**RQ1**
- `tests/unit/test_exp_osm_to_xodr_determinism_normalized.py`: 5 passed, 1 skipped (executed 2026-11-02).
- Structural signature: `reports/post_audit_hardening/C15_RQ4_DR/C15_RQ4_DOMAIN_RANDOMIZATION.json`. The "RQ4" in the filename predates the 2026-09-06 relabel.

**RQ2**
- Source: `reports/production_readiness/20260923_RQ2_REVERIFICATION/local_registration.json`.
- Ratios recomputed from raw counts: 143606.1/53525.3 = 2.683; 450/119 = 3.782; 3536/993 = 3.561.
- Map hashes checked on disk:
  - auto map-of-record: sha256 `370abbbb…4c8c8`, matching the registry;
  - `Grid0828.xodr`: sha256 `5eaece23…e9b0c`.

**RQ4**
- Source: `reports/production_readiness/20260924T000000Z_GAP010_RQ4_LEAKFREE_RETRAIN/aggregate_stats.json` (sha256 `89f5d2ac…`).
- Mean and CI recomputed from the 5 per-seed values with the repo's own bootstrap (`gnn_provenance.py:784-814`, seed 0, 2000 resamples); both match exactly. The post-hoc leakage audit passed for all 5 checkpoints.
- `tools/export_thesis_tables.py` and the README are corrected (`2e0b764a`, `1509c559`). Refreshed table: `reports/production_readiness/20261102T000000Z_RQ_TABLES_REFRESH/`. The historical C19 table is unchanged.

## Map-quality caveats that affect RQ2/RQ3 interpretation

Both are tracked in `reports/production_readiness/20261104T000000Z_GAP_REGISTER_ADDENDUM_2/`.

- **GAP-070 (open):** junction-exit kinks. On the 2026-10-07 regeneration, 3,720 junction exits turn more than 30° at the connector boundary (3,373 at about 53°). Root cause: the default-on junction connector snap in stage 5 rotates connectors (`ROOT_CAUSE_JUNCTION_CONNECTOR_SNAP.md`, `46708baa`). A fix is on branch `fix/gap070-connector-snap-exit-20261103` and was measured on the same stage-5 input: 3,720 → 349 exit kinks. It is not merged until a governed regeneration (X8) confirms it. RQ2's structural metrics (lane width, curvature, density) do not depend on connector heading continuity. Junction-area perception in RQ3 would.
- **GAP-079 (open):** about 0.1 m reversed single-line junction connectors: 58 from CARLA Osm2Odr, and 81 after the netconvert repair. All carry lane routing, so they are not deleted. Whether the reversal is real or only a representation choice is still being investigated (X9b).

## Path to RQ3 / RQ5 (what blocks them, by class)

| Blocker | Class | Detail |
|---|---|---|
| CARLA server | **RUNTIME — blocked (GAP-077)** | The server answered on 2026-10-21 (0.9.16, 15 maps; Grid0828 loaded; an RGB frame was captured). From 2026-11-03, 4 headless pilot attempts all timed out at `wait_for_carla_ready`, before any map was loaded, with 5.9/6.1 GB VRAM in use, 82–84 °C and no GPU driver reset (TDR) events. Next: one visible-window run or a GPU driver check (operator). |
| Auto map in CARLA | **CODE done; runtime blocked** | `tools/rq3_crop_auto_to_manual_footprint.py` (usage: `docs/research/RQ3_AUTO_MAP_CROP_TOOL.md`). Current crop: 19.1 MB, 3,584 roads, 450 junctions, sha256 `b2bc2712…3ea147d12`, 0 dangling references, all 7 hard checks PASS. `<controller>` elements are preserved (fix `47284531`; this supersedes the earlier `5a27f6ee…` crop). It is a pure subset of the map-of-record and covers 100% of Grid0828, with 93% of road length inside the footprint. CARLA loading is not yet verified. |
| Same-place alignment | **OPERATOR data** | A paired capture needs surveyed anchors (CHAT-05: 3 fit + 2 holdout points) to place matching routes on both maps. |
| Capture writer | **Fixed** | The `NameError` on every label write is fixed in `4b3b0e9a`. |
| Admission | **OPERATOR** | The RQ3 gate admits evidence only with an Ed25519-signed independent review receipt. No trust root exists, so any capture can be at most "measured, NOT_ADMITTED". |
| RQ5 training | **RESOURCE** | CPU only (torch 2.9.1+cpu); the frozen budget is 3 epochs × 3 seeds × batch 4. scikit-learn 1.8.0 is available for CORAL/MMD. The launcher's `is_main` crash and ImageNet-weights defects are fixed on this branch. |
| Disk | **RESOURCE** | 2026-11-04: C: ~2.1 GB, E: ~1.7 GB, F: ~2.3 GB, G: ~5.1 GB free. A paired 6-camera capture needs several GB; X8 regeneration needs ≥ 15 GB on one drive. |
| RQ5b data | **EXTERNAL** | Needs a real-world Ingolstadt dataset. |

Smallest honest path to a first RQ3 number:
1. The operator gets CARLA answering again: a visible-window run or a driver check.
2. Load the crop (`b2bc2712…`) and Grid0828; confirm each one loads and renders.
3. Get the anchor set from the operator.
4. Free disk space; run a single-camera, low-resolution paired pilot. Only the main agent or the operator may run CARLA.
5. Report the result as `measured, NOT_ADMITTED` until an external reviewer signs a receipt. State the GAP-070/GAP-079 caveat for junction areas.
