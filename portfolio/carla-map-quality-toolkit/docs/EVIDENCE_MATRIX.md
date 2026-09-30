# Portfolio Evidence Matrix

This matrix connects recruiter-facing claims to inspectable public evidence. It is intentionally narrower than the private thesis/engineering history.

| Claim | Public implementation | Verification evidence |
|---|---|---|
| OpenDRIVE parsing | `src/carla_map_quality_toolkit/io/opendrive.py` | `tests/test_opendrive_parser.py` |
| OSM highway parsing | `src/carla_map_quality_toolkit/io/osm.py` | `tests/test_osm_parser.py` |
| Reference/lane geometry | `geometry/lane_geometry.py` | `tests/test_geometry.py` |
| CRS transformation sanity | `crs/transform.py` | `tests/test_crs.py` |
| Deterministic SE(2) alignment | `alignment/se2.py` | `tests/test_alignment.py` |
| Symmetric discrete Hausdorff | `metrics/hausdorff.py` | `tests/test_metrics.py` |
| Lane-width deviation metrics | `lane_quality/width.py` | `tests/test_lane_quality.py` |
| Road/junction/lane-link integrity | `topology/validation.py` | `tests/test_topology.py` |
| Provenance hashing | `io/provenance.py` | `tests/test_provenance.py` |
| Threshold quality gate | `reporting/report.py` | `tests/test_reporting.py` |
| Regression protection | public synthetic fixtures | `tests/test_regression_fixture.py` |
| PASS/FAIL CLI behavior | `cli.py` | `tests/test_cli.py` |
| Human-readable evidence | Markdown reporting | PASS/FAIL examples under `docs/` |
| Machine-readable evidence | JSON reporting | PASS/FAIL examples under `docs/` |
| Public-data boundary | repository policies | `SANITIZATION.md`, `SECURITY.md`, `CONTRIBUTING.md` |
| Reproducibility gate | root GitHub Actions workflow | Python 3.10/3.12, Ruff, ≥90% coverage, PASS/FAIL CLI |

## Reproduce locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
ruff check .
pytest --cov=carla_map_quality_toolkit --cov-report=term-missing --cov-fail-under=90
carla-map-quality demo --output out/pass
carla-map-quality demo --inject-failure --output out/fail
```

The final command intentionally exits with code `2`; that rejection is expected behavior.

## Claim boundary

This evidence supports a sanitized public portfolio implementation of map-quality methods. It does not prove a complete OpenDRIVE engine, production CARLA deployment, proprietary-map release, or universal real-world acceptance thresholds.
