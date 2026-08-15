# D1 Visual Vertical Datum Resolution

Date: 2026-08-15

Verdict: `VISUAL_VERTICAL_DATUM_WARP_GREEN_WITH_CAVEATS`

## Summary

D1 produced a DEM-elevated environment OBJ for the large OSM2World visual layer without mutating any XODR/map candidate. OSM2World roads remain excluded and the road authority remains `CARLA_GENERATED_ROAD`.

The fix is additive:

```text
new_vertex_y = original_vertex_y + sampled_dem_elevation - obj_origin_elevation
```

This preserves object/building/tree local heights while moving their vertical datum from OSM2World's flat `ele=0` frame onto the DEM terrain used by the elevated road network.

## Inputs And Outputs

| Item | Path | SHA-256 |
| --- | --- | --- |
| Input visual OBJ | `reports/post_audit_hardening/20260810T000000Z_C2_REMEDIATION/visual_layer/artifacts_visual/scene.obj` | `15cdccbcd3374b79e63b590e6e591b9f4e4aa9b7abda6b260fb6f553e2d1907e` |
| DEM | `cities/ingolstadt/dem/dem_ing.tif` | `3cfa665dde3782a015502beaf457854db2f639d01008a386c925d171e41f4ff8` |
| Output visual OBJ | `reports/post_audit_hardening/20260810T000000Z_C2_REMEDIATION/visual_layer/artifacts_visual/scene_dem_elevated.obj` | `6f98898fbc5691795a995c23c8a1b6844b772e1bbe6312a131855fcf7db83bbe` |
| XODR used for road/DEM check | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_drivable_width_faithful.xodr` | `928e5b2397c9eb85448542178766ce8093f4f4457dabf4a7e2c86952b5898b2b` |

The output OBJ is a large generated artifact and is not committed. The tracked evidence is the code, tests, this report, and `D1_VISUAL_VERTICAL_DATUM_RUN.json`.

## Mesh Warp Evidence

| Metric | Value |
| --- | ---: |
| vertices total | 3,159,722 |
| vertices DEM-warped | 3,158,262 |
| DEM-missing vertices left unchanged | 1,460 |
| missing ratio | 0.000462 |
| original OBJ y range | -0.5 m to 200.0 m |
| sampled DEM height range | 355.045 m to 431.917 m |
| warped vertex y range, warped vertices only | 355.045 m to 566.066 m |

The global `y_after_min` is still `0.0` because the 1,460 DEM-missing vertices are intentionally left unchanged rather than filled with invented heights. The missing ratio is below the configured fail-closed limit of `0.02`.

## Road To DEM Check

The road/DEM verifier sampled 2,000 XODR planView geometry anchors and compared each OpenDRIVE `elevationProfile` value with the DEM at the same geographic point.

Important frame note: the verifier uses the F1-verified OpenDRIVE geometry CRS:

```text
+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs
```

It does not use the misleading EPSG:32632-style metadata header, because that header transforms the same numeric XODR coordinates away from Ingolstadt.

| Metric | Value |
| --- | ---: |
| sampled points | 2,000 |
| DEM missing | 0 |
| mean absolute residual | 1.438 m |
| median absolute residual | 0.879 m |
| p95 absolute residual | 4.616 m |
| max absolute residual | 9.725 m |
| p95 threshold | 10.0 m |
| verdict | PASS |

## Tests

| Suite | Result |
| --- | --- |
| D1 red test | missing module import failed as expected |
| D1 targeted final | `4 passed in 0.17s` |
| Full suite final | `698 passed, 49 warnings in 162.29s` |

## Boundaries Preserved

- No CARLA run.
- No XODR mutation.
- No certifier/gate logic changed.
- OSM2World road modules remain excluded.
- The large generated output OBJ is not committed.

## ESCALATE_TO_CLAUDE

- 1,460 visual vertices are outside DEM coverage or otherwise unsampled and were left unchanged; this is low-ratio evidence, not a fabricated fill.
- The visual OSM window is larger than the thesis bbox and slightly larger than DEM coverage; D4 cook dry-run should crop or reject out-of-study geometry if this matters for the perceptual experiment.
- D1 resolves vertical datum for the visual mesh. D3 is still required to prove the Unreal/CARLA import transform is applied exactly once.
- The local raster/PROJ stack emits a `proj.db` version warning, but the DEM is geographic WGS84 and the run completed with road/DEM residual evidence.
