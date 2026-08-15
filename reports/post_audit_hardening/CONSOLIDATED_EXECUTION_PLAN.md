# Consolidated Execution Plan — remaining work (as of 2026-08-15, HEAD 78d63027)

Dependency-ordered runbook for the remaining code + non-code work. Suite: 732 passed.

## Closed (verified green)
E1/E1B/E2 (elevated+crash-safe+loadable) · harness (parameterized+consistency) · A1 (seg labels + label_quality) ·
A2 (GNN characterized) · A3 (aggregator contract) · A4 (mock honesty) · A5 (class-weighted loss @3da86213) ·
A6 (tiling seam tests @78d63027) · C3 (OSM input guard @6354ed28) · C5 (realistic lane widths, code) ·
D1 (DEM vertical warp) · D1b (residual decomposition) · D2 (calibration semantics + B2 calib placement) ·
num_classes right-size (256->29). Adaptation A7 = queued below.

## THE PENDING DECISION (Phase 1 gate — yours/advisor)
C0/C1 evidence (`C0_C1_AUTO_MAP_OF_RECORD`, @2ae70b17) = **PARTIAL_VERIFIED_RETROFIT_NOT_PINNED**.
A width-faithful candidate (`ingolstadt_perception_drivable_width_faithful.xodr`) is VERIFIED (realistic widths,
real elevation 360.8-412.9m, G19=0, loadable) but was produced by a **C5 retrofit** of the E2 candidate, NOT a
clean regeneration. Codex correctly WITHHELD pinning (strict C0 = clean governed regen from tracked code + inputs).

**Decision required:**
- **(A) Clean regeneration (gold standard):** obtain the valid Ingolstadt OSM (absent from branch), run C0 clean,
  pin THAT as map-of-record. Fully reproducible provenance. → do this if OSM is obtainable.
- **(B) Approve the verified retrofit as map-of-record:** pragmatic; usable NOW; but the thesis MUST document
  retrofit-provenance as a reproducibility limitation ("final auto map = fixes retrofitted onto an earlier
  candidate, not a single clean pipeline run").
Recommendation: **(A) if the OSM can be obtained** — provenance is a thesis-defensibility issue. (B) only as a
documented fallback. Either way, one map is pinned by digest before anything downstream uses it.

## Phase order

```
PHASE 1 — Pin the auto map of record       [DECISION above; blocks all structural + cook]
  (A) obtain OSM -> C0 clean regen -> C1 pin   OR   (B) approve retrofit + document provenance -> C1 pin
  ↳ GATE: exactly ONE auto map pinned by sha256; realistic widths + real elevation + G19=0 + preflight=0

PHASE 2 — Manual side to parity            [needs the manual Grid map]
  C2  manual map onto branch -> G19/preflight -> crash-safe repair if defective (human review)
  B3  content-addressed registry pins BOTH maps (fix Grid0821/0828 name<->content drift)
  ↳ GATE: auto(C1) + manual(C2) both pinned + loadable

PHASE 3 — Structural result + independent studies (parallel)
  B4  auto-vs-manual structural gap on the pinned pair -> RQ1 number     [needs C1 + B3]
  B1  determinism/natural-DR verdict — NOTE: my trace shows OSM->XODR conversion is DETERMINISTIC
      ("CONVERSION_DETERMINISTIC"); so natural DR ~absent -> thesis needs EXPLICIT DR (realism_augmentor).
      B1 formalizes this with the N-run study.
  A7  adaptation methods (CORAL characterize; MMD is mean-matching-baseline -> rename or implement kernel-MMD)
  C4  provenance record (fold into whichever Phase-1 path)   ‖   D3 transform-applied-exactly-once verifier
  ↳ B1/A7/C4/D3 are independent; run anytime

PHASE 4 — Perceptual pipeline              [code scaffold now; execution = toolchain + runtime]
  D4  Unreal cook scaffold (UE4.26 project + FBX import + XODR associate + semantic/collision + cook + package)
      — CODE now (parameterized, dry-run validated); EXECUTION needs UE + human operator.
  D5  fair-capture protocol config (SAME rig + SAME assets for BOTH maps; prevents asset-vs-structure confound)
  ↳ then NON-CODE: cook both maps -> capture (D5 rig) -> train (class-weighted; epochs/splits/controls = methodology)
     -> eval (mIoU on labeled sim; entropy/CORAL/Frechet on unlabeled real, reported as SHIFT not ACCURACY)
```

## Model routing
C0/C1, C2, B3, B4, D4 = Codex 5.x high (+ human review for map-touching C0/C1/C2). C3(done)/C4/B1/D3/D5/A7 = mid.

## Non-code gates (decisive — no prompt closes these)
1. Real Ingolstadt dataset path (R8). 2. Unreal cook of BOTH maps. 3. Experiment design (splits/epochs/controls).
4. Claim boundary: unlabeled real eval measures domain SHIFT, not ACCURACY.

## The one blocker only you can clear now
Phase 1 needs the **OSM path** (for clean regen) and Phase 2 needs the **manual-map path**. These two inputs gate
the entire structural critical path; without them, C0 clean-regen is BLOCKED_NEED_OSM_INPUT and only the
retrofit (B) fallback is available.
