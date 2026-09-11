from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.tools.compare_elevation_seam_repairs import (
    canonical_seam_metrics,
    structure_snapshot,
)


def _road(
    road_id: str,
    elevation_a: float,
    *,
    successor: tuple[str, str] | None = None,
    junction: str = "-1",
) -> str:
    link = ""
    if successor is not None:
        target, contact_point = successor
        link = (
            f'<link><successor elementType="road" elementId="{target}" '
            f'contactPoint="{contact_point}" /></link>'
        )
    return f'''<road id="{road_id}" length="10" junction="{junction}">
      {link}
      <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line /></geometry></planView>
      <elevationProfile><elevation s="0" a="{elevation_a}" b="1" c="0" d="0" /></elevationProfile>
      <lanes><laneSection s="0"><center><lane id="0" type="none" level="false" /></center></laneSection></lanes>
    </road>'''


def test_canonical_seam_metrics_honors_target_contact_point_end() -> None:
    # Road 1 ends at z=10.  Road 2 starts at z=0 but ends at z=10, so the
    # declared contactPoint=end is continuous.  A fixed "target=start"
    # legacy measurement would incorrectly report a 10 m discontinuity.
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _road("1", 0.0, successor=("2", "end"))
        + _road("2", 0.0)
        + "</OpenDRIVE>"
    )

    summary = canonical_seam_metrics(root, threshold_m=0.5)

    assert summary["all_road_to_road"]["count"] == 1
    assert summary["all_road_to_road"]["max_m"] == 0.0
    assert summary["all_road_to_road"]["over_threshold"] == 0


def test_structure_snapshot_ignores_only_elevation_a() -> None:
    before = ET.fromstring("<OpenDRIVE>" + _road("1", 1.0) + "</OpenDRIVE>")
    after = ET.fromstring("<OpenDRIVE>" + _road("1", 2.0) + "</OpenDRIVE>")

    assert structure_snapshot(before) == structure_snapshot(after)


def test_structure_snapshot_is_insensitive_to_serializer_whitespace() -> None:
    root = ET.fromstring("<OpenDRIVE>" + _road("1", 1.0) + "</OpenDRIVE>")
    indented = ET.fromstring(ET.tostring(root, encoding="unicode"))
    ET.indent(indented, space="  ")

    assert structure_snapshot(root) == structure_snapshot(indented)
