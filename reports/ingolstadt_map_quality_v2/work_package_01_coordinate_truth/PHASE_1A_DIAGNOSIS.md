# Phase 1A Coordinate Diagnosis

## Inventory Summary

| Artifact | geoReference | Geometry Bounds (x_min, y_min, x_max, y_max) | Frame |
|----------|--------------|-----------------------------------------------|-------|
| Pinned baseline (c8419f8c) | *(empty)* | 832672.90, 5458671.57 → 845935.65, 5472743.65 | tmerc(0,0) |
| Historical run_11 (c765c4da) | *(empty)* | 677592.43, 5401849.20 → 682592.53, 5405850.39 | EPSG:32632 |
| Manual Grid0828 (a42ddfea) | *(empty)* | 678015.80, 5402486.15 → 682410.51, 5405403.33 | EPSG:32632 |
| Manual Grid0821 (69ee3498) | *(empty)* | 678015.80, 5402486.15 → 682410.51, 5405403.33 | EPSG:32632 |
| Manual Grid0821 aligned (67148d18) | *(empty)* | 678015.65, 5402467.04 → 682410.36, 5405384.22 | EPSG:32632 |

## Frame Discrepancy

**Core issue**: The pinned baseline candidate coordinates are in **tmerc(lat_0=0, lon_0=0)** frame (x ~800k+, y ~5.45M+), while all reference artifacts (historical run_11, manual grids) are in **EPSG:32632** frame (x ~680k+, y ~5.40M+).

The header `geoReference` attribute is **empty** in all artifacts. The pinned candidate's header bbox was "pinned" to EPSG:32632 values in the P04 process, but the **geometry coordinates were not transformed** — only the header metadata was updated.

## Metadata vs Transformation

| Artifact | Header bbox claims | Geometry coordinates | Metadata/geometry consistent? |
|----------|-------------------|---------------------|------------------------------|
| Pinned baseline | EPSG:32632 bbox (if pinned) | tmerc(0,0) coordinates | **NO** — header metadata claims EPSG:32632 but geometry is tmerc(0,0) |
| Historical run_11 | none | EPSG:32632 coordinates | N/A (no header claim) |
| Manual grids | none | EPSG:32632 coordinates | N/A (no header claim) |

**Conclusion**: The header pin in P04 updated only the header bbox metadata, not the actual geometry coordinates. The geometry remains in the Osm2Odr native tmerc(0,0) frame.

## Wheel/Osm2Odr Probe (1A.3)

The P05 CRS reconciliation established the true frame via CARLA Osm2Odr wheel probe:

- **CARLA 0.9.16 Osm2Odr** with `use_offsets=True` produces coordinates in **tmerc(lat_0=0, lon_0=0, k=1, x_0=0, y_0=0, datum=WGS84, units=m, no_defs)**
- This matches the pinned baseline's observed coordinate frame (x ~800k+, y ~5.45M+)
- The Osm2Odr output does **not** automatically reproject to EPSG:32632
- The EPSG:32632 header label is metadata-only; the converter does not transform coordinates

**Reconciliation pipeline** (from P05):
1. Source frame: tmerc(lat_0=0, lon_0=0) — proven by Osm2Odr wheel probe
2. Transformation: inverse tmerc(0,0) → WGS84 (lat/lon) → forward EPSG:32632 (pyproj)
3. Result: coordinates in EPSG:32632, matching manual grid frame
4. Validation: manual bbox fully contained in candidate bbox after reprojection

## Coordinate Correction Candidates (1B)

Per the directive, these must be tested independently:

1. **candidate_metadata_only** — Change only header geoReference to correct value, no coordinate change
2. **candidate_correct_georeference** — Add correct geoReference metadata matching actual coordinate frame (tmerc)
3. **candidate_actual_reprojection** — Transform coordinates from tmerc(0,0) to EPSG:32632 (P05 approach)
4. **candidate_local_origin_correction** — Translate origin if false easting/northing present
5. **candidate_alignment_transform_only** — Apply rigid SE(2) alignment without reprojection

The P05 approach (candidate_actual_reprojection) is the only one that produces coordinate-comparable results.

## 1A.4 Manual Map Frames

Both manual grids (Grid0821 and Grid0828) share identical bounds (to ~cm precision), confirming they use the **same EPSG:32632 frame**. The Grid0821 aligned artifact shows minor shifts (meters) from the alignment process.

No evidence of different origins/offsets between the two manual grids.

## 1A.5 Control Points

Distributed control points needed for Phase 1C verification:
- North/south/east/west extents of manual bbox
- Map centre
- Major junctions (identifiable in both auto and manual)
- Roundabouts
- Curved road segments
- Bridge/tunnel locations (if any)
- Historical high-error sectors (from P05 stratification)
- Tile boundaries (if tiling re-enabled)

## Next Steps

Proceed to **Phase 1B** — create coordinate correction candidates and test them with the required coordinate tests (round-trip, inverse consistency, metamorphic invariance, negative controls).