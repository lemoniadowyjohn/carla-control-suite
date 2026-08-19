# Phase 6 + non-code gate status (2026-08-17)

## C2 — manual Grid0828 onto branch
**BLOCKED.** `manual_maps/Grid0828.xodr` (and `Grid0821.xodr`,
`manual_ingolstadt_grid0828.xodr`) do not exist anywhere on this machine.
`manual_refs.resolve_manual_town()` fallback paths
(`_pair_capture_manual/`, `_perception_runs/`, `artifacts/.../strict_evidence/`)
are also empty. The operator must restore the manual XODR files before the
corrected acceptance can be run on the manual side or the pair pinned.

## B3 — content-addressed registry pins
**PARTIAL.** Ledger created (`reports/post_audit_hardening/B3_REGISTRY_20260817/map_registry_ledger.json`):
the auto candidate is pinned (sha256 `83418373f1996c6707293c5571b2798f9cf7c06a5b243e8d049848efdc73080e`,
acceptance PASS + live-CARLA PASS); Grid0821/Grid0828 recorded as ABSENT_ON_DISK.
The name↔content drift the audit found (Grid0821/0828 confusion) is addressed
by design: the ledger binds sha256, not names, and requires verification before
any acceptance call.

## B4 — auto-vs-manual structural gap → RQ1
**BLOCKED on the manual map** (see C2). Measurement plan ready:
`run_structural_domain_gap_batch.py` / `exp_domain_gap_manual_vs_auto.py`
against the pinned auto candidate. Construction-artifact caveats to carry:
elevation-encoding + building-density differences are method artifacts.

---

## Non-code gates

### R8 — real Ingolstadt dataset path
**Human/operator decision.** The thesis uses CARLA-generated captures with
explicit DR; a real-world Ingolstadt dataset is NOT present on this machine.
Recommendation: keep the RQ1 structural-gap claim (auto vs manual CARLA maps)
as the primary evidence, and treat any real-data comparison as future work.

### Experiment design (splits/epochs/controls)
Draft skeleton (to be finalized by the operator):
- Train: auto capture (or paired auto+manual) → segmentation model (U-Net
  class-weighted per `class_weights.py`).
- Eval A (labeled sim): mIoU on held-out labeled frames; classes per
  `carla_classes.py`; raw class ids from `semseg_raw/`.
- Eval B (real/unlabeled): entropy / CORAL / Fréchet reported as domain
  SHIFT metrics — never as accuracy (claim boundary).
- Controls: same rig (K_undistortion cams, vTl LiDAR) on BOTH maps; identical
  capture recipe (`record_route_fixed.py --seg-converter raw`); fixed seeds
  for `RealismAugmentor` (now wired in `dataset_generator.py`, C12).
- Determinism: `check_determinism.py` + stage digests.

### Claim boundary
1. mIoU numbers apply ONLY to labeled-sim evaluation.
2. Real-data numbers are shift metrics; a low value does not imply accuracy.
3. Structural gap (RQ1) is auto-vs-manual CARLA maps — not auto-vs-reality.

### Explicit-DR decision (C12)
**DECISION: explicit DR, wired.** The canonical `RealismAugmentor`
(`ultimate_pipeline/augmentation/realism_augmentor.py`) is now importable from
the capture path (`dataset_generator.py` — was silently None via the stale
`augmentation.realism` import). `perception_runner_local_aug.py` already used
it. DR is therefore explicit and documented; there is no hidden "natural DR".
Tests: `tests/unit/test_c12_explicit_dr_wiring.py` (3 tests, green).

### Operator checklist (things only the human can do)
1. Review `C1_LIVE_CARLA_LOAD_20260817/probe_screenshot.png` (map render).
2. Decide C1 pin: interim geometry pin now, or wait for enriched regen.
3. Restore manual Grid0821/0828 XODRs.
4. Install SUMO (or run regen on a machine with SUMO) for the canonical regen.
