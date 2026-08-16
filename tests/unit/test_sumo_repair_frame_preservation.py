"""F1 CRS contract: SUMO topology repair must preserve the global geometry frame.

Regression test for the stage-02 defect where `netconvert` normalizes node
positions to a local origin (offset ~832671, ~5458671), silently moving geometry
off the Osm2Odr-native tmerc(0,0) frame that the DEM sampling F1 contract requires.
When that happens the DEM sampler fails closed (no_frame_matches_osm_source) and
no elevation can be imported.

The repair round-trip MUST keep coordinates in the input (global) frame.
"""
import os
import re
import subprocess

import pytest

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.topology import sumo_repair
from ultimate_pipeline.topology.sumo_repair import SUMORepair

# One straight 100 m driving road placed at Osm2Odr-native GLOBAL tmerc(0,0)
# coordinates for Ingolstadt (x ~ 840000, y ~ 5464000).
_GLOBAL_X = 840000.0
_GLOBAL_Y = 5464000.0
MINIMAL_XODR = f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="frame_test" version="1.00"
          north="0" south="0" east="0" west="0">
    <geoReference><![CDATA[+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs]]></geoReference>
  </header>
  <road name="R1" length="100.0" id="1" junction="-1">
    <planView>
      <geometry s="0.0" x="{_GLOBAL_X}" y="{_GLOBAL_Y}" hdg="0.0" length="100.0">
        <line/>
      </geometry>
    </planView>
    <lanes>
      <laneSection s="0.0">
        <left>
          <lane id="1" type="driving" level="false">
            <width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/>
          </lane>
        </left>
        <center>
          <lane id="0" type="none" level="false"/>
        </center>
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
"""


def _first_geometry_x(xodr_text: str):
    m = re.search(r'<geometry[^>]*\bx="([-0-9.eE]+)"', xodr_text)
    return float(m.group(1)) if m else None


_sumo = getattr(SETTINGS, "SUMO_NETCONVERT", "")
_sumo_available = bool(_sumo and os.path.exists(_sumo))


def test_sumo_repair_preserve_frame_flag_adds_netconvert_argument(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "ENABLE_SUMO_REPAIR", True, raising=False)
    monkeypatch.setattr(SETTINGS, "SUMO_REPAIR_PRESERVE_FRAME", True, raising=False)
    monkeypatch.setattr(SETTINGS, "SUMO_REPAIR_GEOMETRY_REMOVE", False, raising=False)
    monkeypatch.setattr(SETTINGS, "SUMO_REPAIR_IGNORE_ERRORS", False, raising=False)

    fake_netconvert = tmp_path / "netconvert.exe"
    fake_netconvert.write_text("", encoding="utf-8")
    monkeypatch.setattr(SETTINGS, "SUMO_NETCONVERT", str(fake_netconvert), raising=False)

    inp = tmp_path / "in.xodr"
    inp.write_text(MINIMAL_XODR, encoding="utf-8")
    out = tmp_path / "out.xodr"
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        output_path = cmd[cmd.index("--opendrive-output") + 1]
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(inp.read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(sumo_repair.subprocess, "run", fake_run)

    SUMORepair.repair(str(inp), str(out))

    assert "--offset.disable-normalization" in captured["cmd"]
    idx = captured["cmd"].index("--offset.disable-normalization")
    assert captured["cmd"][idx + 1] == "true"


@pytest.mark.skipif(not _sumo_available, reason="SUMO netconvert not available")
def test_sumo_repair_preserves_global_coordinate_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "ENABLE_SUMO_REPAIR", True, raising=False)
    inp = tmp_path / "in.xodr"
    inp.write_text(MINIMAL_XODR, encoding="utf-8")
    out = tmp_path / "out.xodr"

    SUMORepair.repair(str(inp), str(out))

    txt = out.read_text(encoding="utf-8", errors="ignore")
    x = _first_geometry_x(txt)
    assert x is not None, "SUMO repair produced no planView geometry to check"
    # F1 contract: geometry stays in the global tmerc(0,0) frame (x ~ 840000),
    # NOT normalized to a local origin (x ~ 0). Generous threshold: any value in
    # the global band proves normalization was disabled.
    assert x > 100_000.0, (
        f"SUMO repair normalized geometry off the global frame (x={x}); "
        "expected the input global-frame magnitude (~840000) to be preserved."
    )
