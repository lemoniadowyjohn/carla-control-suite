# CODEX C6 (HIGH) — Geometric-continuity checker correctness: verdict + evidence

Repo: `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main`
Worktree branch: `fix/c6-geometric-continuity-checker` (branched from `fix/post-audit-phase-e-junctions-roundabouts-20260803` @ `95a816ea`)
Interp: `.venv/Scripts/python.exe` (absolute path) · `UP_DISABLE_CARLA=1`

## Verdict

```
CONTINUITY_CHECKER_CORRECTED_TRUE_COUNT=0
C0_CONTINUITY_UNBLOCKED
```

The `geometric_continuity` gate's true (non-junction-connector, hard-fail) offending-segment
count on the named C0 candidate is **0**. The blocker described in the original problem
statement (27193 offending segments) is a checker artifact, not a broken map. The checker fix,
the junction-handling decision, and the acceptance-gate wiring were already present in this
worktree's base branch (commit `a67824966e6ee249e90758d46821aa3dd30ae7f0`, "fix(pipeline):
reduce C0 offline blockers"). This task's contribution is: (1) an independent, spec-exact
characterization/negative-control test suite that reproduces and pins the RED→GREEN evidence,
(2) a fresh naive-vs-corrected measurement + triage on the named candidate, (3) an explicit
map_acceptance re-baseline test proving the aggregator now accepts a map whose only continuity
"issues" are junction-connector lane offsets, and (4) this report.

## Named candidate measured

- Path: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_clean_regen_crashsafe_20260815.xodr`
- sha256: `83418373f1996c6707293c5571b2798f9cf7c06a5b243e8d049848efdc73080e` (verified with `sha256sum` against `reports/post_audit_hardening/C0_CLEAN_REGEN_STATUS.md`, which documents this as the C0 crash-safe repaired candidate)
- Roads: 32297 · Junctions: 3568 · Road-to-road links: 45206
- Note: this file is an intentionally-uncommitted local artifact (per `C0_CLEAN_REGEN_STATUS.md`); it was measured read-only from the sibling main-repo checkout, not copied into this worktree or committed.

## Naive vs corrected counts

| measure | value |
|---|---|
| naive checker (A.end ↔ B.start, ignores `link_kind`/`contactPoint`) — bad links | **27193** (of 45206 checked) — matches the `27193` gate count in `C0_CLEAN_REGEN_STATUS.md` and `C0_C1_AUTO_MAP_OF_RECORD.json` |
| corrected, ordinary (non-junction) road-to-road links checked | 0 |
| corrected, ordinary (non-junction) **hard-fail issues** | **0** |
| corrected, junction-connector links checked | 45206 |
| corrected, junction-connector **diagnostic** issues (`dxy > eps_xy` at a junction boundary) | 9192 |
| junction-connector issue `dxy` distribution | p50 = p95 = **3.5 m** (one lane width), max = 14.0 m |
| corrected residual `dxy > 5 m` (all junction-connector; 0 ordinary) | **231** |
| worst residual after correction | **14.0 m** (vs 4666 m worst naive-flagged case) |
| intra-road planView seams (`check_planview_internal_seams`) | 0 (unchanged; was already 0 pre-fix) |

Every road-to-road link in this candidate touches a junction-connector road (`junction != "-1"`
on one side), so the corrected checker's ordinary/hard-fail bucket is empty and the entire
27193→0 collapse is explained by (a) contactPoint/link_kind mis-selection and (b) reclassifying
junction reference-line offsets as diagnostic rather than hard-fail.

### Triage of the >5 m residual (231 links)

All 231 are junction-connector-link diagnostics, clustered exactly at integer multiples of the
3.5 m driving-lane width, with `dhdg ≈ 0` on inspected samples:

| bucket (`round(dxy / 3.5)`) | dxy | count |
|---|---|---|
| 2 | ~7.0 m | 176 |
| 3 | ~10.5 m | 52 |
| 4 | ~14.0 m | 3 |

This is the same lane-boundary-offset phenomenon as the 3.5 m modal cluster, just at
junction connectors whose connecting road attaches at the 2nd/3rd/4th driving lane instead of
the 1st. Sampled examples (`from_road`, `to_road`, `link_kind`, `contact_point`, `dxy`, `dhdg`):

```
52074 47632 successor   start 7.000 0.000
52077 49526 predecessor end   7.000 0.000
52345 47958 predecessor end   7.000 0.000
53137 51893 successor   start 7.035 0.142
53779 49570 predecessor end   7.000 0.000
```

Interpretation: none of the 231 are genuine reference-line discontinuities — they are all
explained by multi-lane junction-connector attachment offset. **True suspicious residual after
triage: 0.**

## Junction-handling decision: option (b)

Per spec step 3, the fix implements **option (b): exclude junction-internal road-to-road
reference-line checks from the hard-fail gate; report them as diagnostic evidence instead.**

Rationale:
- CARLA routes junction traffic via `<junction><connection><laneLink>` lane-topology, not
  reference-line coincidence, so reference-line offset at a junction connector boundary is not
  a defect signal for routing/collision purposes.
- Reference-line offsets at junction connectors are expected to sit at ~lane-width multiples
  from the incoming road's reference line (measured: 3.5, 7.0, 10.5, 14.0 m — all exact
  multiples of the 3.5 m driving-lane width used across this map), which is not something a
  flat `dxy` threshold can distinguish from a genuine defect without lane-topology awareness.
  A lane-offset-aware tolerance (option c) would need per-connector lane-width lookups to avoid
  either false-passing a real gap or false-failing a legitimate multi-lane offset; a full
  laneLink-based comparison (option a) is the more rigorous long-term fix but is materially
  more implementation and test surface for a checker whose job here is triage, not lane-level
  certification (that is covered separately by `check_lane_section_successors.py` /
  `check_lane_geometry_continuity.py`).
- Implemented as classification, not deletion: junction-connector links are still fully
  evaluated and reported under `junction_connector_issues` / `num_junction_connector_issues`,
  so nothing is silently dropped — they simply do not participate in `report["ok"]` /
  `num_issues`, which is what `map_acceptance.py`'s hard-fail gate consumes.

## Where the fix lives

The checker fix, negative-control-preserving semantics, and junction-connector classification
are implemented in `ultimate_pipeline/quality/check_geometric_continuity.py`
(`_normalize_contact_point`, `_endpoint_s`, `_source_endpoint_for_link`,
`_expected_heading_delta_rad`, and the `is_junction_connector_link` split inside
`check_geometric_continuity`). This logic predates this task's branch point (introduced in
commit `a67824966e6ee249e90758d46821aa3dd30ae7f0`, part of the inherited base
`fix/post-audit-phase-e-junctions-roundabouts-20260803` @ `95a816ea`) — this task did not need
to re-implement it, only verify it against a fresh named-candidate measurement and add
spec-exact characterization coverage.

## Negative control (must still fail)

Both the naive and corrected checker still flag a genuine 5 m gap
(`tests/unit/test_geometric_continuity_contactpoint.py::TestNaiveCheckerIsWrong::test_naive_flags_negative_control_5m_gap`
and `::TestCorrectedCheckerHonorsLinkKindAndContactPoint::test_negative_control_5m_gap_still_fails`).
Honoring `contactPoint`/`link_kind` did not weaken the checker: it only corrects which two poses
are compared and what heading relation is expected, never whether a genuine positional/heading
break is reported.

## map_acceptance.py re-baseline

`ultimate_pipeline/quality/map_acceptance.py`'s `_determine_report_ok()` reads
`geometric_continuity` report's top-level `"ok"` field, which is exactly
`len(issues) == 0` from the corrected checker (junction-connector issues excluded). The
gate-wiring path (`QualityGateManager.gate_geometric_continuity` →
`main_pipeline._run_geometric_continuity_gate` → `geometric_continuity_gate.json` →
`build_map_acceptance`) was already consistent with the corrected metric; no code change to
`map_acceptance.py` itself was required. Added
`tests/unit/test_map_acceptance.py::test_map_acceptance_accepts_when_only_junction_connector_lane_offsets_present`
to prove this end-to-end: a synthetic map with only a 3.5 m junction-connector lane offset now
produces `valid_for_experiments=True`, `failed_gates=[]`.

## C0 status implication

With `CONTINUITY_CHECKER_CORRECTED_TRUE_COUNT=0` on the named candidate, geometric continuity is
no longer a valid blocker for C0/C1 pinning of this candidate. Per
`project_c0_clean_regen_pinned.md`, the other blockers on this candidate (signals=0, provenance
incompleteness, live-CARLA load) are untouched by this task and remain open — this report only
clears the geometric-continuity blocker, it does not re-pin C0.

## Deliverables

- `ultimate_pipeline/quality/check_geometric_continuity.py` — verified correct against fresh
  characterization tests; no changes needed (fix pre-existed on inherited base).
- `tests/unit/test_geometric_continuity_contactpoint.py` — new; spec-exact characterization +
  negative control (10 tests).
- `tests/unit/test_map_acceptance.py` — added end-to-end re-baseline test (1 new test).
- `reports/post_audit_hardening/C6_CONTINUITY_CHECKER.md` — this report.
