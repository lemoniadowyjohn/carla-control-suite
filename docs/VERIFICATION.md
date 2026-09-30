# Verification Receipt

Verification date: 2026-09-30

## Hosted verification

GitHub Actions run **36717210086** verified the sanitized public toolkit on both Python 3.10 and Python 3.12.

Measured result:

- **21 tests passed**;
- **91.39% Python package line coverage**;
- **Ruff: PASS**;
- editable package installation: **PASS**;
- CLI passing synthetic quality-report smoke test: **PASS**;
- CLI intentional-failure rejection path: **PASS** (expected process exit code `2`).

The executable workflow enforces a separate exact **90% minimum coverage gate** after pytest, in addition to Ruff and both CLI behavior checks.

## Public-history sanitization

During verification, the previous portfolio branch lineage was found to include unrelated legacy CARLA files outside the intended public toolkit. The branch reference was rebuilt onto the safe public `main` lineage with a new clean tree. The recruiter-facing branch now retains only the sanitized portfolio toolkit plus its root CI workflow.

This history repair is part of the release evidence: public portfolio code must be isolated from private/proprietary engineering assets, not merely documented as isolated.

## Evidence scope

The public toolkit uses repository-owned synthetic OSM/OpenDRIVE fixtures. It demonstrates deterministic geometry/alignment checks, CRS sanity tests, topology fixtures, invalid lane-link detection, report generation, provenance hashing and regression tests.

This receipt does **not** claim validation of private CARLA maps, employer/customer assets, private thesis datasets, proprietary Unreal content, or a production CARLA deployment.

Live CI remains the release authority for installation, lint, test and coverage status.
