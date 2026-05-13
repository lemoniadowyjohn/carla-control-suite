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
import os
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

    lat_c = 0.5 * (float(gps_bounds["lat_min"]) + float(gps_bounds["lat_max"]))
    lon_c = 0.5 * (float(gps_bounds["lon_min"]) + float(gps_bounds["lon_max"]))

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
        xs.append(float(x))
        ys.append(float(y))

    if not xs:
        raise ValueError(f"No planView geometry points found in {xodr_path}")

    bbox = BBox(min(xs), min(ys), max(xs), max(ys))
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    return bbox, (cx, cy), len(xs)


def translate_xodr_geometry(
    in_path: Path, out_path: Path, dx: float, dy: float
) -> Dict:
    """Translate planView geometry start points by (dx,dy)."""
    tree = ET.parse(in_path)
    root = tree.getroot()

    n = 0
    for geom in _iter_planview_geometries(root):
        x = geom.get("x")
        y = geom.get("y")
        if x is None or y is None:
            continue
        geom.set("x", f"{float(x) + dx:.10f}")
        geom.set("y", f"{float(y) + dy:.10f}")
        n += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    return {"translated_geometry_points": n, "dx": dx, "dy": dy}


def _read_header_offset_xy(xodr_path: Path) -> Tuple[float, float]:
    '''Read header <offset x,y> if present; otherwise return (0,0).'''
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        header = root.find("header")
        if header is None:
            return 0.0, 0.0
        off = header.find("offset")
        if off is None:
            return 0.0, 0.0
        return float(off.get("x", "0.0")), float(off.get("y", "0.0"))
    except Exception:
        return 0.0, 0.0


def deterministic_promote_and_align(
    auto_xodr_in: Path,
    manual_proj: str,
    gps_bounds: Dict,
    manual_bbox: Optional[BBox],
    out_aligned_xodr: Path,
    out_validity_json: Optional[Path] = None,
    require_overlap: bool = True,
) -> Dict:
    """Align auto geometry into manual CRS neighborhood using GPS center anchor."""
    # Guard against silent double-translation if the input already uses a non-zero header offset.
    ox, oy = _read_header_offset_xy(auto_xodr_in)
    offset_mag = float(math.hypot(float(ox), float(oy)))
    allow = os.getenv("UP_ALLOW_ALIGNMENT_WITH_HEADER_OFFSET", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if offset_mag > 1e-6 and not allow:
        raise RuntimeError(
            "deterministic_alignment refuses to translate a map with non-zero <header><offset> "
            f"(offset_mag={offset_mag:.6f}m). This avoids double-translation corruption. "
            "Either normalize offsets before alignment or set UP_ALLOW_ALIGNMENT_WITH_HEADER_OFFSET=1."
        )

    auto_bbox_local, (ax, ay), _ = compute_auto_bbox_and_centroid(auto_xodr_in)
    tx, ty = project_center_from_gps_bounds(gps_bounds, manual_proj)

    dx = tx - ax
    dy = ty - ay

    stats = translate_xodr_geometry(auto_xodr_in, out_aligned_xodr, dx, dy)

    auto_bbox_aligned = BBox(
        auto_bbox_local.minx + dx,
        auto_bbox_local.miny + dy,
        auto_bbox_local.maxx + dx,
        auto_bbox_local.maxy + dy,
    )

    validity = {
        "status": "ok",
        "auto_xodr_in": str(auto_xodr_in),
        "header_offset_xy": {"x": ox, "y": oy, "mag_m": offset_mag},
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
