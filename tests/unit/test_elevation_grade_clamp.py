# Elevation grade clamp (deep-quality-sweep finding): endpoint-based linear
# grade from DEM samples produced physically implausible ramps on short roads
# whose two ends were sampled at different vertical layers (overpass/
# underpass artifacts) — up to ~100-143% grade. The generator must clamp the
# b coefficient to |UP_ELEVATION_MAX_GRADE| (default 0.2) so the checker's
# UP_ELEVATION_MAX_GRADE gate can never fire on freshly generated maps.
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.elevation_importer import ElevationImporter


def _make_road(root: ET.Element, rid: str, x: float, length: float = 10.0) -> None:
    road = ET.SubElement(root, "road", {"id": rid, "length": f"{length:.3f}", "junction": "-1"})
    pv = ET.SubElement(road, "planView")
    ET.SubElement(
        pv,
        "geometry",
        {"s": "0.0", "x": f"{x:.3f}", "y": "0.0", "hdg": "0.0", "length": f"{length:.3f}"},
    ).append(ET.SubElement(ET.Element("dummy"), "line"))


def _sampler(start_z: float, end_x: float, end_z: float):
    def sample(px, py):
        # Neighborhood probes within ~2 m of either endpoint resolve to that
        # endpoint's height; anything else falls back to the start height.
        if abs(px - end_x) < 1.0 and abs(py) < 1.0:
            return end_z, True
        if abs(px) < 1.0 and abs(py) < 1.0:
            return start_z, True
        return start_z, True

    return sample


def test_default_max_grade_clamps_steep_road(monkeypatch) -> None:
    monkeypatch.delenv("UP_ELEVATION_MAX_GRADE", raising=False)
    root = ET.Element("OpenDRIVE")
    _make_road(root, "0", x=0.0, length=10.0)  # start z=100, end z=130 -> b=3.0
    qc = ElevationImporter.apply_dem(
        root, _sampler(100.0, 10.0, 130.0), collect_qc=True, linear_grade=True
    )
    assert qc is not None
    assert qc["max_grade"] == 0.2
    assert "0" in qc["grade_clamped_road_ids"]
    elev = root.find(".//road[@id='0']/elevationProfile/elevation")
    assert elev is not None
    b = float(elev.get("b"))
    assert b == 0.2


def test_explicit_max_grade_disables_clamp(monkeypatch) -> None:
    monkeypatch.setenv("UP_ELEVATION_MAX_GRADE", "10")
    root = ET.Element("OpenDRIVE")
    _make_road(root, "0", x=0.0, length=10.0)
    qc = ElevationImporter.apply_dem(
        root, _sampler(100.0, 10.0, 130.0), collect_qc=True, linear_grade=True
    )
    assert qc is not None
    assert qc["max_grade"] == 10.0
    assert "0" not in qc["grade_clamped_road_ids"]
    elev = root.find(".//road[@id='0']/elevationProfile/elevation")
    assert elev is not None
    assert abs(float(elev.get("b")) - 3.0) < 1e-9


def test_gentle_grade_is_not_clamped(monkeypatch) -> None:
    monkeypatch.delenv("UP_ELEVATION_MAX_GRADE", raising=False)
    root = ET.Element("OpenDRIVE")
    _make_road(root, "0", x=0.0, length=100.0)  # z 100 -> 115 over 100 m: b=0.15
    qc = ElevationImporter.apply_dem(
        root, _sampler(100.0, 100.0, 115.0), collect_qc=True, linear_grade=True
    )
    assert qc is not None
    assert "0" not in qc["grade_clamped_road_ids"]
    elev = root.find(".//road[@id='0']/elevationProfile/elevation")
    assert elev is not None
    assert abs(float(elev.get("b")) - 0.15) < 1e-9
