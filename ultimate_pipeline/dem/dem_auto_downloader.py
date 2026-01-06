import os
import requests
from pathlib import Path


def download_dem_for_bounds(lat_min, lat_max, lon_min, lon_max, dem_type, api_key, out_path):
    """
    Downloads clipped DEM GeoTIFF using OpenTopography global DEM API.
    Requires API key for most high-resolution DEMs.
    """

    Path(os.path.dirname(out_path)).mkdir(parents=True, exist_ok=True)

    url = (
        "https://portal.opentopography.org/API/globaldem?"
        f"demtype={dem_type}"
        f"&south={lat_min}&north={lat_max}"
        f"&west={lon_min}&east={lon_max}"
        f"&outputFormat=GTiff"
        f"&API_Key={api_key}"
    )

    print(f"🌍 Requesting DEM ({dem_type}) from OpenTopography...")
    print(f"   URL: {url}")

    r = requests.get(url, stream=True)

    if r.status_code != 200:
        raise RuntimeError(f"DEM download failed: HTTP {r.status_code}")

    with open(out_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"   ✅ DEM downloaded → {out_path}")
    return out_path


def ensure_dem_exists(gps_bounds, dem_path, dem_type, api_key):
    """
    Checks if DEM exists; otherwise downloads it.
    """

    if os.path.exists(dem_path):
        print(f"   ✔ DEM already present: {dem_path}")
        return dem_path

    if not api_key:
        raise RuntimeError(
            "Missing OpenTopography API key. "
            "Set SETTINGS.OPENTOPO_API_KEY or disable ENABLE_DEM_AUTO_DOWNLOAD."
        )

    print("   ⚠ DEM missing → downloading automatically...")

    return download_dem_for_bounds(
        lat_min=gps_bounds["lat_min"],
        lat_max=gps_bounds["lat_max"],
        lon_min=gps_bounds["lon_min"],
        lon_max=gps_bounds["lon_max"],
        dem_type=dem_type,
        api_key=api_key,
        out_path=dem_path
    )
