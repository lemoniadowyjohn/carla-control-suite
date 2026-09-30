# Contributing

This repository is primarily a public engineering portfolio and reference implementation. Contributions should preserve its reproducibility and sanitization boundary.

Before proposing a change:

1. Use only synthetic or clearly redistributable public data.
2. Add or update tests for behavioral changes.
3. Run `ruff check .` and `pytest --cov=carla_map_quality_toolkit`.
4. Keep validation thresholds explicitly scoped to the demonstration or documented use case.
5. Do not introduce proprietary CARLA/Unreal assets, company data, credentials, or private repository references.
