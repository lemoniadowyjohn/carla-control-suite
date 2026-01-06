#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSM Downloader (Consolidated & Hardened)

Provides:
    • XML OSM extract (nodes + ways + relations)
    • Optional JSON / GeoJSON export
    • Retry logic (429, timeouts, slow responses)
    • Automatic caching on disk
    • Optional multi-endpoint fallback (DE → FR → CH)
    • Pipeline-friendly interface:
        ensure_osm_exists()
        ensure_osm_json_exists()
        ensure_osm_geojson_exists()
        auto_download()

Offline-safe behavior:
    - If `requests` is not installed, the module still imports successfully.
    - Downloading is disabled (raises a clear RuntimeError), but if the target OSM file
      already exists, the pipeline continues without any network access.
"""

from __future__ import annotations

try:
    import requests  # type: ignore
except Exception:
    requests = None  # type: ignore

import time
import os
from pathlib import Path
from typing import Dict, Optional

# Primary + fallback Overpass endpoints
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# ================================================================
# Internal query builders
# ================================================================

def _make_xml_query(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> str:
    """Full OSM extract (XML)."""
    return f"""
    [out:xml][timeout:180];
    (
      node({lat_min},{lon_min},{lat_max},{lon_max});
      way({lat_min},{lon_min},{lat_max},{lon_max});
      relation({lat_min},{lon_min},{lat_max},{lon_max});
    );
    out body;
    >;
    out skel qt;
    """


def _make_json_query(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> str:
    """JSON export for debugging / building footprints loader."""
    return f"""
    [out:json][timeout:180];
    (
      node({lat_min},{lon_min},{lat_max},{lon_max});
      way({lat_min},{lon_min},{lat_max},{lon_max});
      relation({lat_min},{lon_min},{lat_max},{lon_max});
    );
    out geom;
    """


def _make_geojson_query(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> str:
    """GeoJSON-like export (linestrings + polygons)."""
    return f"""
    [out:json][timeout:180];
    (
      way({lat_min},{lon_min},{lat_max},{lon_max})["building"];
      relation({lat_min},{lon_min},{lat_max},{lon_max})["building"];
    );
    out geom;
    """


# ================================================================
# Downloader class
# ================================================================

class OSMDownloader:
    """High-level Overpass OSM downloader for XML/JSON/GeoJSON."""

    MAX_RETRIES = 6
    WAIT_BASE = 6.0  # exponential backoff

    # ------------------------------------------------------------
    # Core HTTP request with fallback endpoints
    # ------------------------------------------------------------
    def _perform_request(self, query: str) -> bytes:
        # ✅ Offline / restricted environment guard
        if requests is None:
            raise RuntimeError(
                "requests is not installed, so OSM auto-download is disabled.\n"
                "Fix options:\n"
                "  1) Ensure the OSM XML file already exists at the configured path (recommended for offline).\n"
                "  2) Install 'requests' in the active venv (if network policy allows).\n"
            )

        for attempt in range(1, self.MAX_RETRIES + 1):
            for endpoint in OVERPASS_ENDPOINTS:

                print(f"🌍 Overpass request (attempt {attempt}/{self.MAX_RETRIES}) → {endpoint}")

                try:
                    response = requests.post(  # type: ignore[union-attr]
                        endpoint,
                        data={"data": query},
                        timeout=180
                    )

                    # RATE LIMIT
                    if response.status_code == 429:
                        print("⏳ Rate limited (429) → retrying on next endpoint…")
                        continue

                    # OTHER FAILURE
                    if response.status_code != 200:
                        print(f"⚠ HTTP {response.status_code}: {response.text[:200]}")
                        continue

                    # SUCCESS
                    return response.content

                except Exception as e:
                    # Avoid tight coupling to requests.exceptions.* (still robust across environments)
                    msg = str(e)
                    if "Timeout" in msg or "timed out" in msg:
                        print("⚠ Timeout → switching endpoint…")
                        continue
                    if "Connection" in msg or "Failed to establish" in msg:
                        print("⚠ Connection error → switching endpoint…")
                        continue

                    print(f"⚠ Request error → switching endpoint… ({type(e).__name__}: {msg[:120]})")
                    continue

            # wait before next retry
            wait = self.WAIT_BASE * attempt
            print(f"⏳ Waiting {wait:.1f} seconds before retry…")
            time.sleep(wait)

        raise RuntimeError("❌ Overpass request failed after all endpoints & retries.")

    # ------------------------------------------------------------
    # Standard downloaders
    # ------------------------------------------------------------

    def download_xml(self, lat_min, lat_max, lon_min, lon_max, out_path) -> str:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        query = _make_xml_query(lat_min, lat_max, lon_min, lon_max)
        data = self._perform_request(query)

        with open(out_path, "wb") as f:
            f.write(data)

        print(f"   ✔ OSM XML saved → {out_path}")
        return str(out_path)

    def download_json(self, lat_min, lat_max, lon_min, lon_max, out_path) -> str:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        query = _make_json_query(lat_min, lat_max, lon_min, lon_max)
        data = self._perform_request(query)

        with open(out_path, "wb") as f:
            f.write(data)

        print(f"   ✔ OSM JSON saved → {out_path}")
        return str(out_path)

    def download_geojson(self, lat_min, lat_max, lon_min, lon_max, out_path) -> str:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        query = _make_geojson_query(lat_min, lat_max, lon_min, lon_max)
        data = self._perform_request(query)

        with open(out_path, "wb") as f:
            f.write(data)

        print(f"   ✔ OSM GeoJSON saved → {out_path}")
        return str(out_path)

    # ------------------------------------------------------------
    # "Ensure file exists" convenience wrappers
    # ------------------------------------------------------------

    def ensure_osm_xml_exists(self, gps_bounds: Dict[str, float], osm_path: str | Path) -> str:
        osm_path = Path(osm_path)

        if osm_path.exists():
            print(f"✔ OSM XML already exists → {osm_path}")
            return str(osm_path)

        print("📥 OSM XML missing → downloading…")
        return self.download_xml(
            gps_bounds["lat_min"],
            gps_bounds["lat_max"],
            gps_bounds["lon_min"],
            gps_bounds["lon_max"],
            osm_path,
        )

    def ensure_osm_json_exists(self, gps_bounds: Dict[str, float], json_path: str | Path) -> str:
        json_path = Path(json_path)

        if json_path.exists():
            print(f"✔ OSM JSON already exists → {json_path}")
            return str(json_path)

        print("📥 OSM JSON missing → downloading…")
        return self.download_json(
            gps_bounds["lat_min"],
            gps_bounds["lat_max"],
            gps_bounds["lon_min"],
            gps_bounds["lon_max"],
            json_path,
        )

    def ensure_osm_geojson_exists(self, gps_bounds: Dict[str, float], geojson_path: str | Path) -> str:
        geojson_path = Path(geojson_path)

        if geojson_path.exists():
            print(f"✔ OSM GeoJSON already exists → {geojson_path}")
            return str(geojson_path)

        print("📥 OSM GeoJSON missing → downloading…")
        return self.download_geojson(
            gps_bounds["lat_min"],
            gps_bounds["lat_max"],
            gps_bounds["lon_min"],
            gps_bounds["lon_max"],
            geojson_path,
        )

    # ------------------------------------------------------------
    # Full auto-download convenience wrapper
    # ------------------------------------------------------------

    def auto_download(
        self,
        gps_bounds: Dict[str, float],
        xml_path: str | Path,
        json_path: Optional[str | Path] = None,
        geojson_path: Optional[str | Path] = None,
        enable_json: bool = False,
        enable_geojson: bool = False,
    ) -> Dict[str, Optional[str]]:
        """
        Download XML + optionally JSON/GeoJSON in one call.
        """
        results = {}
        results["xml"] = self.ensure_osm_xml_exists(gps_bounds, xml_path)

        if enable_json and json_path:
            results["json"] = self.ensure_osm_json_exists(gps_bounds, json_path)
        else:
            results["json"] = None

        if enable_geojson and geojson_path:
            results["geojson"] = self.ensure_osm_geojson_exists(gps_bounds, geojson_path)
        else:
            results["geojson"] = None

        return results


# ================================================================
# Top-level pipeline wrapper (what pipeline expects)
# ================================================================

def ensure_osm_exists(gps_bounds: Dict[str, float], osm_path: str | Path) -> str:
    """
    Pipeline-friendly wrapper: ensure XML OSM exists.
    """
    return OSMDownloader().ensure_osm_xml_exists(gps_bounds, osm_path)
