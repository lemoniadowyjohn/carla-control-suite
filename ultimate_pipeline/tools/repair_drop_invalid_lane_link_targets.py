from __future__ import annotations
import xml.etree.ElementTree as ET
from pathlib import Path

def _i(x: str) -> int:
    try: return int(x)
    except Exception: return 0

def repair_drop_invalid_lane_link_targets(xodr_in: str, xodr_out: str) -> dict:
    tree = ET.parse(xodr_in)
    root = tree.getroot()

    # build lane ids per road per laneSection
    road_ls_ids = {}
    for road in root.findall(".//road"):
        rid = road.get("id","?")
        ls_sets=[]
        for ls in road.findall("./lanes/laneSection"):
            ids=set(_i(l.get("id","0")) for l in ls.findall(".//lane"))
            ls_sets.append(ids)
        road_ls_ids[rid]=ls_sets

    dropped_items = []
    repairs=0
    for road in root.findall(".//road"):
        rid = road.get("id","?")
        sections = road.findall("./lanes/laneSection")
        sets = road_ls_ids.get(rid, [])
        for i, ls in enumerate(sections):
            next_set = sets[i+1] if i+1 < len(sets) else None
            prev_set = sets[i-1] if i-1 >= 0 else None
            for lane in ls.findall(".//lane"):
                lane_id = _i(lane.get("id","0"))
                link = lane.find("./link")
                if link is None:
                    continue
                succ = link.find("./successor")
                if succ is not None and next_set is not None:
                    tgt = _i(succ.get("id","0"))
                    if tgt not in next_set:
                        dropped_items.append({
                            "road_id": rid,
                            "lane_section": i,
                            "lane_id": lane_id,
                            "link_type": "successor",
                            "target_lane_id": tgt,
                        })
                        link.remove(succ)
                        repairs += 1
                pred = link.find("./predecessor")
                if pred is not None and prev_set is not None:
                    tgt = _i(pred.get("id","0"))
                    if tgt not in prev_set:
                        dropped_items.append({
                            "road_id": rid,
                            "lane_section": i,
                            "lane_id": lane_id,
                            "link_type": "predecessor",
                            "target_lane_id": tgt,
                        })
                        link.remove(pred)
                        repairs += 1

    Path(xodr_out).parent.mkdir(parents=True, exist_ok=True)
    tree.write(xodr_out, encoding="utf-8", xml_declaration=True)
    roads = sorted({d.get("road_id") for d in dropped_items if d.get("road_id") is not None})
    dropped_lane_links = {"count": len(dropped_items), "items": dropped_items, "roads": roads}
    if dropped_lane_links["count"]:
        print(f"[REPAIR] Dropped {dropped_lane_links['count']} invalid lane link(s) (roads: {roads})")
    return {"repairs": repairs, "out": xodr_out, "dropped_lane_links": dropped_lane_links}

if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-xodr", required=True)
    ap.add_argument("--out-xodr", required=True)
    args = ap.parse_args()
    print(json.dumps(repair_drop_invalid_lane_link_targets(args.in_xodr, args.out_xodr), indent=2))
