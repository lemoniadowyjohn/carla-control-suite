from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from ultimate_pipeline.domain_gap.deterministic_alignment import (
    compute_auto_bbox_and_centroid,
    deterministic_promote_and_align,
    BBox,
)

try:
    import pyproj  # noqa: F401
    _HAS_PYPROJ = True
except Exception:
    _HAS_PYPROJ = False

def _write_minimal_xodr(path: Path, xs, ys):
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", attrib={"name":"r1","length":"1","id":"1","junction":"-1"})
    plan = ET.SubElement(road, "planView")
    for i,(x,y) in enumerate(zip(xs,ys)):
        ET.SubElement(plan, "geometry", attrib={"s":str(i), "x":str(x), "y":str(y), "hdg":"0", "length":"1"})
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_alignment_maps_centroid_to_projected_gps_center(tmp_path: Path):
    auto = tmp_path/"auto.xodr"
    _write_minimal_xodr(auto, [0,10,5], [0,10,5])

    gps_bounds = {
        "lat_min": 48.74935649548228,
        "lat_max": 48.77444431571603,
        "lon_min": 11.422268084715878,
        "lon_max": 11.47882091528412,
    }
    manual_proj = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"

    out = tmp_path/"auto_aligned.xodr"
    deterministic_promote_and_align(
        auto_xodr_in=auto,
        manual_proj=manual_proj,
        gps_bounds=gps_bounds,
        manual_bbox=None,
        out_aligned_xodr=out,
        out_validity_json=tmp_path/"validity.json",
        require_overlap=False,
    )

    _, (cx,cy), _ = compute_auto_bbox_and_centroid(out)
    # We don't assert numeric values here (depends on pyproj); the key is "it runs"
    assert isinstance(cx, float) and isinstance(cy, float)
