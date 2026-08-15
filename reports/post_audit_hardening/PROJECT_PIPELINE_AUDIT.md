# Project Pipeline Audit — pipeline / domain-gap / GNN / CARLA / perception

Date: 2026-08-15 · Auditor: Claude Opus 4.8 · Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803
Method: read-only survey (subsystem LOC, test coverage, red-flag markers, targeted source reads). No code changed.

## Headline: test-coverage inversion
Heavy rigor sits on the **certification/quality gates**; the **substantive pipeline** (data generation +
analysis) is thinly tested. A perfectly-certified map feeding a label-less dataset into an untested GNN
produces research conclusions no gate checks.

| Subsystem | LOC | test files | note |
|---|--:|--:|---|
| domain_gap_gnn | 1506 | **0** | real torch (GNN encoder, collapse check, latent gap) — unverified |
| domain_gap | 8684 | 2 | orphaned from pipeline_stages/cli (standalone run_full_domain_gap.py) |
| perception | 8310 | 1 | **real defect: empty labels (below)** |
| carla_tools | 10362 | 1 | mock fallbacks that can mask failure |
| enrichment | 8117 | 1 | thin |
| tiling | 1885 | 0 | zero |
| lane | — | 0 | zero |
| geometry | 2254 | 4 | ok-ish |
| quality (gates) | 10223 | many | well-tested ✅ |

Red-flag markers (mock/stub/TODO/FIXME/placeholder), non-test: perception=12, carla_tools=10, domain_gap=5,
enrichment=3, geometry=2; domain_gap_gnn/tiling/topology=0.

## Real defects (not coverage debt)

### D1 — Perception dataset generators write EMPTY labels  🔴 HIGH
Self-documented in-code:
- `perception/segmentation_dataset_generator_queues.py:15` — "dataset generators write YOLO label
  placeholders (empty). That blocks supervised training."
- `perception/perception_runner_local_aug.py:21` — "Writes YOLO label placeholders (empty)".
- `perception/dataset_generator.py:408` — "# Labels placeholder".
→ Perception training data has no labels; the core perception output is non-functional. (Note: the
`record_route.py` "placeholder" hits are the OPPOSITE — validation that *rejects* placeholder paths; keep.)
Fix: prompt **A1**.

### D2 — Analysis engine (domain_gap + domain_gap_gnn) ~unverified  🔴 HIGH
~10k LOC of the actual sim-to-real research (gap metrics + GNN) with 0–2 tests. This is where thesis claims
originate → untested = overclaiming risk (see project RQ-status discipline). `domain_gap_gnn` is genuine torch
(`collapse_check`, `graph_builder`, `map_encoder`, `latent_gap_metrics`), not a stub — but nothing pins it.
Fix: prompts **A2** (GNN) + **A3** (domain_gap metrics).

## Lesser findings
- `carla_tools/fixed_traffic_manager.py`: returns a silent `MockTM` when CARLA is absent (no-op spawns) →
  mock results can be mistaken for real. `sensor_rig.py:147`: rotation extraction is a placeholder
  (calibration precision). Fix: prompt **A4**.
- `main_pipeline.py`: the historical mock harness (`mock_data_generation`/`mock_domain_analysis`) shows no mock
  markers now — appears cleaned; re-audit if reused.
- Map-quality chain (separate program): E1 produced an elevated+crash-safe candidate (`7709d5c9`), but its
  loadability preflight FAILs (24 errors + 1560 elev_jumps) → prompt E2 already queued.

## Targeted prompts (this audit)
| Prompt | Fixes | Model | Independent? |
|---|---|---|---|
| A1_perception_labels | D1 (empty labels) | Codex 5.x high | yes |
| A2_domain_gap_gnn_tests | D2 (GNN unverified) | Codex 5.x high (torch) | yes |
| A3_domain_gap_metric_tests | D2 (metrics unverified) | Codex 5.x mid/high | yes |
| A4_carla_tools_honesty | mock fallbacks / calib | Codex 5.x mid | yes |
All four are in different subsystems → runnable in parallel; none touch map artifacts or certifier gates.
A1 ultimately needs a live CARLA capture to validate end-to-end.
