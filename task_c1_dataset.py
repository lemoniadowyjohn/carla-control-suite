#!/usr/bin/env python3
"""
Task C1 — GAP-026 Failure Cluster Mining
Turn raw GAP-026 lane-link failures into a structured diagnostic dataset.
"""
import json, math, csv, collections, xml.etree.ElementTree as ET
from pathlib import Path
from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder
import gap026_oracle as oracle


def main():
    # Verify pin through registry (authoritative, not hardcoded)
    pinned = verify_pinned_map("auto_map_of_record")
    print(f"Pin verified: {pinned['path']} sha256={pinned['sha256']} bytes={pinned['bytes']}")

    root = ET.parse(pinned["resolved_path"]).getroot()
    roads = {str(r.get("id")): r for r in root.findall("road") if r.get("id")}

    # Run independent kernel oracle
    res_k = oracle.independent_sanitize(root, use_kernel=True)
    print(f"Kernel oracle: checked={res_k['checked']} passed={res_k['passed']} failed={res_k['failed']}")

    # =====================================================================
    # Collect per-laneLink metadata from oracle details
    # Each entry: (dist, ang, j, c, frm, to)
    # =====================================================================
    lane_links_meta = []

    for d, ang, j, c, frm, to in res_k["details"]:
        if not math.isfinite(d):
            continue

        # Find junction in root
        junc_id = str(j)
        conn_id = str(c)
        junc_found = False

        for junc in root.findall("junction"):
            if junc.get("id") != j:
                continue
            for conn in junc.findall("connection"):
                if conn.get("id") != c:
                    continue

                incoming_road_id = conn.get("incomingRoad")
                connecting_road_id = conn.get("connectingRoad")
                cp = conn.get("contactPoint", "start")
                at_start = cp != "end"

                incoming_road = roads.get(incoming_road_id)
                connecting_road = roads.get(connecting_road_id)

                if incoming_road is None or connecting_road is None:
                    continue

                # Get endpoint poses via kernel
                from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint as k_endpoint

                inc_geoms = sorted(
                    incoming_road.findall("./planView/geometry"),
                    key=lambda g: float(g.get("s", 0))
                )
                con_geoms = sorted(
                    connecting_road.findall("./planView/geometry"),
                    key=lambda g: float(g.get("s", 0))
                )

                if not inc_geoms or not con_geoms:
                    continue

                inc_geom = inc_geoms[-1]  # end
                con_geom = con_geoms[0] if at_start else con_geoms[-1]

                try:
                    inc_pose = k_endpoint(inc_geom)
                    con_pose = k_endpoint(con_geom)
                except Exception:
                    continue

                inc_x, inc_y, inc_hdg = float(inc_pose.x), float(inc_pose.y), float(inc_pose.heading)
                con_x, con_y, con_hdg = float(con_pose.x), float(con_pose.y), float(con_pose.heading)

                # Geometry primitives
                inc_prim = next(iter(inc_geom), None)
                con_prim = next(iter(con_geom), None)
                if inc_prim is not None:
                    inc_prim_tag = inc_prim.tag.rsplit("}", 1)[-1]
                else:
                    inc_prim_tag = "unknown"
                if con_prim is not None:
                    con_prim_tag = con_prim.tag.rsplit("}", 1)[-1]
                else:
                    con_prim_tag = "unknown"

                lane_links_meta.append({
                    "junction_id": junc_id,
                    "connection_id": conn_id,
                    "from_lane": str(frm),
                    "to_lane": str(to),
                    "contactPoint": cp,
                    "endpoint_inc_x": inc_x,
                    "endpoint_inc_y": inc_y,
                    "endpoint_inc_hdg": inc_hdg,
                    "endpoint_con_x": con_x,
                    "endpoint_con_y": con_y,
                    "endpoint_con_hdg": con_hdg,
                    "distance_m": d,
                    "angular_deg": math.degrees(ang) if math.isfinite(ang) else float("nan"),
                    "inc_geometry_primitive": inc_prim_tag,
                    "con_geometry_primitive": con_prim_tag,
                })

                junc_found = True
                break
            if junc_found:
                break

    print(f"Collected metadata for {len(lane_links_meta)} laneLinks")

    # =====================================================================
    # Bucket by distance (task-specified bins)
    # =====================================================================
    buckets = {
        "<=0.25": [],
        "0.25-0.5": [],
        "0.5-1": [],
        "1-3": [],
        "3-5": [],
        "5-10": [],
        ">10": [],
    }
    angular_buckets = {
        "0-12": [],
        "12-30": [],
        "30-60": [],
        "60-90": [],
        "90-120": [],
        ">120": [],
    }
    heading_only = []

    for meta in lane_links_meta:
        d = meta["distance_m"]
        a = meta["angular_deg"]

        if not math.isfinite(d):
            continue

        # Distance bucket
        if d <= 0.25:
            buckets["<=0.25"].append(meta)
        elif d <= 0.5:
            buckets["0.25-0.5"].append(meta)
        elif d <= 1.0:
            buckets["0.5-1"].append(meta)
        elif d <= 3.0:
            buckets["1-3"].append(meta)
        elif d <= 5.0:
            buckets["3-5"].append(meta)
        elif d <= 10.0:
            buckets["5-10"].append(meta)
        else:
            buckets[">10"].append(meta)

        # Angular stratification
        is_dist_fail = d > 0.25
        is_ang_fail = a > 12.0

        if is_dist_fail or is_ang_fail:
            if is_ang_fail and not is_dist_fail:
                heading_only.append(meta)
            if is_ang_fail:
                deg = a
                if deg <= 12:
                    angular_buckets["0-12"].append(meta)
                elif deg <= 30:
                    angular_buckets["12-30"].append(meta)
                elif deg <= 60:
                    angular_buckets["30-60"].append(meta)
                elif deg <= 90:
                    angular_buckets["60-90"].append(meta)
                elif deg <= 120:
                    angular_buckets["90-120"].append(meta)
                else:
                    angular_buckets[">120"].append(meta)

    # =====================================================================
    # Analysis
    # =====================================================================
    junction_fail_counts = collections.Counter()
    for bname, items in buckets.items():
        for m in items:
            junction_fail_counts[m["junction_id"]] += 1
    top_junctions = junction_fail_counts.most_common(20)

    distance_error_counts = collections.Counter()
    for bname, items in buckets.items():
        for m in items:
            if math.isfinite(m["distance_m"]):
                distance_error_counts[round(m["distance_m"], 3)] += 1

    angular_error_counts = collections.Counter()
    for bname, items in angular_buckets.items():
        for m in items:
            if math.isfinite(m["angular_deg"]):
                angular_error_counts[round(m["angular_deg"], 1)] += 1

    cp_fail_counts = collections.defaultdict(collections.Counter)
    for bname, items in buckets.items():
        for m in items:
            cp_fail_counts[m["contactPoint"]][m["junction_id"]] += 1

    geom_fail_counts = collections.defaultdict(collections.Counter)
    for bname, items in buckets.items():
        for m in items:
            geom_fail_counts[m["inc_geometry_primitive"]][m["junction_id"]] += 1

    left_lane_fail = 0
    right_lane_fail = 0
    for bname, items in buckets.items():
        for m in items:
            try:
                from_id = int(m["from_lane"])
                if from_id > 0:
                    left_lane_fail += 1
                else:
                    right_lane_fail += 1
            except Exception:
                pass

    extreme_outliers = buckets[">10"]

    # =====================================================================
    # Output JSON dataset
    # =====================================================================
    output_data = {
        "pinned_map": {
            "path": pinned["path"],
            "sha256": pinned["sha256"],
            "registry_sha256": pinned["registry_sha256"],
            "frame": pinned["frame"],
        },
        "summary": {
            "checked": res_k["checked"],
            "passed": res_k["passed"],
            "failed": res_k["failed"],
            "failure_rate_percent": round(res_k["failed"] / res_k["checked"] * 100, 2),
        },
        "distance_buckets": {
            bname: {
                "count": len(items),
                "percentage_of_checked": round(len(items) / res_k["checked"] * 100, 2),
                "percentage_of_failed": round(len(items) / res_k["failed"] * 100, 2) if res_k["failed"] else 0,
            }
            for bname, items in buckets.items()
        },
        "angular_buckets_failures": {
            bname: {
                "count": len(items),
                "percentage_of_failures": round(len(items) / res_k["failed"] * 100, 2) if res_k["failed"] else 0,
            }
            for bname, items in angular_buckets.items()
        },
        "heading_only": {
            "count": len(heading_only),
            "percentage_of_failures": round(len(heading_only) / res_k["failed"] * 100, 2) if res_k["failed"] else 0,
        },
        "analysis": {
            "top_junctions": [
                {"junction_id": jid, "fail_count": cnt}
                for jid, cnt in top_junctions
            ],
            "repeated_distance_errors": [
                {"distance_m": d, "count": c}
                for d, c in sorted(distance_error_counts.items(), key=lambda x: -x[1])[:20]
            ],
            "repeated_angular_errors": [
                {"angular_deg": d, "count": c}
                for d, c in sorted(angular_error_counts.items(), key=lambda x: -x[1])[:20]
            ],
            "contactpoint_distribution": {
                k: {"count": sum(v.values()), "junctions": len(v)}
                for k, v in cp_fail_counts.items()
            },
            "geometry_primitive_distribution": {
                k: {"count": sum(v.values()), "junctions": len(v)}
                for k, v in geom_fail_counts.items()
            },
            "left_right_lane_distribution": {
                "left_lane_fail": left_lane_fail,
                "right_lane_fail": right_lane_fail,
            },
            "extreme_outliers": {
                "count": len(extreme_outliers),
                "details": [
                    {
                        "junction_id": m["junction_id"],
                        "connection_id": m["connection_id"],
                        "from_lane": m["from_lane"],
                        "to_lane": m["to_lane"],
                        "distance_m": m["distance_m"],
                        "angular_deg": m["angular_deg"],
                    }
                    for m in extreme_outliers[:20]
                ]
            }
        }
    }

    with open("GAP026_DIAGNOSTIC_DATASET.json", "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)
    print("Written GAP026_DIAGNOSTIC_DATASET.json")

    # =====================================================================
    # Output CSV
    # =====================================================================
    with open("GAP026_DIAGNOSTIC_CSV.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "bucket", "junction_id", "connection_id", "from_lane", "to_lane",
            "contactPoint", "distance_m", "angular_deg",
            "endpoint_inc_x", "endpoint_inc_y", "endpoint_inc_hdg",
            "endpoint_con_x", "endpoint_con_y", "endpoint_con_hdg",
            "inc_geometry_primitive", "con_geometry_primitive"
        ])
        for bname, items in buckets.items():
            for m in items:
                writer.writerow([
                    bname, m["junction_id"], m["connection_id"], m["from_lane"], m["to_lane"],
                    m["contactPoint"],
                    f"{m['distance_m']:.6f}" if math.isfinite(m["distance_m"]) else "",
                    f"{m['angular_deg']:.2f}" if math.isfinite(m["angular_deg"]) else "",
                    f"{m['endpoint_inc_x']:.6f}", f"{m['endpoint_inc_y']:.6f}", f"{m['endpoint_inc_hdg']:.6f}",
                    f"{m['endpoint_con_x']:.6f}", f"{m['endpoint_con_y']:.6f}", f"{m['endpoint_con_hdg']:.6f}",
                    m["inc_geometry_primitive"], m["con_geometry_primitive"]
                ])
    print("Written GAP026_DIAGNOSTIC_CSV.csv")

    # =====================================================================
    # Summary report
    # =====================================================================
    report_lines = []
    report_lines.append("=" * 60)
    report_lines.append("GAP-026 FAILURE CLUSTER MINING — DIAGNOSTIC REPORT")
    report_lines.append("=" * 60)
    report_lines.append("")
    report_lines.append(f"Map: {pinned['path']}")
    report_lines.append(f"SHA256: {pinned['sha256']}")
    report_lines.append(f"Checked: {res_k['checked']}, Failed: {res_k['failed']} ({res_k['failed']/res_k['checked']*100:.2f}%)")
    report_lines.append("")

    report_lines.append("DISTANCE BUCKETS:")
    for bname in ["<=0.25", "0.25-0.5", "0.5-1", "1-3", "3-5", "5-10", ">10"]:
        items = buckets[bname]
        report_lines.append(f"  {bname}: {len(items)} links ({len(items)/res_k['checked']*100:.2f}% of checked, {len(items)/res_k['failed']*100:.1f}% of failed)")
    report_lines.append("")

    report_lines.append("TOP JUNCTIONS BY FAILURE COUNT:")
    for jid, cnt in top_junctions[:10]:
        report_lines.append(f"  Junction {jid}: {cnt} failures")
    report_lines.append("")

    report_lines.append("REPEATED DISTANCE ERROR MAGNITUDES (top 15):")
    for d, c in sorted(distance_error_counts.items(), key=lambda x: -x[1])[:15]:
        report_lines.append(f"  {d:.3f} m: {c} occurrences")
    report_lines.append("")

    report_lines.append("REPEATED ANGULAR ERROR MAGNITUDES (top 15):")
    for d, c in sorted(angular_error_counts.items(), key=lambda x: -x[1])[:15]:
        report_lines.append(f"  {d:.1f}°: {c} occurrences")
    report_lines.append("")

    report_lines.append("CONTACTPOINT DISTRIBUTION AMONG FAILURES:")
    for cp, jcnts in cp_fail_counts.items():
        report_lines.append(f"  contactPoint={cp}: {sum(jcnts.values())} failures across {len(jcnts)} junctions")
    report_lines.append("")

    report_lines.append("GEOMETRY PRIMITIVE DISTRIBUTION (incoming):")
    for prim, jcnts in geom_fail_counts.items():
        report_lines.append(f"  {prim}: {sum(jcnts.values())} failures across {len(jcnts)} junctions")
    report_lines.append("")

    report_lines.append("LEFT/RIGHT LANE DISTRIBUTION:")
    report_lines.append(f"  Left-lane failures: {left_lane_fail}")
    report_lines.append(f"  Right-lane failures: {right_lane_fail}")
    report_lines.append("")

    report_lines.append("EXTREME OUTLIERS (>10 m):")
    for m in extreme_outliers:
        report_lines.append(
            f"  Junction {m['junction_id']} / Conn {m['connection_id']} "
            f"from={m['from_lane']} to={m['to_lane']}: {m['distance_m']:.3f} m, "
            f"{m['angular_deg']:.1f}°"
        )
    report_lines.append("")

    with open("GAP026_DIAGNOSTIC_REPORT.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print("Written GAP026_DIAGNOSTIC_REPORT.txt")

    print("\nDone! All files generated.")


if __name__ == "__main__":
    main()