"""ultimate_pipeline.domain_gap.deterministic_alignment

Deterministic CRS completion + translation for OpenDRIVE (XODR) using only canonical GPS bounds.

This module eliminates run-provenance coupling by computing the translation vector from:
  (a) canonical lat/lon bounds (center point), and
  (b) local auto-geometry centroid in meters.

It assumes:
- Manual CRS is authoritative (full PROJ string).
- Auto map may have incomplete <geoReference> and local-meter coordinates near origin.
- After CRS completion, we translate planView geometry into the manual CRS neighborhood.

Key invariants:
- Translation depends only on (gps_bounds, manual_proj, auto_xodr_geometry).
- If post-translation bbox does not overlap manual bbox, we can fail fast.

Intended integration point:
- Call from domain-gap alignment code right before tiling.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, Optional, Iterable
import json
import xml.etree.ElementTree as ET
import math

try:
    from pyproj import CRS, Transformer
except Exception:  # pragma: no cover
    CRS = None
    Transformer = None


@dataclass(frozen=True)
class BBox:
    minx: float
    miny: float
    maxx: float
    maxy: float

    def overlaps(self, other: "BBox") -> bool:
        return not (
            self.maxx < other.minx
            or self.minx > other.maxx
            or self.maxy < other.miny
            or self.miny > other.maxy
        )


def project_center_from_gps_bounds(
    gps_bounds: Dict, manual_proj: str
) -> Tuple[float, float]:
    """Project canonical GPS-bbox center into manual CRS (meters)."""
    if CRS is None or Transformer is None:
        raise RuntimeError("pyproj is required for deterministic alignment")

    try:
        lat_c = 0.5 * (float(gps_bounds["lat_min"]) + float(gps_bounds["lat_max"]))
        lon_c = 0.5 * (float(gps_bounds["lon_min"]) + float(gps_bounds["lon_max"]))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid gps_bounds value: {exc}") from exc

    crs = CRS.from_user_input(manual_proj)
    tf = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = tf.transform(lon_c, lat_c)
    return float(x), float(y)


def _iter_planview_geometries(root: ET.Element) -> Iterable[ET.Element]:
    for geom in root.findall(".//road/planView/geometry"):
        yield geom


def compute_auto_bbox_and_centroid(
    xodr_path: Path,
) -> Tuple[BBox, Tuple[float, float], int]:
    """Cheap, stable centroid proxy: average of planView geometry start points."""
    tree = ET.parse(xodr_path)
    root = tree.getroot()

    xs, ys = [], []
    for geom in _iter_planview_geometries(root):
        x = geom.get("x")
        y = geom.get("y")
        if x is None or y is None:
            continue
        # Evaluate both conversions before appending either -- appending x
        # then having y's conversion raise would leave xs one element ahead
        # of ys, silently desynchronizing the two populations (a value from
        # a malformed geometry would then pair with the NEXT geometry's
        # coordinate in the centroid/bbox computation below).
        try:
            fx = float(x)
            fy = float(y)
        except (TypeError, ValueError):
            continue
        xs.append(fx)
        ys.append(fy)

    if not xs:
        raise ValueError(f"No planView geometry points found in {xodr_path}")

    bbox = BBox(min(xs), min(ys), max(xs), max(ys))
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    return bbox, (cx, cy), len(xs)


def _ensure_header(root: ET.Element) -> ET.Element:
    """Return the OpenDRIVE header, keeping it before structural elements."""

    header = root.find("header")
    if header is None:
        header = ET.Element("header")
        root.insert(0, header)
    return header


def translate_xodr_geometry(
    in_path: Path,
    out_path: Path,
    dx: float,
    dy: float,
    *,
    reset_header_offset_xy: bool = False,
    target_georeference: str | None = None,
) -> Dict:
    """Translate planView geometry start points by (dx,dy).

    Also refreshes the <header> west/east/south/north bounds to match the
    translated geometry. Real consumers (xodr_compare_gate.py's north>=south
    /east>=west sanity check, dem_crs_contract.py's CRS-consistency check)
    read these attributes directly; leaving them at their pre-translation
    values after a real alignment shift (which can be on the order of
    hundreds of kilometers, moving near-origin local coordinates into a
    real-world CRS neighborhood) would silently hand them a bounding box
    that no longer describes the file's own geometry.  A caller which moves
    local planView coordinates into a new CRS can request that the source
    header's horizontal offset be reset.  Retaining it in such output would
    apply the source-frame translation a second time.
    """
    tree = ET.parse(in_path)
    root = tree.getroot()

    n = 0
    source_geometry_freeze_invalidated = False
    minx = miny = math.inf
    maxx = maxy = -math.inf
    for geom in _iter_planview_geometries(root):
        x = geom.get("x")
        y = geom.get("y")
        if x is None or y is None:
            continue
        try:
            new_x = float(x) + dx
            new_y = float(y) + dy
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"non-numeric planView geometry x/y: {ET.tostring(geom, encoding='unicode')}"
            ) from exc
        geom.set("x", f"{new_x:.10f}")
        geom.set("y", f"{new_y:.10f}")
        minx = min(minx, new_x)
        maxx = max(maxx, new_x)
        miny = min(miny, new_y)
        maxy = max(maxy, new_y)
        n += 1

    if n > 0:
        header = _ensure_header(root)
        header.set("west", f"{minx:.8f}")
        header.set("east", f"{maxx:.8f}")
        header.set("south", f"{miny:.8f}")
        header.set("north", f"{maxy:.8f}")
        # A coordinate transform changes protected planView geometry.  This is
        # a derived domain-gap artifact, not the pipeline's frozen structural
        # map, so it must not retain a source freeze attestation.
        had_geometry_frozen = header.attrib.pop("geometryFrozen", None) is not None
        had_geometry_freeze_hash = header.attrib.pop("geometryFreezeHash", None) is not None
        source_geometry_freeze_invalidated = bool(
            had_geometry_frozen or had_geometry_freeze_hash
        )
        if reset_header_offset_xy:
            offset = header.find("offset")
            if offset is None:
                offset = ET.SubElement(header, "offset")
            offset.set("x", "0.0000000000")
            offset.set("y", "0.0000000000")
        if target_georeference is not None:
            georef = header.find("geoReference")
            if georef is None:
                georef = ET.SubElement(header, "geoReference")
            georef.text = str(target_georeference)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    return {
        "translated_geometry_points": n,
        "dx": dx,
        "dy": dy,
        "output_header_offset_xy": {
            "x": 0.0 if reset_header_offset_xy else None,
            "y": 0.0 if reset_header_offset_xy else None,
        },
        "source_geometry_freeze_invalidated": source_geometry_freeze_invalidated,
    }


def _read_header_offset(xodr_path: Path) -> Dict[str, float]:
    """Parse finite header-offset values or fail closed on malformed input."""

    root = ET.parse(xodr_path).getroot()
    header = root.find("header")
    offset = header.find("offset") if header is not None else None
    values: Dict[str, float] = {}
    for key in ("x", "y", "z", "hdg"):
        raw = "0.0" if offset is None else offset.get(key, "0.0")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid header offset {key}={raw!r}") from exc
        if not math.isfinite(value):
            raise ValueError(f"invalid header offset {key}={raw!r}")
        values[key] = value
    return values


def deterministic_promote_and_align(
    auto_xodr_in: Path,
    manual_proj: str,
    gps_bounds: Dict,
    manual_bbox: Optional[BBox],
    out_aligned_xodr: Path,
    out_validity_json: Optional[Path] = None,
    require_overlap: bool = True,
) -> Dict:
    """Align local auto geometry into the manual CRS and rebase XY offset.

    The source header's X/Y offset describes the local coordinate frame of
    the input.  This function writes coordinates directly in ``manual_proj``;
    its output consequently resets X/Y offset to zero.  Header rotation is
    deliberately rejected because this translation-only implementation cannot
    preserve it correctly.
    """

    input_offset = _read_header_offset(auto_xodr_in)
    ox, oy = input_offset["x"], input_offset["y"]
    offset_mag = float(math.hypot(ox, oy))
    if abs(input_offset["hdg"]) > 1e-9:
        raise RuntimeError(
            "deterministic_alignment refuses non-zero header offset rotation "
            f"(hdg={input_offset['hdg']:.12g}); translation-only alignment cannot preserve it."
        )

    auto_bbox_local, (ax, ay), _ = compute_auto_bbox_and_centroid(auto_xodr_in)
    tx, ty = project_center_from_gps_bounds(gps_bounds, manual_proj)

    dx = tx - ax
    dy = ty - ay

    stats = translate_xodr_geometry(
        auto_xodr_in,
        out_aligned_xodr,
        dx,
        dy,
        reset_header_offset_xy=True,
        target_georeference=manual_proj,
    )

    auto_bbox_aligned = BBox(
        auto_bbox_local.minx + dx,
        auto_bbox_local.miny + dy,
        auto_bbox_local.maxx + dx,
        auto_bbox_local.maxy + dy,
    )

    validity = {
        "status": "ok",
        "auto_xodr_in": str(auto_xodr_in),
        "input_header_offset_xy": {"x": ox, "y": oy, "mag_m": offset_mag},
        "input_header_offset_z": input_offset["z"],
        "input_header_offset_hdg": input_offset["hdg"],
        "gps_center_projected": {"x": tx, "y": ty},
        "translation": {"dx": dx, "dy": dy},
        "auto_bbox_local": auto_bbox_local.__dict__,
        "auto_bbox_aligned": auto_bbox_aligned.__dict__,
        **stats,
        "require_overlap": require_overlap,
    }

    if manual_bbox is not None:
        overlaps = auto_bbox_aligned.overlaps(manual_bbox)
        validity["manual_bbox"] = manual_bbox.__dict__
        validity["overlap"] = bool(overlaps)
        if require_overlap and not overlaps:
            validity["status"] = "fail"

    if out_validity_json is not None:
        out_validity_json.parent.mkdir(parents=True, exist_ok=True)
        out_validity_json.write_text(json.dumps(validity, indent=2), encoding="utf-8")

    if validity["status"] != "ok":
        raise RuntimeError(
            f"Alignment validity failed (no bbox overlap). See {out_validity_json}"
        )

    return validity
