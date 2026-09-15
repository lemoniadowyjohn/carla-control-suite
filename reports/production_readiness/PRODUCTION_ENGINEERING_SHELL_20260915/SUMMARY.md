# Production Engineering Shell Summary

**Date**: 2026-09-15  
**Run ID**: PRODUCTION_ENGINEERING_SHELL_20260915  
**Status**: READY_FOR_REVIEW  

## Overview

This evidence package documents the production engineering shell hardenings applied to the repository since the 2026-09-15 hygiene pass. It covers release profile unification, quality status modeling, warning taxonomy, CI configuration, package dependency contracts, module origin guarding, and XODR schema validation infrastructure.

## Task Summary

| Task | Description | Result |
|------|-------------|--------|
| T1 | Unify release profile vocabulary to `ReleaseProfile` enum with explicit aliases | PASS |
| T1A | Profile tests (canonical names, aliases, case normalization, unknown, empty) | PASS |
| T2 | Introduce `QualityStatus` model: PASS, FAIL, INCOMPLETE, NOT_RUN, BLOCKED_EXTERNAL, WAIVED | PASS |
| T3 | Create `WarningDefinition` registry with geometry, topology, lanes, DEM, CARLA static compatibility | PASS |
| T4 | CI configuration: add `integration/**` to push trigger for integration branch evidence | PASS |
| T5 | Add module origin guard verifying imported modules originate from repo root | PASS |
| T6 | Split package dependencies into core/geo/carla/research/dev optional extras | PASS |
| T6A | Clean install tests: base package and geo extra both install successfully | PASS |
| T7 | Doctor profiles: `--profile core/offline-map/research/carla-runtime` with dependency classification | PASS |
| T8 | XODR schema validation shell with pinned target ASAM OpenDRIVE 1.3 | PASS |
| T8A | XSD minimal fixture valid/invalid tests | PASS |

## Source Authority

- **Base SHA**: `93ac036b` (feature/full-grid-tile-fbx-cook-v1-20260915)
- **Final SHA**: `cdb256d` (after all hygiene tasks)
- **Branch**: `integration/session-batch1-20260912`

## Prohibited Items Verification

- No map algorithm changes (geometry, lanes, roundabouts, junctions, signals, buildings)
- No FBX/CARLA/Unreal runtime modifications
- No git history rewriting
- No RQ3 regeneration

## Files Modified

- `ultimate_pipeline/contracts/stage_contracts.py` - ReleaseProfile enum, QualityStatus model, WarningRegistry
- `ultimate_pipeline/contracts/release_profile.py` - resolve_release_profile, resolve_experimental_unsafe
- `ultimate_pipeline/cli.py` - doctor --profile option
- `pyproject.toml` - optional dependency extras (geo, carla, research, dev)
- `.github/workflows/tests.yml` - added `integration/**` to push branches
- `docs/archive/large_committed_binaries_audit_20260915.md` - large binaries audit report
- `docs/research/STALE_ARTIFACT_POINTERS.md` - stale artifact pointers
- `docs/archive/large_file_policy_recommendation_20260915.md` - LFS policy recommendation
- `docs/archive/root_reports_pre_20260912/` - archived root-level audit artifacts
- `docs/archive/unrelated_scripts_pre_20260915/` - archived personal scripts

## Artifacts

- `reports/production_readiness/PRODUCTION_ENGINEERING_SHELL_20260915/SUMMARY.md`
- `reports/production_readiness/PRODUCTION_ENGINEERING_SHELL_20260915/SUMMARY.json`
- `reports/production_readiness/PRODUCTION_ENGINEERING_SHELL_20260915/DEPENDENCY_AUDIT.json`
- `reports/production_readiness/PRODUCTION_ENGINEERING_SHELL_20260915/PROFILE_AUDIT.json`
- `reports/production_readiness/PRODUCTION_ENGINEERING_SHELL_20260915/CI_AUDIT.json`
- `reports/production_readiness/PRODUCTION_ENGINEERING_SHELL_20260915/TEST_RESULTS.txt`