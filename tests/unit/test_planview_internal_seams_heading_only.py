"""check_planview_internal_seams (ultimate_pipeline/quality/check_geometric_continuity.py)
computes hdg_delta_rad for every consecutive planView geometry pair, but only USES it to
classify an already-detected position seam -- `if dxy <= eps_xy: continue` skips the pair
entirely whenever position is continuous, so a real heading-only discontinuity (position
continuous, tangent direction jumps sharply -- a visible kink/bend in the road centerline)
was never reported at all.

Confirmed against the real pinned map (auto_map_of_record, 2026-08-27): 48 ordinary
(non-junction-connector) roads have exactly this pattern -- xy_gap ~= 0, hdg_gap from 5.1
to 180 degrees. `audit_xodr_visual_geometry.py`'s independent implementation catches these
(it checks heading unconditionally); this established, pipeline-live gate does not.

Fix is purely additive: a new `heading_only_discontinuities` list + `num_heading_only_
discontinuities` count, gated by a new `eps_hdg_only_deg` parameter (default 5.0 degrees,
matching the threshold that separates real cases (>=5.1 deg observed) from noise in this
investigation). Existing fields (`ok`, `seams`, `num_seams`, `max_seam_m`, `worst_road_id`)
are completely unchanged -- this function participates in a LIVE pipeline gate
(stage_06_links.py, stage_09_tiling.py) with auto-repair triggering and
UP_STRICT_QUALITY_GATES blocking semantics, so changing its existing pass/fail behavior
without explicit sign-off would be a materially riskier change than adding new, separate
diagnostic visibility.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.check_geometric_continuity import check_planview_internal_seams


def _write_xodr(path: Path, geoms: list) -> None:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="20.0", junction="-1")
    plan = ET.SubElement(road, "planView")
    for (x, y, hdg, length) in geoms:
        geom = ET.SubElement(
            plan, "geometry", s="0", x=str(x), y=str(y), hdg=str(hdg), length=str(length),
        )
        ET.SubElement(geom, "line")
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


def test_position_continuous_but_heading_discontinuous_is_now_reported(tmp_path: Path) -> None:
    # First line: 10m along hdg=0, ends at (10, 0). Second line STARTS exactly at (10, 0)
    # (position-continuous, xy_gap=0) but its own hdg is 90 degrees -- a sharp kink with no
    # visible position gap. Previously silently skipped entirely.
    xodr = tmp_path / "kink.xodr"
    _write_xodr(xodr, [
        (0.0, 0.0, 0.0, 10.0),
        (10.0, 0.0, math.pi / 2.0, 10.0),
    ])
    report = check_planview_internal_seams(str(xodr))
    assert report["num_heading_only_discontinuities"] == 1
    entry = report["heading_only_discontinuities"][0]
    assert entry["road_id"] == "1"
    assert entry["xy_gap_m"] < 1e-6
    assert abs(math.degrees(entry["hdg_delta_rad"]) - 90.0) < 1e-3


def test_existing_ok_and_seams_fields_are_unaffected_by_a_heading_only_case(tmp_path: Path) -> None:
    """The whole point of this being additive: a map whose ONLY issue is a heading-only kink
    must still report ok=True / num_seams=0 -- the live pipeline gate's existing pass/fail
    behavior is untouched by this fix."""
    xodr = tmp_path / "kink.xodr"
    _write_xodr(xodr, [
        (0.0, 0.0, 0.0, 10.0),
        (10.0, 0.0, math.pi / 2.0, 10.0),
    ])
    report = check_planview_internal_seams(str(xodr))
    assert report["ok"] is True
    assert report["num_seams"] == 0
    assert report["seams"] == []
    assert report["max_seam_m"] == 0.0


def test_small_heading_change_below_threshold_is_not_flagged(tmp_path: Path) -> None:
    # 2 degrees is well below the default 5-degree threshold -- a normal, expected small
    # heading transition (e.g. sub-segment serialization), not a real kink.
    xodr = tmp_path / "smooth.xodr"
    _write_xodr(xodr, [
        (0.0, 0.0, 0.0, 10.0),
        (10.0, 0.0, math.radians(2.0), 10.0),
    ])
    report = check_planview_internal_seams(str(xodr))
    assert report["num_heading_only_discontinuities"] == 0


def test_a_real_position_seam_is_not_double_counted_as_heading_only(tmp_path: Path) -> None:
    """A pair that already fails the xy_gap check must appear in `seams` (existing behavior)
    and must NOT also appear in heading_only_discontinuities -- the two lists are meant to
    be disjoint (heading_only is specifically for the case the xy check misses)."""
    xodr = tmp_path / "gap.xodr"
    _write_xodr(xodr, [
        (0.0, 0.0, 0.0, 10.0),
        (15.0, 0.0, math.pi / 2.0, 10.0),  # starts 5m away AND has a heading jump
    ])
    report = check_planview_internal_seams(str(xodr))
    assert report["num_seams"] == 1
    assert report["num_heading_only_discontinuities"] == 0


def test_custom_heading_threshold_is_respected(tmp_path: Path) -> None:
    xodr = tmp_path / "kink.xodr"
    _write_xodr(xodr, [
        (0.0, 0.0, 0.0, 10.0),
        (10.0, 0.0, math.radians(6.0), 10.0),
    ])
    default_report = check_planview_internal_seams(str(xodr))
    assert default_report["num_heading_only_discontinuities"] == 1  # 6 > default 5deg

    loose_report = check_planview_internal_seams(str(xodr), eps_hdg_only_deg=10.0)
    assert loose_report["num_heading_only_discontinuities"] == 0  # 6 < 10deg threshold


def test_real_pinned_map_matches_the_investigated_count() -> None:
    """Integration check against the real pinned map used to discover this bug: 48 ordinary
    (non-junction-connector) roads with a position-continuous heading kink, at the default
    5-degree threshold."""
    xodr_path = (
        Path(__file__).resolve().parents[2]
        / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate"
        / "ingolstadt_perception_map_of_record_20260819_160350_C29_BUILDING_PATCH.xodr"
    )
    if not xodr_path.is_file():
        return  # pinned artifact not present in this environment; skip rather than fail
    report = check_planview_internal_seams(str(xodr_path))
    affected_roads = {e["road_id"] for e in report["heading_only_discontinuities"]}
    assert len(affected_roads) == 48
    # Existing pass/fail behavior for this candidate is untouched.
    assert report["ok"] is True
    assert report["num_seams"] == 0
