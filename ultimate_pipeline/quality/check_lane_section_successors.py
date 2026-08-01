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

    report = {"repairs": repairs, "failures": failures, "input": xodr_path}
    if out_path:
        tree.write(out_path, encoding="utf-8", xml_declaration=True)
        report["output"] = out_path

    if failures and strict:
        raise RuntimeError(
            f"LaneSection successor resolvability failed: {len(failures)} issues. "
            f"Example: {failures[0]}"
        )

    return report
