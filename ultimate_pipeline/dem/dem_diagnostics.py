#!/usr/bin/env python3
from __future__ import annotations

import os
from typing import Optional

try:
    import rasterio  # type: ignore
except Exception:
    rasterio = None  # type: ignore


class DEMDiagnostics:
    @staticmethod
    def summarize(dem_path: str) -> dict:
        """
        Quick sanity-check of a DEM GeoTIFF.

        Important: rasterio is an optional dependency.
        If rasterio is not installed, we still return a valid summary dict
        so the pipeline can continue (typically with flat elevation / DEM disabled).
        """
        if not os.path.exists(dem_path):
            return {"exists": False, "error": f"DEM not found: {dem_path}", "path": dem_path}

        # If rasterio is unavailable, do NOT crash pipeline at import-time.
        if rasterio is None:
            try:
                size_bytes = os.path.getsize(dem_path)
            except Exception:
                size_bytes = None

            return {
                "exists": True,
                "path": dem_path,
                "rasterio_available": False,
                "file_bytes": size_bytes,
                "note": "rasterio not installed -> DEM diagnostics disabled (pipeline can continue with flat elevation).",
            }

        # rasterio is available -> do actual inspection
        try:
            with rasterio.open(dem_path) as ds:  # type: ignore[union-attr]
                bounds = ds.bounds
                crs = str(ds.crs)
                res = ds.res
                nodata = ds.nodata

                # Read band 1 (can be large; still ok for typical cropped DEMs)
                band = ds.read(1)
                min_val = float(band.min())
                max_val = float(band.max())

            return {
                "exists": True,
                "path": dem_path,
                "rasterio_available": True,
                "crs": crs,
                "bounds": {
                    "left": float(bounds.left),
                    "bottom": float(bounds.bottom),
                    "right": float(bounds.right),
                    "top": float(bounds.top),
                },
                "resolution": {"x": float(res[0]), "y": float(res[1])},
                "nodata": nodata,
                "elevation_min": min_val,
                "elevation_max": max_val,
            }

        except Exception as e:
            # DEM exists but cannot be opened/parsed
            return {
                "exists": True,
                "path": dem_path,
                "rasterio_available": True,
                "error": f"rasterio_failed_to_open: {e}",
            }
