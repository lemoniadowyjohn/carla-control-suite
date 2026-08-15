# D1b Elevation Residual Decomposition

Date: 2026-08-15

Verdict: `PARTIAL_REVIEW_REQUIRED`

## Summary

D1 fixed the flat visual mesh by DEM-warping the OSM2World environment layer. D1b decomposes the remaining XODR-vs-DEM road elevation residuals by F3 structure class so grade-separated roads do not get misread as alignment errors.

The result is mixed:

- At-grade p95 is acceptable: `4.437 m` against a `5.0 m` review threshold.
- At-grade max is not acceptable: `12.030 m` against a `10.0 m` review threshold.
- The largest residual is `terrain_following`, not bridge/elevated/tunnel/underpass.

This means the D1 residual tail is **not** fully explained by legitimate bridge or overpass separation. It needs targeted review before cook.

## Inputs

| Item | Path / SHA-256 |
| --- | --- |
| XODR | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_drivable_width_faithful.xodr` |
| XODR SHA-256 | `928e5b2397c9eb85448542178766ce8093f4f4457dabf4a7e2c86952b5898b2b` |
| DEM | `cities/ingolstadt/dem/dem_ing.tif` |
| DEM SHA-256 | `3cfa665dde3782a015502beaf457854db2f639d01008a386c925d171e41f4ff8` |
| F3 structure cache | `reports/post_audit_hardening/20260810T000000Z_C2_REMEDIATION/F3_STRUCTURE_PER_ROAD_CACHE.json` |
| F3 structure cache SHA-256 | `47a9033fc3ac0d7cd0d6e0dc49d40d19d48cfe4340c74440b02dbd54e3ed624d` |

## Residual Summary

| Bucket | Count | Median abs m | Mean abs m | P95 abs m | Max abs m |
| --- | ---: | ---: | ---: | ---: | ---: |
| overall | 80,261 | 0.921 | 1.413 | 4.437 | 12.030 |
| at-grade | 73,865 | 0.906 | 1.406 | 4.437 | 12.030 |
| grade-separated | 463 | 1.381 | 1.621 | 3.950 | 6.357 |
| unknown/fail-closed | 5,933 | 1.088 | 1.489 | 4.455 | 10.663 |

Thresholds:

- At-grade p95 threshold: `5.0 m` -> pass.
- At-grade max threshold: `10.0 m` -> fail review.

## Top Residuals

| Rank | Road ID | Class | Bucket | Abs residual m |
| ---: | --- | --- | --- | ---: |
| 1 | `47237` | `terrain_following` | `at_grade` | 12.030 |
| 2 | `40167` | `terrain_following` | `at_grade` | 11.050 |
| 3 | `47049` | `unknown` | `unknown_fail_closed` | 10.663 |
| 4 | `47237` | `terrain_following` | `at_grade` | 10.483 |
| 5 | `40167` | `terrain_following` | `at_grade` | 10.476 |

## Tooling

- Added `ultimate_pipeline/tools/d1b_elevation_residual_decomposition.py`.
- Extended `ultimate_pipeline/tools/visual_mesh_elevation_warp.py` with `decompose_xodr_dem_elevation_residuals(...)`.
- Added synthetic tests for grade-separated bucketing and at-grade max fail-closed behavior.

## ESCALATE_TO_CLAUDE

- Review top at-grade residual roads `47237` and `40167`; these are not explained by the F3 grade-separated bucket.
- Resolve or justify unknown road `47049` before cook, because unknown structure classes are fail-closed for tail interpretation.
- D1 should remain `GREEN_WITH_CAVEATS`; D1b prevents upgrading it to fully green until the at-grade max tail is explained or repaired.
