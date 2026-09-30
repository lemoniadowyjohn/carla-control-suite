# CARLA / OpenDRIVE Portfolio CV Blocks

These variants describe the **sanitized public toolkit** and the underlying engineering themes without claiming that private map assets or employer code are public.

## Variant A — Automotive / Simulation

**CARLA Map Quality Toolkit — Automotive Simulation & Map Validation | Python, OpenDRIVE, OSM, CARLA**  
- Built a sanitized, reproducible Python toolkit for validating generated road-network maps used in automotive simulation workflows, using synthetic/public fixtures rather than proprietary assets.
- Implemented OpenDRIVE parsing, lane-geometry reconstruction, CRS transformation checks, deterministic SE(2) alignment, discrete Hausdorff distance, lane-width deviation metrics, and topology/lane-link validation.
- Added quantitative quality gates for geometry, alignment residuals, lane-width tolerances, predecessor/successor integrity and invalid junction lane links, with machine-readable and human-readable reports.
- Created unit, synthetic-geometry, CRS, topology, invalid-link and regression tests plus CI to make map-quality checks reproducible and reviewable.
- Verified the sanitized public implementation in GitHub Actions on Python 3.10/3.12 with Ruff, 21 automated tests, 91.39% package coverage, a passing CLI report, and verified rejection of intentionally degraded input.

## Variant B — Python / Data

**Geospatial Map Quality Toolkit — Python Engineering & Validation**  
- Developed a modular Python package for parsing and validating OpenDRIVE/OSM-derived road data, structured around I/O, geometry, CRS, alignment, metrics, topology and reporting layers.
- Implemented vectorized numerical checks with NumPy, coordinate transformations with pyproj, deterministic rigid 2D alignment, Hausdorff-based geometry comparison and statistical lane-width deviation analysis.
- Designed threshold-based quality reports with explicit provenance, failure reasons and JSON/Markdown outputs suitable for automated pipelines and CI.
- Added regression fixtures and automated tests for geometry, coordinate systems and referential integrity to detect map-generation defects before downstream simulation use.
- Verified the sanitized public implementation in GitHub Actions on Python 3.10/3.12 with Ruff, 21 automated tests, 91.39% package coverage, a passing CLI report, and verified rejection of intentionally degraded input.

## Variant C — Digital Twin / Industrial AI

**Digital-Twin Data Quality Toolkit — Geospatial Validation & Evidence-Based Gates**  
- Created a sanitized validation layer for simulation/digital-twin map assets, converting geometric and topological consistency checks into reproducible, evidence-producing quality gates.
- Combined CRS sanity checks, deterministic spatial alignment, lane-level deviation metrics and graph-style topology validation to identify malformed or inconsistent road-network data before simulation ingestion.
- Implemented provenance-aware reports and regression tests so map-generation changes can be evaluated against measurable acceptance criteria rather than visual inspection alone.
- Structured the toolkit for future integration with automated map-generation and AI-assisted engineering workflows while keeping validation deterministic and independently testable.
- Verified the sanitized public implementation in GitHub Actions on Python 3.10/3.12 with Ruff, 21 automated tests, 91.39% package coverage, a passing CLI report, and verified rejection of intentionally degraded input.

## Claim boundary

The repository is now public and its hosted CI passes; wording such as **“built / implemented / validated in a sanitized public toolkit”** is supported for the public implementation. For earlier thesis/private engineering work, use **“worked on / developed concepts and validation methods around…”** unless you can independently evidence the exact implementation.
