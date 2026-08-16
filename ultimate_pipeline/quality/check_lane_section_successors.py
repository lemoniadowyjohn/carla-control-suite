# ultimate_pipeline/quality/check_lane_section_successors.py
from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

def _lane_id_int(lane_el: ET.Element) -> Optional[int]:
    try:
        return int(lane_el.get("id"))
    except Exception:
        return None

def _get_lane_link_child(lane_el: ET.Element, tag: str) -> Optional[ET.Element]:
    link = lane_el.find("link")
    if link is None:
        return None
    return link.find(tag)

def _ensure_link(lane_el: ET.Element) -> ET.Element:
    link = lane_el.find("link")
    if link is None:
        link = ET.SubElement(lane_el, "link")
    return link

def _choose_best_target(src_id: int, next_ids: List[int]) -> Optional[int]:
    if not next_ids:
        return None
    if src_id in next_ids:
        return src_id
    # prefer same sign
    same_sign = [i for i in next_ids if (i == 0) == (src_id == 0) and (i * src_id) > 0]
    cand = same_sign if same_sign else next_ids
    return min(cand, key=lambda x: (abs(x - src_id), abs(x)))

def _lane_width_average(lane_el: ET.Element) -> float:
    vals = []
    for width in lane_el.findall("width"):
        try:
            vals.append(float(width.get("a") or 0.0))
        except Exception:
            pass
    return (sum(vals) / len(vals)) if vals else 0.0

def _lane_map_by_id(section: ET.Element) -> Dict[int, ET.Element]:
    out: Dict[int, ET.Element] = {}
    for lane in section.findall(".//lane"):
        lane_id = _lane_id_int(lane)
        if lane_id is not None:
            out[lane_id] = lane
    return out

def _is_drivable_type(lane_el: Optional[ET.Element], lane_types: Tuple[str, ...]) -> bool:
    return lane_el is not None and lane_el.get("type") in lane_types

def _reclassify_linked_none_or_restricted_lanes(
    lane_sections: List[ET.Element],
    *,
    lane_types: Tuple[str, ...],
) -> int:
    if not lane_types:
        return 0
    target_type = lane_types[0]
    section_maps = [_lane_map_by_id(section) for section in lane_sections]
    reclassified = 0

    for idx, section in enumerate(lane_sections):
        prev_map = section_maps[idx - 1] if idx > 0 else {}
        next_map = section_maps[idx + 1] if idx + 1 < len(section_maps) else {}
        for lane in section.findall(".//lane"):
            lane_id = _lane_id_int(lane)
            if lane_id is None or lane_id == 0:
                continue
            if lane.get("type") not in {"none", "restricted"}:
                continue
            width = _lane_width_average(lane)
            if not (2.5 <= width <= 6.0):
                continue

            linked_to_driving = _is_drivable_type(prev_map.get(lane_id), lane_types)
            linked_to_driving = linked_to_driving or _is_drivable_type(next_map.get(lane_id), lane_types)

            pred = _get_lane_link_child(lane, "predecessor")
            if pred is not None:
                pred_id = _lane_id_int(pred)
                linked_to_driving = linked_to_driving or _is_drivable_type(prev_map.get(pred_id), lane_types)
            succ = _get_lane_link_child(lane, "successor")
            if succ is not None:
                succ_id = _lane_id_int(succ)
                linked_to_driving = linked_to_driving or _is_drivable_type(next_map.get(succ_id), lane_types)

            if linked_to_driving:
                lane.set("type", target_type)
                reclassified += 1
    return reclassified

def repair_and_assert_lane_section_successors(
    xodr_path: str,
    out_path: Optional[str] = None,
    lane_types: Tuple[str, ...] = ("driving",),
    strict: bool = True,
) -> Dict:
    """
    Ensures laneSection-to-laneSection successor/predecessor links resolve within each road.

    - Repairs missing/broken successor/predecessor IDs by mapping to best matching lane in next section.
    - If strict=True, raises RuntimeError if any lane in lane_types cannot be repaired.
    """
    tree = ET.parse(xodr_path)
    root = tree.getroot()

    failures = []
    repairs = 0
    reclassified = 0

    for road in root.findall(".//road"):
        road_id = road.get("id", "?")
        lane_sections = road.findall("./lanes/laneSection")
        if len(lane_sections) < 2:
            continue

        # sort by s
        def s_val(ls: ET.Element) -> float:
            try:
                return float(ls.get("s", "0"))
            except Exception:
                return 0.0

        lane_sections.sort(key=s_val)
        reclassified += _reclassify_linked_none_or_restricted_lanes(
            lane_sections,
            lane_types=lane_types,
        )

        # helper: collect lane ids by laneSection
        def collect_ids(ls: ET.Element) -> List[int]:
            ids = []
            for lane in ls.findall(".//lane"):
                lid = _lane_id_int(lane)
                if lid is not None:
                    ids.append(lid)
            return ids

        for i in range(len(lane_sections) - 1):
            a = lane_sections[i]
            b = lane_sections[i + 1]
            a_ids = collect_ids(a)
            b_ids = collect_ids(b)
            b_idset = set(b_ids)
            a_driving_ids = [
                lid
                for lid, lane in _lane_map_by_id(a).items()
                if lane.get("type") in lane_types
            ]
            a_driving_idset = set(a_driving_ids)

            # lanes in A that we care about
            for lane in a.findall(".//lane"):
                if lane.get("type") not in lane_types:
                    continue

                src_id = _lane_id_int(lane)
                if src_id is None:
                    continue

                # successor must exist and must resolve into B
                link = _ensure_link(lane)
                succ = link.find("successor")
                succ_id = None
                if succ is not None:
                    try:
                        succ_id = int(succ.get("id"))
                    except Exception:
                        succ_id = None

                if succ_id is None or succ_id not in b_idset:
                    best = _choose_best_target(src_id, b_ids)
                    if best is None:
                        failures.append(
                            {"road": road_id, "laneSection_from": i, "lane_id": src_id, "reason": "no_target_in_next_section"}
                        )
                        continue
                    if succ is None:
                        succ = ET.SubElement(link, "successor")
                    succ.set("id", str(best))
                    repairs += 1
                    succ_id = best

                # ensure reverse predecessor exists in B for that target lane
                target_lane = None
                for ln in b.findall(".//lane"):
                    try:
                        if int(ln.get("id")) == succ_id:
                            target_lane = ln
                            break
                    except Exception:
                        pass

                if target_lane is None:
                    failures.append(
                        {"road": road_id, "laneSection_from": i, "lane_id": src_id, "reason": "target_lane_missing_even_after_repair"}
                    )
                    continue

                tlink = _ensure_link(target_lane)
                pred = tlink.find("predecessor")
                pred_id = None
                if pred is not None:
                    try:
                        pred_id = int(pred.get("id"))
                    except Exception:
                        pred_id = None

                if pred_id != src_id:
                    if pred is None:
                        pred = ET.SubElement(tlink, "predecessor")
                    pred.set("id", str(src_id))
                    repairs += 1

            # Mirror pass for driving lanes in B: repair a missing predecessor
            # only when A has a compatible driving lane. Do not fabricate
            # links from newly-born lanes back to sidewalks/non-driving lanes.
            for lane in b.findall(".//lane"):
                if lane.get("type") not in lane_types:
                    continue
                dst_id = _lane_id_int(lane)
                if dst_id is None:
                    continue
                link = _ensure_link(lane)
                pred = link.find("predecessor")
                pred_id = None
                if pred is not None:
                    try:
                        pred_id = int(pred.get("id"))
                    except Exception:
                        pred_id = None
                if pred_id in a_driving_idset:
                    continue
                best = _choose_best_target(dst_id, a_driving_ids)
                if best is None:
                    continue
                if pred is None:
                    pred = ET.SubElement(link, "predecessor")
                pred.set("id", str(best))
                repairs += 1

    report = {
        "repairs": repairs,
        "reclassified_none_or_restricted_lanes": reclassified,
        "failures": failures,
        "input": xodr_path,
    }
    if out_path:
        tree.write(out_path, encoding="utf-8", xml_declaration=True)
        report["output"] = out_path

    if failures and strict:
        raise RuntimeError(
            f"LaneSection successor resolvability failed: {len(failures)} issues. "
            f"Example: {failures[0]}"
        )

    return report
