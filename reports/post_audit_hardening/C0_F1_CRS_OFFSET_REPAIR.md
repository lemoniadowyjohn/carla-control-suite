# C0 F1 CRS Offset Repair

Date: 2026-08-15

## Verdict

`F1_CRS_OFFSET_REPAIR_GREEN`

## Failure

C0 clean regeneration failed closed during DEM sampling setup:

```text
F1 CRS contract unresolved: cannot establish the geographic frame of .../06_geometry_frozen_C0_CLEAN_REGEN.xodr
(verdict=UNRESOLVED, reason=no_frame_matches_osm_source)
```

The OSM source was present and passed through as `UP_OSM_FILE`. The defect was in the CRS verifier: it evaluated local
header bounds directly and ignored `<header><offset>`, while the DEM sampler applies that offset before sampling.

## Fix

`ultimate_pipeline/dem/dem_crs_contract.py` now:

- parses `<header><offset>`;
- keeps raw header/geometry bounds in the evidence record;
- adds offset-applied bounds to the evidence record;
- uses offset-applied bounds for CRS plausibility checks.

This preserves fail-closed behavior. The verifier still raises when neither the claimed CRS nor the native Osm2Odr
frame places the offset-applied map extent inside the OSM source bounds.

## Evidence

Targeted red:

```text
1 failed, 12 passed
```

Targeted green:

```text
13 passed in 0.72s
```

Exact failed C0 artifact after the fix:

```text
source: claimed_geoReference_ambiguous
verdict: AMBIGUOUS
header_bounds_with_offset: west=832671.61 east=845938.74 south=5458670.93 north=5472743.72
native_frame_header_bounds_wgs84: lon=11.322196..11.527554 lat=48.684205..48.826011
```

The `AMBIGUOUS` verdict is expected here because `+proj=tmerc` and the Osm2Odr native frame are equivalent after the
header offset is applied. It is still geographically resolved to Ingolstadt and therefore safe for DEM sampling.

Full suite:

```text
740 passed, 49 warnings in 166.29s (0:02:46)
```

## ESCALATE_TO_CLAUDE

- The C0 rerun must happen after this fix is committed, otherwise the map provenance commit will not match the code
  actually used for DEM CRS verification.
