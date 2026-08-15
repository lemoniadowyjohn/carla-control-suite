# CODEX A3 (MED) — domain_gap core-metric characterization tests (8684 LOC, 2 tests)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1
MODEL: Codex 5.x MID/HIGH. Independent of A1/A2/A4.

## Problem
`ultimate_pipeline/domain_gap/` (8684 LOC) is the sim-to-real gap analysis but has only 2 tests and is orphaned
from the main pipeline (run standalone via run_full_domain_gap.py). Its numbers feed research claims.

## Goal
Characterization tests that pin the core gap metrics + the aggregator, on synthetic map pairs — no metric
redefinition.

## Steps
1. Target the core metrics: `geometry_gap.py`, `curvature_gap.py`, `structural_gap.py`, `semantic_gap.py`,
   `connectivity_gap.py`, `topology_gap.py`, and `domain_gap_aggregator.py`.
2. Tests on synthetic pairs:
   - identical maps → each gap ≈ 0 (within tolerance);
   - a known single perturbation (e.g. shift/rotate/drop-a-road/change-a-lane-type) → the RIGHT metric moves in
     the RIGHT direction with a plausible magnitude, others ~unchanged;
   - aggregator: fixed weighting produces the expected combined score from component inputs.
3. Edge cases: empty map, single road, disconnected components → assert no NaN/None/crash (flag any that occur).
4. Findings report: which metrics are now pinned, any that returned NaN/None, and the aggregator weights.

## Boundaries
- Tests + report ONLY. Do NOT redefine a metric or reweight the aggregator (ESCALATE_TO_CLAUDE if one is wrong).
- Deterministic, fast, offline.

## Deliverables / git
tests/unit/test_domain_gap_metrics_*.py; report reports/post_audit_hardening/A3_DOMAIN_GAP_CHARACTERIZATION.md.
Atomic commits; push; local==remote; full suite green.
Verdict: DG_CHARACTERIZED_GREEN | PARTIAL | BLOCKED_NEEDS_DECISION.
