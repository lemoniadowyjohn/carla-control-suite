# Verification Receipt

Verification date: 2026-09-30

## Canonical public release

The sanitized toolkit is published directly on the repository's default `main` branch.

Canonical promotion commit:

`bcd36de4e80a09d9fbd11d2104bda27b1519b3e6`

Hosted GitHub Actions run **36718173073** verified that default-branch release on both Python 3.10 and Python 3.12.

Measured result on both jobs:

- **21 tests passed**;
- **91.39% Python package line coverage**;
- **Ruff: PASS**;
- editable package installation: **PASS**;
- CLI passing synthetic quality-report path: **PASS**;
- CLI intentional-failure rejection path: **PASS** with expected process exit code `2`;
- separate exact coverage gate: **PASS** at the enforced 90% minimum.

## Public-scope audit

The default branch was constructed from the sanitized toolkit tree rather than from the legacy CARLA development tree.

A targeted GitHub code-search audit of the promoted default branch found no matches for:

- private-key markers;
- API-key/password/Bearer-token patterns searched;
- Windows user paths or `/home/` paths;
- employer/customer names included in the targeted audit list;
- known legacy Ingolstadt/production-readiness artifact identifiers;
- known private/legacy CARLA branch identifiers.

This is a targeted public-scope check, not a claim that pattern matching can prove the absence of every possible sensitive value.

## Historical branch boundary

The acceptance claim applies to the default `main` branch and the sanitized toolkit. Historical/non-default branches in the parent repository are not part of this portfolio release boundary.

The earlier recruiter-facing portfolio branch was rebuilt onto a safe public lineage before the toolkit was promoted to `main`.

## Evidence scope

The toolkit uses repository-owned synthetic OSM/OpenDRIVE fixtures. It demonstrates deterministic geometry/alignment checks, CRS sanity tests, topology fixtures, invalid lane-link detection, report generation, provenance hashing, regression protection and executable PASS/FAIL gates.

This receipt does **not** claim:

- a complete OpenDRIVE implementation;
- a production CARLA deployment;
- validation of private employer/customer assets;
- publication of private thesis datasets;
- universal real-world acceptance thresholds.

Live GitHub Actions on `main` is the release authority for installation, lint, tests, coverage and CLI behavior.
