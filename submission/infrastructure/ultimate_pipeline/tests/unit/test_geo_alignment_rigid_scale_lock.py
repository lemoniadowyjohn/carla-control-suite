from __future__ import annotations

import math
from pathlib import Path

from ultimate_pipeline.domain_gap.geo_alignment import GeoAligner


def _write_xodr(path: Path, x1: float, y1: float, x2: float, y2: float) -> None:
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="test" version="1.00" date="2026-04-03">
    <geoReference>+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs</geoReference>
  </header>
  <road name="TestRoad" length="100.0" id="1" junction="-1">
    <planView>
      <geometry s="0.0" x="{x1}" y="{y1}" hdg="0.0" length="50.0"><line/></geometry>
      <geometry s="50.0" x="{x2}" y="{y2}" hdg="0.0" length="50.0"><line/></geometry>
    </planView>
    <lanes>
      <laneSection s="0.0">
        <center><lane id="0" type="none" level="false"/></center>
        <right><lane id="-1" type="driving" level="false"><width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/></lane></right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def test_geo_aligner_locks_scale_to_one_for_rigid_fit(tmp_path: Path) -> None:
    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    _write_xodr(manual, 678000.0, 5403000.0, 678050.0, 5403000.0)
    _write_xodr(auto, 678100.0, 5403100.0, 678150.0, 5403100.0)

    result = GeoAligner.estimate_from_xodr(str(manual), str(auto), strict=True)

    assert result["transform"]["scale"] == 1.0
    assert result["diagnostics"]["scale_locked"] == 1.0
    assert result["diagnostics"]["rigid_only"] is True
    assert "fit_metric_note" in result["diagnostics"]


def test_geo_aligner_recovers_small_known_rotation(tmp_path: Path) -> None:
    manual = tmp_path / "manual_rot.xodr"
    auto = tmp_path / "auto_rot.xodr"
    _write_xodr(manual, 100.0, 100.0, 150.0, 100.0)

    theta = math.radians(1.0)
    c = math.cos(theta)
    sn = math.sin(theta)

    def _rot(x: float, y: float) -> tuple[float, float]:
        xr = c * x - sn * y + 10.0
        yr = sn * x + c * y + 20.0
        return xr, yr

    x1, y1 = _rot(100.0, 100.0)
    x2, y2 = _rot(150.0, 100.0)
    _write_xodr(auto, x1, y1, x2, y2)

    result = GeoAligner.estimate_from_xodr(str(manual), str(auto), strict=True)

    angle_deg = math.degrees(math.atan2(result["transform"]["sin"], result["transform"]["cos"]))
    assert result["transform"]["scale"] == 1.0
    assert abs(angle_deg + 1.0) <= 0.2
    assert result["diagnostics"]["init_method"] == "mean_centroid_translation"
    assert "fit_metric_note" in result["diagnostics"]
