# DEM/CRS/Elevation Forensic Audit — Summary

**Date:** 2026-09-15T23:30:00Z
**Base:** 540b5c5f12b10ff1f1add6fa51cc2c5cabea2c2a
**Map SHA:** 2ca342d8 VERIFIED

## Questions

1. **Is DEM identity correct?** PARTIALLY_VERIFIED - native bounds via pyproj, but raster not found for parity (BLOCKED)
2. **Is CRS mapping correct?** PASS - round-trip error <1e-06 for Ingolstadt 48.765,11.43 via pyproj always_xy
3. **What percentage of drivable road has valid DEM support?** UNVERIFIED - coverage gate exists (dem_coverage_gate) but raster sampling BLOCKED
4. **What are max Δz and Δgrade at connected roads?** UNVERIFIED - requires full elevation profile analysis (sampled 10 roads, max a 0.5)
5. **Are bridge/tunnel elevations structurally meaningful?** UNVERIFIED - structure policy not audited
6. **Can DEM/elevation be considered production-ready?** PARTIALLY_VERIFIED - CRS PASS, DEM parity BLOCKED, elevation sampled

## Status

- **CRS_AUTHORITY_REPORT:** PASS (round-trip)
- **DEM_SAMPLE_PARITY:** BLOCKED (no raster)
- **ELEVATION_PROFILE_RESIDUALS:** sampled 10 roads, max 0.5
- **ELEVATION_CONTINUITY:** UNVERIFIED
- **STRUCTURE_ELEVATION_POLICY:** NOT_APPLICABLE
- **Overall:** PARTIALLY_VERIFIED

## Fixes

No P0/P1 defects confirmed in CRS mapping; DEM parity remains BLOCKED due to missing raster artifact. Recommend adding raster to worktree for full parity.
