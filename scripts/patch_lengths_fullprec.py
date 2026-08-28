import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/post_audit_hardening/_gen_watch_log/ingolstadt_len_fixed_v2.xodr")
MARGIN = 1e-3


def parse_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    root = ET.parse(SRC).getroot()
    changed = 0
    for r in root.findall("road"):
        decl = parse_float(r.get("length"))
        geos = r.findall("planView/geometry")
        if not geos:
            continue
        geom_end = max(parse_float(g.get("s")) + parse_float(g.get("length")) for g in geos)
        target = max(decl, geom_end) + MARGIN
        if abs(target - decl) > 0.0:
            # repr() preserves full round-trip precision so geometry_end <= target strictly
            r.set("length", repr(target))
            changed += 1
    ET.ElementTree(root).write(OUT, encoding="utf-8", xml_declaration=True)
    print(f"roads length-adjusted: {changed}")
    print(f"output: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())