# CODEX C9 (HIGH) — Gate/checker correctness sweep (measurement bugs + positive/negative controls)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: `./.venv/Scripts/python.exe` · UP_DISABLE_CARLA=1
Rules: TDD (RED→GREEN); full-suite green; **EXPLICIT-PATHSPEC commit**. Model: Codex 5.x high.
**Coordinate with C6:** C6 owns `check_geometric_continuity`. Do NOT modify it here — this is the REST of the measurement bugs. Independent of C7/C8.

## Problem — a measurement-bug epidemic: acceptance gates don't measure what they claim
The C0 audit found the map is often much better than the gates report, because several checkers are wrong. Unreliable gates mean pinning decisions rest on noise. Confirmed instances (all on the completed C0 candidate):

1. **`diagnostics/elevation_summary.py::summarize_elevation` returns null min/max** on a map that demonstrably carries **32297 real `<elevation>` records (361.85–408.67 m)**. It silently reports "no elevation," which false-fails elevation gates. (Its `max_abs_grade_estimate` was non-null while min/max were null — internally inconsistent.)
2. **`08H full_map_metrics.elevation_continuity` measures nothing**: emits `{"max_gradient":0.0,"variance":0.0,"num_segments":0}` on a sloped map — a dead sub-metric that always "passes."
3. **`check_elevation_continuity`** reports 977 z-seam issues concentrated on the SAME predecessor/junction-connector links that C6 showed are contactPoint/link-direction artifacts in the geometric checker. Audit whether it shares the blind spot (endpoint selection + `contactPoint` + junction lane-offset) and correct/classify accordingly.
4. **Length-invariant (G19) tolerance is inconsistent**: the ad-hoc C0 gate reported `issue_count=0` using a loose tolerance while the certifier (`run_n_certify._length_invariant_evidence`, tol 1e-9) reports **798**. All length-invariant reporting must use ONE documented tolerance (the certifier's), so a "0" can never hide sub-1e-6 violations.
5. **Systemic:** most `check_*continuity` / quality gates lack a **negative control**, so a gate that silently passes everything looks identical to a healthy map.

## Steps (TDD)
1. **`summarize_elevation`**: RED test on a fixture with real `<elevationProfile><elevation a=...>` records → current returns null; fix to parse the `a` coefficients (and evaluate the cubic if needed) → returns correct min/max/span. Add a flat-map fixture (min≈max) and an empty fixture (null) as controls.
2. **`08H` elevation_continuity sub-metric**: RED on a sloped fixture → current `num_segments==0`; fix to actually sample consecutive elevation segments (or delete the dead metric and stop reporting a false pass). Control: flat map → gradient≈0; sloped map → gradient>0.
3. **`check_elevation_continuity`**: audit endpoint/contactPoint/link-direction selection (mirror C6's analysis). If it shares the blind spot, correct it and re-measure the TRUE z-seam count; classify expected junction lane-offset separately from genuine z-steps. Negative control: inject a 1 m z-step → must flag.
4. **Length-invariant tolerance**: make the C0/acceptance length checks call the certifier helper (or its exact tolerance 1e-9); document the single source of truth. Test: a fixture with a 1e-7 m excess must be reported by BOTH the acceptance gate and the certifier (no loose-tolerance escape).
5. **Positive/negative-control mandate**: for each continuity/quality gate touched, ensure a test proves it (a) passes a clean fixture AND (b) fails an injected defect. List any gate still lacking a negative control in the report.

## Boundaries
- Do NOT touch `check_geometric_continuity` (C6) or perception (C8) or enrichment (C7). Deterministic, offline; synthetic XODR fixtures only.
- Fixes must not loosen gates into passing genuine defects — every fix ships with its negative control.

## Deliverables / verdict
- Fixed `diagnostics/elevation_summary.py`, the `08H` elevation sub-metric, `check_elevation_continuity` (if defective), and the length-invariant tolerance unification.
- `tests/unit/test_gate_measurement_correctness.py` (per-gate positive + negative controls).
- `reports/post_audit_hardening/C9_GATE_CORRECTNESS.md`: for each gate — before/after result on a NAMED candidate + the negative-control proof + the true re-measured count.
- Push (explicit pathspec); local==remote; full suite green.
- **Verdict:** `GATES_CORRECTED elevation_summary=OK 08H=OK elevation_continuity_true=<n> g19_tol=unified` | PARTIAL | BLOCKED.
