from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.quality.check_lane_count_changes import check_lane_count_changes


def _lane(lane_id: int, source: str | None = None) -> str:
    metadata = (
        f'<userData><vector key="lane_count_source" value="{source}"/></userData>'
        if source
        else ""
    )
    return (
        f'<lane id="{lane_id}" type="driving"><width sOffset="0" a="3.5"/>'
        f"{metadata}</lane>"
    )


def _road(
    road_id: str,
    lanes: str,
    *,
    predecessor: str = "",
    successor: str = "",
) -> str:
    return (
        f'<road id="{road_id}" length="10" junction="-1"><link>'
        f"{predecessor}{successor}</link><planView>"
        '<geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        "</planView><lanes><laneSection s=\"0\"><right>"
        f"{lanes}</right></laneSection></lanes></road>"
    )


def test_reports_osm_explained_unexplained_and_unchanged_boundaries(tmp_path: Path) -> None:
    path = tmp_path / "map.xodr"
    path.write_text(
        "<OpenDRIVE>"
        + _road(
            "1",
            _lane(-1, "osm:lanes"),
            successor='<successor elementType="road" elementId="2" contactPoint="start"/>',
        )
        + _road(
            "2",
            _lane(-1, "osm:lanes") + _lane(-2, "osm:lanes"),
            predecessor='<predecessor elementType="road" elementId="1" contactPoint="end"/>',
            successor='<successor elementType="road" elementId="3" contactPoint="start"/>',
        )
        + _road(
            "3",
            _lane(-1),
            predecessor='<predecessor elementType="road" elementId="2" contactPoint="end"/>',
            successor='<successor elementType="road" elementId="4" contactPoint="start"/>',
        )
        + _road(
            "4",
            _lane(-1),
            predecessor='<predecessor elementType="road" elementId="3" contactPoint="end"/>',
        )
        + "</OpenDRIVE>",
        encoding="utf-8",
    )

    report = check_lane_count_changes(path)

    assert report["summary_metrics"] == {
        "road_link_boundaries": 3,
        "no_change": 1,
        "osm_explained_change": 1,
        "unexplained_change": 1,
        "unresolved_road_links": 0,
    }
    categories = [finding["category"] for finding in report["findings"]]
    assert categories.count("OSM_EXPLAINED_CHANGE") == 1
    assert categories.count("UNEXPLAINED_CHANGE") == 1


def test_missing_link_target_is_reported_without_crashing(tmp_path: Path) -> None:
    path = tmp_path / "map.xodr"
    path.write_text(
        "<OpenDRIVE>"
        + _road(
            "1",
            _lane(-1),
            successor='<successor elementType="road" elementId="missing" contactPoint="start"/>',
        )
        + "</OpenDRIVE>",
        encoding="utf-8",
    )

    report = check_lane_count_changes(path)

    assert report["summary_metrics"]["unresolved_road_links"] == 1
    assert report["findings"] == []
