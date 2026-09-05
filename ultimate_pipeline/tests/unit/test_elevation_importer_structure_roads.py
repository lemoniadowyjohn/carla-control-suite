# Round-6 fix: ElevationImporter.apply_dem never consulted structure_classifier.py's
# bridge/tunnel/underpass classification, so grade-separated structures got flattened
# to a single ground-DEM sample (or the *global* linear_grade slope) like any other
# road. structure_road_ids lets specific roads be forced into the existing
# start/end-interpolated "linear_grade" behavior regardless of the global flag,
# reusing the elevation math apply_dem already has -- no new elevation model.
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.elevation_importer import ElevationImporter


def _xodr_with_roads(n: int) -> ET.Element:
    root = ET.Element("OpenDRIVE", {"version": "1.4"})
    for i in range(n):
        road = ET.SubElement(
            root,
            "road",
            {"id": str(i), "length": "10.0", "junction": "-1"},
        )
        pv = ET.SubElement(road, "planView")
        g = ET.SubElement(
            pv,
            "geometry",
            {
                "s": "0.0",
                "x": f"{float(i) * 20.0:.3f}",
                "y": "0.0",
                "hdg": "0.0",
                "length": "10.0",
            },
        )
        ET.SubElement(g, "line")
    return root


def _ramp_sampler(x, y):
    # z increases linearly with x -- lets us observe a genuine nonzero slope
    # for roads that actually get endpoint interpolation.
    return 100.0 + float(x) * 0.05, True


def _b_coeff(root: ET.Element, road_id: str) -> float:
    road = root.find(f"./road[@id='{road_id}']")
    elev = road.find("elevationProfile/elevation")
    assert elev is not None, f"road {road_id} has no <elevation> element"
    return float(elev.get("b"))


class TestStructureRoadIdsOverride:
    def test_road_not_in_structure_ids_stays_flat_when_global_linear_grade_false(self):
        root = _xodr_with_roads(2)
        ElevationImporter.apply_dem(
            root, _ramp_sampler, collect_qc=True, linear_grade=False,
            structure_road_ids={"0"},
        )
        assert _b_coeff(root, "1") == 0.0

    def test_road_in_structure_ids_gets_linear_grade_even_when_global_flag_false(self):
        root = _xodr_with_roads(2)
        collected = ElevationImporter.apply_dem(
            root, _ramp_sampler, collect_qc=True, linear_grade=False,
            structure_road_ids={"0"},
        )
        b0 = _b_coeff(root, "0")
        assert b0 != 0.0
        expected = (100.0 + 10.0 * 0.05 - (100.0 + 0.0 * 0.05)) / 10.0
        assert abs(b0 - expected) < 1e-6
        assert "0" in collected.get("linear_grade_road_ids", [])
        assert "1" not in collected.get("linear_grade_road_ids", [])

    def test_structure_road_ids_omitted_is_backward_compatible(self):
        root_baseline = _xodr_with_roads(2)
        ElevationImporter.apply_dem(
            root_baseline, _ramp_sampler, collect_qc=True, linear_grade=False,
        )
        root_new = _xodr_with_roads(2)
        ElevationImporter.apply_dem(
            root_new, _ramp_sampler, collect_qc=True, linear_grade=False,
        )
        assert _b_coeff(root_baseline, "0") == _b_coeff(root_new, "0") == 0.0
        assert _b_coeff(root_baseline, "1") == _b_coeff(root_new, "1") == 0.0

    def test_structure_road_ids_empty_set_behaves_like_none(self):
        root = _xodr_with_roads(2)
        ElevationImporter.apply_dem(
            root, _ramp_sampler, collect_qc=True, linear_grade=False,
            structure_road_ids=set(),
        )
        assert _b_coeff(root, "0") == 0.0
        assert _b_coeff(root, "1") == 0.0
