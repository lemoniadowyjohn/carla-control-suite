# Project Pipeline Audit — pipeline / domain-gap / GNN / CARLA / perception

Date: 2026-08-15 · Auditor: Claude Opus 4.8 · Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803
Method: initial read-only survey (subsystem LOC, test coverage, red-flag markers, targeted source reads), then
post-A1 status refresh after the semantic-label path was characterized.

## Headline: test-coverage inversion
Heavy rigor sits on the **certification/quality gates**; the **substantive pipeline** (data generation +
analysis) is thinly tested. A perfectly-certified map feeding weak or unverified perception/domain-gap evidence
into an untested GNN produces research conclusions no gate checks.

| Subsystem | LOC | test files | note |
|---|--:|--:|---|
| domain_gap_gnn | 1506 | **0** | real torch (GNN encoder, collapse check, latent gap) — unverified |
| domain_gap | 8684 | 2 | orphaned from pipeline_stages/cli (standalone run_full_domain_gap.py) |
| perception | 8310 | 1 | YOLO placeholders; semantic labels characterized by A1 |
| carla_tools | 10362 | 1 | mock fallbacks that can mask failure |
| enrichment | 8117 | 1 | thin |
| tiling | 1885 | 0 | zero |
| lane | — | 0 | zero |
| geometry | 2254 | 4 | ok-ish |
| quality (gates) | 10223 | many | well-tested ✅ |

Red-flag markers (mock/stub/TODO/FIXME/placeholder), non-test: perception=12, carla_tools=10, domain_gap=5,
enrichment=3, geometry=2; domain_gap_gnn/tiling/topology=0.

## Real defects (not coverage debt)

### D1 — Perception label premise corrected by A1
The original audit over-scoped the empty-label finding. Empty `.txt` placeholders remain in the YOLO/detection
track, but the thesis segmentation path writes real `semseg_raw/<camera>/*.png` class-id masks and the FCN training
path consumes those masks. A1 added offline label-quality checks and characterized the CARLA BGRA R-channel raw-id
extraction. Remaining work is live-capture wiring for degenerate-frame accounting, plus a decision on whether to
implement or delete the unused YOLO/detection path.

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
- Map-quality chain (separate program): E1 produced an elevated+crash-safe candidate (`7709d5c9`); E1B repaired
  the zero-length connector loadability errors (`90f1e4f7`); E2 produced the current offline-loadable elevated
  candidate (`352c9003`) with G19=0 and preflight errors=0. Live CARLA proof remains separate.

## Targeted prompts (this audit)
| Prompt | Fixes | Model | Independent? |
|---|---|---|---|
| A1_perception_labels | D1 corrected; semantic label quality guard | Codex 5.x high | yes |
| A2_domain_gap_gnn_tests | D2 (GNN unverified) | Codex 5.x high (torch) | yes |
| A3_domain_gap_metric_tests | D2 (metrics unverified) | Codex 5.x mid/high | yes |
| A4_carla_tools_honesty | mock fallbacks / calib | Codex 5.x mid | yes |
A2/A3/A4 remain in different subsystems and are runnable in parallel; none touch map artifacts or certifier gates.
A1 semantic-mask characterization is offline-green; capture-loop guard wiring still needs a live CARLA capture.
