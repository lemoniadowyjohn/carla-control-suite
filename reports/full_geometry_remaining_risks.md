# Full Geometry Program — Remaining Risks

Ordered by severity. Verdict context: `FAIL_REPORTS_NOT_REPRODUCIBLE`.

## Critical (block approval)

1. **Reviewed implementation is not in version control.**
   The canonical `opendrive_geometry/` package (`primitives.py`, `evaluator.py`, `model.py`, `errors.py`, `__init__.py`) and **all** geometry tests/fixtures are untracked (`git ls-files opendrive_geometry/` empty; `git check-ignore` exit 1 → not ignored, never added). A clean checkout of `faa20bb5` or `4561f953` from the remote yields **none** of the reviewed code. Nothing can be reproduced from a pinned revision.

2. **I02 Stage 6 containment is uncommitted.**
   `settings.py`, `release_profile.py`, `stage_06_links.py`, `stage_05_geometry.py` carry 740 uncommitted insertions. The safety behavior is real and tested in the working tree but is unpinnable.

3. **Unpublished / diverged lineage.**
   Local HEAD (`4561f953`) is ahead of the remote-tracking ref (`faa20bb5`); the live remote could not be reached (SSL). All reports cite `faa20bb5`, which lacks the implementation. This is the §23 "reports reference another SHA without disclosure" condition.

4. **Concurrent mutation of the branch during review.**
   HEAD advanced mid-session (external commit). Eleven live worktrees and governance/dispatcher processes share this repo. Verification requires a frozen, single-writer branch or a pinned tag.

## High (block later mutation phases; not the read-only model)

5. **Artifact-safety transaction framework absent.**
   No candidate directory, atomic promotion, rejected-candidate retention, or rollback; no failure-injection tests. Any future junction/connector/LaneLink/elevation mutation is unsafe until this exists and is tested. (`FAIL_ARTIFACT_SAFETY` for the mutation scope; out of the read-only scope.)

6. **`autofix_postprune_elevation.py` — ungoverned active elevation mutator.**
   Env-gated (`UP_AUTOFIX_POSTPRUNE_ELEVATION`, default off) at `main_pipeline.py:2048`; rewrites `<elevation>` elements via `tree.write()`. Uses inline `_pose_arc` (correct local-frame) and numeric `_pose_spiral` outside the single authority. Omitted from every prior inventory. Not gated by the Stage 6 release-profile policy. Governance and single-authority migration required before any elevation-mutation task.

## Medium (must be enforced by the read model's design)

7. **Spiral and Poly3 have no canonical evaluator.**
   Only unverified numeric/inline forms exist in frozen mutation-adjacent code. Mitigation: the two production maps contain **zero** spiral/poly3, and the dominant connector primitive (ParamPoly3) is canonical. The read model must **typed-reject** spiral/poly3 (raise), never silently line-fallback. Reusing `geometry_seam_checker._geometry_endpoint`'s "unknown → straight line" fallback would violate §3.4.

8. **Projection / nearest-s not implemented.**
   `ReferenceLineEvaluator.project` is protocol-only; `ProjectionResult` is never produced. A read-only validator that must map points to `s` (lane-center alignment, object placement) is blocked until this is built. Endpoint-to-endpoint continuity checks do not need it.

9. **Lane-center derivation has no plan or implementation.**
   Lane center = reference line + lane-width/lateral-profile offsets; none of that is integrated into the geometry authority. Geometric LaneLink *validation* (predecessor/successor lane-center agreement) depends on it. Must be scoped as an explicit deliverable of the read model task.

## Low (quality / hygiene)

10. **Arc bounds are sampled (64 pts), not analytical**, and there is no `dk/ds` (curvature derivative) for any primitive. Adequate for a read model; note for smoothness metrics.

11. **Bounded epsilon artifact at `k=1e-12`**: arc closed form shows ~`5e-5` position cancellation wobble exactly at the EPS boundary; off-boundary from production arcs (`k≈0.1`). Quantified, non-blocking.

12. **Report hygiene**: batch labels drift (I02/G02/G03); four expected reports are missing (`geometry_improvement_reverification.*`, `line_arc_hardening.*`, `geometry_caller_contracts.*`, `geometry_authority_readiness_review.*`). The working tree is polluted with many untracked audit artifacts and archives, obscuring a clean lineage.

## Verification actions still required (not run this session)

`compileall`; full `--collect-only`; full `-m "not carla"` regression; `python -O` optimization-mode; `cross_compare_implementations.py` (must include map_plotter and map_diff and return non-zero on real discrepancies); XODR before/after byte-and-semantic hashing of the migrated validators on representative maps to confirm zero mutation. All to be executed **after** the artifacts are committed and pinned, then re-gated.
