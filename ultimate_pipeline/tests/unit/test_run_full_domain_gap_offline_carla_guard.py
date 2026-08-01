from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from ultimate_pipeline.run_full_domain_gap import _cli_main


MINIMAL_XODR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="test" north="5405000" south="5402000" east="682000" west="678000">
    <geoReference><![CDATA[+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs]]></geoReference>
  </header>
  <road name="TestRoad" length="100.0" id="1" junction="-1">
    <planView>
      <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="100.0"><line/></geometry>
    </planView>
    <lanes>
      <laneSection s="0.0">
        <center><lane id="0" type="none" level="false"/></center>
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0.0" a="3.5" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
"""


def test_offline_mode_marks_carla_drivability_as_not_validated(
    tmp_path: Path, monkeypatch
) -> None:
    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    manual.write_text(MINIMAL_XODR, encoding="utf-8")
    auto.write_text(MINIMAL_XODR, encoding="utf-8")
    out_dir = tmp_path / "headless_out"

    monkeypatch.setenv("UP_DISABLE_CARLA", "1")
    monkeypatch.setenv("UP_AUTO_FINAL_XODR", str(auto))
    monkeypatch.setenv("UP_MANUAL_MAP_XODR", str(manual))
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_full_domain_gap.py", "--output_dir", str(out_dir)],
    )

    exit_code = _cli_main()

    assert exit_code == 0

    carla_status = json.loads((out_dir / "carla_status.json").read_text(encoding="utf-8"))
    full_report = json.loads((out_dir / "domain_gap" / "full_report.json").read_text(encoding="utf-8"))
    with (out_dir / "domain_gap" / "summary.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert carla_status["tile_qa_status"] == "SKIPPED_CARLA_NOT_INVOKED"
    assert full_report["carla_drivability_validated"] is False
    assert (
        full_report["carla_drivability_note"]
        == "CARLA not invoked; drivability is inferred from offline structural gates only"
    )
    assert any(
        row["metric"] == "carla_drivability_validated" and row["value"] == "False"
        for row in rows
    )
