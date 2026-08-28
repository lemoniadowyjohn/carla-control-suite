# Master remediation plan — path to a fully drivable, perception-ready, reproducible map (2026-08-16)

Supersedes CONSOLIDATED_EXECUTION_PLAN.md. Ties together every open issue from the whole-pipeline audit
(`PIPELINE_CRITICAL_AUDIT_20260816.md`) into a dependency-ordered, step-by-step plan.

## The core lesson driving the ordering
Two failure classes, and telling them apart is the whole game:
- **Class A — the GATE is wrong** (continuity 27k→~0, tiles 407→~0, elevation_summary null, 08H metric dead, G19 tolerance). Fix the gates FIRST or every downstream decision rests on noise.
- **Class B — the ARTIFACT is wrong** (perception labels, 1 building, signals-as-props, islands, 1 cm lane, genuine z-seams, unpinned inputs). Fix after the gates can be trusted.

## Prompt inventory
| ID | Title | Sev | Class | Depends on | Parallel? |
|----|-------|-----|-------|-----------|-----------|
| C6 | Geometric-continuity checker correctness (+tiles) | HIGH | A | — | running |
| C7 | Enrichment completeness (buildings + functional signals) | HIGH | B | — | ✓ |
| C8 | Perception dataset correctness (raw labels + layout) | **SEV-1** | B | — | ✓ |
| C9 | Gate/checker correctness sweep (elev summary, 08H, elev-continuity, G19 tol, controls) | HIGH | A | coord w/ C6 | ✓ |
| C10 | Map hygiene (islands, 1 cm lane, genuine z-seams) | MED | B | z-seams ← C9 | islands now |
| C11 | Reproducibility & governance (pin inputs, preanchor default, decouple STRICT, canonical cmd) | HIGH | — | canonical ← C6–C10 | pinning now |

Held (not drafted yet, gated): **residual geometry repair** (the C6 >5 m tail) ← C6 re-measure; **live-CARLA load test** ← C6(+C7); **C12 explicit-DR** (methodology).

---

## PHASE 0 — Reconcile the dangling SUMO fix (Codex decides; DECISION: HOLD)
- **Status:** the uncommitted `M ultimate_pipeline/topology/sumo_repair.py` (`--offset.disable-normalization`, forces GLOBAL coords) + `?? tests/unit/test_sumo_repair_frame_preservation.py` (asserts global-frame preservation) OVERLAP Codex's committed `1be9b767` (honor-header-offset, keeps LOCAL coords). Two solutions to the same stage-05 DEM-CRS problem.
- **User decision (2026-08-16): HOLD** — do not revert; **Codex reconciles**. Codex must pick ONE and drop the other:
  - Recommended: keep Codex's `1be9b767` (LOCAL coords → better CARLA float32 precision), and **drop** the SUMO `--offset.disable-normalization` change + its test.
  - If instead the SUMO fix is adopted: `1be9b767`'s offset-honoring becomes a no-op and the map ships GLOBAL coords (flag the float32 precision risk at live-CARLA).
- **Conflict to resolve before commit:** the held test asserts GLOBAL-frame preservation, which contradicts `1be9b767`'s LOCAL design — running the suite with both may fail or encode conflicting behavior.
- GATE: exactly ONE CRS approach active; the other (code + test) removed; suite green on HEAD.

## PHASE 1 — Correctness: make the gates trustworthy (C6, C7, C8, C9 — all parallel)
Step 1. **C6** — fix `check_geometric_continuity` (link_kind + contactPoint + junction lane-offset); re-baseline `map_acceptance`. Report `CORRECTED_TRUE_COUNT`. This also clears the 407/531 tile failures.
Step 2. **C9** — fix `summarize_elevation`, the dead `08H` elevation metric, audit `check_elevation_continuity`, unify G19 tolerance to 1e-9, add positive/negative controls to every gate touched. (Boundary: never touch `check_geometric_continuity` — that's C6.)
Step 3. **C7** — pin a building source + wire offline (fail-closed on empty); emit functional `<signal>`s; reconcile the signal count.
Step 4. **C8** — unify capture → `rgb/`+`semseg_raw/` with raw class ids (no palette label); handle `Any=255`; real/explicit detection labels; capture→train round-trip test.
- GATE 1: all acceptance gates have a passing positive control AND a failing negative control; `map_acceptance` reflects reality; perception round-trip test green.

## PHASE 2 — Map completion (after C6 + C9 re-measure)
Step 5. **Residual geometry repair** — draft once C6 gives `CORRECTED_TRUE_COUNT`; scope to exactly the genuine >5 m links (expected a handful, not 27k). TDD; negative control.
Step 6. **C10** — quarantine islands (~35 roads), repair the 1 cm lane; after C9, repair the genuine z-seams.
- GATE 2: the candidate PASSES the corrected `map_acceptance` (continuity, lane successors, elevation, connectivity) with real numbers.

## PHASE 3 — Reproducibility (C11; pinning parts can begin in Phase 1)
Step 7. Fix the **preanchor default** (recommend default False).
Step 8. **Pin all inputs** (roads OSM ✓ + DEM + building source) → `source/INPUTS_MANIFEST.json` + build-time digest guard (fail-closed on mismatch).
Step 9. **Decouple** generation from the manual map (`manual_deferred` CRS record; hard-fail behind `REQUIRE_MANUAL_FOR_CRS`).
Step 10. **Canonical committed regen entrypoint** (`scripts/regen_map_of_record.py`) encoding the corrected config; refuses to emit unless acceptance passes. PROJ env guard.
- GATE 3: ONE committed command reproduces the map-of-record deterministically from pinned inputs.

## PHASE 4 — Pin + first real drivability verification
Step 11. Run the canonical command → **C1 pin** the candidate by sha256 (governed, human review).
Step 12. **Live-CARLA load test** (draft prompt): load the pinned XODR in a running CARLA server, spawn ego, drive a route, confirm no crash + float32 precision acceptable (global vs local coords). First real "drivable" evidence.
- GATE 4: pinned, reproducible, and **verified drivable in CARLA**.

## PHASE 5 — Perception readiness (after C8 + Phase 4)
Step 13. **Cook** both maps (D4, UE4.26 + operator): FBX import + XODR associate + **semantic tags per mesh** + collision + package.
Step 14. **Fair capture** (D5): same rig (K_undistortion cams, vTl LiDAR) + same assets on BOTH maps; **confirm LiDAR capture exists** in the canonical path.
Step 15. **Explicit DR** (C12, methodology): wire `realism_augmentor` — natural DR is absent (deterministic conversion), so DR must be explicit and documented.
Step 16. **Train** (class-weighted) + **eval**: mIoU on labeled sim; entropy/CORAL/Fréchet on unlabeled real reported as **domain SHIFT, not accuracy**.
- GATE 5: non-empty correct labels; trained model; eval within the stated claim boundary.

## PHASE 6 — Manual side + the RQ1 number
Step 17. **C2** manual Grid0828 onto branch → corrected acceptance (crash-safe repair if needed, human review).
Step 18. **B3** content-addressed registry pins BOTH maps (fix Grid0821/0828 name↔content drift).
Step 19. **B4** auto-vs-manual structural gap on the pinned pair → **RQ1** number. (Carry the construction-artifact caveats: elevation-encoding + building-density differences are method artifacts, not pure domain gap.)
- GATE 6: RQ1 structural gap quantified on a pinned, reproducible, drivable pair.

## Non-code gates (only the human/operator can clear)
1. Real Ingolstadt dataset path (R8). 2. UE cook of both maps. 3. Experiment design (splits/epochs/controls). 4. Claim boundary (shift ≠ accuracy). 5. Explicit-DR decision.

## Critical path (shortest route to each milestone)
```
C6+C9  → gates trustworthy
   → C10 + residual repair            → map PASSES real acceptance   (Phase 2 gate)
   → C11                              → reproducible from one command (Phase 3 gate)
   → C1 pin + live-CARLA load         → DRIVABLE, pinned, reproducible (Phase 4 gate)
C8 (parallel) + cook + fair capture + explicit DR + train/eval → PERCEPTION-READY (Phase 5 gate)
C2 + B3 + B4 → RQ1 number (Phase 6 gate)
```
