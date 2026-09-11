from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.tools.investigate_g6_lane_coverage import (
    acceptance_component_details,
)


def test_acceptance_component_details_exposes_singleton_driving_lane() -> None:
    root = ET.fromstring(
        """
        <OpenDRIVE>
          <road id="1" length="10"><lanes><laneSection s="0"><right>
            <lane id="-1" type="driving" />
          </right></laneSection></lanes></road>
        </OpenDRIVE>
        """
    )

    report = acceptance_component_details(root)

    assert report["isolated_lane_component_count"] == 1
    assert report["isolated_lane_nodes"] == ["1:0:-1"]
