import xml.etree.ElementTree as ET
from pathlib import Path

P = Path("reports/post_audit_hardening/_gen_watch_log/ingolstadt_stub_fixed.xodr")


def main() -> int:
    root = ET.parse(P).getroot()
    print("== roads with geometry s+len > declared length ==")
    n = 0
    for road in root.findall("road"):
        decl = float(road.get("length"))
        for g in road.findall("planView/geometry"):
            s = float(g.get("s"))
            lg = float(g.get("length"))
            if s + lg > decl + 1e-3:
                n += 1
                print(f"  road {road.get('id')} len={decl:.3f} geo s={s:.3f}+{lg:.3f}={s+lg:.3f}")
                if n > 25:
                    break
    print("total exceeding:", n)
    print()
    print("== lane widths: section_s + sOffset > road length ==")
    n = 0
    for road in root.findall("road"):
        decl = float(road.get("length"))
        for ls in road.findall("lanes/laneSection"):
            ls_s = float(ls.get("s"))
            for w in ls.findall(".//width"):
                off = float(w.get("sOffset"))
                if ls_s + off > decl + 1e-3:
                    n += 1
                    print(f"  road {road.get('id')} len={decl:.3f} ls_s={ls_s:.3f} width_off={off:.3f} sum={ls_s+off:.3f}")
                    if n > 25:
                        break
    print("total exceeding:", n)
    print()
    print("== lanes with successor/predecessor links (junction) on stub roads ==")
    for road in root.findall("road"):
        if float(road.get("length")) <= 0.5:
            rid = road.get("id")
            lnk = road.find("link")
            has_lanes = road.find("lanes") is not None
            n_geos = len(road.findall("planView/geometry"))
            print(f"  road {rid} junction={road.get('junction')} geos={n_geos} lanes={has_lanes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())