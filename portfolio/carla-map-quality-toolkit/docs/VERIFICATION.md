# Verification Receipt

Verification date: 2026-09-30

## Public release gates

The portfolio branch is configured to verify the toolkit on Python 3.10 and 3.12 with:

- clean editable installation from `pyproject.toml`;
- Ruff static/lint checks;
- pytest with coverage;
- an enforced minimum package coverage threshold of 80%;
- a command-line synthetic quality-report smoke test.

The exact hosted GitHub Actions result for the latest release commit is the release authority for installation and lint verification.

## Evidence already established

The public toolkit uses only repository-owned synthetic OSM/OpenDRIVE fixtures. It includes deterministic geometry/alignment checks, CRS sanity tests, topology fixtures, invalid lane-link tests, report generation, provenance hashing and regression tests.

## Scope boundary

This verification applies only to this sanitized public implementation. It does not claim validation of private CARLA maps, employer/customer assets, private thesis datasets, proprietary Unreal content, or a production CARLA deployment.
