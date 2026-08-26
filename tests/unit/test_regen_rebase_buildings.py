"""C29 bug 2: scripts.regen_map_of_record._rebase_to_local only shifted
planView/geometry x/y into the local frame -- it never touched
<object><outline><cornerGlobal> points. Combined with bug 1 (fixed separately in
osm_polygon_loader.py), buildings drifted 7,665m from the road network on the real
pinned map. This extends the rebase to shift cornerGlobal by the SAME (dx, dy) as roads.
"""
from __future__ import annotations

from pathlib import Path

import scripts.regen_map_of_record as regen

# Global-frame road geometry (>10km from origin, forces the "shifted" branch) plus a
# building object with a cornerGlobal outline at a DIFFERENT global-frame position.
_XODR = """<?xml version="1.0"?>
<OpenDRIVE>
  <header/>
  <road name="" length="10.0" id="1" junction="-1">
    <planView>
      <geometry s="0" x="832671.676" y="5458671.104" hdg="0" length="10.0"><line/></geometry>
      <geometry s="10" x="832681.676" y="5458671.104" hdg="0" length="10.0"><line/></geometry>
    </planView>
    <objects>
      <object id="bld_1" name="B" type="building" s="0.0" t="0.0" zOffset="0.0"
              orientation="absolute" height="10.0" hdg="0.0" length="0.0" width="0.0">
        <outline id="0" fillType="concrete">
          <cornerGlobal x="832700.000" y="5458700.000" z="0.0"/>
          <cornerGlobal x="832710.000" y="5458700.000" z="0.0"/>
          <cornerGlobal x="832710.000" y="5458710.000" z="0.0"/>
        </outline>
      </object>
    </objects>
  </road>
</OpenDRIVE>
"""


def test_rebase_shifts_corner_global_by_same_dx_dy_as_roads(tmp_path):
    xodr_in = tmp_path / "in.xodr"
    xodr_in.write_text(_XODR, encoding="utf-8")
    xodr_out = tmp_path / "out.xodr"

    report = regen._rebase_to_local(xodr_in, xodr_out)
    assert report["shifted"] is True
    dx, dy = report["dx"], report["dy"]

    import xml.etree.ElementTree as ET

    out_root = ET.parse(xodr_out).getroot()
    corners = out_root.findall(".//object/outline/cornerGlobal")
    assert len(corners) == 3

    expected = [(832700.000 - dx, 5458700.000 - dy),
                (832710.000 - dx, 5458700.000 - dy),
                (832710.000 - dx, 5458710.000 - dy)]
    got = [(float(c.get("x")), float(c.get("y"))) for c in corners]
    for (ex, ey), (gx, gy) in zip(expected, got):
        assert abs(ex - gx) < 1e-3
        assert abs(ey - gy) < 1e-3


def test_rebase_corner_global_z_is_unchanged(tmp_path):
    xodr_in = tmp_path / "in.xodr"
    xodr_in.write_text(_XODR, encoding="utf-8")
    xodr_out = tmp_path / "out.xodr"
    regen._rebase_to_local(xodr_in, xodr_out)

    import xml.etree.ElementTree as ET

    out_root = ET.parse(xodr_out).getroot()
    for c in out_root.findall(".//object/outline/cornerGlobal"):
        assert c.get("z") == "0.0"


def test_rebase_with_no_buildings_still_works(tmp_path):
    # Backward-compat: a road-only XODR (no <object>) must rebase exactly as before.
    xodr_in = tmp_path / "in.xodr"
    xodr_in.write_text(
        '<?xml version="1.0"?><OpenDRIVE><header/>'
        '<road name="" length="10.0" id="1" junction="-1"><planView>'
        '<geometry s="0" x="832671.676" y="5458671.104" hdg="0" length="10.0"><line/></geometry>'
        "</planView></road></OpenDRIVE>",
        encoding="utf-8",
    )
    xodr_out = tmp_path / "out.xodr"
    report = regen._rebase_to_local(xodr_in, xodr_out)
    assert report["shifted"] is True
