# CARLA / OpenDRIVE Map Quality & Validation

Public-safe portfolio landing page for Michał Dembski's CARLA / OpenDRIVE / OSM map-quality engineering work.

## Recruiter-facing toolkit

The sanitized, runnable implementation is available on the dedicated portfolio branch:

**[Open `carla-map-quality-toolkit`](https://github.com/lemoniadowyjohn/carla-control-suite/tree/portfolio/carla-map-quality-toolkit-20260930/portfolio/carla-map-quality-toolkit)**

The portfolio branch contains a standalone Python package, synthetic OpenDRIVE/OSM fixtures, automated tests, CI, architecture documentation, quality-report examples, provenance handling and explicit public-release boundaries. Its branch history has been rebuilt onto the safe public lineage so unrelated private/legacy CARLA assets are not part of the recruiter-facing branch.

### Verified release status

GitHub Actions verifies the toolkit on Python 3.10 and 3.12 with:

- clean editable installation;
- Ruff static/lint checks;
- pytest + an explicit exact 90% coverage gate;
- passing and intentional-rejection command-line quality-report checks.

Latest fully verified portfolio commit: `c1133ad2717ef1af699979cfaff9399ba6176e8c`.

At that commit:

- **21 automated tests pass**;
- **91.39% measured package line coverage**, with a **90% CI floor**;
- Ruff passes;
- the synthetic CLI demo produces a PASS quality report;
- the intentional degraded-input demo is rejected with the expected FAIL report and exit code `2`.

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

See the toolkit's `SANITIZATION.md`, `SECURITY.md`, and `docs/VERIFICATION.md` for the exact claim and public-data boundary.

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
