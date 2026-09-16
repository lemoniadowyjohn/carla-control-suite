# DEM Availability Check — Ingolstadt Elevation Gate

**Date:** 2026-09-16
**Verdict:** **(a) A usable DEM exists and is correctly wired to the settings path.**

---

## Executive Summary

A valid DEM raster for the Ingolstadt area **exists** at the expected path, is readable
by `rasterio`, covers the full map bounding box, and the settings resolve to it correctly.
The "planar/no-DEM map" label in prior audit reports was a **mischaracterization** — the
`ElevationGap` domain-gap module computes XODR-to-XODR elevation profile differences
(not DEM-based), and it returns `disabled` when road profiles can't be matched between
manual and auto maps. This is expected behavior for planar maps, not a DEM availability issue.

The DEM is used by **Stage 5** (`stage_05_geometry.py`) for terrain elevation sampling,
which is a separate pipeline stage from the domain-gap elevation comparison.

---

## Checklist Results

### 1. Expected Path/Settings

| Setting | Value | Source |
|---|---|---|
| `DEM_DIR` | `cities/ingolstadt/dem` | `settings.py:791-796` via `city_dir("ingolstadt") / "dem"` |
| `DEM_FILENAME` | `dem_ing.tif` | `settings.py:797` |
| `DEM_TIF` (computed) | `cities/ingolstadt/dem/dem_ing.tif` | `settings.py:807-808` |
| `DEM_EXPANDED_TIF_PATH` | `cities/ingolstadt/dem/dem_ing_expanded.tif` | `settings.py:798-804` |
| `DEM_PROVIDER` | `COP30` | `settings.py:788` |
| `ENABLE_DEM_AUTO_DOWNLOAD` | `True` | `settings.py:789` |

The `DEM_TIF` property (`settings.py:807-808`) joins `DEM_DIR` + `DEM_FILENAME`.
`DEM_DIR` resolves via `city_dir("ingolstadt")` → `cities_root() / "ingolstadt"`.
`cities_root()` (`paths.py:20-39`) checks `UP_CITIES_DIR` env, then
`<repo>/ultimate_pipeline/cities`, then `<repo>/cities`. Since `ultimate_pipeline/cities`
doesn't exist, it falls back to `<repo>/cities`.

### 2. Does the File Exist?

**YES.**

```
Path:     F:\...\cities\ingolstadt\dem\dem_ing.tif
Size:     1,711,684 bytes (1.7 MB)
Modified: 2026-09-16 02:09:59
```

Verified via `os.path.isfile(SETTINGS.DEM_TIF)` → `True`.

The expanded DEM (`dem_ing_expanded.tif`) does **not** exist, but the pipeline
falls back to the base DEM when the expanded path is missing (`stage_05_geometry.py:327-331`).

### 3. Auto-Download Configuration

| Item | Status |
|---|---|
| `ENABLE_DEM_AUTO_DOWNLOAD` | `True` |
| `DEM_PROVIDER` | `COP30` (Copernicus DEM 30m) |
| `OPENTOPO_API_KEY` env var | **Set** (`bd362006...`) |
| Auto-download mechanism | `ensure_dem_exists()` in `dem_auto_downloader.py:61-86` |
| Could it work? | **Yes** — API key is present, provider is valid, download endpoint is `portal.opentopography.org` |

Auto-download is a fallback for when the DEM file is missing. Since the file already
exists, auto-download is not needed for current runs.

### 4. Search for DEM Rasters

| Location | Found? | Notes |
|---|---|---|
| `cities/ingolstadt/dem/dem_ing.tif` | **YES** | The canonical DEM (1.7 MB) |
| `cities/ingolstadt/dem/dem_ing_expanded.tif` | No | Not yet generated |
| Any other `.tif`/`.tiff` in repo | No | Only `scene_dem_elevated.obj` (3D model, not raster) |
| `C:\Users\admin\**\*.tif` | No other DEMs | — |

### 5. DEM Validity (rasterio)

```
CRS:           WGS 84 (EPSG:4326)
Bounds:        lon [11.3121, 11.5374] lat [48.6743, 48.8363]
Resolution:    0.000278° (~30m)
Dimensions:    811 x 583 pixels
Valid pixels:  472,813 (of 472,813 — no nodata)
Elevation:     346.79m — 487.01m (mean 378.85m)
```

### 6. Coverage Check

```
Map bounds (DEFAULT_GPS_BOUNDS):
  lon [11.4223, 11.4788] lat [48.7494, 48.7744]
  ~4,150m x 2,773m

DEM fully covers map: YES
```

The DEM bounds extend well beyond the map bbox in all directions
(~12km x 18km DEM vs ~4km x 3km map).

---

## Why Prior Reports Said "planar/no-DEM map"

The string `"elevation_comparison": "DISABLED (planar/no-DEM map)"` appears in:
- `reports/production_readiness/20260915T203000Z_COMPREHENSIVE_GAP_AUDIT/RQ_COMPLETENESS_MATRIX.json`
- `reports/production_readiness/20260915T203000Z_COMPREHENSIVE_GAP_AUDIT/LARGE_MAP_AUDIT.json`

This was a **human-written observation** by the auditor, not a programmatic output.
The `ElevationGap.compute()` method (`elevation_gap.py:276-359`) compares XODR
`<elevationProfile>` polynomials between manual and auto maps. It returns
`{"disabled": True, "reason": "missing_road_profiles"}` or `"no_matched_roads"`
when the XODR files lack elevation data or roads can't be matched — which is the
case for planar (flat-elevation) maps. The auditor interpreted this correctly as
"the map is planar" but incorrectly implied a DEM was missing.

The DEM is used by a **different** pipeline stage (Stage 5) for terrain elevation
sampling, not by the domain-gap elevation comparison.

---

## Architecture Clarification

Two separate elevation systems exist in this pipeline:

1. **Stage 5 — DEM Elevation Sampling** (`stage_05_geometry.py`)
   - Loads `dem_ing.tif` via `ElevationImporter.make_raster_sampler()`
   - Samples terrain elevation at road geometry XY positions
   - Applies elevation profiles to the XODR
   - Has full DEM QC: coverage gate, nodata ratio, CRS validation
   - **This is where the DEM is used.**

2. **Domain Gap — Elevation Comparison** (`elevation_gap.py`)
   - Compares `<elevationProfile>` polynomials between two XODR files
   - Does NOT load any DEM raster
   - Returns "disabled" when roads can't be matched (expected for planar maps)
   - **This is NOT a DEM-dependent module.**

---

## Conclusion

**Answer: (a) — A usable DEM exists and is correctly wired.**

No config fix is needed. The DEM is present, valid, and the settings resolve to it.
The "planar/no-DEM map" label was a misinterpretation of the domain-gap elevation
module's disabled status, which is unrelated to DEM availability.
