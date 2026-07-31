# C55V01a Final Status

Verdict: CRS_CONTRACT_READY_CANDIDATES_STAGED

OSM SHA: `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f`
XODR SHA: `ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d`
XODR geoReference: `+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs`
Visual SHA: `CARLA_GENERATED_ROAD`
Vertical datum: `LOCAL_FLAT_ZERO_NO_DEM`
C44V01 verdict: `CRS_CONTRACT_READY`
Toolchain: `BLOCKED_TOOLCHAIN`
Real map mutation authorized: `NO`

The candidate artifacts are staged as hash-addressed metadata and local XODR files. Structural mutation, horizontal freeze, elevation fitting, Unreal cook, CARLA runtime, and perception capture remain out of scope.

## Test Execution

| Gate | Result |
|---|---|
| compileall | PASS |
| pytest collect-only | PASS, 336 collected |
| geometry suite | PASS, 2202 passed, 78 skipped |
| full non-CARLA suite | PASS, 336 passed, 48 warnings |
| cross-comparison | PASS, expected EPS-policy differences only |
