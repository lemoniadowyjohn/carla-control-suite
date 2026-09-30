# CARLA / OpenDRIVE Map Quality & Validation

Public-safe portfolio landing page for Michał Dembski's CARLA / OpenDRIVE / OSM map-quality engineering work.

## Recruiter-facing toolkit

The sanitized, runnable implementation is available on the dedicated portfolio branch:

**[Open `carla-map-quality-toolkit`](https://github.com/lemoniadowyjohn/carla-control-suite/tree/portfolio/carla-map-quality-toolkit-20260930/portfolio/carla-map-quality-toolkit)**

The portfolio branch contains a standalone Python package, synthetic OpenDRIVE/OSM fixtures, automated tests, CI, architecture documentation, quality-report examples, provenance handling and explicit public-release boundaries.

### Verified release status

GitHub Actions verifies the toolkit on Python 3.11 with:

- clean editable installation;
- Ruff static/lint checks;
- pytest + coverage;
- command-line quality-report smoke test.

Latest verified portfolio commit: `79fb506d96c01dddbcf6431d0c8f54c7984ed7ed`.

At that commit:

- **14 tests pass**;
- **83% package coverage**;
- Ruff passes;
- the synthetic CLI demo produces a PASS quality report.

## Engineering scope

The public toolkit demonstrates transferable methods used in automotive simulation and digital-map validation:

- OpenDRIVE parsing;
- synthetic OSM parsing;
- road-reference and lane-center geometry;
- coordinate-reference-system transformation and sanity checks;
- deterministic SE(2) alignment;
- symmetric discrete Hausdorff distance;
- lane-width deviation metrics;
- predecessor/successor integrity;
- junction lane-link validation;
- provenance hashing;
- threshold-based PASS/FAIL quality gates;
- JSON and Markdown evidence reports;
- regression fixtures and CI.

## Why map validation matters

Generated road-network maps can appear visually plausible while containing geometric, coordinate-system or topology defects that affect routing, lane following and downstream simulation. The toolkit treats validation as a measurable engineering step rather than relying only on visual inspection.

## Evidence boundary

This public portfolio does **not** publish proprietary maps, employer/customer data, private thesis assets, credentials or private repository history.

The defensible claim is hands-on academic/project engineering in Python-based CARLA/OpenDRIVE/OSM map-quality validation, plus a sanitized public implementation demonstrating the methods.

The toolkit is intentionally **not** presented as:

- a complete OpenDRIVE implementation;
- a production CARLA deployment;
- a replacement for CARLA runtime validation;
- proof that illustrative synthetic thresholds are universal acceptance criteria.

See the toolkit's `SANITIZATION.md` and documented limitations for the exact claim boundary.

## Portfolio relevance

This work supports applications in:

- Automotive Digitalisation;
- Simulation Engineering;
- Digital Twin Engineering;
- Python / Data Engineering;
- Automotive Data;
- Validation Engineering;
- Technical Project Engineering;
- Applied AI / industrial-data roles where deterministic validation and evidence quality matter.
