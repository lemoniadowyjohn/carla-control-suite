from __future__ import annotations

import json
from pathlib import Path

from ultimate_pipeline.tools.audit_building_frame_alignment import (
    audit_building_frame_alignment,
    main,
)


def _write_source_buildings(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "elements": [
                    {
                        "type": "way",
                        "id": 1,
                        "tags": {"building": "yes"},
                        "geometry": [
                            {"lon": 11.4, "lat": 48.7},
                            {"lon": 11.4001, "lat": 48.7},
                            {"lon": 11.4001, "lat": 48.7001},
                            {"lon": 11.4, "lat": 48.7001},
                            {"lon": 11.4, "lat": 48.7},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _write_xodr(
    path: Path,
    source_path: Path,
    *,
    dx: float = 0.0,
    dy: float = 0.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> None:
    from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader

    building = OSMPolygonLoader.load_buildings_from_geojson(str(source_path))[0]
    points = building.footprint[:-1]
    corners = "".join(
        f'<cornerGlobal x="{x - offset_x + dx}" y="{y - offset_y + dy}" z="0"/>'
        for x, y in points
    )
    path.write_text(
        f'<OpenDRIVE><header><offset x="{offset_x}" y="{offset_y}" z="0" hdg="0"/>'
        "</header><road id=\"1\"><objects><object id=\"osm_bld_1\" type=\"building\">"
        f"<outline>{corners}</outline></object></objects></road></OpenDRIVE>",
        encoding="utf-8",
    )


def test_audit_passes_for_matching_source_and_local_corner_global(tmp_path: Path) -> None:
    source, xodr = tmp_path / "buildings.json", tmp_path / "map.xodr"
    _write_source_buildings(source)
    _write_xodr(xodr, source)

    report = audit_building_frame_alignment(xodr, source)

    assert report["status"] == "PASS"
    assert report["counts"]["common_building_ids"] == 1
    assert report["systematic_offset_m"]["p95_per_building_distance"] == 0.0


def test_audit_applies_the_header_offset_to_source_buildings(tmp_path: Path) -> None:
    source, xodr = tmp_path / "buildings.json", tmp_path / "map.xodr"
    _write_source_buildings(source)
    _write_xodr(xodr, source, offset_x=832671.676, offset_y=5458671.104)

    report = audit_building_frame_alignment(xodr, source)

    assert report["status"] == "PASS"
    assert report["inputs"]["header_offset_m"] == {"x": 832671.676, "y": 5458671.104}


def test_audit_fails_a_systemic_ten_metre_frame_shift(tmp_path: Path) -> None:
    source, xodr = tmp_path / "buildings.json", tmp_path / "map.xodr"
    _write_source_buildings(source)
    _write_xodr(xodr, source, dx=10.1, dy=-2.0)

    report = audit_building_frame_alignment(xodr, source)

    assert report["status"] == "FAIL"
    assert report["frame_alignment"] == "FAIL"
    assert report["systematic_offset_m"]["median_vector_magnitude"] > 10.0


def test_audit_reports_individual_drift_without_calling_it_a_frame_failure(tmp_path: Path) -> None:
    source, xodr = tmp_path / "buildings.json", tmp_path / "map.xodr"
    _write_source_buildings(source)
    # One shared building cannot establish a robust population frame.  Add 20
    # exact shared copies to make the single changed building a true outlier.
    # Build matching source ids by duplicating the one source geometry with
    # different IDs.  This keeps the test focused on robust statistics.
    source_data = json.loads(source.read_text(encoding="utf-8"))
    source_data["elements"] = [
        {**source_data["elements"][0], "id": index} for index in range(1, 22)
    ]
    source.write_text(json.dumps(source_data), encoding="utf-8")
    # Rewrite with nineteen exact objects and the shifted original object.
    from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader

    footprint = OSMPolygonLoader.load_buildings_from_geojson(str(source))[0].footprint[:-1]
    def object_xml(object_id: int, offset: float) -> str:
        corners = "".join(
            f'<cornerGlobal x="{x + offset}" y="{y}" z="0"/>' for x, y in footprint
        )
        return f'<object id="osm_bld_{object_id}" type="building"><outline>{corners}</outline></object>'
    xodr.write_text(
        '<OpenDRIVE><header><offset x="0" y="0" z="0" hdg="0"/></header><road id="1"><objects>'
        + object_xml(1, 15.0)
        + "".join(object_xml(index, 0.0) for index in range(2, 22))
        + "</objects></road></OpenDRIVE>",
        encoding="utf-8",
    )

    report = audit_building_frame_alignment(xodr, source)

    assert report["status"] == "PASS"
    assert report["counts"]["individual_geometry_drift_count"] == 1
    assert report["individual_geometry_drift"][0]["object_id"] == "osm_bld_1"


def test_cli_writes_only_a_json_report_and_does_not_mutate_xodr(tmp_path: Path) -> None:
    source, xodr, report_path = tmp_path / "buildings.json", tmp_path / "map.xodr", tmp_path / "report.json"
    _write_source_buildings(source)
    _write_xodr(xodr, source)
    before = xodr.read_bytes()

    assert main(["--xodr", str(xodr), "--buildings", str(source), "--out", str(report_path)]) == 0

    assert xodr.read_bytes() == before
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "PASS"
