# tests/unit/test_topology_certification.py
# -*- coding: utf-8 -*-

"""
Tests for OC-2 topology certification (AREA-008): the literal-spec graph vs
the recovered-diagnostic graph, and the interaction with the acceptance gate.

Covered:
- component_reachability_summary(literal=True) counts a flipped-contactPoint
  road-level link as unmatched where the recovered graph tolerates it.
- certify_topology emits SPEC_TOPOLOGY / RECOVERY_DIAGNOSTIC QualityStatus
  values; production evidence is always LITERAL_SPEC.
- Missing evidence surfaces as INCOMPLETE (fail-closed), never PASS.
- build_map_acceptance hard-fails on the LITERAL spec fraction; a governed
  waiver downgrades a would-be hard fail to a WAIVED soft warning.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.map_acceptance import (
    build_map_acceptance,
    component_reachability_summary,
)
from ultimate_pipeline.quality.topology_certification import certify_topology


def _road(rid: str, sections: list[str]) -> str:
    lanes = "".join(
        f'<laneSection><right>{s}</right></laneSection>' for s in sections
    )
    return f'<road id="{rid}"><lanes>{lanes}</lanes></road>'


def _lane(lid: str, *links: str) -> str:
    link_xml = "".join(links)
    link = f"<link>{link_xml}</link>" if links else ""
    return f'<lane id="{lid}" type="driving">{link}</lane>'


def _xodr(roads: str) -> ET.Element:
    return ET.fromstring(f"<OpenDRIVE>{roads}</OpenDRIVE>")


# ---------------------------------------------------------------------------
# Literal vs recovered graph behavior
# ---------------------------------------------------------------------------


def test_literal_mode_flags_flipped_contact_point_road_link() -> None:
    """A ROAD-level link whose lane only exists at the target's OTHER
    boundary is tolerated by the recovered graph but counted as an unmatched
    spec deviation in literal mode."""
    # road 0 (one section, lane -2) links to road 1 with contactPoint="start";
    # road 1 has lane -2 only at its END section, not its start section.
    road0 = (
        '<road id="0"><link><successor elementType="road" elementId="1" '
        'contactPoint="start"/></link>'
        '<lanes><laneSection><right><lane id="-2" type="driving"/></right>'
        "</laneSection></lanes></road>"
    )
    road1 = (
        '<road id="1"><lanes>'
        '<laneSection><right><lane id="-1" type="driving"/></right></laneSection>'
        '<laneSection><right><lane id="-2" type="driving"/>'
        '<lane id="-1" type="driving"/></right></laneSection>'
        "</lanes></road>"
    )
    root = _xodr(road0 + road1)

    recovered = component_reachability_summary(root)
    literal = component_reachability_summary(root, literal=True)

    assert recovered is not None and literal is not None
    assert recovered["graph_source"] == "RECOVERED_DIAGNOSTIC"
    assert literal["graph_source"] == "LITERAL_SPEC"
    assert recovered["unmatched_cross_links"] == 0
    assert literal["unmatched_cross_links"] >= 1
    assert literal["largest_component_fraction"] < recovered["largest_component_fraction"]


def test_literal_and_recovered_agree_on_clean_spec() -> None:
    """When every reference resolves at its declared side, literal and
    recovered must report the same reachability and zero unmatched links."""
    road0 = (
        '<road id="0"><link><successor elementType="road" elementId="1" '
        'contactPoint="start"/></link>'
        '<lanes><laneSection><right><lane id="1" type="driving"/>'
        '<lane id="-1" type="driving"/></right></laneSection></lanes></road>'
    )
    road1 = (
        '<road id="1"><link><predecessor elementType="road" elementId="0" '
        'contactPoint="end"/></link>'
        '<lanes><laneSection><right><lane id="1" type="driving"/>'
        '<lane id="-1" type="driving"/></right></laneSection></lanes></road>'
    )
    root = _xodr(road0 + road1)
    recovered = component_reachability_summary(root)
    literal = component_reachability_summary(root, literal=True)

    assert recovered["unmatched_cross_links"] == 0
    assert literal["unmatched_cross_links"] == 0
    assert literal["largest_component_fraction"] == recovered["largest_component_fraction"]


# ---------------------------------------------------------------------------
# certify_topology semantics
# ---------------------------------------------------------------------------


def test_certify_recovered_pass_literal_fail() -> None:
    """The canonical OC-2 case: the recovered graph looks healthy but the
    literal spec graph does not -- the map is NOT topology-spec-conformant."""
    literal = {"graph_source": "LITERAL_SPEC", "largest_component_fraction": 0.90, "unmatched_cross_links": 3}
    recovered = {"largest_component_fraction": 0.96, "unmatched_cross_links": 0}

    cert = certify_topology(literal, recovered)

    assert cert["SPEC_TOPOLOGY"] == "fail"
    assert cert["RECOVERY_DIAGNOSTIC"] == "pass"
    assert cert["production_evidence"] == "LITERAL_SPEC"
    assert cert["literal_largest_component_fraction"] == 0.90
    assert cert["recovered_largest_component_fraction"] == 0.96
    assert cert["literal_unmatched_cross_links"] == 3


def test_certify_both_pass() -> None:
    literal = {"graph_source": "LITERAL_SPEC", "largest_component_fraction": 0.97, "unmatched_cross_links": 0}
    recovered = {"largest_component_fraction": 0.99, "unmatched_cross_links": 0}
    cert = certify_topology(literal, recovered)
    assert cert["SPEC_TOPOLOGY"] == "pass"
    assert cert["RECOVERY_DIAGNOSTIC"] == "pass"


def test_certify_missing_evidence_is_incomplete_never_pass() -> None:
    cert = certify_topology(None, None)
    assert cert["SPEC_TOPOLOGY"] == "incomplete"
    assert cert["RECOVERY_DIAGNOSTIC"] == "incomplete"
    assert cert != "pass"


# ---------------------------------------------------------------------------
# Acceptance gate: literal authority + governed waiver
# ---------------------------------------------------------------------------


def _fragmented_map(tmp_path):
    xodr = tmp_path / "fragmented.xodr"
    xodr.write_text(
        "<OpenDRIVE>" + _road("0", [_lane("1"), _lane("-1")]) + _road("1", [_lane("1"), _lane("-1")]) + "</OpenDRIVE>",
        encoding="utf-8",
    )
    return str(xodr)


def test_acceptance_records_literal_spec_metrics(tmp_path) -> None:
    acceptance = build_map_acceptance(
        {}, final_xodr_path=_fragmented_map(tmp_path), require_component_reachability=True
    )
    assert acceptance["valid_for_experiments"] is False
    assert "component_reachability" in acceptance["failed_gates"]
    assert acceptance["metrics"]["component_reachability_spec_status"] == "fail"
    assert acceptance["metrics"]["component_reachability_recovery_status"] == "fail"
    assert acceptance["metrics"]["topology_production_evidence"] == "LITERAL_SPEC"
    assert acceptance["metrics"]["largest_component_fraction"] == 0.25
    assert acceptance["metrics"]["largest_component_fraction_spec"] == 0.25


def test_acceptance_gate_waiver_downgrades_to_waived(tmp_path) -> None:
    acceptance = build_map_acceptance(
        {},
        final_xodr_path=_fragmented_map(tmp_path),
        require_component_reachability=True,
        component_reachability_waiver="runtime experiment requires fragmented layout",
    )
    assert acceptance["valid_for_experiments"] is True
    assert "component_reachability" not in acceptance["failed_gates"]
    assert acceptance["metrics"]["component_reachability_waiver_applied"] is True
    assert acceptance["metrics"]["component_reachability_spec_status"] == "waived"
    waived = [w for w in acceptance["soft_warnings"] if w["gate"] == "component_reachability"]
    assert any("WAIVED by governed waiver" in w["reason"] for w in waived)


def test_acceptance_gate_skip_when_no_evidence_is_incomplete(tmp_path) -> None:
    acceptance = build_map_acceptance({})
    assert acceptance["valid_for_experiments"] is True
    assert "component_reachability_spec_status" not in acceptance["metrics"]