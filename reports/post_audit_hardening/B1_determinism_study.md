# CODEX B1 — Conclusive determinism / natural-domain-randomization study (R2, R5)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1
MODEL: Codex 5.x MID/HIGH. Independent of A/E/other-B prompts.

## Problem
The thesis asks: "does the created map change when converting the same OSM map?" and "does domain randomization
occur naturally?" Current evidence is INCONCLUSIVE — verdicts across the repo are mixed (4 DETERMINISTIC /
4 NONDETERMINISTIC). This headline research question has no single answer.

## Goal
A conclusive, reproducible verdict: run the OSM→XODR pipeline N times on the FIXED bbox and decide
DETERMINISTIC vs NATURAL_RANDOMIZATION vs NONDETERMINISTIC, with a signed evidence bundle.

## Steps
1. Use the fixed bbox (lat 48.74935649548228..48.77444431571603, lon 11.422268084715878..11.47882091528412)
   and the canonical entrypoint (`python -m ultimate_pipeline.cli` / run_determinism_audit.py).
2. Generate N runs (>= agent_sync.yaml determinism.min_runs=5, prefer 10) from the SAME OSM input; for each,
   record the signature fields from the contract: `xodr_sha256`, `tile_metadata_sha256`, `tile_count`,
   `road_count`, `junction_count`.
3. Aggregate: identical signatures across runs → DETERMINISTIC; bounded natural variation → NATURAL_RANDOMIZATION;
   unbounded/uncontrolled → NONDETERMINISTIC. Use check_determinism.py / determinism_classify.py.
4. If DETERMINISTIC: state that natural DR does NOT occur → the explicit path
   (experiments/thesis/exp_natural_domain_randomization.py + augmentation/realism_augmentor.py) is required;
   characterize what that augmentor varies. If NONDETERMINISTIC: identify the source (seed/threading/ordering).
5. Report a single verdict + the per-run signature table + the methodological implication for the thesis.

## Boundaries
- Do NOT change pipeline behavior to force determinism; MEASURE and report. No map mutation.
- Deterministic, reproducible harness; commit the harness + report, not large generated maps (sha256-anchored).

## Deliverables / git
Harness/test under tests/ or tools/; report reports/post_audit_hardening/B1_DETERMINISM_STUDY.md/.json with the
verdict + signature table. Atomic commits; push; local==remote; suite green.
Verdict: DETERMINISM_VERDICT_ISSUED (DETERMINISTIC|NATURAL_RANDOMIZATION|NONDETERMINISTIC) | PARTIAL | BLOCKED.
