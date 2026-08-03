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

    def to_dict(self) -> Dict[str, Any]:
        return {
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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DEMProvenance":
        return cls(
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
        )


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
) -> DEMProvenance:
    """Compute and record provenance for a DEM file. Raises if missing."""
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"DEM not found: {path}")
    return DEMProvenance(
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
    )


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
