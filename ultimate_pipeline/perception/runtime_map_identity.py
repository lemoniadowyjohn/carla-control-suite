"""Layer-2 runtime OpenDRIVE structural identity (NEW-252 / NEW-253 / NEW-254).

Layer 1 is name matching only (``map_names_match``).  It is necessary but not
sufficient: a server can report the right map *name* while serving structurally
different content.

This module builds a **canonical structural fingerprint** of an OpenDRIVE
document and compares two fingerprints under explicitly documented
normalisation rules.  It is deliberately byte-equality-free: CARLA re-serialises
OpenDRIVE on the way out of the engine (attribute order, whitespace, floating
point formatting, georeference injection), so byte equality after
``world.get_map().to_opendrive()`` is the wrong test.

Normalisation rules (documented, deterministic)
-----------------------------------------------
1. XML parsed with ``defusedxml`` when available, else ``xml.etree``.
2. Whitespace inside text nodes collapsed; attribute order irrelevant.
3. All floating point values parsed and re-emitted with ``repr``-level
   round-tripping via ``float`` -> format with 9 significant digits, so
   ``1.0`` and ``1.000000000`` are equal, and ``1e-9`` drift below 1e-9 is
   tolerated by the documented ``float_quantum`` rule.
4. Element order IS significant for ``planView`` geometry sequences (a road
   whose geometry moved is a different map) but NOT for attribute ordering.
5. ``header/geoReference`` is compared only when both sides declare one; a
   missing georeference on one side is reported as ``georeference_present_mismatch``
   rather than a hard structural mismatch, because CARLA does not always
   round-trip it.
6. Road link / junction connection graphs are compared as sorted edge sets.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency
    from defusedxml import ElementTree as _ET  # type: ignore
except Exception:  # pragma: no cover
    import xml.etree.ElementTree as _ET  # type: ignore

FLOAT_QUANTUM = 1e-6
_CANON_FLOAT_SIG = 9


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _local(tag: Any) -> str:
    text = str(tag or "")
    if "}" in text:
        text = text.split("}", 1)[1]
    return text


def _canon_float(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        number = float(str(value).strip())
    except Exception:
        return f"raw:{str(value).strip()}"
    if number != number:  # NaN
        return "nan"
    if number in (float("inf"), float("-inf")):
        return "inf" if number > 0 else "-inf"
    if abs(number) < FLOAT_QUANTUM:
        number = 0.0
    text = f"{number:.{_CANON_FLOAT_SIG}g}"
    if text in ("-0", "-0.0"):
        text = "0"
    return text


def _canon_attrs(attrs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in sorted((attrs or {}).items()):
        name = _local(key)
        if re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", str(value).strip() or ""):
            canon = _canon_float(value)
            out[name] = canon if canon is not None else str(value)
        else:
            out[name] = str(value).strip()
    return out


def _text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_opendrive(text: str) -> Any:
    return _ET.fromstring(text)


def _child(elem: Any, name: str) -> Optional[Any]:
    for item in list(elem):
        if _local(item.tag) == name:
            return item
    return None


def _children(elem: Any, name: str) -> List[Any]:
    return [item for item in list(elem) if _local(item.tag) == name]


def _sha(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------


def structural_fingerprint(opendrive_text: str) -> Dict[str, Any]:
    """Build the canonical structural fingerprint of an OpenDRIVE document.

    Returns a JSON-serialisable dict.  ``fingerprint_sha256`` covers the whole
    structure; the individual components are exposed so a mismatch can be
    explained (which road, which junction, which graph edge).
    """
    root = parse_opendrive(opendrive_text)

    header = _child(root, "header")
    header_attrs = _canon_attrs(header.attrib if header is not None else {})
    geo_ref_elem = _child(header, "geoReference") if header is not None else None
    georeference = _text(geo_ref_elem.text if geo_ref_elem is not None else None)

    roads = _children(root, "road")
    junctions = _children(root, "junction")

    road_ids: List[str] = []
    junction_ids: List[str] = []
    lane_section_count = 0
    lane_count = 0
    planview_signatures: List[Dict[str, Any]] = []
    road_links: List[Tuple[str, str, str]] = []
    road_entries: List[Dict[str, Any]] = []

    for road in roads:
        attrs = _canon_attrs(road.attrib)
        road_id = attrs.get("id", "")
        road_ids.append(road_id)
        name = attrs.get("name", "")
        length = attrs.get("length")
        road_type = attrs.get("type", "")

        link = _child(road, "link")
        if link is not None:
            for rel in ("predecessor", "successor"):
                node = _child(link, rel)
                if node is None:
                    continue
                nattrs = _canon_attrs(node.attrib)
                road_links.append(
                    (road_id, rel, f"{nattrs.get('elementType','')}:{nattrs.get('elementId','')}")
                )

        plan_view = _child(road, "planView")
        geoms: List[Dict[str, Any]] = []
        if plan_view is not None:
            for geom in _children(plan_view, "geometry"):
                gattrs = _canon_attrs(geom.attrib)
                entry: Dict[str, Any] = {
                    "s": gattrs.get("s"),
                    "x": gattrs.get("x"),
                    "y": gattrs.get("y"),
                    "hdg": gattrs.get("hdg"),
                    "length": gattrs.get("length"),
                }
                for shape in ("line", "arc", "spiral", "poly3", "paramPoly3"):
                    node = _child(geom, shape)
                    if node is not None:
                        entry["shape"] = shape
                        entry["shape_attrs"] = _canon_attrs(node.attrib)
                        break
                else:
                    entry["shape"] = None
                geoms.append(entry)
        planview_signatures.append({"road": road_ids[-1], "geometry": geoms})

        lanes = _child(road, "lanes")
        sections_here = 0
        lanes_here = 0
        if lanes is not None:
            for section in _children(lanes, "laneSection"):
                sections_here += 1
                for side in ("left", "center", "right"):
                    lanes_here += len(_children(section, side))
        lane_section_count += sections_here
        lane_count += lanes_here

        road_entries.append(
            {
                "id": road_id,
                "name": name,
                "length": length,
                "type": road_type,
                "lane_sections": sections_here,
                "lanes": lanes_here,
                "link_count": len(_children(link, "predecessor")) + len(_children(link, "successor"))
                if link is not None
                else 0,
            }
        )

    junction_links: List[Tuple[str, str, str, str, str]] = []
    junction_entry_count = 0
    for junction in junctions:
        attrs = _canon_attrs(junction.attrib)
        junction_ids.append(attrs.get("id", ""))
        for connection in _children(junction, "connection"):
            junction_entry_count += 1
            cattrs = _canon_attrs(connection.attrib)
            incoming = _child(connection, "incomingRoad")
            connecting = _child(connection, "connectingRoad")
            junction_links.append(
                (
                    attrs.get("id", ""),
                    cattrs.get("id", ""),
                    _canon_attrs(incoming.attrib).get("id", "") if incoming is not None else cattrs.get("incomingRoad", ""),
                    _canon_attrs(connecting.attrib).get("id", "") if connecting is not None else cattrs.get("connectingRoad", ""),
                    cattrs.get("contactPoint", ""),
                )
            )

    components: Dict[str, Any] = {
        "header": header_attrs,
        "georeference": georeference,
        "road_ids": sorted(road_ids),
        "junction_ids": sorted(junction_ids),
        "road_count": len(road_ids),
        "junction_count": len(junction_ids),
        "lane_section_count": lane_section_count,
        "lane_count": lane_count,
        "road_link_graph": sorted(["|".join(edge) for edge in road_links]),
        "junction_connection_graph": sorted(["|".join(edge) for edge in junction_links]),
        "junction_connection_count": junction_entry_count,
        "planview_structural_signatures": planview_signatures,
        "road_entries": sorted(road_entries, key=lambda item: item.get("id", "")),
    }

    # The headline structural digest excludes volatile header attributes that
    # CARLA may rewrite on re-serialisation (revMajor/revMinor/geoReference
    # injection, date/time).  Both the strict and structural digests are kept.
    structural_core = {
        key: components[key]
        for key in (
            "road_ids",
            "junction_ids",
            "road_count",
            "junction_count",
            "lane_section_count",
            "lane_count",
            "road_link_graph",
            "junction_connection_graph",
            "junction_connection_count",
            "planview_structural_signatures",
            "road_entries",
        )
    }
    fingerprint = dict(components)
    fingerprint["structural_sha256"] = _sha(structural_core)
    fingerprint["full_sha256"] = _sha(components)
    return fingerprint


def fingerprint_sha256(opendrive_text: str) -> str:
    return str(structural_fingerprint(opendrive_text)["structural_sha256"])


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------

COMPONENT_RULES: Dict[str, str] = {
    "road_ids": "exact set equality (sorted)",
    "junction_ids": "exact set equality (sorted)",
    "road_count": "exact integer equality",
    "junction_count": "exact integer equality",
    "lane_section_count": "exact integer equality",
    "lane_count": "exact integer equality",
    "road_link_graph": "exact sorted edge-set equality",
    "junction_connection_graph": "exact sorted edge-set equality",
    "junction_connection_count": "exact integer equality",
    "planview_structural_signatures": "exact sequence equality after float quantisation to 1e-6",
    "road_entries": "exact equality after float quantisation to 1e-6",
    "georeference": "compared only when both sides present; presence mismatch reported separately",
    "header": "reported for information; never a mismatch driver",
}


def compare_fingerprints(
    expected: Dict[str, Any],
    actual: Dict[str, Any],
    *,
    require_georeference_match: bool = False,
) -> Dict[str, Any]:
    """Compare two structural fingerprints under the documented rules."""
    mismatches: List[str] = []
    details: Dict[str, Any] = {}

    for key in (
        "road_ids",
        "junction_ids",
        "road_count",
        "junction_count",
        "lane_section_count",
        "lane_count",
        "road_link_graph",
        "junction_connection_graph",
        "junction_connection_count",
        "planview_structural_signatures",
        "road_entries",
    ):
        left = expected.get(key)
        right = actual.get(key)
        equal = left == right
        details[key] = {"equal": bool(equal)}
        if not equal:
            mismatches.append(key)
            if isinstance(left, list) and isinstance(right, list):
                lset = {json.dumps(item, sort_keys=True, default=str) for item in left}
                rset = {json.dumps(item, sort_keys=True, default=str) for item in right}
                details[key]["only_in_expected"] = sorted(lset - rset)[:20]
                details[key]["only_in_actual"] = sorted(rset - lset)[:20]
                details[key]["expected_len"] = len(left)
                details[key]["actual_len"] = len(right)
            else:
                details[key]["expected"] = left
                details[key]["actual"] = right

    geo_left = _text(expected.get("georeference"))
    geo_right = _text(actual.get("georeference"))
    if geo_left and geo_right:
        if geo_left != geo_right:
            mismatches.append("georeference")
            details["georeference"] = {"equal": False, "expected": geo_left, "actual": geo_right}
        else:
            details["georeference"] = {"equal": True}
    else:
        presence_mismatch = bool(geo_left) != bool(geo_right)
        details["georeference"] = {
            "equal": not (presence_mismatch and require_georeference_match),
            "expected_present": bool(geo_left),
            "actual_present": bool(geo_right),
            "note": "presence-only mismatch; documented as non-blocking unless require_georeference_match",
        }
        if presence_mismatch and require_georeference_match:
            mismatches.append("georeference_presence")

    expected_digest = str(expected.get("structural_sha256") or "")
    actual_digest = str(actual.get("structural_sha256") or "")
    digest_equal = bool(expected_digest) and expected_digest == actual_digest

    return {
        "schema": "RUNTIME_MAP_STRUCTURAL_COMPARE/v1",
        "match": not mismatches,
        "digest_match": digest_equal,
        "expected_structural_sha256": expected_digest,
        "actual_structural_sha256": actual_digest,
        "mismatched_components": mismatches,
        "component_details": details,
        "normalization_rules": COMPONENT_RULES,
        "byte_equality_required": False,
        "byte_equality_note": (
            "CARLA re-serialises OpenDRIVE; structural fingerprint equality within "
            "the documented rules is the authority, never raw byte equality."
        ),
    }


# ---------------------------------------------------------------------------
# runtime capture
# ---------------------------------------------------------------------------


def runtime_opendrive_from_world(world: Any) -> Tuple[Optional[str], Dict[str, Any]]:
    """Best-effort ``world.get_map().to_opendrive()`` with diagnostics."""
    diagnostics: Dict[str, Any] = {"attempted": True, "supported": None, "error": None}
    try:
        carla_map = world.get_map()
    except Exception as exc:
        diagnostics["error"] = f"get_map_failed:{exc}"
        diagnostics["supported"] = False
        return None, diagnostics
    to_opendrive = getattr(carla_map, "to_opendrive", None)
    if to_opendrive is None:
        diagnostics["error"] = "to_opendrive_not_supported"
        diagnostics["supported"] = False
        return None, diagnostics
    try:
        text = to_opendrive()
    except Exception as exc:
        diagnostics["error"] = f"to_opendrive_failed:{exc}"
        diagnostics["supported"] = False
        return None, diagnostics
    diagnostics["supported"] = True
    diagnostics["bytes"] = len(str(text or ""))
    return str(text), diagnostics


def capture_runtime_map_identity(
    *,
    world: Any,
    expected_xodr_text: Optional[str],
    expected_label: str,
    output_path: Any,
    map_name_matched: bool,
    map_names_match_result: Optional[bool] = None,
    registry_key: Optional[str] = None,
    source_xodr_sha256: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Prove *correct canonical map + approved runtime structure*.

    Writes ``manual_grid_runtime_identity.json`` (or the caller's path) and
    returns the payload.  ``layer1`` is the name check, ``layer2`` is the
    structural check; both must pass for ``runtime_identity_pass``.
    """
    runtime_text, diag = runtime_opendrive_from_world(world)

    actual_fp: Optional[Dict[str, Any]] = None
    expected_fp: Optional[Dict[str, Any]] = None
    comparison: Optional[Dict[str, Any]] = None

    if expected_xodr_text:
        try:
            expected_fp = structural_fingerprint(expected_xodr_text)
        except Exception as exc:
            expected_fp = {"error": f"expected_parse_failed:{exc}"}

    if runtime_text:
        try:
            actual_fp = structural_fingerprint(runtime_text)
        except Exception as exc:
            actual_fp = {"error": f"runtime_parse_failed:{exc}"}

    if expected_fp and actual_fp and "error" not in expected_fp and "error" not in actual_fp:
        comparison = compare_fingerprints(expected_fp, actual_fp)
    else:
        comparison = {
            "schema": "RUNTIME_MAP_STRUCTURAL_COMPARE/v1",
            "match": False,
            "digest_match": False,
            "mismatched_components": ["structural_fingerprint_unavailable"],
            "component_details": {},
            "normalization_rules": COMPONENT_RULES,
            "byte_equality_required": False,
        }

    layer1_pass = bool(map_name_matched)
    layer2_pass = bool(comparison.get("match"))

    actual_map_name = None
    try:
        actual_map_name = str(world.get_map().name)
    except Exception:
        actual_map_name = None

    payload: Dict[str, Any] = {
        "schema": "MANUAL_GRID_RUNTIME_IDENTITY/v1",
        "expected_label": str(expected_label),
        "actual_map_name": actual_map_name,
        "registry_key": registry_key,
        "source_xodr_sha256": source_xodr_sha256,
        "layer1_name_identity": {
            "method": "map_names_match",
            "substring_matching_used": False,
            "passed": layer1_pass,
            "map_names_match_result": map_names_match_result,
        },
        "layer2_structural_identity": {
            "method": "canonical_structural_fingerprint",
            "passed": layer2_pass,
            "runtime_opendrive_diagnostics": diag,
            "expected_structural_sha256": (expected_fp or {}).get("structural_sha256"),
            "actual_structural_sha256": (actual_fp or {}).get("structural_sha256"),
            "comparison": comparison,
        },
        "runtime_identity_pass": bool(layer1_pass and layer2_pass),
    }
    if extra:
        payload["extra"] = dict(extra)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)
    return payload


def load_expected_manual_grid_xodr(
    *,
    registry_key: str = "manual_grid0828",
    repo_root: Optional[Any] = None,
) -> Dict[str, Any]:
    """Resolve the pinned manual Grid source XODR through the map registry."""
    from ultimate_pipeline.carla_tools.map_registry import PINNED_MAP_REGISTRY

    entry = PINNED_MAP_REGISTRY[registry_key]
    path = Path(entry["path"])
    if repo_root is not None:
        candidate = Path(repo_root) / path
        if candidate.exists():
            path = candidate
    text = path.read_text(encoding="utf-8", errors="replace")
    import hashlib

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "registry_key": registry_key,
        "path": str(path),
        "sha256": digest,
        "pinned_sha256": entry.get("sha256"),
        "sha_matches_pin": digest == entry.get("sha256"),
        "text": text,
    }
