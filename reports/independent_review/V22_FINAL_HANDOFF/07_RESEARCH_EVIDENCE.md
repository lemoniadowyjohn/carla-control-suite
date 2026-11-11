# V22 RESEARCH EVIDENCE CLASSIFICATION (RQ1–RQ5)

## RQ1 — Determinism

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Repeated-run identity | NOT_RUN | No live experiments in V22 |
| Same source/input data | OFFLINE_VERIFIED | `test_deterministic_alignment.py` passes (16/16) |
| Effective seed | OFFLINE_VERIFIED | Thesis contract enforces seed consistency |
| Structural outputs | OFFLINE_VERIFIED | XODR digest/hashing tests pass |
| Topology metrics | OFFLINE_VERIFIED | Structure scanner invariants pass |
| Run-count completeness | NOT_RUN | No experimental runs executed |
| Correct run index | IMPLEMENTED | `create_run_id` format verified |
| Actual artifact hashes | IMPLEMENTED | SHA256 validation (G2 gate) |
| Source-bound receipts | OFFLINE_VERIFIED | R1 release receipt test passes |

**Status**: OFFLINE_VERIFIED for tooling; RUNTIME_READY pending live experiments.

**Tooling Fixes (V22)**:
- `tools/rq1_complete_receipt.py`: receipt generation defects identified in V21 (A-I) — undefined variables, hardcoded run index, incorrect settings hash, placeholder metrics — require fix with direct regression tests.

---

## RQ2 — Structural Domain Gap

| Criterion | Status | Evidence |
|-----------|--------|----------|
| OSM/generated map identity | NOT_RUN | No map generation in V22 |
| Manual reference identity | NOT_RUN | No map generation |
| Same geographic footprint | NOT_RUN | Requires live CARLA |
| CRS transformation | IMPLEMENTED | Coordinate transformation code present |
| Alignment | OFFLINE_VERIFIED | Deterministic alignment tests pass |
| Lane-width metrics | IMPLEMENTED | Topology structure scanner |
| Hausdorff/RMSE methodology | IMPLEMENTED | Geometry comparison tools exist |
| Junction topology | IMPLEMENTED | Junction connector rebuild |
| Uncertainty reporting | IMPLEMENTED | Thesis contract gates |

**Status**: IMPLEMENTED tooling; MEASURED requires live map generation.

---

## RQ3 — Perceptual Domain Gap

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Paired manual/generated captures | NOT_RUN | No live CARLA |
| Sensor calibration | IMPLEMENTED | `sweep_calib_setups.py` |
| Frame synchronization | IMPLEMENTED | Recorder timestamp handling |
| Map identity | IMPLEMENTED | GeoReference binding |
| Route/weather/seed controls | IMPLEMENTED | Thesis experiment config |
| Dataset manifest completeness | PARTIALLY_FIXED | `tools/rq3_dataset_manifest_verifier.py` identified gaps |
| Sensor timestamps | IMPLEMENTED | Recorder manifest includes timestamps |
| Class-map schema | IMPLEMENTED | Sensor rig contracts |

**Status**: IMPLEMENTED tooling; manifest verifier gaps need fixing.

**Tooling Fixes (V22)**:
- `tools/rq3_dataset_manifest_verifier.py`: manifest validation needs hardening against missing fields, incorrect schema, incomplete paired captures.

---

## RQ4 — GNN Variability

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Graph construction | IMPLEMENTED | GNN provenance module |
| Dataset identity | IMPLEMENTED | Dataset manifest hashing |
| Train/test separation | IMPLEMENTED | Nested K-subset selection |
| No leakage | IMPLEMENTED | Leakage audit in provenance |
| Model checkpoint provenance | IMPLEMENTED | Checkpoint manifest + compatibility |
| Reproducible evaluation | IMPLEMENTED | Determinism summary generation |
| Statistical support | IMPLEMENTED | Per-K multi-seed statistics |

**Status**: IMPLEMENTED tooling; OFFLINE_VERIFIED for determinism; MEASURED requires live training.

---

## RQ5 — Generalization

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Training condition | NOT_RUN | No live training |
| Evaluation target | NOT_RUN | No live eval |
| Dataset/checkpoint identity | IMPLEMENTED | Provenance manifest |
| Class mappings | IMPLEMENTED | Sensor rig contracts |
| Actual metrics | NOT_RUN | No live eval |
| Source provenance | IMPLEMENTED | Git SHA + artifact SHA |
| Incomplete run handling | IMPLEMENTED | Thesis contract gates |
| Wrapper exit status | IMPLEMENTED | `run_determinism_audit.py` exit codes |

**Status**: IMPLEMENTED tooling; MEASURED requires live training/eval.

---

## Scientific Statuses Summary

| RQ | Source Path | Tooling Status | Evidence Status | Missing |
|----|-------------|----------------|-----------------|---------|
| RQ1 | `tools/rq1_complete_receipt.py` | IMPLEMENTED (needs fix) | OFFLINE_VERIFIED | Receipt defects A-I |
| RQ2 | `tools/run_full_domain_gap.py` | IMPLEMENTED | NOT_RUN | Live map generation |
| RQ3 | `tools/rq3_dataset_manifest_verifier.py` | IMPLEMENTED (needs fix) | PARTIALLY_FIXED | Manifest verifier gaps |
| RQ4 | `domain_gap_gnn/gnn_provenance.py` | IMPLEMENTED | OFFLINE_VERIFIED | Live training |
| RQ5 | `tools/run_generalization_experiments.py` | PARTIALLY_COMPLETE | NOT_RUN | 3 commits + live eval |

---

## Classification

| RQ | Classification | Reason |
|----|----------------|--------|
| RQ1 | OFFLINE_VERIFIED | Tooling passes offline regressions; receipt defects A-I need fix |
| RQ2 | IMPLEMENTED | Tooling complete; no live measurements |
| RQ3 | OFFLINE_VERIFIED | Tooling complete; manifest verifier needs fix |
| RQ4 | OFFLINE_VERIFIED | Tooling complete; no live measurements |
| RQ5 | IMPLEMENTED | 2/5 commits done; tooling partial; 3 commits needed |

**Note**: SCIENTIFICALLY_ADMITTED requires actual valid measurements under official protocol. Not claimed for any RQ in V22.