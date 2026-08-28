import sys
import xml.etree.ElementTree as ET
from pathlib import Path

GOVERNED = Path("campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr")
MAX_VIOLATIONS = 40

def parse_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def main() -> int:
    root = ET.parse(GOVERNED).getroot()
    roads = root.findall("road")
    n = len(roads)
    print(f"total roads: {n}")

    violations = []
    for road in roads:
        rid = road.get("id")
        decl_len = parse_float(road.get("length"))
        # max s from geometry + its length
        geos = road.findall("planView/geometry")
        max_geo_s = 0.0
        for g in geos:
            s = parse_float(g.get("s"))
            lg = parse_float(g.get("length"))
            max_geo_s = max(max_geo_s, s + lg)
        # max lane section s
        max_ls_s = 0.0
        for ls in road.findall("lanes/laneSection"):
            max_ls_s = max(max_ls_s, parse_float(ls.get("s")))
        # signals / objects s
        max_sig_s = 0.0
        for sig in road.findall("signals/signal"):
            max_sig_s = max(max_sig_s, parse_float(sig.get("s")))
        for obj in road.findall("objects/object"):
            max_sig_s = max(max_sig_s, parse_float(obj.get("s")))
        # widths: offset within lane section: width sOffset
        max_width_off = 0.0
        for w in road.findall(".//width"):
            max_width_off = max(max_width_off, parse_float(w.get("sOffset")))
        max_any = max(max_geo_s, max_ls_s, max_sig_s, max_width_off)

        issues = []
        tol = 1e-3
        if max_geo_s > decl_len + tol:
            issues.append(f"geo max_s+len={max_geo_s:.3f} > length={decl_len:.3f}")
        if max_ls_s > decl_len + tol:
            issues.append(f"laneSection s={max_ls_s:.3f} > length={decl_len:.3f}")
        if max_sig_s > decl_len + tol:
            issues.append(f"signal/object s={max_sig_s:.3f} > length={decl_len:.3f}")
        if max_width_off > decl_len + tol:
            issues.append(f"width sOffset={max_width_off:.3f} > length={decl_len:.3f}")
        # geometry coverage: sum of geometry lengths vs declared length
        geo_sum = sum(parse_float(g.get("length")) for g in geos)
        if geos and abs(geo_sum - decl_len) > 0.01 * max(decl_len, 1.0):
            issues.append(f"geo_sum={geo_sum:.3f} != length={decl_len:.3f}")

        if issues:
            violations.append((rid, decl_len, issues))

    print(f"roads with potential s/length violations: {len(violations)}")
    for rid, decl_len, issues in violations[:MAX_VIOLATIONS]:
        print(f"  road id={rid} length={decl_len:.3f}")
        for i in issues:
            print(f"      - {i}")
    if len(violations) > MAX_VIOLATIONS:
        print(f"  ... and {len(violations) - MAX_VIOLATIONS} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())