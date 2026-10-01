#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/route_frame_binding.py

NEW-295: Coordinate-frame semantics executable module.

This module defines exactly what the canonical paired-route coordinates mean
and provides explicit transforms for both map arms.

The route manifest records coordinate_frame, crs, and geo_reference.
This module binds those to actual CARLA world coordinates using
pinned map/georeference identities.

Two canonical coordinate frames:
1. canonical route frame (WGS84 geo-referenced, UTM-based local meters)
2. CARLA world coordinates (Unreal-style left-handed, x-forward y-right z-up)

The transforms are:
  canonical route frame ↓ manual CARLA world coordinates (via geo_reference)
  canonical route frame ↓ generated CARLA world coordinates (via geo_reference)

If both maps genuinely share exactly the same CARLA world frame, this is
proved using pinned map/georeference identities, not assumed from matching
coordinate numbers.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, Optional, Tuple

# Import georef utilities
from ultimate_pipeline.core.georef_utils import (
    CANONICAL_MANUAL_GEOREFERENCE,
    canonical_manual_georeference,
    normalize_georeference,
    parse_georeference,
)


def canonical_dumps(obj: Any) -> str:
    """Deterministic JSON serialization for hashing."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_crs_identity(value: Any) -> Optional[int]:
    """
    NEW-295 fix: resolve a declared CRS to a canonical EPSG code.

    A route manifest may declare its frame as an authority code ("EPSG:25832")
    while a map declares the same frame as a PROJ.4 string
    ("+proj=utm +zone=32 ..."). Comparing those two as raw strings can never be
    equal, so string comparison silently reported "frame not shared" for maps
    that genuinely share a frame. Identity must be decided on resolved CRS
    identity instead.

    Returns None when the value cannot be resolved to an EPSG code; callers
    must treat None as FAIL-CLOSED, never as a match.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    text_norm = normalize_georeference(text)

    upper = text_norm.upper()
    if upper.startswith("EPSG:"):
        digits = upper[5:].strip()
        return int(digits) if digits.isdigit() else None

    if "+proj=" not in text_norm:
        return None

    try:
        from pyproj import CRS  # noqa: PLC0415 - optional dependency, imported lazily

        epsg = CRS.from_string(text_norm).to_epsg()
    except Exception:  # noqa: BLE001 - unresolvable CRS is fail-closed
        return None
    return int(epsg) if epsg else None


def route_frame_binding_from_manifest(
    route_manifest: Dict[str, Any],
    *,
    manual_geo_reference: Optional[str] = None,
    auto_geo_reference: Optional[str] = None,
    manual_map_identity: Optional[str] = None,
    auto_map_identity: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create the route coordinate-frame binding record.
    
    This proves that the route coordinates are explicitly bound to
    the map's georeference rather than being assumed.
    """
    route_crs = str(route_manifest.get("crs", ""))
    route_geo_ref = str(route_manifest.get("geo_reference", ""))
    route_frame = str(route_manifest.get("coordinate_frame", ""))

    manual_norm = normalize_georeference(manual_geo_reference) if manual_geo_reference else ""
    auto_norm = normalize_georeference(auto_geo_reference) if auto_geo_reference else ""

    # Check CRS compatibility
    manual_params_valid, manual_params_complete, _ = parse_georeference(manual_norm)
    auto_params_valid, auto_params_complete, _ = parse_georeference(auto_norm)

    # NEW-295 fix: decide frame sharing on resolved CRS identity, not on raw
    # string equality between an authority code and a PROJ.4 string.
    route_epsg = canonical_crs_identity(route_crs)
    route_geo_ref_epsg = canonical_crs_identity(route_geo_ref)
    manual_epsg = canonical_crs_identity(manual_norm)
    auto_epsg = canonical_crs_identity(auto_norm)

    manual_frame_shares = bool(manual_epsg) and manual_epsg == route_epsg
    auto_frame_shares = bool(auto_epsg) and auto_epsg == route_epsg

    both_share_same_frame = manual_frame_shares and auto_frame_shares

    # Build transform evidence
    manual_transform_payload = {
        "route_crs": route_crs,
        "manual_crs": manual_norm,
        "manual_crs_epsg": manual_epsg,
        "manual_map_identity": manual_map_identity,
        "frame_shares": manual_frame_shares,
        "geo_reference_valid": manual_params_valid,
        "geo_reference_params_complete": manual_params_complete,
    }
    manual_transform_sha = sha256_text(canonical_dumps(manual_transform_payload))

    auto_transform_payload = {
        "route_crs": route_crs,
        "auto_crs": auto_norm,
        "auto_crs_epsg": auto_epsg,
        "auto_map_identity": auto_map_identity,
        "frame_shares": auto_frame_shares,
        "geo_reference_valid": auto_params_valid,
        "geo_reference_params_complete": auto_params_complete,
    }
    auto_transform_sha = sha256_text(canonical_dumps(auto_transform_payload))

    return {
        "route_coordinate_frame": route_frame,
        "route_crs": route_crs,
        "manual_map_frame": manual_norm,
        "manual_transform_sha256": manual_transform_sha,
        "auto_map_frame": auto_norm,
        "auto_transform_sha256": auto_transform_sha,
        "both_maps_share_exact_frame": both_share_same_frame,
        "route_crs_epsg": route_epsg,
        "route_geo_reference_epsg": route_geo_ref_epsg,
        "manual_crs_epsg": manual_epsg,
        "auto_crs_epsg": auto_epsg,
        "manual_geo_reference_valid": manual_params_valid,
        "manual_geo_reference_params_complete": manual_params_complete,
        "auto_geo_reference_valid": auto_params_valid,
        "auto_geo_reference_params_complete": auto_params_complete,
        "manual_geo_reference_norm": manual_norm,
        "auto_geo_reference_norm": auto_norm,
        "can_prove_shared_frame": both_share_same_frame,
        "proof_method": "pinned_map_georeference_identity" if both_share_same_frame else "frame_difference",
    }


def validate_frame_binding(
    route_manifest: Dict[str, Any],
    binding: Dict[str, Any],
) -> List[str]:
    """
    Validate that the coordinate-frame binding is sound.
    Returns list of failure reasons (empty = valid).
    """
    reasons: list[str] = []

    if not route_manifest.get("crs"):
        reasons.append("route_manifest_missing_crs")

    if not route_manifest.get("geo_reference"):
        reasons.append("route_manifest_missing_geo_reference")

    if not route_manifest.get("coordinate_frame"):
        reasons.append("route_manifest_missing_coordinate_frame")

    # NEW-295 fix: a manifest whose declared `crs` contradicts its own declared
    # `geo_reference` is internally inconsistent and must be rejected. Without
    # this check a route could declare EPSG:32633 while carrying UTM-zone-32
    # PROJ parameters and still be reported as a valid binding.
    route_epsg = canonical_crs_identity(route_manifest.get("crs"))
    route_ref_epsg = canonical_crs_identity(route_manifest.get("geo_reference"))
    if route_epsg is None:
        reasons.append("route_crs_unresolvable")
    if route_ref_epsg is None:
        reasons.append("route_georeference_unresolvable")
    if route_epsg is not None and route_ref_epsg is not None and route_epsg != route_ref_epsg:
        reasons.append(
            f"route_crs_georeference_mismatch:crs_epsg={route_epsg}:georef_epsg={route_ref_epsg}"
        )

    # If both maps don't share the frame, transforms must exist
    if not binding.get("both_maps_share_exact_frame"):
        if not binding.get("manual_transform_sha256"):
            reasons.append("manual_transform_missing_sha256")
        if not binding.get("auto_transform_sha256"):
            reasons.append("auto_transform_missing_sha256")

    # If frame is shared, verify it's actually the same
    if binding.get("both_maps_share_exact_frame"):
        if not binding.get("can_prove_shared_frame"):
            reasons.append("shared_frame_not_provable")

    # Validate geo-reference completeness
    if not binding.get("manual_geo_reference_params_complete") and not binding.get("manual_geo_reference_valid"):
        reasons.append("manual_georeference_invalid_or_incomplete")
    if not binding.get("auto_geo_reference_params_complete") and not binding.get("auto_geo_reference_valid"):
        reasons.append("auto_georeference_invalid_or_incomplete")

    # NEW-295 fix: an arm's georeference is unusable for this route when its
    # resolved CRS identity differs from the route's declared CRS. This is the
    # "numerically fine, wrong declared frame" case: a UTM-zone-32 PROJ string
    # is syntactically valid but cannot carry a route declared in another zone.
    if route_epsg is not None:
        manual_epsg = binding.get("manual_crs_epsg")
        auto_epsg = binding.get("auto_crs_epsg")
        if manual_epsg is None or manual_epsg != route_epsg:
            reasons.append(
                f"manual_georeference_crs_mismatch:route_epsg={route_epsg}:manual_epsg={manual_epsg}"
            )
        if auto_epsg is None or auto_epsg != route_epsg:
            reasons.append(
                f"auto_georeference_crs_mismatch:route_epsg={route_epsg}:auto_epsg={auto_epsg}"
            )

    return reasons


def build_route_frame_binding(
    route_manifest: Dict[str, Any],
    *,
    manual_geo_reference: Optional[str] = None,
    auto_geo_reference: Optional[str] = None,
    manual_map_identity: Optional[str] = None,
    auto_map_identity: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Complete route-frame binding with validation.
    """
    binding = route_frame_binding_from_manifest(
        route_manifest,
        manual_geo_reference=manual_geo_reference,
        auto_geo_reference=auto_geo_reference,
        manual_map_identity=manual_map_identity,
        auto_map_identity=auto_map_identity,
    )
    reasons = validate_frame_binding(route_manifest, binding)
    binding["validation_errors"] = reasons
    binding["valid"] = not reasons
    return binding


def write_route_correspondence(
    manual_validation: Dict[str, Any],
    auto_validation: Dict[str, Any],
    paired_validation: Dict[str, Any],
    out_dir: str,
) -> Dict[str, Any]:
    """
    Create route_correspondence_manual.json,
    route_correspondence_auto.json,
    paired_route_correspondence.json
    """
    import os

    os.makedirs(out_dir, exist_ok=True)

    # Manual
    with open(os.path.join(out_dir, "route_correspondence_manual.json"), "w", encoding="utf-8") as f:
        json.dump(manual_validation, f, indent=2, sort_keys=True)

    # Auto
    with open(os.path.join(out_dir, "route_correspondence_auto.json"), "w", encoding="utf-8") as f:
        json.dump(auto_validation, f, indent=2, sort_keys=True)

    # Paired
    with open(os.path.join(out_dir, "paired_route_correspondence.json"), "w", encoding="utf-8") as f:
        json.dump(paired_validation, f, indent=2, sort_keys=True)

    return {
        "manual_path": "route_correspondence_manual.json",
        "auto_path": "route_correspondence_auto.json",
        "paired_path": "paired_route_correspondence.json",
    }
