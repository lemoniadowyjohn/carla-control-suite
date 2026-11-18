"""Trusted release scope derived from the pinned map-of-record.

The candidate under evaluation is never an authority for its own expected
road membership or geographic frame.  The authority is the verified registry
pin and its bytes; the OSM identity is frozen alongside that pin.
"""
from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCOPE_SCHEMA = "TRUSTED_MAP_SCOPE/v1"
EXPECTED_OSM_SHA256 = "b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f"
EXPECTED_MAP_SHA256 = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"


class MapScopeAuthorityError(RuntimeError):
    """The trusted release scope could not be established."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _trusted_map_profile(repo_root: Path) -> tuple[dict[str, Any], Path]:
    from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

    try:
        receipt = verify_pinned_map("auto_map_of_record", base_dir=repo_root)
    except Exception as exc:
        raise MapScopeAuthorityError(f"pinned map verification failed: {exc}") from exc
    if receipt.get("verification_status") != "VERIFIED":
        raise MapScopeAuthorityError("pinned map registry did not return VERIFIED")
    if receipt.get("sha256_actual") != receipt.get("sha256_expected"):
        raise MapScopeAuthorityError("pinned map digest does not match registry")
    if receipt.get("registry_key") != "auto_map_of_record":
        raise MapScopeAuthorityError("unexpected registry identity")
    if receipt.get("frame_id") != "ingolstadt_local_rebased":
        raise MapScopeAuthorityError("unexpected map coordinate frame")
    if receipt.get("sha256_expected") != EXPECTED_MAP_SHA256:
        raise MapScopeAuthorityError("release map pin differs from governed scope profile")

    osm_path = repo_root / "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm"
    if not osm_path.is_file() or _sha256(osm_path) != EXPECTED_OSM_SHA256:
        raise MapScopeAuthorityError("pinned OSM source missing or identity-mismatched")
    profile = {
        "schema": SCOPE_SCHEMA,
        "authority": "verified_map_registry",
        "registry_key": receipt["registry_key"],
        "map_sha256": receipt["sha256_actual"],
        "map_bytes": receipt["bytes_actual"],
        "source_osm_sha256": EXPECTED_OSM_SHA256,
        "frame_id": "ingolstadt_local_rebased",
        "frame": "rebased-to-local (dx=832671.676 dy=5458671.104)",
        "rebase_dx": 832671.676,
        "rebase_dy": 5458671.104,
        "study_bounds_wgs84": {
            "lat": [48.74935649548228, 48.77444431571603],
            "lon": [11.422268084715878, 11.47882091528412],
        },
    }
    return profile, Path(receipt["resolved_path"])


def _map_scope(path: Path, profile: dict[str, Any]) -> dict[str, Any]:
    """Derive exact road membership and geometry-anchor bounds from authority bytes."""
    road_ids: set[str] = set()
    xs: list[float] = []
    ys: list[float] = []
    try:
        for event, element in ET.iterparse(path, events=("end",)):
            if element.tag == "road":
                rid = element.get("id")
                if not rid or rid in road_ids:
                    raise MapScopeAuthorityError("trusted map has missing or duplicate road IDs")
                road_ids.add(rid)
                for geometry in element.findall("./planView/geometry"):
                    x, y = float(geometry.attrib["x"]), float(geometry.attrib["y"])
                    length, heading = float(geometry.attrib["length"]), float(geometry.attrib["hdg"])
                    if not all(math.isfinite(v) for v in (x, y, length, heading)) or length < 0:
                        raise MapScopeAuthorityError("trusted map has invalid geometry anchor")
                    xs.extend((x, x + length * math.cos(heading)))
                    ys.extend((y, y + length * math.sin(heading)))
                element.clear()
    except MapScopeAuthorityError:
        raise
    except Exception as exc:
        raise MapScopeAuthorityError(f"cannot derive trusted map scope: {exc}") from exc
    if not road_ids or not xs:
        raise MapScopeAuthorityError("trusted map has no road geometry")
    profile.update({
        "road_count": len(road_ids),
        "expected_road_ids": sorted(road_ids),
        "anchor_bounds_xy": [min(xs), min(ys), max(xs), max(ys)],
    })
    return profile


def resolve_trusted_release_scope(repo_root: Path | None = None) -> dict[str, Any]:
    """Return a source-bound scope; fail closed if any authority input drifts."""
    root = repo_root or Path(__file__).resolve().parents[2]
    profile, map_path = _trusted_map_profile(root)
    if _sha256(map_path) != profile["map_sha256"]:
        raise MapScopeAuthorityError("map bytes changed while deriving scope")
    return _map_scope(map_path, profile)


def validate_candidate_scope(root: ET.Element, expected_scope: dict[str, Any]) -> dict[str, Any]:
    """Require exact membership, source identity, frame and anchored footprint."""
    issues: list[dict[str, Any]] = []
    if not isinstance(expected_scope, dict) or expected_scope.get("schema") != SCOPE_SCHEMA:
        return {"ok": False, "issues": [{"kind": "missing_or_invalid_trusted_scope"}]}
    if expected_scope.get("authority") != "verified_map_registry":
        issues.append({"kind": "untrusted_scope_authority"})
    if expected_scope.get("map_sha256") != EXPECTED_MAP_SHA256:
        issues.append({"kind": "map_identity_mismatch"})
    if expected_scope.get("source_osm_sha256") != EXPECTED_OSM_SHA256:
        issues.append({"kind": "source_identity_mismatch"})
    if expected_scope.get("frame_id") != "ingolstadt_local_rebased":
        issues.append({"kind": "frame_identity_mismatch"})

    roads = root.findall("road")
    actual_ids = {road.get("id") for road in roads}
    expected_ids = set(expected_scope.get("expected_road_ids", []))
    if actual_ids != expected_ids:
        issues.append({"kind": "road_membership_mismatch", "missing": sorted(expected_ids - actual_ids)[:20],
                       "unexpected": sorted(actual_ids - expected_ids)[:20]})
    try:
        coords = []
        for geometry in root.findall("./road/planView/geometry"):
            x, y = float(geometry.attrib["x"]), float(geometry.attrib["y"])
            length, heading = float(geometry.attrib["length"]), float(geometry.attrib["hdg"])
            coords.extend(((x, y), (x + length * math.cos(heading), y + length * math.sin(heading))))
        actual_bounds = [min(x for x, _ in coords), min(y for _, y in coords),
                         max(x for x, _ in coords), max(y for _, y in coords)]
        expected_bounds = expected_scope["anchor_bounds_xy"]
        tolerance = float(expected_scope.get("bounds_tolerance_m", 1.0))
        if len(expected_bounds) != 4 or any(abs(a - b) > tolerance for a, b in zip(actual_bounds, expected_bounds)):
            issues.append({"kind": "geographic_footprint_mismatch", "expected": expected_bounds,
                           "actual": actual_bounds, "tolerance_m": tolerance})
    except Exception as exc:
        issues.append({"kind": "invalid_scope_geometry", "reason": f"{type(exc).__name__}: {exc}"})
    return {"ok": not issues, "issues": issues, "scope_identity": {
        "map_sha256": expected_scope.get("map_sha256"),
        "source_osm_sha256": expected_scope.get("source_osm_sha256"),
        "frame_id": expected_scope.get("frame_id"),
        "road_count": expected_scope.get("road_count"),
    }}
