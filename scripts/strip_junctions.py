import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/post_audit_hardening/_gen_watch_log/ingolstadt_nojunctions.xodr")


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    root = ET.parse(SRC).getroot()
    roads0 = len(root.findall("road"))
    juncs = root.findall("junction")
    for j in list(juncs):
        root.remove(j)
    # strip <link> blocks from each road so no dangling successor/predecessor wiring
    stripped_links = 0
    for r in root.findall("road"):
        lnk = r.find("link")
        if lnk is not None:
            r.remove(lnk)
            stripped_links += 1
    ET.ElementTree(root).write(OUT, encoding="utf-8", xml_declaration=True)
    import hashlib
    h = hashlib.sha256(OUT.read_text(encoding="utf-8").encode()).hexdigest()
    print(f"roads={roads0} junctions_removed={len(juncs)} links_stripped={stripped_links}")
    print(f"output: {OUT} sha256={h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())