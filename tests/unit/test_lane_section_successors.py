from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.check_lane_section_successors import (
    repair_and_assert_lane_section_successors,
)


def _write_xodr(path: Path, lane0_type: str = "none", lane0_width: str = "3.500") -> None:
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="6"/>
  <road id="1" length="10" junction="10">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <lanes>
      <laneSection s="0">
        <center><lane id="0" type="none"/></center>
        <right>
          <lane id="-1" type="{lane0_type}">
            <link><successor id="-1"/></link>
            <width sOffset="0" a="{lane0_width}" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
      <laneSection s="0.05">
        <center><lane id="0" type="none"/></center>
        <right>
          <lane id="-1" type="driving">
            <link><successor id="-1"/></link>
            <width sOffset="0" a="3.500" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def test_repair_reclassifies_linked_none_lane_and_adds_mirror_predecessor(tmp_path: Path) -> None:
    src = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(src, lane0_type="none", lane0_width="3.500")

    report = repair_and_assert_lane_section_successors(str(src), str(out), strict=True)

    assert report["reclassified_none_or_restricted_lanes"] == 1
    assert report["failures"] == []
    root = ET.parse(out).getroot()
    sections = root.findall("./road/lanes/laneSection")
    first_lane = sections[0].find("./right/lane[@id='-1']")
    second_lane = sections[1].find("./right/lane[@id='-1']")
    assert first_lane is not None
    assert second_lane is not None
    assert first_lane.get("type") == "driving"
    pred = second_lane.find("./link/predecessor")
    assert pred is not None
    assert pred.get("id") == "-1"


def test_repair_reclassifies_linked_restricted_lane(tmp_path: Path) -> None:
    src = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(src, lane0_type="restricted", lane0_width="3.500")

    report = repair_and_assert_lane_section_successors(str(src), str(out), strict=True)

    assert report["reclassified_none_or_restricted_lanes"] == 1
    root = ET.parse(out).getroot()
    first_lane = root.find("./road/lanes/laneSection/right/lane[@id='-1']")
    assert first_lane is not None
    assert first_lane.get("type") == "driving"


def test_repair_does_not_reclassify_sidewalk_width_lane(tmp_path: Path) -> None:
    src = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(src, lane0_type="none", lane0_width="2.000")

    report = repair_and_assert_lane_section_successors(str(src), str(out), strict=True)

    assert report["reclassified_none_or_restricted_lanes"] == 0
    root = ET.parse(out).getroot()
    first_lane = root.find("./road/lanes/laneSection/right/lane[@id='-1']")
    assert first_lane is not None
    assert first_lane.get("type") == "none"
