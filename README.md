# CARLA / OpenDRIVE Map Quality & Validation

Public-safe portfolio landing page for Michał Dembski's CARLA/OpenDRIVE/OSM map-quality work.

## Scope

The underlying academic and engineering work covers a Python-based evaluation workflow for comparing OSM-derived CARLA/OpenDRIVE maps with reference geometry. The methodology includes:

- OpenDRIVE geometry extraction;
- coordinate-reference-system handling and transformation;
- deterministic SE(2) alignment;
- Hausdorff-distance analysis;
- lane-width comparison;
- topology checks;
- predecessor/successor and lane-link reasoning;
- reproducible report generation and provenance concepts.

## Evidence boundary

This repository currently documents the **public-safe methodology and portfolio scope**. It does not expose proprietary maps, employer data, private thesis source material, or private engineering repositories.

The public repository must not be treated as proof of a production CARLA deployment. The defensible claim is: **academic/project hands-on work in Python-based CARLA/OpenDRIVE/OSM map-quality validation and reproducible technical analysis**.

## Current status

The recruiter-facing runnable toolkit is still being sanitized for public release. Until sample fixtures, tests and a documented end-to-end command are present here, CV/LinkedIn wording should remain method-focused rather than claiming a production-ready simulation toolkit.

## Planned public release gate

A recruiter-ready release should contain:

- synthetic or public OSM/OpenDRIVE fixtures;
- documented Python package structure;
- deterministic sample alignment;
- map-quality metrics;
- topology validation;
- automated report output;
- tests;
- reproducible setup;
- limitations and data-provenance notes.

No confidential customer/employer material should be committed.
