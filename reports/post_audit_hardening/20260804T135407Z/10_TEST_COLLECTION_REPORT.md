# 6.1 Repository tests + 6.3 Fixture corpus (Phase M)

- Run ID: `20260804T135407Z`

## 6.1 Mandatory repository tests
- compileall ultimate_pipeline: `PASS` (rc via subprocess)
- pytest --collect-only: `588` tests collected, rc=0, collection errors=0
- pytest -m "not carla": `588` passed, `0` skipped, `0` failed, `0` errors, rc=0
- summary: `================ 588 passed, 49 warnings in 163.31s (0:02:43) =================`
- verdict: `PASS`

## 6.3 Required fixture corpus
- required fixtures present: 8/9
- present: ['straight', 'spiral', 'roundabout', 'bridge', 'sidewalk', 'OSM2World', 'Blender', 'paramPoly3']
- missing: ['tile_boundary']

## Notes
- The single pre-existing mandatory skip (`test_deterministic_alignment.py`, gated on pyproj) is now enabled: pyproj is installed in the venv, so the test runs and passes -> 0 mandatory skips.
