# ultimate_pipeline/core/odr_io.py
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional
import xml.etree.ElementTree as ET

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.file_utils import read_xodr, write_xodr
from ultimate_pipeline.core.georef_utils import normalize_georeference


def load_xodr(path: str) -> Tuple[ET.ElementTree, ET.Element]:
    """
    Wrapper around read_xodr that returns (tree, root).
    """
    return read_xodr(path)


def save_xodr(tree: ET.ElementTree, path: str) -> None:
    """
    Wrapper around write_xodr.
    """
    write_xodr(tree, path)


def _normalize_georeference(text: Optional[str]) -> str:
    """
    Normalize geoReference whitespace for comparison purposes.
    Collapses all whitespace to single spaces, strips leading/trailing.
    Also strips CDATA wrappers for comparison.
    Does NOT change semantic meaning.
    """
    return normalize_georeference(text)


def _is_valid_georeference(text: Optional[str]) -> bool:
    """
    Check if geoReference is valid/well-formed.

    A geoReference is considered valid if:
    - It is non-empty after normalization (including CDATA stripping)
    - It contains a projection definition (+proj=)

    Handles:
    - Standard PROJ.4 strings: +proj=utm, +proj=tmerc, etc.
    - Pipeline projections: +proj=pipeline +step ...
    - CDATA-wrapped geoReferences (common in manual CARLA maps)
    - Multi-line formatted projections

    Returns False for missing, empty, whitespace-only, or truly malformed values.
    """
    if text is None:
        return False
    normalized = _normalize_georeference(text)
    if not normalized:
        return False
    # Must contain a projection definition to be considered valid
    # This catches +proj=utm, +proj=tmerc, +proj=pipeline, etc.
    return "+proj=" in normalized


def _build_georeference_string(lat0: float, lon0: float) -> str:
    """Build a canonical geoReference string from lat/lon."""
    return (
        f"+proj=tmerc +lat_0={lat0} +lon_0={lon0} "
        "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )


def check_original_has_valid_georeference(input_xodr_path: str) -> bool:
    """
    Check if the ORIGINAL input file has a valid geoReference.

    This is used to determine policy: if the original map author included
    a geoReference, we should preserve it. If the original had none, we
    should create one from coordinates.json.

    This check is separate from the sanitized file because the sanitizer
    may create a default geoReference that shouldn't be preserved.
    """
    try:
        tree = ET.parse(input_xodr_path)
        root = tree.getroot()
        header = root.find("header")
        if header is None:
            return False
        geo = header.find("geoReference")
        if geo is None:
            return False
        return _is_valid_georeference(geo.text)
    except Exception:
        return False


def handle_georeference(
    root,
    lat0: float | None = None,
    lon0: float | None = None,
    policy: str = "preserve"
) -> Dict[str, Any]:
    """
    Conditionally handle <geoReference> with provenance tracking.

    Academic Policy (default: "preserve"):
    - If existing geoReference is valid (non-empty and contains +proj=), KEEP it.
    - If missing, empty, whitespace-only, or malformed -> patch from coordinates.json.
    - Always record provenance for transparency.

    Args:
        root: OpenDRIVE XML root element
        lat0: Override latitude (else from SETTINGS.load_gps_bounds())
        lon0: Override longitude (else from SETTINGS.load_gps_bounds())
        policy: "preserve" (default) = keep valid existing; "force" = always overwrite

    Returns:
        Decision struct:
        {
            "action": "kept" | "patched" | "created",
            "original_raw": str | None,
            "original_norm": str | None,
            "final_raw": str,
            "final_norm": str,
            "reason": "already_valid" | "missing" | "empty" | "whitespace_only" | "malformed" | "forced",
            "source_lat0": float,
            "source_lon0": float,
        }
    """
    # Load GPS bounds for potential patching
    if lat0 is None or lon0 is None:
        gps = SETTINGS.load_gps_bounds()
        lat0 = gps["lat_min"]
        lon0 = gps["lon_min"]

    header = root.find("header")
    if header is None:
        raise RuntimeError("OpenDRIVE root has no <header> element")

    geo = header.find("geoReference")

    # Capture original state
    original_raw: Optional[str] = None
    original_norm: Optional[str] = None
    if geo is not None and geo.text is not None:
        original_raw = geo.text
        original_norm = _normalize_georeference(geo.text)

    # Determine reason for action
    if geo is None:
        reason = "missing"
        needs_patch = True
    elif geo.text is None:
        reason = "empty"
        needs_patch = True
    elif not geo.text.strip():
        reason = "whitespace_only"
        needs_patch = True
    elif not _is_valid_georeference(geo.text):
        reason = "malformed"
        needs_patch = True
    elif policy == "force":
        reason = "forced"
        needs_patch = True
    else:
        reason = "already_valid"
        needs_patch = False

    # Apply patch if needed
    if needs_patch:
        if geo is None:
            geo = ET.SubElement(header, "geoReference")
            action = "created"
        else:
            action = "patched"

        enforced_georef = _build_georeference_string(lat0, lon0)
        geo.text = enforced_georef
    else:
        action = "kept"

    # Capture final state
    final_raw = geo.text if geo is not None else ""
    final_norm = _normalize_georeference(final_raw)

    return {
        "action": action,
        "original_raw": original_raw,
        "original_norm": original_norm,
        "final_raw": final_raw,
        "final_norm": final_norm,
        "reason": reason,
        "source_lat0": lat0,
        "source_lon0": lon0,
    }


def write_georeference_provenance(
    decision: Dict[str, Any],
    output_dir: str,
    input_xodr_path: str,
    output_xodr_path: str,
    coordinates_json_path: Optional[str] = None,
    original_had_valid_georef: Optional[bool] = None,
    policy_used: Optional[str] = None,
) -> str:
    """
    Write geoReference provenance record to JSON file.

    This supports academic reproducibility by documenting exactly what
    happened to the geoReference during pipeline execution.

    DETERMINISM: The main provenance file is fully deterministic (no timestamp).
    A separate _meta.json file contains the timestamp for human inspection,
    but is NOT included in fingerprint/hash calculations.

    Args:
        decision: Decision struct from handle_georeference()
        output_dir: Directory to write provenance file
        input_xodr_path: Path to input XODR file
        output_xodr_path: Path to output XODR file
        coordinates_json_path: Path to coordinates.json (optional)
        original_had_valid_georef: Whether the original input had valid geoRef
        policy_used: The policy that was applied ("preserve" or "force")

    Returns:
        Path to the written provenance file (deterministic, hashable)
    """
    os.makedirs(output_dir, exist_ok=True)
    provenance_path = os.path.join(output_dir, "georeference_provenance.json")
    meta_path = os.path.join(output_dir, "georeference_provenance_meta.json")

    # Main provenance: DETERMINISTIC (no timestamp) - safe for hashing/fingerprinting
    provenance = {
        "schema_version": "1.0",
        "input_xodr": input_xodr_path,
        "output_xodr": output_xodr_path,
        "coordinates_json": coordinates_json_path or SETTINGS.COORDINATES_JSON,
        "original_input_had_valid_georeference": original_had_valid_georef,
        "policy_used": policy_used,
        "action": decision["action"],
        "reason": decision["reason"],
        "original_georeference_raw": decision["original_raw"],
        "original_georeference_normalized": decision["original_norm"],
        "final_georeference_raw": decision["final_raw"],
        "final_georeference_normalized": decision["final_norm"],
        "source_gps_bounds": {
            "lat0": decision["source_lat0"],
            "lon0": decision["source_lon0"],
        },
    }

    with open(provenance_path, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2, ensure_ascii=False)

    # Metadata file: NON-DETERMINISTIC (timestamp) - excluded from hashing
    # This file is for human inspection / thesis audit trail only.
    meta = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provenance_file": "georeference_provenance.json",
        "_note": "This file contains non-deterministic metadata. Exclude from fingerprinting.",
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return provenance_path


def force_georeference(root, lat0: float | None = None, lon0: float | None = None) -> None:
    """
    Ensure <geoReference> exists on the <header> and matches coordinates.json.

    DEPRECATED: Use handle_georeference() for new code to preserve existing
    geoReferences and track provenance. This function unconditionally overwrites.

    If lat0/lon0 are provided explicitly, they override coordinates.json.
    Otherwise, they are taken from SETTINGS.load_gps_bounds().
    """
    # fallback to coordinates.json if explicit values not given
    if lat0 is None or lon0 is None:
        gps = SETTINGS.load_gps_bounds()
        lat0 = gps["lat_min"]
        lon0 = gps["lon_min"]

    header = root.find("header")
    if header is None:
        raise RuntimeError("OpenDRIVE root has no <header> element")

    geo = header.find("geoReference")
    if geo is None:
        geo = ET.SubElement(header, "geoReference")

    geo.text = _build_georeference_string(lat0, lon0)
