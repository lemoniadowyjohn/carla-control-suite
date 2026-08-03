# 06_EXECUTION_ORDER.md

**Generated:** 2026-08-02
**Coordinator:** Prompt 01 — Campaign Coordinator

## Dependency-ordered execution

1. **P02 AUDIT-NORM-001** — Audit normalization (mostly committed at e9ff5986). Remaining: add normalization tests (missing/duplicate IDs, invalid PASS, stale identity, missing negative controls, contradictions, wrong profile effect, premature manifest, archive mismatch) + clean archive round-trip + acceptance. Depends on: nothing new.
2. **P03 SYS-001** — Canonical release tree. Fix root import failure (8 missing module references), capability diff, canonical CLI/entry points, lazy optional deps, donor deprecation, import-smoke tests, `compileall`, collection. Depends on: P02.
3. **P04 TEST-TRACE-001** — Reports only (matrix CSV, collection inventory, weak assertions, negative-control gaps, ownership). Depends on: P03 (so paths resolve).
4. **P05 GEO-FRZ-001** — Geometry evaluators + fail-closed freeze. Depends on: P03, P04.
5. **P06 TOP-JCT-RAB-LLK-001** — Topology/junctions/roundabouts/LaneLinks. Depends on: P05.
6. **P07 ELV-LAN-001** — DEM/elevation/lanes. Depends on: P05, P06.
7. **P08 SIG-ENR-001** — Signals/controllers/enrichment. Depends on: P07.
8. **P09 TIL-EQV-001** — Tiling/equivalence. Depends on: P05-P08.
9. **P10 O2W-BLD-001** — OSM2World/Blender validators. Depends on: P09 (coordinate/tiling policy).
10. **P11 REVIEW-STATIC-001** — Static regression sweep (plan).
11. **P12 REVIEW-EVIDENCE-001** — Adversarial evidence review (plan).
12. **P13 REVIEW-DIFF-001** — Diff and preservation review (plan).
13. **P14 INTEGRATION-001** — Final integration: full offline suite + verdict. No Unreal cooking; verdict may declare readiness to provision the cooking toolchain only.

## Parallelism

- P11, P12, P13 are independent plan-mode reviews; can run in parallel once P02-P10 commits are in place.
- P04 runs as plan-only and can start as soon as P03 lands.

## Commit discipline

- Each Build prompt lands atomic commit(s) on `integration/governed-map-quality-20260729`.
- Every fix carries tests; every validator is read-only; every mutation writes new candidates.
- No threshold relaxations; no QA bypass flags introduced or enabled; no deletion of roads/semantics.
