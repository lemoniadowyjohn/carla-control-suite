#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEM-001 — DEM provenance record.

Records DEM path, SHA-256 hash, CRS, vertical datum if known, bounds,
resolution, no-data value, and provider/licence.  ``verify_dem_provenance``
re-checks the stored hash against the file on disk so release evidence can
prove the DEM has not drifted.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def sha256_file(path: str, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class DEMProvenance:
    path: str
    sha256: str
    crs: Optional[str] = None
    vertical_datum: Optional[str] = None
    bounds: Optional[Dict[str, float]] = None
    resolution_m: Optional[float] = None
    no_data: Optional[float] = None
    provider: Optional[str] = None
    licence: Optional[str] = None
    recorded_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    file_bytes: Optional[int] = None
    # Observed raster values (when verify_against_raster=True)
    _observed_crs: Optional[str] = field(default=None, repr=False)
    _observed_bounds: Optional[Dict[str, float]] = field(default=None, repr=False)
    _observed_nodata: Optional[float] = field(default=None, repr=False)
    _observed_resolution_m: Optional[float] = field(default=None, repr=False)
    _rasterio_unavailable: Optional[bool] = field(default=None, repr=False)
    _raster_read_error: Optional[str] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "path": self.path,
            "sha256": self.sha256,
            "crs": self.crs,
            "vertical_datum": self.vertical_datum,
            "bounds": self.bounds,
            "resolution_m": self.resolution_m,
            "no_data": self.no_data,
            "provider": self.provider,
            "licence": self.licence,
            "recorded_at_utc": self.recorded_at_utc,
            "file_bytes": self.file_bytes,
        }
        # Include observed raster values if present
        if self._observed_crs is not None:
            result["observed_crs"] = self._observed_crs
        if self._observed_bounds is not None:
            result["observed_bounds"] = self._observed_bounds
        if self._observed_nodata is not None:
            result["observed_nodata"] = self._observed_nodata
        if self._observed_resolution_m is not None:
            result["observed_resolution_m"] = self._observed_resolution_m
        if self._rasterio_unavailable is not None:
            result["rasterio_unavailable"] = self._rasterio_unavailable
        if self._raster_read_error is not None:
            result["raster_read_error"] = self._raster_read_error
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DEMProvenance":
        obj = cls(
            path=str(data.get("path", "")),
            sha256=str(data.get("sha256", "")),
            crs=data.get("crs"),
            vertical_datum=data.get("vertical_datum"),
            bounds=data.get("bounds"),
            resolution_m=data.get("resolution_m"),
            no_data=data.get("no_data"),
            provider=data.get("provider"),
            licence=data.get("licence"),
            recorded_at_utc=str(data.get("recorded_at_utc", "")),
            file_bytes=data.get("file_bytes"),
            extra=data.get("extra"),
        )
        obj._observed_crs = data.get("observed_crs")
        obj._observed_bounds = data.get("observed_bounds")
        obj._observed_nodata = data.get("observed_nodata")
        obj._observed_resolution_m = data.get("observed_resolution_m")
        obj._rasterio_unavailable = data.get("rasterio_unavailable")
        obj._raster_read_error = data.get("raster_read_error")
        return obj


def record_dem_provenance(
    path: str,
    *,
    crs: Optional[str] = None,
    vertical_datum: Optional[str] = None,
    bounds: Optional[Dict[str, float]] = None,
    resolution_m: Optional[float] = None,
    no_data: Optional[float] = None,
    provider: Optional[str] = None,
    licence: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    verify_against_raster: bool = False,
) -> DEMProvenance:
    """Compute and record provenance for a DEM file.

    When verify_against_raster=True and rasterio is available, reads the
    actual CRS, bounds, resolution, and nodata from the raster file and
    includes them in the provenance record. Declared values are kept as
    metadata but actual raster values are recorded separately for verification.
    """
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"DEM not found: {path}")

record = DEMProvenance(
        path=os.path.abspath(path),
        sha256=sha256_file(path),
        crs=crs,
        vertical_datum=vertical_datum,
        bounds=bounds,
        resolution_m=resolution_m,
        no_data=no_data,
        provider=provider,
        licence=licence,
        file_bytes=os.path.getsize(path),
        extra=extra,
    )

    if verify_against_raster:
        try:
            import rasterio
            with rasterio.open(path) as ds:
                record._observed_crs = str(ds.crs) if ds.crs else None
                record._observed_bounds = {
                    "left": float(ds.bounds.left),
                    "bottom": float(ds.bounds.bottom),
                    "right": float(ds.bounds.right),
                    "top": float(ds.bounds.top),
                } if ds.bounds else None
                record._observed_nodata = float(ds.nodata) if ds.nodata is not None else None
                if ds.res:
                    record._observed_resolution_m = float(ds.res[0])
                else:
                    record._observed_resolution_m = None
                # Try to extract vertical datum from CRS if available
                try:
                    from pyproj import CRS
                    crs_obj = CRS.from_user_input(ds.crs) if ds.crs else None
                    if crs_obj and crs_obj.is_compound:
                        # Get the vertical component
                        sub_crs_list = crs_obj.sub_crs_list
                        for sub_crs in sub_crs_list:
                            if sub_crs.is_vertical:
                                record.vertical_datum = sub_crs.name
                                break
                except Exception:
                    pass
        except ImportError:
            record._rasterio_unavailable = True
        except Exception as exc:
            record._raster_read_error = str(exc)

    return record


def verify_dem_provenance(record: DEMProvenance, *, path: Optional[str] = None) -> Dict[str, Any]:
    """Re-hash the file on disk and compare against the recorded hash."""
    target = path or record.path
    if not os.path.isfile(target):
        return {"ok": False, "reason": "missing", "recorded": record.sha256}
    try:
        current = sha256_file(target)
    except Exception as exc:
        return {"ok": False, "reason": f"hash_error: {exc}", "recorded": record.sha256}
    match = current == record.sha256
    return {"ok": match, "reason": "match" if match else "hash_mismatch", "recorded": record.sha256, "current": current}


def save_dem_provenance(record: DEMProvenance, out_path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(record.to_dict(), fh, indent=2)
    return out_path


def load_dem_provenance(path: str) -> DEMProvenance:
    with open(path, encoding="utf-8") as fh:
        return DEMProvenance.from_dict(json.load(fh))
