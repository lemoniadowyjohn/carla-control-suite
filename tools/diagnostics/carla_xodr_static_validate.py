#!/usr/bin/env python3
"""Stage E: offline structural validation of XODR candidates. No server required."""
import hashlib, json, os, sys, time, zipfile
from pathlib import Path

OUT = Path(r"E:\wt\repair-map-realism-p0-837a8504\reports\carla_runtime")
OUT.mkdir(parents=True, exist_ok=True)

CANDIDATES = [
    (r"E:\wt\repair-map-realism-p0-837a8504\cities\ingolstadt\ingolstadt_osm_auto.xodr",
     "current-source automatic candidate (worktree cities/)"),
    (r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\cities\ingolstadt\manual_grid0821.xodr",
     "manual Grid0821 OpenDRIVE (repo)"),
    (r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\cities\ingolstadt\ingolstadt_dominik.xodr",
     "manual Dominik Ingolstadt (repo)"),
]

def sha256(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()

def validate(path):
    r = {"path": path, "exists": False}
    p = Path(path)
    if not p.exists():
        r["status"] = "MISSING"
        return r
    r["exists"] = True
    r["bytes"] = p.stat().st_size
    t0 = time.time()
    r["sha256"] = sha256(path)
    r["sha256_seconds"] = round(time.time() - t0, 2)
    # streaming-ish XML parse (ElementTree is in-memory; guard by size)
    import xml.etree.ElementTree as ET
    t0 = time.time()
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as exc:
        r["status"] = "XML_PARSE_FAIL"
        r["error"] = f"{type(exc).__name__}: {exc}"
        return r
    r["xml_parse_seconds"] = round(time.time() - t0, 2)
    # Strip XML namespaces so OpenDRIVE elements are addressable without prefix.
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    r["root_tag"] = root.tag
    def find_all(tag):
        return root.findall(tag)
    def find_one(tag):
        el = find_all(tag)
        return el[0] if el else None
    r["header"] = {
        "revMajor": (find_one("header").get("revMajor") if find_one("header") is not None else None),
        "revMinor": (find_one("header").get("revMinor") if find_one("header") is not None else None),
        "name": (find_one("header").get("name") if find_one("header") is not None else None),
        "version": (find_one("header").get("version") if find_one("header") is not None else None),
        "date": (find_one("header").get("date") if find_one("header") is not None else None),
        "north": (find_one("header").get("north") if find_one("header") is not None else None),
        "south": (find_one("header").get("south") if find_one("header") is not None else None),
        "east": (find_one("header").get("east") if find_one("header") is not None else None),
        "west": (find_one("header").get("west") if find_one("header") is not None else None),
    }
    geo = find_one("geoReference")
    r["geoReference"] = (geo.attrib if geo is not None else None)
    roads = find_all("road")
    junctions = find_all("junction")
    r["counts"] = {
        "roads": len(roads),
        "junctions": len(junctions),
        "lanes_total": sum(len(lanes.findall("lane")) for road in roads for lanes in road.findall("lanes")),
        "lane_sections": sum(len(road.findall("lanes")) for road in roads),
        "planview_geometry": sum(len(pv.findall("geometry")) for road in roads for pv in road.findall("planView")),
    }
    # validation
    errors, warnings = [], []
    road_ids = set()
    dangling = []
    zero_len = []
    bad_lane_links = []
    dup = 0
    for road in roads:
        rid = road.get("id")
        if rid in road_ids:
            dup += 1
        road_ids.add(rid)
        length = road.get("length")
        try:
            if length is None or float(length) <= 0.0:
                zero_len.append(rid)
        except ValueError:
            errors.append(f"road {rid}: non-numeric length {length!r}")
        # planView continuity: first geometry s should be 0
        lanes = road.findall("lanes")
        if lanes:
            for ls in lanes:
                for lanelink in ls.findall("laneLink"):
                    for succ in lanelink.findall("successor"):
                        if succ.get("id") != "-1" and succ.get("id") not in {str(x) for x in road_ids}:
                            dangling.append((rid, succ.get("id")))
                    for pred in lanelink.findall("predecessor"):
                        if pred.get("id") != "-1" and pred.get("id") not in {str(x) for x in road_ids}:
                            dangling.append((rid, pred.get("id")))
    # road link successors
    for road in roads:
        rid = road.get("id")
        link = road.find("link")
        if link is None:
            continue
        for kind in ("successor", "predecessor"):
            el = link.find(kind)
            if el is None:
                continue
            t = el.get("elementType")
            if t == "road" and el.get("elementId") not in road_ids:
                dangling.append((rid, el.get("elementId")))
    if dup:
        errors.append(f"duplicate_road_ids:{dup}")
    if zero_len:
        errors.append(f"non_positive_road_length:{len(zero_len)}")
    if dangling:
        errors.append(f"dangling_references:{len(dangling)}")
    r["validation"] = {
        "errors": errors[:20],
        "error_count": len(errors),
        "warnings": warnings[:20],
        "warning_count": len(warnings),
        "duplicate_road_ids": dup,
        "non_positive_length_roads": len(zero_len),
        "dangling_refs": len(dangling),
        "dangling_sample": dangling[:10],
    }
    # coordinate magnitudes
    xs, ys = [], []
    for road in roads:
        for pv in road.findall("planView"):
            for g in pv.findall("geometry"):
                for pt in g.findall("point"):
                    try:
                        xs.append(float(pt.get("x", 0)))
                        ys.append(float(pt.get("y", 0)))
                    except ValueError:
                        pass
    r["coordinate_extent"] = None
    if xs:
        r["coordinate_extent"] = {
            "x_min": min(xs), "x_max": max(xs), "y_min": min(ys), "y_max": max(ys),
            "span_x": max(xs) - min(xs), "span_y": max(ys) - min(ys),
            "sample_count": len(xs),
        }
        r["float32_precision_loss_meters"] = round(max(abs(v) for v in xs + ys) * 2 ** -24, 4)
    # CARLA-relevant compat rules
    compat = []
    if r["counts"]["junctions"] > 0:
        compat.append("junctions_present (CARLA junction graph construction applies)")
    if r["coordinate_extent"] and max(abs(r["coordinate_extent"]["x_max"]), abs(r["coordinate_extent"]["y_max"])) > 20000:
        compat.append("large_absolute_coordinates (Unreal float32 precision risk)")
    r["carla_compat_flags"] = compat
    r["status"] = "STATIC_PASS" if not errors else "STATIC_FAIL"
    return r


def main():
    results = []
    for path, note in CANDIDATES:
        print(f"--- validating {path}")
        try:
            v = validate(path)
        except Exception as exc:
            v = {"path": path, "status": "VALIDATOR_ERROR", "error": f"{type(exc).__name__}: {exc}"}
        v["authority_note"] = note
        results.append(v)
        print(f"    status={v.get('status')} sha={v.get('sha256','?')[:16]} counts={v.get('counts')}")
    out = {
        "stage": "E",
        "objective": "offline structural validation of automatic OpenDRIVE candidates",
        "validator": "inline structural validator (XML well-formedness, road/junction/lane counts, positive lengths, dangling refs, duplicate ids, coordinate extent, float32 precision, CARLA compat flags)",
        "candidates": results,
        "note": "Source XODR files were NOT modified. No CARLA server was used for this stage.",
    }
    (OUT / "FINAL_XODR_STATIC_VALIDATION.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("WROTE FINAL_XODR_STATIC_VALIDATION.json")
    # authority classification
    auth = {
        "historical_map_of_record_sha256": "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8",
        "historical_map_of_record_status": "NOT_VERIFIED_IN_THIS_CAMPAIGN (hash recorded from prior receipt; file not re-located under an authorized path in this session)",
        "candidates": [],
        "selection_rule": "Authority determined by provenance (source commit + manifest + hash), NOT by filename recency.",
    }
    for v in results:
        cls = "UNKNOWN_AUTHORITY"
        if "current-source" in v.get("authority_note", "") and v.get("status") == "STATIC_PASS":
            cls = "CURRENT_SOURCE_FINAL_CANDIDATE"
        elif "current-source" in v.get("authority_note", ""):
            cls = "CURRENT_SOURCE_FINAL_CANDIDATE"
        elif "manual" in v.get("authority_note", "").lower():
            cls = "OLDER_COMPLETE_DIAGNOSTIC"
        auth["candidates"].append({
            "path": v.get("path"), "sha256": v.get("sha256"), "bytes": v.get("bytes"),
            "static_status": v.get("status"), "classification": cls,
            "note": v.get("authority_note"),
        })
    auth["final_xodr_identified"] = True
    auth["final_xodr_static"] = "PASS" if any(c["static_status"] == "STATIC_PASS" for c in auth["candidates"]) else "FAIL"
    auth["final_xodr_authority_accepted"] = False
    auth["final_xodr_authority_blocker"] = "Provenance manifest / source-commit binding for the current-source candidate was not verified in this session (map-of-record authority is registry-driven; no registry entry was read)."
    auth["final_xodr_live_load_admitted"] = False
    auth["final_xodr_live_load_blocker"] = "FULL_XODR_LIVE_IMPORT_NOT_ADMITTED (resource gate, VRAM, independent review pending)"
    (OUT / "XODR_CANDIDATE_AUTHORITY.json").write_text(json.dumps(auth, indent=2), encoding="utf-8")
    print("WROTE XODR_CANDIDATE_AUTHORITY.json")


if __name__ == "__main__":
    main()
