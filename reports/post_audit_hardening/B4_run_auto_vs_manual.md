# CODEX B4 — Run the auto-vs-manual structural comparison → RQ1 results (R3)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1
MODEL: Codex 5.x HIGH. PREREQ: B3 (manual reference pinned).

## Problem
The comparison CAPABILITY exists (`ultimate_pipeline/domain_gap/manual_vs_auto_comparator.py`,
`experiments/thesis/exp_domain_gap_manual_vs_auto.py`, alignment tested) but has NOT been RUN to produce the
RQ1 structural-gap result. RQ1 output is a core thesis deliverable, currently missing.

## Goal
Produce the auto-vs-manual STRUCTURAL domain-gap result artifacts on the pinned maps, spatially aligned, with a
reproducible evidence bundle.

## Steps
1. Inputs: the OSM-auto Ingolstadt map + the B3-pinned canonical manual reference (by sha256). Confirm both via
   the B3 registry before running (fail closed on mismatch).
2. Align: run domain_gap/deterministic_alignment.py + run_alignment_and_matching.py to register auto↔manual into a
   common frame (both EPSG:32632 / documented offset); record the alignment transform + residual.
3. Compute the structural gap: geometry, curvature, structural, topology, connectivity, semantic gaps +
   domain_gap_aggregator; emit per-metric values + the combined score.
4. Emit result artifacts (JSON + CSV + the standard domain_gap report set) under a timestamped dir; record input
   sha256s so the result is reproducible.
5. Report: the RQ1 structural-gap numbers, alignment residual, and any metric that returned NaN/None (flag).

## Boundaries
- Do NOT redefine metrics (that is A3's characterization; here you RUN them). Do NOT mutate maps.
- If alignment residual is implausible or a metric is degenerate → ESCALATE_TO_CLAUDE (do not ship a bad number).

## Deliverables / git
Run harness + report reports/post_audit_hardening/B4_AUTO_VS_MANUAL_RESULT.md/.json (+ CSVs). Large maps
sha256-anchored, not committed. Atomic commits; push; local==remote; suite green.
Verdict: RQ1_STRUCTURAL_GAP_PRODUCED | PARTIAL | BLOCKED_NEEDS_DECISION.
Note: this is the STRUCTURAL gap. The PERCEPTUAL gap additionally needs both maps cooked + sensor capture (toolchain).
