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
from typing import Any, Dict, List, Optional


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
    extra: Optional[Dict[str, Any]] = None
    # Observed raster values (when verify_against_raster=True)
    _observed_crs: Optional[str] = field(default=None, repr=False)
    _observed_bounds: Optional[Dict[str, float]] = field(default=None, repr=False)
    _observed_nodata: Optional[float] = field(default=None, repr=False)
    _observed_resolution_m: Optional[float] = field(default=None, repr=False)
    _rasterio_unavailable: Optional[bool] = field(default=None, repr=False)
    _raster_read_error: Optional[str] = field(default=None, repr=False)
    # Declared-vs-observed disagreement (empty list = verified clean; None = not verified)
    _provenance_mismatches: Optional[List[str]] = field(default=None, repr=False)
    _vertical_datum_source: Optional[str] = field(default=None, repr=False)

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
            "extra": self.extra,
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
        if self._provenance_mismatches is not None:
            result["provenance_mismatches"] = self._provenance_mismatches
        if self._vertical_datum_source is not None:
            result["vertical_datum_source"] = self._vertical_datum_source
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
        obj._provenance_mismatches = data.get("provenance_mismatches")
        obj._vertical_datum_source = data.get("vertical_datum_source")
        return obj


def _normalize_crs(value: Optional[str]) -> Optional[str]:
    """Best-effort normalization for CRS comparison (e.g. 'epsg:32632' vs
    'EPSG:32632' vs a WKT string describing the same CRS). Falls back to a
    simple case-folded string compare if pyproj is unavailable or the value
    cannot be parsed."""
    if value is None:
        return None
    try:
        from pyproj import CRS as _CRS

        authority = _CRS.from_user_input(value).to_authority()
        if authority:
            return ":".join(authority)
    except Exception:
        pass
    return str(value).strip().upper()


def _compare_declared_vs_observed(
    *,
    declared_crs: Optional[str],
    observed_crs: Optional[str],
    declared_bounds: Optional[Dict[str, float]],
    observed_bounds: Optional[Dict[str, float]],
    declared_no_data: Optional[float],
    observed_no_data: Optional[float],
    declared_resolution_m: Optional[float],
    observed_resolution_m: Optional[float],
    bounds_tol_m: float = 1e-3,
) -> List[str]:
    """Compare declared metadata against values actually observed on the
    raster and return a list of human-readable mismatch descriptions (empty
    if everything declared agrees with what was observed, or nothing
    declared to compare)."""
    mismatches: List[str] = []

    if declared_crs is not None and observed_crs is not None:
        if _normalize_crs(declared_crs) != _normalize_crs(observed_crs):
            mismatches.append(
                f"crs: declared={declared_crs!r} observed={observed_crs!r}"
            )

    if declared_bounds is not None and observed_bounds is not None:
        for key in ("left", "bottom", "right", "top"):
            dv = declared_bounds.get(key)
            ov = observed_bounds.get(key)
            if dv is None or ov is None:
                continue
            try:
                if abs(float(dv) - float(ov)) > bounds_tol_m:
                    mismatches.append(
                        f"bounds.{key}: declared={dv} observed={ov}"
                    )
            except (TypeError, ValueError):
                mismatches.append(
                    f"bounds.{key}: declared={dv!r} observed={ov!r} (non-numeric)"
                )

    if declared_no_data is not None and observed_no_data is not None:
        try:
            if abs(float(declared_no_data) - float(observed_no_data)) > 1e-9:
                mismatches.append(
                    f"no_data: declared={declared_no_data} observed={observed_no_data}"
                )
        except (TypeError, ValueError):
            mismatches.append(
                f"no_data: declared={declared_no_data!r} observed={observed_no_data!r} (non-numeric)"
            )

    if declared_resolution_m is not None and observed_resolution_m is not None:
        try:
            if abs(float(declared_resolution_m) - float(observed_resolution_m)) > 1e-6:
                mismatches.append(
                    f"resolution_m: declared={declared_resolution_m} observed={observed_resolution_m}"
                )
        except (TypeError, ValueError):
            mismatches.append(
                f"resolution_m: declared={declared_resolution_m!r} "
                f"observed={observed_resolution_m!r} (non-numeric)"
            )

    return mismatches


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
    compares them against the declared values passed in. Any disagreement
    is recorded in ``record._provenance_mismatches`` (empty list if
    everything declared checks out) rather than silently trusting the
    declared metadata. Vertical datum truth cannot generally be read from a
    raster's horizontal CRS -- when the raster CRS is a compound CRS with an
    explicit vertical component that is used as a best-effort cross-check;
    otherwise the declared ``vertical_datum`` remains unverified and is
    recorded as such via ``record._vertical_datum_source``.
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
                record._observed_resolution_m = float(ds.res[0]) if ds.res else None

                record._provenance_mismatches = _compare_declared_vs_observed(
                    declared_crs=crs,
                    observed_crs=record._observed_crs,
                    declared_bounds=bounds,
                    observed_bounds=record._observed_bounds,
                    declared_no_data=no_data,
                    observed_no_data=record._observed_nodata,
                    declared_resolution_m=resolution_m,
                    observed_resolution_m=record._observed_resolution_m,
                )

                # Best-effort vertical datum cross-check: only a compound CRS
                # exposes a vertical component directly. This is NOT possible
                # for the common case (a 2D projected/geographic CRS whose
                # heights are referenced to some geoid by convention/provider
                # documentation only) -- record that honestly rather than
                # implying verification happened.
                record._vertical_datum_source = "declared_unverified"
                try:
                    from pyproj import CRS as _CRS

                    crs_obj = _CRS.from_user_input(ds.crs) if ds.crs else None
                    if crs_obj is not None and crs_obj.is_compound:
                        for sub_crs in crs_obj.sub_crs_list:
                            if sub_crs.is_vertical:
                                observed_vertical = sub_crs.name
                                if vertical_datum and observed_vertical and (
                                    observed_vertical.strip().upper()
                                    != str(vertical_datum).strip().upper()
                                ):
                                    record._provenance_mismatches.append(
                                        "vertical_datum: declared="
                                        f"{vertical_datum!r} observed_from_compound_crs="
                                        f"{observed_vertical!r}"
                                    )
                                elif not vertical_datum:
                                    record.vertical_datum = observed_vertical
                                record._vertical_datum_source = "compound_crs_verified"
                                break
                except Exception:
                    pass
        except ImportError:
            record._rasterio_unavailable = True
        except Exception as exc:
            record._raster_read_error = str(exc)

    return record


def verify_dem_provenance_against_raster(
    record: DEMProvenance, *, path: Optional[str] = None
) -> Dict[str, Any]:
    """Re-open the DEM raster and verify the record's declared CRS/bounds/
    resolution/no-data against what the file actually contains right now.

    Fails closed (``ok=False``) if rasterio is unavailable, the file cannot
    be opened, or any declared value disagrees with the observed raster --
    it never silently accepts declared metadata without checking it.
    """
    target = path or record.path
    try:
        import rasterio
    except ImportError:
        return {"ok": False, "reason": "rasterio_unavailable"}

    if not os.path.isfile(target):
        return {"ok": False, "reason": "missing", "path": target}

    try:
        with rasterio.open(target) as ds:
            observed_crs = str(ds.crs) if ds.crs else None
            observed_bounds = {
                "left": float(ds.bounds.left),
                "bottom": float(ds.bounds.bottom),
                "right": float(ds.bounds.right),
                "top": float(ds.bounds.top),
            } if ds.bounds else None
            observed_nodata = float(ds.nodata) if ds.nodata is not None else None
            observed_resolution_m = float(ds.res[0]) if ds.res else None
    except Exception as exc:
        return {"ok": False, "reason": f"open_failed:{exc}", "path": target}

    mismatches = _compare_declared_vs_observed(
        declared_crs=record.crs,
        observed_crs=observed_crs,
        declared_bounds=record.bounds,
        observed_bounds=observed_bounds,
        declared_no_data=record.no_data,
        observed_no_data=observed_nodata,
        declared_resolution_m=record.resolution_m,
        observed_resolution_m=observed_resolution_m,
    )

    return {
        "ok": not mismatches,
        "reason": "match" if not mismatches else "provenance_mismatch",
        "mismatches": mismatches,
        "observed_crs": observed_crs,
        "observed_bounds": observed_bounds,
        "observed_nodata": observed_nodata,
        "observed_resolution_m": observed_resolution_m,
    }


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
