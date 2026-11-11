#!/usr/bin/env python3
"""Phase 4: MANUAL_AUTO_ALIGNMENT_VERIFICATION.

Executes the project's own registration code on the real manual/auto pair and
records what actually happened.  No synthetic PASS.  No source file mutation.
"""
import json
import os
import sys
import time

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
sys.path.insert(0, REPO)

AUTO = r"E:\wt\repair-map-realism-p0-837a8504\cities\ingolstadt\ingolstadt_osm_auto.xodr"
MANUAL = os.path.join(REPO, "cities", "ingolstadt", "manual_grid0821.xodr")


def main():
    out = {
        "stage": "MANUAL_AUTO_ALIGNMENT_VERIFICATION",
        "executed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "local_head": "69c818be",
        "method": "ultimate_pipeline.domain_gap.local_registration.compute_local_registration",
        "auto_path": AUTO,
        "manual_path": MANUAL,
        "footprint": "bbox",
        "building_frame_shift": "auto",
        "results": [],
        "negative_controls": [],
        "verdict": None,
    }

    from ultimate_pipeline.domain_gap.local_registration import (
        compute_local_registration,
        manual_geometry_bbox,
        read_offset,
        read_georef_proj4,
    )
    import xml.etree.ElementTree as ET

    # --- per-file header facts (offsets / CRS) ---------------------------
    headers = {}
    for label, path in (("auto", AUTO), ("manual", MANUAL)):
        try:
            root = ET.parse(path).getroot()
            headers[label] = {
                "offset": read_offset(root),
                "proj4": read_georef_proj4(root)[:400],
            }
        except Exception as exc:
            headers[label] = {"error": f"{type(exc).__name__}: {exc}"}
    out["headers"] = headers

    # --- manual footprint (hull) ----------------------------------------
    try:
        root = ET.parse(MANUAL).getroot()
        bbox = manual_geometry_bbox(root)
        out["manual_geometry_bbox"] = list(bbox)
        out["manual_bbox_span_m"] = [round(bbox[2] - bbox[0], 2), round(bbox[3] - bbox[1], 2)]
    except Exception as exc:
        out["manual_geometry_bbox"] = f"ERROR {type(exc).__name__}: {exc}"

    # --- primary registration run ---------------------------------------
    t0 = time.time()
    try:
        res = compute_local_registration(AUTO, MANUAL, footprint="bbox", building_frame_shift="auto")
        out["results"].append({
            "footprint": "bbox",
            "status": "EXECUTED",
            "elapsed_s": round(time.time() - t0, 1),
            "type": str(type(res)),
        })
        # Serialise only JSON-safe, small attributes.
        for attr in ("cropped_auto_stats", "cropped_manual_stats", "auto_stats", "manual_stats"):
            val = getattr(res, attr, None)
            if isinstance(val, dict):
                out["results"][-1][attr] = {k: v for k, v in val.items() if isinstance(v, (int, float, str, bool, type(None)))}
        for attr in dir(res):
            if attr.startswith("_"):
                continue
            val = getattr(res, attr)
            if isinstance(val, (int, float, str, bool, type(None))):
                out["results"][-1][attr] = val
    except Exception as exc:
        out["results"].append({
            "footprint": "bbox",
            "status": "EXECUTION_EXCEPTION",
            "elapsed_s": round(time.time() - t0, 1),
            "error": f"{type(exc).__name__}: {exc}",
        })

    # --- negative control: swapped identity -----------------------------
    t0 = time.time()
    try:
        res2 = compute_local_registration(AUTO, AUTO, footprint="bbox", building_frame_shift="auto")
        out["negative_controls"].append({
            "control": "IDENTITY_SELF_PAIR (auto vs auto)",
            "status": "EXECUTED",
            "elapsed_s": round(time.time() - t0, 1),
            "expectation": "This is a control only; it is NOT evidence about manual/auto correspondence.",
        })
    except Exception as exc:
        out["negative_controls"].append({
            "control": "IDENTITY_SELF_PAIR (auto vs auto)",
            "status": "EXECUTION_EXCEPTION",
            "error": f"{type(exc).__name__}: {exc}",
        })

    primary = out["results"][0]
    if primary.get("status") != "EXECUTED":
        out["verdict"] = "MANUAL_AUTO_ALIGNMENT_BLOCKED (execution exception; no alignment claim)"
    else:
        out["verdict"] = "MANUAL_AUTO_ALIGNMENT_EXECUTED (see residuals for acceptance decision)"

    with open(os.path.join(REPO, "MANUAL_AUTO_ALIGNMENT_VERIFICATION.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print("WROTE MANUAL_AUTO_ALIGNMENT_VERIFICATION.json")
    print(json.dumps({"results": out["results"], "headers": out["headers"]}, indent=2)[:2500])


if __name__ == "__main__":
    main()
