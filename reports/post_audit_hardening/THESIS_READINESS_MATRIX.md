# Thesis Readiness Matrix (R1–R8)

Date: 2026-08-15 · Claude Opus 4.8 · Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803
Source-of-truth completeness assessment for the thesis: *domain gap between OSM-auto 3D maps and a manually
modeled 3D map of Ingolstadt in CARLA, and its effect on perception-model generalization.*

Fixed contract facts (verified): GPS bbox lat[48.74935649548228, 48.77444431571603],
lon[11.422268084715878, 11.47882091528412] matches `agent_sync.yaml` exactly. Sensor rules
(use_K_undistortion; ignore K,D; cTv = vehicle→camera; vTl = LiDAR→vehicle) match `agent_sync.yaml` `sensor_rig`.

## R1–R8 status

| # | Requirement | Status | Evidence | Ultimate gate | Fixer |
|---|---|---|---|---|---|
| R1 | OSM→CARLA pipeline, correct GPS bbox | ⚠️ strengthen | bbox exact; 32710-road map builds | map flat+barren | codex E1/E2 |
| R2 | Same OSM→same map? / natural DR | 🔴 inconclusive | verdicts **4 DET / 4 NONDET** | conclusive N-run study | **codex B1** |
| R3 | Structural diff auto vs manual | ⚠️ strengthen | `manual_vs_auto_comparator.py`, `exp_domain_gap_manual_vs_auto.py`, alignment tested | manual-map provenance; not yet run | **codex B3+B4** |
| R4 | Perceptual diff + perception generalization | 🔴 BROKEN | perception writes EMPTY labels; GNN untested | labels **+ cook both maps** | **codex A1/A2** + toolchain |
| R5 | Generate many maps, analyze natural DR | ⚠️ strengthen | `exp_natural_domain_randomization.py`, `realism_augmentor.py` | tied to B1 verdict | **codex B1** |
| R6 | Objects on map + visual check | 🔴 blocked | 66 objects; no cooked map | Unreal cook | toolchain (human) |
| R7 | Sensors from calib_data.json on ego | ⚠️ strengthen | rich rig + contract test; calib rules correct | `calib_data.json` not in canonical tree | **codex B2** |
| R8 | Real-world unlabeled generalization | 🔴 blocked | `eval_real_unlabeled.py` needs `--real-dir` | **real Ingolstadt dataset MISSING** | **you (data)** |

## Blockers by fixer

- **Codex-fixable (queued):** A1 (labels, CRITICAL), A2/A3 (verify gap engine + GNN), A4 (mock honesty),
  B1 (determinism verdict), B2 (calib placement), B3 (manual-map registry), B4 (run auto-vs-manual),
  E1✓/E2 (map quality). Structural arc R1/R2/R3/R5/R7 is completable in code.
- **DATA — NOT codex-fixable (yours):** real-world unlabeled Ingolstadt imagery/LiDAR (R8). No prompt fixes this.
- **TOOLCHAIN — blocked (UE + human):** cook BOTH the auto AND manual maps for perceptual capture (R4 perceptual, R6);
  live CARLA run for capture (server launches OK).
- **Methodology:** conclude the natural-DR question (B1); pin a fair capture protocol (same assets + same
  `calib_data.json` rig for both maps) or the perceptual gap is confounded.

## Critical path
The analysis toolkit (alignment, perceptual gap, CORAL/MMD adaptation, GNN, natural-DR experiment) is largely
built. The three things between "code ready" and "thesis tasks accomplished" are:
1. **A1** — real perception labels (unblocks R4/R8 training). *A prompt.*
2. **Real Ingolstadt dataset** — unblocks R8. *Data acquisition (yours).*
3. **Unreal cook of both maps** — unblocks perceptual R4/R6. *Toolchain + human.*

Prompts: `A1–A4_*.md`, `B1–B4_*.md`, `OPENCODE_EXECUTION_PLAN.md`, `LIVE_RUN_PROTOCOL_MAP.md` (this dir).
