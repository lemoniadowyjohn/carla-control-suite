# C55V01 — Governed New-Campaign Integration + Structural & Visual Candidate

**Assigned model:** Codex 5.5 (normal/high) · **Difficulty:** 9/10
**Status:** **BLOCKED** until ALL prerequisites below hold. Do NOT begin until the Claude coordinator releases it.

## Prerequisites (ALL required before any write)
1. Clean pushed base (R00) + canonical writer lock acquired by C55V01.
2. Artifact transactions independently verified (hashing.py + locking.py present & tested).
3. Claude donor decision (`CLAUDE_donor_decision.md`) approved.
4. `C44V01` = `CRS_CONTRACT_READY`.
5. Authoritative OSM selected (Claude §11.3) + FBX reuse/regeneration decision (Claude §11.2).

## Hard rules
- One writer. Immutable parent → isolated candidate → read-only validation → atomic promotion. No in-place map mutation.
- Import ONLY exact reviewed donor commits or minimal recreated patches (NO whole-worktree merge).
- Do NOT overwrite/rename/delete `run_11`, `scenario_b_audit/contract_run/`, `08_final_structural_gap.xodr`.
- Do NOT begin FULL-MAP cooking in this task (fixture only).

## Stages
1. **Integration branch** — isolated worktree off approved base; import only selected donor commits; run full offline tests after each batch.
2. **Campaign manifest** — `campaigns/ingolstadt_cooked_perception_v1/` binding: Git SHA · OSM SHA · OSM bounds · converter profile · CARLA/Osm2Odr version · CRS-contract hash · DEM hash (if used) · OSM2World version · Blender version · visual config · seeds.
3. **Deterministic raw XODR** — generate from authoritative OSM; run ≥2 identical conversions; compare semantic hashes. Do NOT modify run_11.
4. **Structural candidate** — every mutation via artifact transactions. FORBID: heading-only smoothing · type-ignorant segment merge · unknown-primitive→Line · straight-chord turn fallback · unexplained road/junction deletion · implicit elevation zero. Record preservation metrics before/after.
5. **Horizontal freeze** — `horizontal_freeze.json` hashing: road IDs+lengths · PlanView · road links · junctions · connectors · lane topology · coordinate contract.
6. **Elevation** — ONLY after freeze; known CRS+datum; BLOCK on unknown datum / missing DEM coverage.
7. **Matched visual candidate** — if FBX approved: copy into candidate store by hash (unaltered source). If regenerate: same authoritative OSM → approved OSM2World config → approved Blender → matched artifact; record all source+transform hashes.
8. **Alignment gate** — run C44V01 verifier against final structural + visual candidates.
9. **Minimal fixture ONLY** — representative small fixture: Unreal import · semantic tagging · materials · collision · navigation · cook · package · clean CARLA load · route · sensor smoke. Do NOT proceed to full map on fixture failure.

## Required outputs
`reports/new_campaign/C55V01_integration.*` … `C55V09_final_status.*` (per prompt §12).

## Verdicts
`NEW_STRUCTURAL_CANDIDATE_READY` · `MATCHED_VISUAL_CANDIDATE_READY` · `MINIMAL_FIXTURE_READY` ·
`MINIMAL_FIXTURE_COOKED_AND_LOADED` · `FAIL_OSM_CONVERSION` · `FAIL_STRUCTURAL_PRESERVATION` ·
`FAIL_CRS_ALIGNMENT` · `FAIL_VISUAL_GENERATION` · `FAIL_FIXTURE_COOK` · `BLOCKED_ARTIFACT_SAFETY` ·
`BLOCKED_TOOLCHAIN` · `BLOCKED_RUNTIME`.

> Note (coordinator): this task also inherits the P4-gate base blockers B2/B3/B4 (see AG07). B4 (cook toolchain on a
> Linux/UE4.26 source build) gates stages 9's cook/package/load; expect `BLOCKED_TOOLCHAIN` there until B4 closes.
