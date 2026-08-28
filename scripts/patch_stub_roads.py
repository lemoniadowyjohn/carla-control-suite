import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path("campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr")
OUT = Path("reports/post_audit_hardening/_gen_watch_log/ingolstadt_stub_fixed.xodr")


def parse_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC, OUT)
    root = ET.parse(OUT).getroot()
    fixed = 0
    for road in root.findall("road"):
        decl = parse_float(road.get("length"))
        geos = road.findall("planView/geometry")
        if not geos:
            continue
        geo_sum = sum(parse_float(g.get("length")) for g in geos)
        if abs(geo_sum - decl) > 0.01 * max(decl, 1.0):
            delta = decl - geo_sum
            last = geos[-1]
            old = parse_float(last.get("length"))
            last.set("length", f"{old + delta:.8f}")
            fixed += 1
    tree = ET.ElementTree(root)
    tree.write(OUT, encoding="utf-8", xml_declaration=True)
    print(f"patched roads: {fixed}")
    print(f"output: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())