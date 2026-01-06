# ultimate_pipeline/enrichment/elevation_importer.py

import xml.etree.ElementTree as ET
from typing import Callable, Optional

try:
    import rasterio
except ImportError:
    rasterio = None


class ElevationImporter:
    """
    Fills OpenDRIVE <elevation> records from a DEM.

    Strategy:
    - You provide a sampler: (x, y) -> z
    - For each <elevation> element: set a=z, b=c=d=0
    - If no <elevation> exists but DEM is present: create a single flat segment.
    """

    @staticmethod
    def apply_dem(root: ET.Element, sampler: Callable[[float, float], float]) -> None:
        for road in root.findall("road"):
            plan = road.find("planView")
            if plan is None:
                continue

            geos = plan.findall("geometry")
            if not geos:
                continue

            elev_elem = road.find("elevationProfile")
            if elev_elem is None:
                elev_elem = ET.SubElement(road, "elevationProfile")

            # if there are existing elevation segments, overwrite them
            existing = list(elev_elem.findall("elevation"))
            for e in existing:
                elev_elem.remove(e)

            # take start of first geometry as anchor
            g0 = geos[0]
            try:
                x0 = float(g0.get("x", "0"))
                y0 = float(g0.get("y", "0"))
            except Exception:
                x0, y0 = 0.0, 0.0

            z0 = float(sampler(x0, y0))

            ET.SubElement(elev_elem, "elevation", {
                "s": "0.0",
                "a": f"{z0:.3f}",
                "b": "0.0",
                "c": "0.0",
                "d": "0.0",
            })

    # ---------- DEM from GeoTIFF ----------

    # ---------- DEM from GeoTIFF ----------

    @staticmethod
    def make_raster_sampler(tif_path: str):
        """
        Returns a callable (x, y) -> z using a GeoTIFF DEM.

        NOTE: This assumes the DEM is in the same coordinate system
        as your OpenDRIVE x/y. If not, you must pre-transform coords.
        """
        if rasterio is None:
            raise RuntimeError("rasterio is not installed. `pip install rasterio` first.")

        import numpy as np

        from ultimate_pipeline.config.settings import SETTINGS  # to use DEM smoothing toggles

        ds = rasterio.open(tif_path)
        band1 = ds.read(1).astype(float)

        # ------------------------------------------------------------
        # DEM smoothing to avoid steep, unnatural slopes in CARLA
        # ------------------------------------------------------------
        band1_smooth = band1
        if getattr(SETTINGS, "ENABLE_DEM_SMOOTHING", True):
            try:
                from scipy.ndimage import gaussian_filter
                sigma = getattr(SETTINGS, "DEM_SMOOTHING_SIGMA", 1.0)
                print(f"🌄 Smoothing DEM using Gaussian filter (sigma={sigma})…")
                band1_smooth = gaussian_filter(band1, sigma=sigma)
            except Exception as e:
                print(f"⚠ DEM smoothing skipped (SciPy missing or error: {e})")
                band1_smooth = band1

        def sampler(x: float, y: float) -> float:
            # assumes x,y in same CRS as ds
            row, col = ds.index(x, y)
            if (
                row < 0 or col < 0 or
                row >= band1_smooth.shape[0] or col >= band1_smooth.shape[1]
            ):
                return 0.0
            try:
                return float(band1_smooth[row, col])
            except Exception:
                return 0.0

        return sampler
