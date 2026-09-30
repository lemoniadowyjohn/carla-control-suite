# Acceptance Checklist

This checklist maps the original public-portfolio requirements to inspectable repository evidence.

## Architecture and modules

| Requirement | Status | Evidence |
|---|---|---|
| Sanitized public toolkit | PASS | `SANITIZATION.md`, `SECURITY.md`, clean portfolio branch lineage |
| `io/` | PASS | OpenDRIVE, OSM and provenance modules |
| `geometry/` | PASS | reference-line sampling and lane-center reconstruction |
| `crs/` | PASS | pyproj transformations and roundtrip sanity |
| `alignment/` | PASS | deterministic SE(2) fitting |
| `lane_quality/` | PASS | lane-width deviation statistics |
| `topology/` | PASS | road links, reciprocal links and junction laneLink validation |
| `metrics/` | PASS | symmetric discrete Hausdorff distance |
| `reporting/` | PASS | threshold gates plus JSON/Markdown output |
| `tests/` | PASS | unit, synthetic, CRS, topology, invalid-link, regression and CLI tests |

## Requested functions

| Function | Status | Evidence |
|---|---|---|
| Parse OpenDRIVE | PASS | `io/opendrive.py` |
| Parse lane geometry | PASS | `geometry/lane_geometry.py` |
| Coordinate transform | PASS | `crs/transform.py` |
| SE(2) alignment | PASS | `alignment/se2.py` |
| Hausdorff metric | PASS | `metrics/hausdorff.py` |
| Lane-width comparison | PASS | `lane_quality/width.py` |
| Topology check | PASS | `topology/validation.py` |
| Predecessor/successor validation | PASS | reciprocal road-link checks |
| Quality report | PASS | `reporting/report.py` |
| Threshold gate | PASS | `build_quality_report` plus CLI exit status |

## Test requirements

| Test requirement | Status | Evidence |
|---|---|---|
| Unit tests | PASS | pytest suite |
| Synthetic geometry tests | PASS | `tests/test_geometry.py` |
| CRS sanity tests | PASS | `tests/test_crs.py` |
| Topology fixture tests | PASS | `tests/test_topology.py` |
| Invalid lane-link tests | PASS | `invalid_lane_link.xodr` + topology tests |
| Regression fixtures | PASS | `tests/test_regression_fixture.py` |
| PASS/FAIL gate behavior | PASS | `tests/test_cli.py`, intentional rejection CI step |

## Documentation and presentation

| Requirement | Status | Evidence |
|---|---|---|
| Engineering problem explained | PASS | `README.md` |
| Why generated maps need validation | PASS | `README.md` |
| Metrics documented | PASS | README metric table |
| Architecture documented | PASS | README + `docs/architecture.svg` |
| Sample input | PASS | synthetic OSM/OpenDRIVE fixtures |
| Sample output | PASS | PASS and intentional-FAIL Markdown/JSON reports |
| Screenshots/plots | PASS | architecture SVG + synthetic quality-report SVG |
| Limitations | PASS | README limitations section |
| Three CV variants | PASS | `CARLA_PORTFOLIO_CV_BLOCK.md` |
| Evidence-to-claim traceability | PASS | `docs/EVIDENCE_MATRIX.md` |
| Hosted verification receipt | PASS | `docs/VERIFICATION.md` |

## Acceptance criteria

- **Reproducible:** PASS — installable package, deterministic fixtures, matrix CI and explicit commands.
- **Sanitized:** PASS — portfolio branch rebuilt onto safe public lineage; synthetic/public-safe assets only inside the toolkit.
- **Testable:** PASS — hosted CI on Python 3.10 and 3.12 with a strict coverage gate and PASS/FAIL CLI checks.
- **Documented:** PASS — README, architecture, evidence matrix, verification, security, sanitization and contribution guidance.
- **No proprietary assets in the public toolkit:** PASS — repository policy and sanitized toolkit tree; no private map assets are required to run tests/examples.
- **Understandable without the thesis:** PASS — architecture, fixtures, commands, metrics, examples and limitations are self-contained.

## Scope note

This checklist applies to the recruiter-facing `carla-map-quality-toolkit` implementation. It does not assert that unrelated historical content elsewhere in the parent repository has the same evidence boundary, and it does not present the toolkit as a complete OpenDRIVE engine or production CARLA deployment.
