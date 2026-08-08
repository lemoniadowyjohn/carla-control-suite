#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R13 - crosswalk fixtures + XML object count evidence tests (offline).

Validates the evidence produced by stage_r13_production.py:
  - R13G fixture rows: deterministic orientation/position/context coverage,
    cornerLocal-only polylines (no cornerGlobal), 66 real + synthetic fallback;
  - R13J: candidate holds exactly 66 unique crosswalk objects and only
    local corner coordinates;
  - R13H: subtype authority normalized from S07 crossing tags;
  - R13I: handoff carries name/visual-marking mapping and the explicit void.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
R13 = REPO / "reports" / "post_audit_hardening" / "20260808T000000Z_C0_REMEDIATION"

sys.path.insert(0, str(REPO))


def _csv(name: str):
    with open(R13 / name, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_r13g_fixture_coverage():
    rows = _csv("R13G_CROSSWALK_COORDINATE_FIXTURES.csv")
    assert len(rows) >= 66
    orient = {r["orientation"] for r in rows}
    ctx = {r["context"] for r in rows}
    pos = {r["position"] for r in rows}
    assert {"E", "S", "W", "N"} <= orient
    assert {"JUNCTION", "ROUNDABOUT"} <= ctx
    assert "CENTER" in pos
    real = [r for r in rows if r["source"] == "REAL"]
    assert len(real) >= 66
    for r in real:
        import json as _json
        assert _json.loads(r["cornerLocal"])  # parseable polyline
    assert len({r["fixture_id"] for r in rows}) == len(rows)  # unique ids


def test_r13_j_xml_object_count():
    ev = json.loads((R13 / "R13J_XML_OBJECT_COUNT_EVIDENCE.json").read_text())
    assert ev["crosswalk_objects"] == 66
    assert ev["unique_crosswalk_ids"] == 66
    assert ev["cornerGlobal_total"] == 0
    assert ev["cornerLocal_total"] > 0
    assert ev["verified_66_unique_local_only"] is True
    assert ev["verdict"] == "XML_OBJECT_COUNT_VERIFIED"


def test_r13_h_subtype_authority():
    rows = _csv("R13H_CROSSWALK_SUBTYPE_AUTHORITY.csv")
    assert len(rows) == 179
    norms = {r["normalized_subtype"] for r in rows}
    assert norms <= {"SIGNALIZED", "UNCONTROLLED", "MARKED", "ZEBRA",
                     "UNMARKED", "UNCLASSIFIED"}
    for r in rows:
        raw = (r["crossing_type_raw"] or "").lower()
        if raw in ("traffic_signals", "uncontrolled", "marked", "zebra", "unmarked"):
            expect = {"traffic_signals": "SIGNALIZED", "uncontrolled": "UNCONTROLLED",
                      "marked": "MARKED", "zebra": "ZEBRA",
                      "unmarked": "UNMARKED"}[raw]
            assert r["normalized_subtype"] == expect


def test_r13_i_handoff():
    ev = json.loads((R13 / "R13I_PACKAGE_SEMANTIC_HANDOFF.json").read_text())
    assert ev["void"] == ""
    assert "crosswalk_{osm_id}" in ev["provenance_in_object_id"]
    total = sum(ev["emitted_name_counts"].values())
    assert total == 66
    assert "ZEBRA" in ev["expected_visual_marking"]


def test_r13_g_pedestrian_counts():
    ev = json.loads((R13 / "R13L_PEDESTRIAN_SOURCE_COUNTS.json").read_text())
    assert ev["authority_total"] == 5431
    assert ev["accounting_invariant_pass"] is True
    assert ev["classification_counts"]["CROSSING"] == 179
    assert ev["verdict"] == "PEDESTRIAN_SOURCE_AUTHORITY_RECOMPUTED"
    km = _csv("R13K_PEDESTRIAN_SOURCE_AUTHORITY.csv")
    assert len(km) == 5431
    assert len(km) == ev["accounted_total"]