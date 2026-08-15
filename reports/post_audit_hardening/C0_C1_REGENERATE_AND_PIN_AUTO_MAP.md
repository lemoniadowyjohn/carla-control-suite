# C0/C1 Regenerate And Pin Auto Map Of Record

Date: 2026-08-15

Purpose: prevent the research pipeline from comparing, cooking, or certifying a stale auto-map artifact that predates the code fixes now landed on this branch.

## Current Finding

The code fixes are ahead of the map artifacts:

- `0df64b29` fixes lane-width generation so the auto map no longer stamps constant 6.0 m driving lanes.
- `9099d41f` fixes the visual mesh vertical datum by DEM-warping the OSM2World environment mesh.
- `41fa7550` adds D1b residual decomposition and locks D2 calibration semantics.
- `a98114c5` right-sizes CARLA semantic segmentation class policy.

Existing on-disk candidates and visual artifacts may predate some of those commits. A green code tree does not prove the map artifact of record contains the fixes.

## Goal

Produce and pin one fresh auto map of record generated from the fixed pipeline at the current pushed commit, with evidence that it contains the intended code-level fixes.

## Boundaries

- Offline only; set `UP_DISABLE_CARLA=1`.
- Do not run CARLA and do not certify.
- Do not overwrite immutable parent candidates.
- Write any regenerated `.xodr` or visual mesh as new generated artifacts, not tracked source.
- Do not change certifier/gate logic.
- Fail closed if the working tree has uncommitted code changes that would affect generation.

## C0 - Regenerate Fresh Auto Candidate

1. Verify `git rev-parse HEAD == git rev-parse '@{u}'`.
2. Verify the intended generation code commits are present:
   - `0df64b29` lane-width fidelity
   - `9099d41f` visual DEM warp
   - `41fa7550` D1b/D2
   - `a98114c5` perception class policy
3. Re-run the governed OSM-to-XODR candidate production path from the fixed Ingolstadt bbox and source inputs.
4. Write a new candidate under `campaigns/ingolstadt_cooked_perception_v1/candidate/` with a freshness-tagged filename.
5. Preserve the generated candidate as an untracked artifact and record its SHA-256.

## C0 Verification

The regenerated candidate must prove:

- Driving lane widths are no longer constant 6.0 m placeholders.
- Roads/junctions/signals/objects are preserved or any delta is explicitly justified.
- Elevation remains non-flat and matches the E2/D1 lineage expectations.
- G19 length invariant remains `0` violations.
- Offline loadability/preflight errors remain `0`.
- Strict XODR/schema validation passes.
- Candidate digest is recorded with source OSM/DEM/config/pipeline commit hashes.

If any check fails, return `PARTIAL` or `BLOCKED_NEEDS_DECISION`; do not pin the candidate.

## C1 - Pin Auto Map Of Record

Only after C0 verification passes:

1. Register the regenerated candidate in the map registry by full SHA-256.
2. Mark it as the canonical auto map of record for B4/RQ1 and D4 cook dry-run inputs.
3. Record why it supersedes older candidates, especially any candidate with stale 6.0 m lane widths or flat visual-mesh lineage.
4. Add provenance report `reports/post_audit_hardening/C0_C1_AUTO_MAP_OF_RECORD.md/.json`.

## Acceptance

Verdict: `AUTO_MAP_REGENERATED_AND_PINNED_GREEN`

Required evidence:

- New candidate SHA-256.
- Pipeline commit SHA.
- OSM/DEM/config SHA-256 anchors.
- Lane-width histogram showing realistic policy output.
- G19 `0` violations.
- Preflight errors `0`.
- Elevation non-flat.
- No stale-artifact pin.

## ESCALATE_TO_CLAUDE

- If regeneration cannot be run deterministically from tracked code and recorded inputs.
- If the regenerated candidate loses roads, junctions, signals, objects, elevation, or crash safety.
- If the pipeline still writes constant 6.0 m driving lanes after `0df64b29`.
- If C1 cannot unambiguously supersede older auto-map candidates by digest and provenance.
