from __future__ import annotations

import json
import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.quality.check_geometric_continuity import (
    _angle_diff,
    _parse_geometries,
    _pose_at_s,
    _road_length,
    _road_sort_key,
)


@dataclass(frozen=True)
class _RoadContext:
    road: ET.Element
    road_id: str
    length: float
    geoms: list[Any]
    warnings: list[str]


@dataclass(frozen=True)
class _EndpointCandidate:
    road_id: str
    endpoint: str
    pose_x: float
    pose_y: float
    pose_hdg: float


def _normalize_contact_point(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if raw in {"start", "end"}:
        return raw
    return None


def _endpoint_s(endpoint: str, road_length: float) -> float:
    ep = str(endpoint or "").strip().lower()
    return 0.0 if ep == "start" else float(max(0.0, road_length))


def _from_endpoint_for_link(link_kind: str, contact_point: Optional[str]) -> str:
    # OpenDRIVE road links are anchored at the predecessor-start / successor-end of source road.
    kind = str(link_kind or "").strip().lower()
    return "start" if kind == "predecessor" else "end"


def _expected_heading_delta_rad(from_endpoint: str, to_endpoint: str) -> float:
    return math.pi if str(from_endpoint) == str(to_endpoint) else 0.0


def _percentile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    vv = sorted(float(v) for v in values)
    qq = max(0.0, min(1.0, float(q)))
    if len(vv) == 1:
        return float(vv[0])
    pos = qq * (len(vv) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(vv[lo])
    frac = pos - lo
    return float(vv[lo] * (1.0 - frac) + vv[hi] * frac)


def _road_contexts(root: ET.Element) -> Dict[str, _RoadContext]:
    out: Dict[str, _RoadContext] = {}
    for road in root.findall("road"):
        rid = str(road.get("id") or "").strip()
        if not rid:
            continue
        geoms, warns = _parse_geometries(road)
        out[rid] = _RoadContext(
            road=road,
            road_id=rid,
            length=float(max(0.0, _road_length(road))),
            geoms=geoms,
            warnings=list(warns),
        )
    return out


def _sorted_roads(root: ET.Element) -> List[ET.Element]:
    roads = list(root.findall("road"))
    roads.sort(key=lambda r: _road_sort_key(str(r.get("id") or "")))
    return roads


def _extract_link_element(
    road: ET.Element,
    link_kind: str,
) -> Optional[ET.Element]:
    link = road.find("link")
    if link is None:
        return None
    return link.find(link_kind)


def _eval_link_with_target(
    *,
    contexts: Dict[str, _RoadContext],
    from_road_id: str,
    link_kind: str,
    to_road_id: str,
    contact_point: Optional[str],
) -> Dict[str, Any]:
    from_ctx = contexts.get(from_road_id)
    if from_ctx is None:
        return {
            "ok": False,
            "error": "missing_from_road",
            "dxy_m": None,
            "dhdg_rad": None,
        }
    to_ctx = contexts.get(to_road_id)
    if to_ctx is None:
        return {
            "ok": False,
            "error": "missing_target_road",
            "dxy_m": None,
            "dhdg_rad": None,
        }

    from_endpoint = _from_endpoint_for_link(link_kind, contact_point)
    from_s = _endpoint_s(from_endpoint, from_ctx.length)
    from_pose, from_warn = _pose_at_s(from_ctx.geoms, from_s)

    to_endpoint = contact_point if contact_point in {"start", "end"} else "start"
    to_s = _endpoint_s(to_endpoint, to_ctx.length)
    to_pose, to_warn = _pose_at_s(to_ctx.geoms, to_s)

    dxy = math.hypot(to_pose.x - from_pose.x, to_pose.y - from_pose.y)
    expected_heading_delta = _expected_heading_delta_rad(from_endpoint, to_endpoint)
    dhdg = abs(_angle_diff(to_pose.hdg, from_pose.hdg + expected_heading_delta))
    return {
        "ok": True,
        "error": "",
        "from_endpoint": str(from_endpoint),
        "to_endpoint": str(to_endpoint),
        "expected_heading_delta_rad": float(expected_heading_delta),
        "from_pose": {
            "x": float(from_pose.x),
            "y": float(from_pose.y),
            "hdg": float(from_pose.hdg),
        },
        "to_pose": {
            "x": float(to_pose.x),
            "y": float(to_pose.y),
            "hdg": float(to_pose.hdg),
        },
        "dxy_m": float(dxy),
        "dhdg_rad": float(dhdg),
        "warnings": list(from_ctx.warnings) + list(to_ctx.warnings) + from_warn + to_warn,
    }


def build_road_link_endpoint_errors(
    xodr_path: str,
    *,
    top_k: int = 50,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "schema_version": "1.0",
        "xodr_path": str(xodr_path),
        "num_roads": 0,
        "num_road_links": 0,
        "num_missing_targets": 0,
        "num_invalid_contact_point": 0,
        "summary": {
            "dxy_m": {"p95": None, "p99": None, "max": None},
            "dhdg_rad": {"p95": None, "p99": None, "max": None},
        },
        "top_offenders": [],
        "links": [],
        "warnings": [],
    }
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as exc:
        report["warnings"].append(f"failed_to_parse_xodr: {exc}")
        return report

    contexts = _road_contexts(root)
    report["num_roads"] = int(len(contexts))

    dxy_values: List[float] = []
    dhdg_values: List[float] = []
    links: List[Dict[str, Any]] = []

    for road in _sorted_roads(root):
        from_road_id = str(road.get("id") or "").strip()
        if not from_road_id:
            continue
        for link_kind in ("predecessor", "successor"):
            link_el = _extract_link_element(road, link_kind)
            if link_el is None:
                continue
            etype = str(link_el.get("elementType") or "").strip()
            to_road_id = str(link_el.get("elementId") or "").strip()
            if etype != "road" or not to_road_id:
                continue

            cp_raw = str(link_el.get("contactPoint") or "").strip()
            cp_norm = _normalize_contact_point(cp_raw)
            if cp_norm is None and cp_raw:
                report["num_invalid_contact_point"] = int(
                    report["num_invalid_contact_point"]
                ) + 1

            rec: Dict[str, Any] = {
                "from_road_id": str(from_road_id),
                "link_kind": str(link_kind),
                "to_road_id": str(to_road_id),
                "contact_point_raw": cp_raw,
                "contact_point": cp_norm,
                "contact_point_defaulted": bool(cp_norm is None),
            }

            link_eval = _eval_link_with_target(
                contexts=contexts,
                from_road_id=from_road_id,
                link_kind=link_kind,
                to_road_id=to_road_id,
                contact_point=cp_norm,
            )
            rec["status"] = "ok" if bool(link_eval.get("ok", False)) else str(
                link_eval.get("error") or "unknown_error"
            )
            if not bool(link_eval.get("ok", False)):
                if rec["status"] == "missing_target_road":
                    report["num_missing_targets"] = int(report["num_missing_targets"]) + 1
                rec["dxy_m"] = None
                rec["dhdg_rad"] = None
                rec["from_endpoint"] = _from_endpoint_for_link(link_kind, cp_norm)
                rec["to_endpoint"] = cp_norm if cp_norm in {"start", "end"} else "start"
                rec["warnings"] = list(link_eval.get("warnings", []))
            else:
                rec["from_endpoint"] = str(link_eval.get("from_endpoint"))
                rec["to_endpoint"] = str(link_eval.get("to_endpoint"))
                rec["from_pose"] = dict(link_eval.get("from_pose", {}))
                rec["to_pose"] = dict(link_eval.get("to_pose", {}))
                rec["dxy_m"] = float(link_eval.get("dxy_m", 0.0))
                rec["dhdg_rad"] = float(link_eval.get("dhdg_rad", 0.0))
                rec["warnings"] = list(link_eval.get("warnings", []))
                dxy_values.append(float(rec["dxy_m"]))
                dhdg_values.append(float(rec["dhdg_rad"]))
            links.append(rec)

    report["num_road_links"] = int(len(links))
    report["links"] = links
    if dxy_values:
        report["summary"]["dxy_m"]["p95"] = _percentile(dxy_values, 0.95)
        report["summary"]["dxy_m"]["p99"] = _percentile(dxy_values, 0.99)
        report["summary"]["dxy_m"]["max"] = float(max(dxy_values))
    if dhdg_values:
        report["summary"]["dhdg_rad"]["p95"] = _percentile(dhdg_values, 0.95)
        report["summary"]["dhdg_rad"]["p99"] = _percentile(dhdg_values, 0.99)
        report["summary"]["dhdg_rad"]["max"] = float(max(dhdg_values))

    offenders = [
        rec
        for rec in links
        if isinstance(rec.get("dxy_m"), (int, float))
        and isinstance(rec.get("dhdg_rad"), (int, float))
    ]
    offenders.sort(
        key=lambda rec: (
            -float(rec.get("dxy_m", 0.0)),
            -float(rec.get("dhdg_rad", 0.0)),
            _road_sort_key(str(rec.get("from_road_id", ""))),
            str(rec.get("link_kind", "")),
            _road_sort_key(str(rec.get("to_road_id", ""))),
            str(rec.get("to_endpoint", "")),
        )
    )
    report["top_offenders"] = offenders[: max(1, int(top_k))]
    return report


def write_road_link_endpoint_errors(
    *,
    xodr_path: str,
    out_json: str,
    top_k: int = 50,
) -> Dict[str, Any]:
    report = build_road_link_endpoint_errors(xodr_path, top_k=top_k)
    os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=True, sort_keys=True)
    return report


def _road_endpoint_catalog(
    contexts: Dict[str, _RoadContext],
) -> List[_EndpointCandidate]:
    out: List[_EndpointCandidate] = []
    for rid in sorted(contexts.keys(), key=_road_sort_key):
        ctx = contexts[rid]
        start_pose, _ = _pose_at_s(ctx.geoms, 0.0)
        end_pose, _ = _pose_at_s(ctx.geoms, max(0.0, float(ctx.length)))
        out.append(
            _EndpointCandidate(
                road_id=str(rid),
                endpoint="start",
                pose_x=float(start_pose.x),
                pose_y=float(start_pose.y),
                pose_hdg=float(start_pose.hdg),
            )
        )
        out.append(
            _EndpointCandidate(
                road_id=str(rid),
                endpoint="end",
                pose_x=float(end_pose.x),
                pose_y=float(end_pose.y),
                pose_hdg=float(end_pose.hdg),
            )
        )
    return out


def _search_best_nearby_endpoint(
    *,
    from_road_id: str,
    from_endpoint: str,
    from_pose: Dict[str, float],
    current_target: str,
    allow_new_self_link: bool,
    endpoints: List[_EndpointCandidate],
    preferred_endpoint: Optional[str],
    radius_start_m: float,
    radius_cap_m: float,
    radius_step_m: float,
) -> Optional[Dict[str, Any]]:
    start_r = max(0.0, float(radius_start_m))
    cap_r = max(start_r, float(radius_cap_m))
    step_r = max(0.1, float(radius_step_m))
    radius = start_r
    while radius <= cap_r + 1e-9:
        candidates: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
        for endpoint in endpoints:
            if (
                endpoint.road_id == from_road_id
                and str(current_target) != str(from_road_id)
                and not allow_new_self_link
            ):
                continue
            dxy = math.hypot(
                float(endpoint.pose_x) - float(from_pose["x"]),
                float(endpoint.pose_y) - float(from_pose["y"]),
            )
            if dxy > radius + 1e-9:
                continue
            expected_heading_delta = _expected_heading_delta_rad(from_endpoint, endpoint.endpoint)
            dhdg = abs(
                float(
                    _angle_diff(
                        float(endpoint.pose_hdg),
                        float(from_pose["hdg"]) + expected_heading_delta,
                    )
                )
            )
            endpoint_rank = 0 if str(endpoint.endpoint) == "start" else 1
            score = (
                float(dxy),
                float(dhdg),
                _road_sort_key(str(endpoint.road_id)),
                int(endpoint_rank),
            )
            candidates.append(
                (
                    score,
                    {
                        "to_road_id": str(endpoint.road_id),
                        "to_endpoint": str(endpoint.endpoint),
                        "dxy_m": float(dxy),
                        "dhdg_rad": float(dhdg),
                        "expected_heading_delta_rad": float(expected_heading_delta),
                    },
                )
            )
        if candidates:
            if preferred_endpoint in {"start", "end"}:
                preferred_only = [
                    item
                    for item in candidates
                    if str(item[1].get("to_endpoint")) == str(preferred_endpoint)
                ]
                if preferred_only:
                    candidates = preferred_only
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1]
        radius += step_r
    return None


def repair_road_link_targets(
    *,
    xodr_path: str,
    output_path: Optional[str] = None,
    repair_log_jsonl: Optional[str] = None,
    bad_dxy_threshold_m: float = 50.0,
    search_radius_start_m: float = 10.0,
    search_radius_cap_m: float = 30.0,
    search_radius_step_m: float = 10.0,
) -> Dict[str, Any]:
    threshold = float(max(0.0, bad_dxy_threshold_m))
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as exc:
        return {
            "applied": False,
            "error": f"failed_to_parse_xodr: {exc}",
            "xodr_path": str(xodr_path),
            "output_path": str(output_path or xodr_path),
            "num_links_considered": 0,
            "num_repaired": 0,
        }

    contexts = _road_contexts(root)
    endpoints = _road_endpoint_catalog(contexts)

    changes: List[Dict[str, Any]] = []
    num_links_considered = 0

    for road in _sorted_roads(root):
        from_road_id = str(road.get("id") or "").strip()
        if not from_road_id:
            continue
        for link_kind in ("predecessor", "successor"):
            link_el = _extract_link_element(road, link_kind)
            if link_el is None:
                continue
            etype = str(link_el.get("elementType") or "").strip()
            to_road_id = str(link_el.get("elementId") or "").strip()
            if etype != "road" or not to_road_id:
                continue

            cp_raw = str(link_el.get("contactPoint") or "").strip()
            cp_norm = _normalize_contact_point(cp_raw)
            cur_eval = _eval_link_with_target(
                contexts=contexts,
                from_road_id=from_road_id,
                link_kind=link_kind,
                to_road_id=to_road_id,
                contact_point=cp_norm,
            )
            num_links_considered += 1

            cur_dxy = (
                float(cur_eval.get("dxy_m"))
                if isinstance(cur_eval.get("dxy_m"), (int, float))
                else None
            )
            needs_repair = (not bool(cur_eval.get("ok", False))) or (
                cur_dxy is not None and float(cur_dxy) > threshold
            )
            if not needs_repair:
                continue

            before = {
                "from_road_id": str(from_road_id),
                "link_kind": str(link_kind),
                "to_road_id": str(to_road_id),
                "contact_point_raw": cp_raw,
                "contact_point": cp_norm,
                "dxy_m": cur_dxy,
                "dhdg_rad": cur_eval.get("dhdg_rad"),
                "status": "ok" if bool(cur_eval.get("ok", False)) else str(cur_eval.get("error")),
            }

            changed = False
            change_reason = ""

            # 1) Try contactPoint changes on current target first.
            if bool(cur_eval.get("ok", False)):
                cp_candidates: List[str] = []
                if cp_norm in {"start", "end"}:
                    cp_candidates = ["end" if cp_norm == "start" else "start"]
                else:
                    cp_candidates = ["start", "end"]

                cp_scored: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
                for cp_cand in cp_candidates:
                    cand_eval = _eval_link_with_target(
                        contexts=contexts,
                        from_road_id=from_road_id,
                        link_kind=link_kind,
                        to_road_id=to_road_id,
                        contact_point=cp_cand,
                    )
                    if not bool(cand_eval.get("ok", False)):
                        continue
                    cand_dxy = float(cand_eval.get("dxy_m", 0.0))
                    cand_dhdg = float(cand_eval.get("dhdg_rad", 0.0))
                    cp_scored.append(
                        (
                            (cand_dxy, str(cp_cand)),
                            {
                                "contact_point": cp_cand,
                                "dxy_m": cand_dxy,
                                "dhdg_rad": cand_dhdg,
                            },
                        )
                    )
                if cp_scored:
                    cp_scored.sort(key=lambda item: item[0])
                    best_cp = cp_scored[0][1]
                    if (
                        float(best_cp["dxy_m"]) <= threshold
                        and str(best_cp["contact_point"]) != str(cp_norm)
                    ):
                        link_el.set("contactPoint", str(best_cp["contact_point"]))
                        changed = True
                        change_reason = "contact_point_flip"

            # 2) If still bad/missing, search nearby endpoints.
            if not changed:
                from_pose_for_search: Optional[Dict[str, float]] = None
                if bool(cur_eval.get("ok", False)):
                    fp = cur_eval.get("from_pose")
                    if isinstance(fp, dict) and {"x", "y", "hdg"} <= set(fp.keys()):
                        from_endpoint_for_search = str(cur_eval.get("from_endpoint") or _from_endpoint_for_link(link_kind, cp_norm))
                        from_pose_for_search = {
                            "x": float(fp["x"]),
                            "y": float(fp["y"]),
                            "hdg": float(fp["hdg"]),
                        }
                else:
                    from_ctx = contexts.get(from_road_id)
                    if from_ctx is not None:
                        from_endpoint = _from_endpoint_for_link(link_kind, cp_norm)
                        from_s = _endpoint_s(from_endpoint, from_ctx.length)
                        from_pose, _ = _pose_at_s(from_ctx.geoms, from_s)
                        from_endpoint_for_search = str(from_endpoint)
                        from_pose_for_search = {
                            "x": float(from_pose.x),
                            "y": float(from_pose.y),
                            "hdg": float(from_pose.hdg),
                        }
                if from_pose_for_search is not None:
                    best_near = _search_best_nearby_endpoint(
                        from_road_id=from_road_id,
                        from_endpoint=from_endpoint_for_search,
                        from_pose=from_pose_for_search,
                        current_target=to_road_id,
                        allow_new_self_link=False,
                        endpoints=endpoints,
                        preferred_endpoint=(
                            "start"
                            if link_kind == "successor"
                            else ("end" if link_kind == "predecessor" else None)
                        ),
                        radius_start_m=search_radius_start_m,
                        radius_cap_m=search_radius_cap_m,
                        radius_step_m=search_radius_step_m,
                    )
                    if best_near is not None:
                        same_target = str(best_near["to_road_id"]) == str(to_road_id)
                        same_cp = str(best_near["to_endpoint"]) == str(cp_norm or "")
                        if not (same_target and same_cp):
                            if (
                                str(best_near["to_road_id"]) == str(from_road_id)
                                and str(to_road_id) != str(from_road_id)
                            ):
                                # Never create a brand new self-link.
                                best_near = None
                            if best_near is not None:
                                link_el.set("elementType", "road")
                                link_el.set("elementId", str(best_near["to_road_id"]))
                                link_el.set("contactPoint", str(best_near["to_endpoint"]))
                                changed = True
                                change_reason = "nearby_endpoint_search"

            if not changed:
                continue

            new_to_road_id = str(link_el.get("elementId") or "").strip()
            new_cp = _normalize_contact_point(str(link_el.get("contactPoint") or "").strip())
            after_eval = _eval_link_with_target(
                contexts=contexts,
                from_road_id=from_road_id,
                link_kind=link_kind,
                to_road_id=new_to_road_id,
                contact_point=new_cp,
            )
            changes.append(
                {
                    "reason": str(change_reason),
                    "before": before,
                    "after": {
                        "from_road_id": str(from_road_id),
                        "link_kind": str(link_kind),
                        "to_road_id": str(new_to_road_id),
                        "contact_point": new_cp,
                        "dxy_m": after_eval.get("dxy_m"),
                        "dhdg_rad": after_eval.get("dhdg_rad"),
                        "status": "ok"
                        if bool(after_eval.get("ok", False))
                        else str(after_eval.get("error")),
                    },
                }
            )

    out_path = str(output_path or xodr_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)

    if repair_log_jsonl:
        log_path = Path(repair_log_jsonl)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            for change in changes:
                f.write(json.dumps(change, ensure_ascii=True, sort_keys=True))
                f.write("\n")

    return {
        "applied": bool(changes),
        "xodr_path": str(xodr_path),
        "output_path": out_path,
        "repair_log_jsonl": str(repair_log_jsonl) if repair_log_jsonl else None,
        "num_links_considered": int(num_links_considered),
        "num_repaired": int(len(changes)),
        "bad_dxy_threshold_m": float(threshold),
        "search_radius_start_m": float(search_radius_start_m),
        "search_radius_cap_m": float(search_radius_cap_m),
        "search_radius_step_m": float(search_radius_step_m),
    }
