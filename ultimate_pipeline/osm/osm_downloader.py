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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

# Primary + fallback Overpass endpoints

def _force_refresh_enabled() -> bool:
    v = os.environ.get("UP_FORCE_OSM_DOWNLOAD", "").strip() or os.environ.get("UP_REFRESH_OSM", "").strip()
    return v.lower() in ("1", "true", "yes", "on")


def _backup_existing(path: Path) -> None:
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup = path.with_name(path.name + f".bak_{ts}")
        path.replace(backup)
    except Exception:
        return


OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


class OSMInputValidationError(RuntimeError):
    """Raised when an OSM XML input is missing, malformed, or not real map data."""


def looks_like_html_or_api_error(data: bytes | str) -> bool:
    """Detect common Overpass/html failure payloads before XML conversion."""
    if isinstance(data, bytes):
        text = data[:4096].decode("utf-8", errors="ignore")
    else:
        text = str(data)[:4096]
    lower = text.lstrip("\ufeff \t\r\n").lower()
    return any(
        marker in lower
        for marker in (
            "<!doctype html",
            "<html",
            "<body",
            "overpass api error",
            "osm3s runtime error",
            "runtime error:",
            "query timed out",
            "too many requests",
            "rate limit",
            "gateway timeout",
        )
    )


def validate_osm_xml_input(osm_path: str | Path, *, min_features: int = 1) -> Path:
    """Fail closed unless ``osm_path`` is a non-empty OSM 0.6-style XML extract."""
    path = Path(osm_path)
    if not path.exists():
        raise OSMInputValidationError(f"OSM input file not found: {path}")
    if not path.is_file():
        raise OSMInputValidationError(f"OSM input path is not a file: {path}")
    if path.stat().st_size <= 0:
        raise OSMInputValidationError(f"OSM input is empty: {path}")

    head = path.read_bytes()[:4096]
    if looks_like_html_or_api_error(head):
        raise OSMInputValidationError(
            f"OSM input looks like an HTML/API error response, not OSM XML: {path}"
        )

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise OSMInputValidationError(f"OSM input is not parseable XML: {path}: {exc}") from exc

    if root.tag != "osm":
        raise OSMInputValidationError(
            f"OSM input root element must be <osm>, got <{root.tag}>: {path}"
        )

    feature_count = sum(len(root.findall(tag)) for tag in ("node", "way", "relation"))
    if feature_count < int(min_features):
        raise OSMInputValidationError(
            f"OSM input has no OSM nodes/ways/relations: {path}"
        )

    return path

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

        validate_osm_xml_input(out_path)
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
            if _force_refresh_enabled():
                if requests is None:
                    print(f"⚠️ [OSM] Force refresh requested but requests not available; using existing → {osm_path}")
                    validate_osm_xml_input(osm_path)
                    return str(osm_path)
                print(f"📥 [OSM] Force refresh enabled — re-downloading xml…")
                _backup_existing(osm_path)
            else:
                validate_osm_xml_input(osm_path)
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
            if _force_refresh_enabled():
                if requests is None:
                    print(f"⚠️ [OSM] Force refresh requested but requests not available; using existing → {json_path}")
                    return str(json_path)
                print(f"📥 [OSM] Force refresh enabled — re-downloading json…")
                _backup_existing(json_path)
            else:
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
            if _force_refresh_enabled():
                if requests is None:
                    print(f"⚠️ [OSM] Force refresh requested but requests not available; using existing → {geojson_path}")
                    return str(geojson_path)
                print(f"📥 [OSM] Force refresh enabled — re-downloading geojson…")
                _backup_existing(geojson_path)
            else:
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
