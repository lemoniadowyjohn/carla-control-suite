# CODEX C6 (HIGH) — Geometric-continuity checker correctness (contactPoint + link-direction + junction lane-offset)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: `./.venv/Scripts/python.exe` · UP_DISABLE_CARLA=1
Rules: TDD (RED→GREEN, watch it fail first); full-suite green; **EXPLICIT-PATHSPEC commit** (`git commit -m "..." -- <files>`). Model: Codex 5.x high.

## Problem — the #1 C0 blocker is largely a CHECKER artifact, not a broken map
C0 acceptance fails closed on `geometric_continuity` with **27193 offending segments** (`map_acceptance.py`, gate `geometric_continuity_gate.json`). A read-only root-cause trace shows the map geometry is fine and the count is inflated by defects in
`ultimate_pipeline/quality/check_geometric_continuity.py::check_geometric_continuity`:

- **Intra-road planView continuity is PERFECT** — `check_planview_internal_seams()` returns **0 seams**. Every road's own geometry is continuous end-to-end.
- Failures are 100% at **road-to-road links**; **92% of offenders are junction connecting roads** (`road.junction != "-1"`).
- The checker (≈ lines 665–673) ALWAYS compares road A's **end** pose (`_pose_at_s(geoms_a, len_a)`) to road B's **start** pose (`_pose_at_s(geoms_b, 0.0)`), **ignoring `link_kind` and `contactPoint`** — although `contactPoint` is present on **100% of the 45206** road-to-road links.
  - For **predecessor** links it must compare A's **start** (s=0), not A's end.
  - It must honor **`contactPoint`**: `"start"` → B at s=0, `"end"` → B at s=road_length_B.
  - **End-contact** connections are **anti-parallel by design** (headings ~π apart); the checker's flat `dhdg > 0.01` flags them as false discontinuities (this is the entire "reversed~π" cluster).
- Junction connecting roads meet the incoming road at a **LANE boundary**, offset from the reference line by ~lane_width. Reference-line coincidence is the WRONG continuity measure for them — CARLA routes junctions via `<junction><connection><laneLink>`, not reference-line coincidence.

### Evidence (Claude trace; re-verify on your candidate `83418373` or any C0 candidate)
| measure | value |
|---|---|
| naive checker (A.end ↔ B.start, ignores contactPoint) | ~**26701** "bad" (≈ the 27193 gate count) |
| corrected (honor link_kind + contactPoint) | **8231** |
| corrected residual dxy | concentrated at **exactly 3.5 m** (p50 = p95 = 3.5 m = one lane width) |
| corrected residual > 5 m | only **231** |
| worst naive case (4666 m) after correction | **< 14 m** |
| intra-road planView seams | **0** |

Interpretation: ~18.5k of 27k are pure endpoint/contactPoint mis-selection; the remaining ~8k are the expected junction **lane-offset** (3.5 m). True suspicious residual is at most ~231 links.

## Steps (TDD)
1. **Characterize (RED)** with tiny synthetic OpenDRIVE fixtures:
   - predecessor + `contactPoint="end"`: A.start meets B.end, headings anti-parallel → **current checker FLAGS (RED)**; corrected must PASS.
   - successor + `contactPoint="start"`: co-linear → passes.
   - **negative control**: endpoints 5 m apart → must STILL fail (both checkers).
2. **Fix `check_geometric_continuity`**:
   - A contact end by `link_kind` (predecessor → s=0, successor → s=road_length).
   - B contact end by `contactPoint` (start → s=0, end → s=road_length_B).
   - Position compare as today; **heading compare modulo the expected relation** (co-directional for start-contact, anti-parallel/π for end-contact).
3. **Junction connecting roads** (`junction != "-1"`): reference-line continuity is not the correct measure. Implement ONE (document the choice):
   (a) compare at the **lane boundary** (use `<laneLink>` + lane widths); OR
   (b) **exclude** junction-internal road-to-road reference-line checks; assert junction connection topology + lane continuity instead; OR
   (c) keep reference-line but apply a **lane-offset-aware tolerance** and CLASSIFY (never hard-fail on the expected lane offset).
4. **Re-measure** the true continuity failure count on a C0 candidate. Triage the genuine residual (~231 links > 5 m): real defect vs multi-lane offset. Only real defects get a geometry repair (separate task — do NOT attempt here).
5. **Re-baseline `map_acceptance.py`** geometric_continuity gate against the corrected metric so the gate reflects reality (it currently fails closed on ~27k false positives).

## Boundaries
- Fix the CHECKER + acceptance wiring FIRST. Do **NOT** "repair" 27193 geometries — they are overwhelmingly not broken. Deterministic, offline (no CARLA/dataset).
- Must NOT weaken the checker into passing genuine gaps: the 5 m negative-control fixture must still fail.
- If the corrected true count is ~0 after junction handling, **the continuity blocker is CLEARED** — state that explicitly; C0 then advances to signals-enrichment + live-CARLA load.

## Deliverables / verdict
- Fixed `ultimate_pipeline/quality/check_geometric_continuity.py`
- `tests/unit/test_geometric_continuity_contactpoint.py` (characterization + negative control)
- `reports/post_audit_hardening/C6_CONTINUITY_CHECKER.md` — naive vs corrected counts on a NAMED candidate + the junction-handling decision
- `map_acceptance.py` re-baselined + `tests/unit/test_map_acceptance.py` updated
- Push (explicit pathspec); local==remote; full suite green.
- **Verdict:** `CONTINUITY_CHECKER_CORRECTED_TRUE_COUNT=<n>` | PARTIAL | BLOCKED. If `<n>` is ~0, add `C0_CONTINUITY_UNBLOCKED`.

## Reproduce the trace (Claude scratch logic, for reference)
- Per-road-link corrected continuity: for each `<link>` (elementType="road"), take A's pose at (predecessor? s=0 : s=length) and B's pose at (contactPoint=="end"? s=length_B : s=0); flag dxy>0.05. Intra-road: `check_planview_internal_seams(path, eps_xy=0.2)`.
