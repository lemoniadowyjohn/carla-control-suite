# tests/unit/test_component_classifier.py
# -*- coding: utf-8 -*-

"""
Tests for the OC-2 topology component classifier and its integration into
island quarantine (map_hygiene.quarantine_island_roads).

Scope (TOPOLOGY_COMPONENT_AUDIT AREA-020 / component_size_quarantine):
- `classify_component` deterministically assigns one of the nine categories.
- PRIVATE_OR_SERVICE/PARKING_OR_YARD/SOURCE_DISCONNECTED and all defect
  categories remain auto-deletable by island quarantine.
- INTENTIONAL_ISLAND and UNKNOWN are never auto-deleted unless explicitly
  allowed (production fail-closed policy).
- `classify_components=False` reproduces the historical blind size-based
  quarantine exactly (env UP_CLASSIFY_QUARANTINE_COMPONENTS=0).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.quality.map_hygiene import quarantine_island_roads
from ultimate_pipeline.topology.component_classifier import (
    BOUNDARY_TRUNCATION,
    INTENTIONAL_ISLAND,
    ROAD_LINK_DEFECT,
    SOURCE_DISCONNECTED,
    UNKNOWN,
    classify_component,
    component_classification_report,
)


def _road(
    rid: str,
    length: float = 10.0,
    x: float = 0.0,
    y: float = 0.0,
    *,
    successor: str = None,
    predecessor: str = None,
    road_type: str = None,
    intentional_marker: bool = False,
) -> str:
    link = ""
    if successor is not None or predecessor is not None:
        parts = []
        if predecessor is not None:
            parts.append(
                f'<predecessor elementType="road" elementId="{predecessor}" contactPoint="end"/>'
            )
        if successor is not None:
            parts.append(
                f'<successor elementType="road" elementId="{successor}" contactPoint="start"/>'
            )
        link = "<link>" + "".join(parts) + "</link>"
    marker = ""
    if intentional_marker:
        marker = "<userData><intentionalIsland value=\"1\"/></userData>"
    type_attr = f' type="{road_type}"' if road_type else ""
    return (
        f'<road id="{rid}" length="{length}" junction="-1"{type_attr}>'
        f"{link}"
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="0" length="{length}"><line/></geometry></planView>'
        f"{marker}"
        "</road>"
    )


def _wrap(roads_xml: str) -> str:
    return '<?xml version="1.0" encoding="utf-8"?><OpenDRIVE>' + roads_xml + "</OpenDRIVE>"


def _chain(first: int, last: int, x: float = 0.0, y_base: float = 0.0) -> str:
    """A linear chain of roads first..last (inclusive) along +y."""
    parts = []
    for i in range(first, last + 1):
        succ = str(i + 1) if i < last else None
        pred = str(i - 1) if i > first else None
        parts.append(_road(str(i), length=100.0, x=x, y=y_base + (i - first) * 100.0, successor=succ, predecessor=pred))
    return "".join(parts)


def _parse_roads(xodr_path: str):
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    return {r.get("id"): r for r in root.findall("road")}, root


def _road_element(rid: str, **kwargs):
    return ET.fromstring(_road(rid, **kwargs))


# ---------------------------------------------------------------------------
# Classifier unit behavior
# ---------------------------------------------------------------------------


def test_classify_source_disconnected_internal_linked() -> None:
    roads = {
        "101": _road_element("101", successor="102"),
        "102": _road_element("102", predecessor="101"),
    }
    result = classify_component({"101", "102"}, roads, [], None)
    assert result["category"] == SOURCE_DISCONNECTED
    assert result["deletable"] is True


def test_classify_intentional_island_marker() -> None:
    roads = {
        "101": _road_element("101", successor="102", intentional_marker=True),
        "102": _road_element("102", predecessor="101"),
    }
    result = classify_component({"101", "102"}, roads, [], None)
    assert result["category"] == INTENTIONAL_ISLAND
    assert result["deletable"] is False


def test_classify_road_link_defect() -> None:
    roads = {"101": _road_element("101", successor="9999")}
    result = classify_component({"101"}, roads, [], None)
    assert result["category"] == ROAD_LINK_DEFECT
    assert result["deletable"] is True


def test_classify_type_semantics() -> None:
    roads = {"101": _road_element("101", road_type="service")}
    result = classify_component({"101"}, roads, [], None)
    assert result["category"] == "PRIVATE_OR_SERVICE"

    roads = {"101": _road_element("101", road_type="parking")}
    result = classify_component({"101"}, roads, [], None)
    assert result["category"] == "PARKING_OR_YARD"


# ---------------------------------------------------------------------------
# Quarantine integration: preservation is fail-closed
# ---------------------------------------------------------------------------


def test_unknown_component_preserved_not_auto_deleted(tmp_path: Path) -> None:
    """An UNKNOWN component (intentional marker + boundary truncation) must
    NOT be quarantined in production (fail-closed), and must be reported."""
    main = _chain(1, 25, x=100.0, y_base=0.0)  # x=100 fixed, y spans 0..2400
    # Island on the map's min-x edge with an intentional marker -> conflict
    # -> UNKNOWN. Map extent is non-degenerate (x-span 100, y-span 2400).
    island = (
        _road("101", length=40.0, x=0.0, y=0.0, intentional_marker=True)
        + _road("102", length=40.0, x=0.0, y=40.0, predecessor="101")
    )
    xodr = str(tmp_path / "unknown.xodr")
    Path(xodr).write_text(_wrap(main + island), encoding="utf-8")
    out = str(tmp_path / "unknown_out.xodr")

    report = quarantine_island_roads(xodr, out, min_component_roads=20)

    # Not quarantined: preserved.
    assert report["quarantined_road_ids"] == []
    assert report["count"] == 0
    preserved = report["preserved_components"]
    assert len(preserved) == 1
    assert preserved[0]["category"] == UNKNOWN
    assert set(preserved[0]["road_ids"]) == {"101", "102"}

    out_root = ET.parse(out).getroot()
    assert {r.get("id") for r in out_root.findall("road")} == {str(i) for i in range(1, 26)} | {"101", "102"}


def test_source_disconnected_still_quarantined(tmp_path: Path) -> None:
    """A genuinely disconnected (internally linked, no semantics) island
    remains auto-quarantined exactly as before the hardening."""
    main = _chain(1, 25)
    island = _road("101", successor="102") + _road("102", predecessor="101")
    xodr = str(tmp_path / "disc.xodr")
    Path(xodr).write_text(_wrap(main + island), encoding="utf-8")
    out = str(tmp_path / "disc_out.xodr")

    report = quarantine_island_roads(xodr, out, min_component_roads=20)

    assert set(report["quarantined_road_ids"]) == {"101", "102"}
    classification = report["component_classifications"][0]
    assert classification["category"] == SOURCE_DISCONNECTED
    assert classification["preserved"] is False
    assert report["preserved_components"] == []


def test_boundary_truncation_island_still_quarantined(tmp_path: Path) -> None:
    """A boundary-truncated (but not intentional/unknown) island is still
    auto-quarantined; BOUNDARY_TRUNCATION is a deletable category."""
    main = _chain(1, 25, x=500.0, y_base=0.0)
    island = _road("101", length=40.0, x=0.0, y=0.0)
    xodr = str(tmp_path / "bounds.xodr")
    Path(xodr).write_text(_wrap(main + island), encoding="utf-8")
    out = str(tmp_path / "bounds_out.xodr")

    report = quarantine_island_roads(xodr, out, min_component_roads=20)

    assert set(report["quarantined_road_ids"]) == {"101"}
    assert report["component_classifications"][0]["category"] == BOUNDARY_TRUNCATION


def test_allow_unknown_auto_delete_flag(tmp_path: Path) -> None:
    """Explicitly allowing UNKNOWN auto-delete restores legacy deletion for
    the flagged call only; the default stays fail-closed."""
    main = _chain(1, 25, x=100.0, y_base=0.0)
    island = (
        _road("101", length=40.0, x=0.0, y=0.0, intentional_marker=True)
        + _road("102", length=40.0, x=0.0, y=40.0, predecessor="101")
    )
    xodr = str(tmp_path / "allow.xodr")
    Path(xodr).write_text(_wrap(main + island), encoding="utf-8")
    out = str(tmp_path / "allow_out.xodr")

    report = quarantine_island_roads(
        xodr, out, min_component_roads=20, allow_unknown_auto_delete=True
    )
    assert set(report["quarantined_road_ids"]) == {"101", "102"}


def test_classify_components_false_reproduces_legacy_behavior(tmp_path: Path) -> None:
    """classify_components=False must delete every small component verbatim
    (the historical blind behavior), including UNKNOWN ones, and must still
    report the legacy keys."""
    main = _chain(1, 25)
    island = _road("101", successor="102") + _road("102", predecessor="101")
    xodr = str(tmp_path / "legacy.xodr")
    Path(xodr).write_text(_wrap(main + island), encoding="utf-8")
    out = str(tmp_path / "legacy_out.xodr")

    report = quarantine_island_roads(
        xodr, out, min_component_roads=20, classify_components=False
    )

    assert report["classify_components"] is False
    assert set(report["quarantined_road_ids"]) == {"101", "102"}
    assert report["count"] == 2
    assert "component_sizes_before" in report
    assert "quarantined_components" in report
    assert report["preserved_components"] == []


def test_classify_components_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """UP_CLASSIFY_QUARANTINE_COMPONENTS=0 forces legacy blind quarantine."""
    monkeypatch.setenv("UP_CLASSIFY_QUARANTINE_COMPONENTS", "0")
    main = _chain(1, 25)
    island = _road("101", successor="102") + _road("102", predecessor="101")
    xodr = str(tmp_path / "env.xodr")
    Path(xodr).write_text(_wrap(main + island), encoding="utf-8")
    out = str(tmp_path / "env_out.xodr")

    report = quarantine_island_roads(xodr, out, min_component_roads=20)
    assert report["classify_components"] is False
    assert "component_classifications" in report  # still present for audit
    assert set(report["quarantined_road_ids"]) == {"101", "102"}


def test_component_classification_report_counts(tmp_path: Path) -> None:
    """The audit-grade report tallies categories over ALL components."""
    main = _chain(1, 25)
    island = _road("101", successor="102") + _road("102", predecessor="101")
    xodr = str(tmp_path / "report.xodr")
    Path(xodr).write_text(_wrap(main + island), encoding="utf-8")
    roads, root = _parse_roads(xodr)
    junctions = root.findall("junction")

    result = component_classification_report([{str(i) for i in range(1, 26)}, {"101", "102"}], roads, junctions)
    assert result["component_count"] == 2
    assert result["categories"][SOURCE_DISCONNECTED] == 2