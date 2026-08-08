#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R13 - digest v2 discriminator tests (offline; no CARLA runtime).

Proves the v2 traffic-control and structural digests discriminate:
  EMPTY != MISSING != PARSE_FAILURE, semantic mutation detected, record
  reordering invariant, and the R13E evidence verdicts reproducible.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
R13 = REPO / "reports" / "post_audit_hardening" / "20260808T000000Z_C0_REMEDIATION"

sys.path.insert(0, str(REPO))
from phase_q.common import sha256_text  # noqa: E402
from phase_q.signal_digest import (  # noqa: E402
    traffic_control_digests_v2, traffic_control_digests_v2_from_text)
from phase_q.structural_digest import structural_digests_v2  # noqa: E402

SIG_A = ('<signal id="s1" s="10.0" t="-3.5" zOffset="0.0" type="1000001" '
         'subtype="-1" dynamic="no" country="deu" name="traffic" value="0" '
         'unit="none" orientation="none"/>')
SIG_B = ('<signal id="s2" s="20.0" t="-3.5" zOffset="0.0" type="1000001" '
         'subtype="-1" dynamic="no" country="deu" name="traffic" value="0" '
         'unit="none" orientation="none"/>')
SIG_B_MUT = ('<signal id="s2" s="20.0" t="-3.5" zOffset="0.0" type="1000001" '
             'subtype="-1" dynamic="no" country="deu" name="advisory" value="1" '
             'unit="none" orientation="none"/>')
REF_A = '<signalReference id="r1" s="12.0" t="-1.5" type="1000001" subtype="-1"/>'


def _doc(children: str) -> str:
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<OpenDRIVE>\n  <header revMajor=\"1\" revMinor=\"4\"/>\n"
            "  <road id=\"1\">\n    <planView/>\n" + children
            + "  </road>\n</OpenDRIVE>\n")


@pytest.fixture(scope="module")
def digests():
    return {
        "present": traffic_control_digests_v2_from_text(
            _doc("  <signals>\n    " + SIG_A + "\n    " + SIG_B + "\n  </signals>\n")),
        "empty": traffic_control_digests_v2_from_text(_doc("  <signals/>\n")),
        "missing": traffic_control_digests_v2_from_text(_doc("")),
        "parse": traffic_control_digests_v2_from_text('<OpenDRIVE><road id="1"'),
        "reorder": traffic_control_digests_v2_from_text(
            _doc("  <signals>\n    " + SIG_B + "\n    " + SIG_A + "\n  </signals>\n")),
        "mut": traffic_control_digests_v2_from_text(
            _doc("  <signals>\n    " + SIG_A + "\n    " + SIG_B_MUT + "\n  </signals>\n")),
        "ref": traffic_control_digests_v2_from_text(
            _doc("  <signals>\n    " + REF_A + "\n  </signals>\n")),
    }


def test_empty_differs_from_missing(digests):
    assert digests["empty"]["signal_element_state"] == "EMPTY_COLLECTION"
    assert digests["missing"]["signal_element_state"] == "MISSING_COLLECTION"
    assert (digests["empty"]["signal_element_digest"]
            != digests["missing"]["signal_element_digest"])


def test_parse_failure_is_distinct_sentinel(digests):
    d = digests["parse"]
    assert d["parse_failure"] is True
    assert d["signal_element_state"] == "PARSE_FAILURE"
    assert (d["signal_element_digest"]
            != digests["empty"]["signal_element_digest"])


def test_empty_digest_is_not_count_only(digests):
    assert digests["empty"]["signal_element_digest"] != sha256_text("0")


def test_signal_reference_changes_ref_digest(digests):
    assert digests["ref"]["signal_reference_count"] == 1
    assert (digests["ref"]["signal_reference_digest"]
            != digests["empty"]["signal_reference_digest"])


def test_semantic_mutation_changes_digest_same_count(digests):
    assert (digests["mut"]["signal_element_digest"]
            != digests["present"]["signal_element_digest"])
    assert digests["mut"]["signal_count"] == digests["present"]["signal_count"]


def test_reordering_does_not_change_digest(digests):
    assert (digests["reorder"]["signal_element_digest"]
            == digests["present"]["signal_element_digest"])


def test_four_collection_states_distinct(digests):
    states = [digests[k]["signal_element_state"] for k in
              ("present", "empty", "missing", "parse")]
    assert len(set(states)) == 4


def test_v2_api_accepts_parsed_tree():
    """traffic_control_digests_v2(parsed) path executes without error."""
    from phase_q.common import XodrTree
    parsed = XodrTree(_doc("  <signals/>\n"))
    d = traffic_control_digests_v2(parsed)
    assert d["schema"] == "phase_q/signal_digest/v2"
    assert d["signal_element_state"] == "EMPTY_COLLECTION"


def test_structural_digests_v2_schema():
    small = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
             "<OpenDRIVE>\n  <header revMajor=\"1\" revMinor=\"4\"/>\n"
             "  <road id=\"1\">\n    <planView>\n      <geometry s=\"0\" x=\"0\" "
             "y=\"0\" hdg=\"0\" length=\"10\" type=\"line\"/>\n    </planView>\n"
             "    <lanes>\n      <laneSection s=\"0\">\n        <center>\n"
             "          <lane id=\"0\" type=\"driving\"/>\n        </center>\n"
             "      </laneSection>\n    </lanes>\n  </road>\n"
             "  <junction id=\"9\">\n    <connection id=\"0\" in=\"1\" "
             "out=\"2\" type=\"normal\">\n      <laneLink from=\"0\" to=\"0\"/>\n"
             "    </connection>\n  </junction>\n</OpenDRIVE>\n")
    s = structural_digests_v2(small, repaired_junction_ids=None)
    assert s["schema"] == "phase_q/structural_digest/v13"
    assert s["roads"] == 1
    assert s["junctions"] == 1
    assert s["roadmark_state"] in ("PRESENT", "EMPTY_COLLECTION", "MISSING_COLLECTION")
    assert s["superelevation_crossfall_state"] in (
        "PRESENT", "EMPTY_COLLECTION", "MISSING_COLLECTION")
    assert s["connector_repair_state"] == "MISSING_COLLECTION"
    for k in ("planview_digest", "road_link_digest", "junction_connection_digest",
              "lanelink_digest", "lanesection_digest", "elevation_digest",
              "superelevation_crossfall_digest", "roadmark_digest",
              "connector_repair_digest", "combined_structural_digest"):
        assert isinstance(s[k], str) and len(s[k]) == 64


def test_r13d_evidence_passes():
    ev = json.loads((R13 / "R13D_DIGEST_V2_TEST_EVIDENCE.json").read_text())
    assert ev["all_cases_pass"] is True
    assert ev["verdict"] == "DIGEST_V2_DISCRIMINATOR_PASS"


def test_r13e_evidence_gates_pass():
    ev = json.loads((R13 / "R13E_SEMANTIC_PARENT_AUTHORITY_V2.json").read_text())
    assert all(ev["gates"].values()), ev["gates"]
    assert ev["verdict"] == "SEMANTIC_PARENT_AUTHORITY_V2"
    assert ev["counts"]["roads"] == 32710
    assert ev["counts"]["junctions"] == 3646
    assert ev["counts"]["signals"] == 3467