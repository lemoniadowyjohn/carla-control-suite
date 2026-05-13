import os
import requests
from pathlib import Path


def download_dem_for_bounds(
    lat_min, lat_max, lon_min, lon_max, dem_type, api_key, out_path
):
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
    redacted_url = (
        url.replace(f"API_Key={api_key}", "API_Key=***REDACTED***")
        if api_key
        else url.replace("API_Key=", "API_Key=***REDACTED***")
    )
    print(f"   URL: {redacted_url}")

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
        out_path=dem_path,
    )


def _parse_osm_bbox(bbox_str: str):
    """
    Parse `lat_min,lon_min,lat_max,lon_max` into floats.

    Naming uses OSM convention (lat,lon), but OpenTopography API also expects
    south/north/west/east in degrees.
    """
    parts = [p.strip() for p in str(bbox_str).split(",") if p.strip()]
    if len(parts) != 4:
        raise ValueError(
            "Invalid bbox. Expected 'lat_min,lon_min,lat_max,lon_max' (4 comma-separated numbers)."
        )
    lat_min, lon_min, lat_max, lon_max = [float(p) for p in parts]
    if lat_max < lat_min:
        lat_min, lat_max = lat_max, lat_min
    if lon_max < lon_min:
        lon_min, lon_max = lon_max, lon_min
    return lat_min, lon_min, lat_max, lon_max


def _apply_margin(lat_min, lon_min, lat_max, lon_max, margin_deg: float):
    m = float(margin_deg)
    return lat_min - m, lon_min - m, lat_max + m, lon_max + m


def ensure_dem_covers_bbox(
    projected_bbox_wgs84: dict,
    dem_path: str,
    dem_type: str,
    api_key: str,
    margin_deg: float = 0.01,
    expanded_dem_dir: str = None,
) -> str:
    """
    Ensures DEM covers the map bbox (projected_bbox_wgs84).

    If existing DEM doesn't cover it, downloads an expanded DEM.
    Returns path to the DEM that covers the bbox.

    Args:
        projected_bbox_wgs84: {"minx": lon_min, "miny": lat_min, "maxx": lon_max, "maxy": lat_max}
        dem_path: Path to existing DEM
        dem_type: OpenTopography demtype (e.g., COP30)
        api_key: OpenTopography API key
        margin_deg: Margin to add around bbox (default 0.01° ≈ 1.1km)
        expanded_dem_dir: Directory for expanded DEM (default: same as dem_path with _expanded suffix)

    Returns:
        Path to DEM that covers the bbox
    """
    import rasterio
    from rasterio.warp import transform_bounds

    # Check if existing DEM covers the bbox
    if os.path.exists(dem_path):
        try:
            with rasterio.open(dem_path) as src:
                # Transform DEM bounds from native CRS to WGS84 for comparison
                if src.crs and str(src.crs).upper() != "EPSG:4326":
                    dem_bounds_wgs84 = transform_bounds(
                        src.crs, "EPSG:4326",
                        src.bounds.left, src.bounds.bottom,
                        src.bounds.right, src.bounds.top
                    )
                    dem_left, dem_bottom, dem_right, dem_top = dem_bounds_wgs84
                else:
                    # DEM is already in WGS84
                    dem_left = src.bounds.left
                    dem_bottom = src.bounds.bottom
                    dem_right = src.bounds.right
                    dem_top = src.bounds.top

                map_bbox = projected_bbox_wgs84

                covers = (
                    dem_left <= map_bbox["minx"] and
                    dem_bottom <= map_bbox["miny"] and
                    dem_right >= map_bbox["maxx"] and
                    dem_top >= map_bbox["maxy"]
                )

                if covers:
                    print(f"   ✔ Existing DEM covers map bbox: {dem_path}")
                    return dem_path
                else:
                    print(f"   ⚠ Existing DEM does not fully cover map bbox.")
                    print(f"      DEM bounds (WGS84): lon [{dem_left:.6f}, {dem_right:.6f}], lat [{dem_bottom:.6f}, {dem_top:.6f}]")
                    print(f"      Map bbox:           lon [{map_bbox['minx']:.6f}, {map_bbox['maxx']:.6f}], lat [{map_bbox['miny']:.6f}, {map_bbox['maxy']:.6f}]")
        except Exception as e:
            print(f"   ⚠ Could not read existing DEM bounds: {e}")

    # Need to download expanded DEM
    if not api_key:
        raise RuntimeError(
            "DEM does not cover map bbox and no OpenTopography API key provided. "
            "Set OPENTOPO_API_KEY or UP_OPENTOPO_API_KEY, or manually provide a larger DEM."
        )

    # Compute expanded bbox
    map_bbox = projected_bbox_wgs84
    lat_min = map_bbox["miny"] - margin_deg
    lat_max = map_bbox["maxy"] + margin_deg
    lon_min = map_bbox["minx"] - margin_deg
    lon_max = map_bbox["maxx"] + margin_deg

    # Determine output path
    if expanded_dem_dir:
        Path(expanded_dem_dir).mkdir(parents=True, exist_ok=True)
        out_path = str(Path(expanded_dem_dir) / "dem_expanded.tif")
    else:
        dem_dir = Path(dem_path).parent
        out_path = str(dem_dir / "dem_expanded.tif")

    print(f"   📥 Downloading expanded DEM with margin {margin_deg}°...")
    print(f"      Expanded bbox: lon [{lon_min:.6f}, {lon_max:.6f}], lat [{lat_min:.6f}, {lat_max:.6f}]")

    download_dem_for_bounds(
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        dem_type=dem_type,
        api_key=api_key,
        out_path=out_path,
    )

    return out_path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Download a clipped DEM GeoTIFF via OpenTopography global DEM API."
    )
    ap.add_argument(
        "--osm-bbox",
        required=True,
        help="lat_min,lon_min,lat_max,lon_max (degrees)",
    )
    ap.add_argument(
        "--demtype",
        default=os.getenv("UP_DEM_PROVIDER", "") or os.getenv("DEM_PROVIDER", "") or "COP30",
        help="OpenTopography demtype (e.g., COP30, SRTMGL1). Default: env UP_DEM_PROVIDER or COP30.",
    )
    ap.add_argument(
        "--api-key",
        default=os.getenv("OPENTOPO_API_KEY", "") or os.getenv("UP_OPENTOPO_API_KEY", ""),
        help="OpenTopography API key (env OPENTOPO_API_KEY).",
    )
    ap.add_argument(
        "--out",
        default="dem_clip.tif",
        help="Output GeoTIFF path.",
    )
    ap.add_argument(
        "--margin-deg",
        type=float,
        default=0.0,
        help="Optional +/- degree margin added to bbox (e.g., 0.01).",
    )

    args = ap.parse_args()
    lat_min, lon_min, lat_max, lon_max = _parse_osm_bbox(args.osm_bbox)
    if float(args.margin_deg) != 0.0:
        lat_min, lon_min, lat_max, lon_max = _apply_margin(
            lat_min, lon_min, lat_max, lon_max, float(args.margin_deg)
        )

    download_dem_for_bounds(
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        dem_type=str(args.demtype),
        api_key=str(args.api_key),
        out_path=str(args.out),
    )
