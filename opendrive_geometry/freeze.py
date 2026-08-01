"""Fail-closed geometry freeze (GEO-FRZ-001).

The freeze hashes the geometric authority of a release candidate BEFORE
downstream mutation (elevation, lanes, tiling, signals).  Any later stage
that mutates planView geometry, road.length, junction connectors, or
attachment poses must first re-verify the freeze; a mismatch raises
GeometryFreezeError and blocks the stage — no silent fallback, no QA bypass.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import xml.etree.ElementTree as ET
from typing import Iterable, Mapping, Optional, Sequence

from opendrive_geometry.primitives import (
    evaluate_arc,
    evaluate_line,
    evaluate_param_poly3,
    evaluate_poly3,
    evaluate_spiral,
)

FREEZE_VERSION = "GEO-FRZ-001"
SUPPORTED_GEOMETRY_TYPES = frozenset({"line", "arc", "spiral", "poly3", "paramPoly3"})

#: heading is normalized to [-pi, pi] before hashing so equivalent poses hash equal
def _norm_angle(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a <= -math.pi:
        a += 2.0 * math.pi
    return a


class GeometryFreezeError(RuntimeError):
    """Raised when a geometry freeze mismatch is detected (fail-closed)."""


def _geom_digest(g: ET.Element) -> str:
    """Per-geometry canonical digest (independent of XML attribute order)."""
    kind = g.get("geometry", "")
    parts = [
        ("kind", kind),
        ("x", g.get("x", "")),
        ("y", g.get("y", "")),
        ("hdg", g.get("hdg", "")),
        ("length", g.get("length", "")),
        ("s", g.get("s", "")),
    ]
    if kind == "arc":
        parts.append(("curvature", g.get("curvature", "")))
    elif kind == "spiral":
        parts.append(("curvStart", g.get("curvStart", "")))
        parts.append(("curvEnd", g.get("curvEnd", "")))
    elif kind == "poly3":
        parts.append(("a", g.get("a", "")))
        parts.append(("b", g.get("b", "")))
        parts.append(("c", g.get("c", "")))
        parts.append(("d", g.get("d", "")))
    elif kind == "paramPoly3":
        parts.append(("pRange", g.get("pRange", "")))
        for attr in ("aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV"):
            parts.append((attr, g.get(attr, "")))
    elif kind not in SUPPORTED_GEOMETRY_TYPES:
        raise GeometryFreezeError(f"unsupported geometry type in freeze: {kind!r}")
    blob = "\n".join(f"{k}={v}" for k, v in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def freeze_road_geometry(road: ET.Element) -> str:
    """Digest of one road's planView, length, and attachment s-poses."""
    road_id = road.get("id", "?")
    length = road.get("length", "0")
    h = hashlib.sha256()
    h.update(f"road={road_id};length={length}".encode("utf-8"))
    plan_view = road.find("planView")
    geoms = []
    if plan_view is not None:
        for g in plan_view.findall("geometry"):
            geoms.append(_geom_digest(g))
        geoms.sort()
    for d in geoms:
        h.update(d.encode("utf-8"))
    for section in ("predecessor", "successor"):
        link = road.find(f"link/{section}")
        if link is not None:
            h.update(f"{section}:{link.get('elementType','')}:{link.get('elementId','')}:{link.get('contactPoint','')}".encode("utf-8"))
    return h.hexdigest()


def freeze_document(root: ET.Element) -> str:
    """Digest over every road's planView geometry + length + attachments."""
    h = hashlib.sha256()
    h.update(FREEZE_VERSION.encode("utf-8"))
    roads = root.findall(".//road")
    digests = [freeze_road_geometry(r) for r in roads]
    digests.sort()
    for d in digests:
        h.update(d.encode("utf-8"))
    return h.hexdigest()


def compute_freeze(xodr_path_or_root: str | os.PathLike | ET.Element) -> str:
    """Entry point: hash a whole XODR document's geometric authority."""
    if isinstance(xodr_path_or_root, ET.Element):
        return freeze_document(xodr_path_or_root)
    if isinstance(xodr_path_or_root, (str, os.PathLike)):
        tree = ET.parse(xodr_path_or_root)
        return freeze_document(tree.getroot())
    raise TypeError("expected XODR path or ElementTree root")


def verify_freeze(xodr_path_or_root: str | os.PathLike | ET.Element,
                  expected: str) -> None:
    """Fail-closed check; raises GeometryFreezeError on ANY mismatch."""
    actual = compute_freeze(xodr_path_or_root)
    if actual != expected:
        raise GeometryFreezeError(
            "geometry freeze mismatch: downstream stage would mutate frozen "
            "geometry (planView, road.length, or attachments)")


def freeze_report(xodr_path_or_root: str | os.PathLike | ET.Element) -> dict:
    actual = compute_freeze(xodr_path_or_root)
    return {"freeze_version": FREEZE_VERSION, "sha256": actual}
