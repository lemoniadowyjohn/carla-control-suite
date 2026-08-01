"""
ultimate_pipeline.tools.xodr_compare_gate

Thesis utility: compare two OpenDRIVE (.xodr) files for *coordinate-system comparability*.

Why this exists:
- Your auto-generated maps often embed a local projection (e.g., +proj=tmerc +lat_0... +lon_0...)
  plus a big offset.
- Your manually authored CARLA map may use a different geoReference (often UTM-like).
- If you compare geometry/perception across mismatched CRS, you measure "coordinate mismatch",
  not "domain gap".

This module is intentionally stdlib-only.

API:
  build_report(a_path, b_path) -> dict

CLI:
  python -m ultimate_pipeline.tools.xodr_compare_gate --a A.xodr --b B.xodr [--out report.json]

Exit codes:
  0  comparable (gate passes)
  2  not comparable (gate fails)
  3  unexpected error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional
from ultimate_pipeline.core.georef_utils import parse_georeference


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _as_float(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _finite(x: Optional[float]) -> bool:
    return x is not None and math.isfinite(x)


def _parse_xodr_header(path: str) -> Dict[str, Any]:
    """
    Parse a subset of XODR header info needed for comparability.

    Returns dict with:
      has_geoReference: bool
      geoReference_norm: Optional[str]
      header_bounds: dict {north,south,east,west} (floats or None)
      header_offset: dict {x,y,z,hdg} (floats or None)
      xodr_sha256: str
    Raises:
      FileNotFoundError, ET.ParseError, OSError
    """
    sha = _sha256_file(path)

    tree = ET.parse(path)
    root = tree.getroot()

    # OpenDRIVE root can have namespaces; keep it simple by stripping if needed
    def _strip_ns(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    header = None
    for child in root:
        if _strip_ns(child.tag) == "header":
            header = child
            break

    bounds = {"north": None, "south": None, "east": None, "west": None}
    georef_norm: Optional[str] = None
    georef_params_complete: Optional[bool] = None
    has_georef = False
    offset = {"x": None, "y": None, "z": None, "hdg": None}

    if header is not None:
        # bounds are attributes on <header ... north="..." ...>
        bounds["north"] = _as_float(header.attrib.get("north"))
        bounds["south"] = _as_float(header.attrib.get("south"))
        bounds["east"] = _as_float(header.attrib.get("east"))
        bounds["west"] = _as_float(header.attrib.get("west"))

        # <geoReference> ... </geoReference>
        for sub in header:
            tag = _strip_ns(sub.tag)
            if tag == "geoReference":
                txt = (sub.text or "").strip()
                if txt:
                    valid, params_complete, norm = parse_georeference(txt)
                    georef_norm = norm or None
                    georef_params_complete = bool(params_complete)
                    has_georef = True
            elif tag == "offset":
                offset["x"] = _as_float(sub.attrib.get("x"))
                offset["y"] = _as_float(sub.attrib.get("y"))
                offset["z"] = _as_float(sub.attrib.get("z"))
                offset["hdg"] = _as_float(sub.attrib.get("hdg"))

    return {
        "has_geoReference": bool(has_georef),
        "geoReference_norm": georef_norm,
        "geoReference_params_complete": georef_params_complete,
        "header_bounds": bounds,
        "header_offset": offset,
        "xodr_sha256": sha,
    }


def _bounds_sanity(bounds: Dict[str, Optional[float]]) -> bool:
    """
    Bounds sanity: if any bound is present, all must be finite and consistent.
    Consistent means: north >= south and east >= west.
    If all are None -> False (no usable bounds).
    """
    n, s, e, w = bounds.get("north"), bounds.get("south"), bounds.get("east"), bounds.get("west")

    if n is None and s is None and e is None and w is None:
        return False
    if not (_finite(n) and _finite(s) and _finite(e) and _finite(w)):
        return False
    if n < s:
        return False
    if e < w:
        return False
    return True


def build_report(a_path: str, b_path: str) -> Dict[str, Any]:
    """
    Build a deterministic comparability report for two XODR files.

    Policy (strict by default):
      comparable=True iff:
        - both parse successfully
        - both have geoReference
        - normalized geoReference strings match exactly
        - header bounds are sane for both (finite + consistent)

    This deliberately refuses comparisons when geoReference is missing or different.
    """
    # Pre-fill stable shape so callers can rely on keys existing.
    report: Dict[str, Any] = {
        "comparable": False,
        "reason": "",
        "georef_match": False,
        "bounds_sanity": False,
        "a": {
            "has_geoReference": False,
            "geoReference_norm": None,
            "header_bounds": {"north": None, "south": None, "east": None, "west": None},
            "header_offset": {"x": None, "y": None, "z": None, "hdg": None},
            "xodr_sha256": None,
        },
        "b": {
            "has_geoReference": False,
            "geoReference_norm": None,
            "header_bounds": {"north": None, "south": None, "east": None, "west": None},
            "header_offset": {"x": None, "y": None, "z": None, "hdg": None},
            "xodr_sha256": None,
        },
    }

    try:
        if not os.path.isfile(a_path):
            report["reason"] = f"missing_file: a:{a_path}"
            return report
        if not os.path.isfile(b_path):
            report["reason"] = f"missing_file: b:{b_path}"
            return report

        a_info = _parse_xodr_header(a_path)
        b_info = _parse_xodr_header(b_path)
        report["a"] = a_info
        report["b"] = b_info

        a_has = bool(a_info.get("has_geoReference"))
        b_has = bool(b_info.get("has_geoReference"))

        if not a_has and not b_has:
            report["reason"] = "missing_georef: both"
            return report
        if not a_has:
            report["reason"] = "missing_georef: a"
            return report
        if not b_has:
            report["reason"] = "missing_georef: b"
            return report

        a_gr = a_info.get("geoReference_norm")
        b_gr = b_info.get("geoReference_norm")

        georef_match = bool(a_gr) and bool(b_gr) and (a_gr == b_gr)
        report["georef_match"] = georef_match
        if not georef_match:
            report["reason"] = "different_georef"
            return report

        a_bs = _bounds_sanity(a_info.get("header_bounds", {}))
        b_bs = _bounds_sanity(b_info.get("header_bounds", {}))
        report["bounds_sanity"] = bool(a_bs and b_bs)
        if not report["bounds_sanity"]:
            report["reason"] = "invalid_bounds"
            return report

        report["comparable"] = True
        report["reason"] = "same_georef"
        return report

    except ET.ParseError as e:
        report["reason"] = f"parse_error: {e.__class__.__name__}: {e}"
        return report
    except OSError as e:
        report["reason"] = f"io_error: {e.__class__.__name__}: {e}"
        return report
    except Exception as e:
        # Unexpected errors should still return a shaped report.
        report["reason"] = f"error: {e.__class__.__name__}: {e}"
        return report


def _write_json(path: Optional[str], obj: Dict[str, Any]) -> None:
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True)
    if not text.endswith("\n"):
        text += "\n"
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="XODR CRS comparability gate (stdlib-only).")
    ap.add_argument("--a", required=True, help="Path to XODR A")
    ap.add_argument("--b", required=True, help="Path to XODR B")
    ap.add_argument("--out", default=None, help="Output JSON path (default: stdout)")
    args = ap.parse_args(argv)

    try:
        report = build_report(args.a, args.b)
        _write_json(args.out, report)
        return 0 if report.get("comparable") is True else 2
    except Exception:
        # Only truly unexpected failures should land here.
        # Keep stderr short and deterministic.
        print("xodr_compare_gate: unexpected exception", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
