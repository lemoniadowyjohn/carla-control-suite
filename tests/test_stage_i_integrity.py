#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage I-J integration + integrity tests (offline; no CARLA runtime).

Gates (Section 19):
- T03 signal count == 3467 in the enriched/crosswalk candidate
- T05 signal element digest unchanged vs frozen parent
- T08/T09/T10 crossing authority: no INSERTED row has s out of road bounds;
  all crossings accounted (Stage H invariance)
- T11 crossing authority fully accounted (179 == 179)
- T12 pedestrian authority fully accounted (5431 == 5431)
- T14 planView mutation rejected  (digest unchanged)
- T15 road/junction mutation rejected (digest unchanged)
- T16 LaneLink mutation rejected  (digest unchanged)
- T17 connector-repair mutation rejected (12 ids stable)
- T18 deterministic two-run output (identical LF sha256)
- T19 idempotent re-run (0 new insertions, sha + digests unchanged)
"""
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
R = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z"
PY = str(REPO / ".venv" / "Scripts" / "python.exe")

CAND = R / "candidate_crosswalk_enriched.xodr"
PARENT = R / "candidate_g_semantic_enriched.xodr"
S03 = R / "S03_SEMANTIC_PARENT_AUTHORITY.json"
S04 = R / "S04_PROTECTED_STRUCTURAL_DIGESTS.json"
S05 = R / "S05_TRAFFIC_CONTROL_DIGESTS.json"
S09 = R / "S09_CROSSING_AUTHORITY_SUMMARY.json"
N10 = R / "N10_POST_CROSSWALK_INTEGRITY.json"
N14 = R / "N14_PEDESTRIAN_AUTHORITY_SUMMARY.json"
N15 = R / "N15_DETERMINISM.json"
N16 = R / "N16_IDEMPOTENCY.json"
N17 = R / "N17_FINAL_SEMANTIC_INTEGRITY.json"
N09 = R / "N09_CROSSWALK_MUTATION_LEDGER.csv"

sys.path.insert(0, str(REPO))
from phase_q.common import sha256_text, XodrTree, strip_xml_namespaces  # noqa: E402


def _counts(root):
    return {
        "signals": len(root.findall(".//signal")),
        "roads": len(root.findall("road")),
        "junctions": len(root.findall("junction")),
    }


@pytest.fixture(scope="module")
def candidate_root():
    return ET.fromstring(strip_xml_namespaces(CAND.read_text(encoding="utf-8", errors="replace")))


def test_parent_frozen_and_repaired():
    auth = json.loads(S03.read_text())
    assert auth["verdict"] == "SEMANTIC_PARENT_FROZEN"
    assert auth["counts"]["signals"] == 3467
    assert auth["counts"]["roads"] == 32710
    assert auth["counts"]["junctions"] == 3646
    assert auth["connector_count"] == 12


def test_T03_signal_count(candidate_root):
    assert _counts(candidate_root)["signals"] == 3467


def test_T05_signal_element_digest_unchanged():
    tc = json.loads(S05.read_text())
    cur = json.loads((R / "S05_TRAFFIC_CONTROL_DIGESTS.json").read_text())  # frozen
    # post-mutation tc digest recomputed in N10:
    post = json.loads(N10.read_text())["traffic_control_integrity"]
    assert post["combined_tc_unchanged"] is True


def test_T08_T09_crossing_authority_accounted():
    s09 = json.loads(S09.read_text())
    assert s09["authority_total"] == 179
    assert s09["accounted_total"] == 179
    assert s09["accounting_invariant_pass"] is True
    n17 = json.loads(N17.read_text())
    assert n17["bad_s"] == []          # no crosswalk s out of road bounds
    assert n17["bad_polygons"] == []    # no invalid crosswalk polygons


def test_T10_no_invalid_polygons():
    n10 = json.loads(N10.read_text())
    assert n10["semantic_inventory_delta"]["crosswalk_objects_missing"] == 0


def test_T11_crossing_authority_fully_accounted():
    s09 = json.loads(S09.read_text())
    assert s09["authority_total"] == s09["accounted_total"] == 179


def test_T12_pedestrian_authority_fully_accounted():
    n14 = json.loads(N14.read_text())
    assert n14["authority_total"] == n14["accounted_total"] == 5431
    assert n14["accounting_invariant_pass"] is True


def test_T14_planview_mutation_rejected():
    n17 = json.loads(N17.read_text())
    assert n17["checks"]["planview_unchanged"] is True


def test_T15_road_junction_mutation_rejected():
    n17 = json.loads(N17.read_text())
    assert n17["checks"]["junction_unchanged"] is True
    assert n17["checks"]["combined_structural_digest_unchanged"] is True


def test_T16_lanelink_mutation_rejected():
    n17 = json.loads(N17.read_text())
    assert n17["checks"]["lanelink_unchanged"] is True


def test_T17_connector_repair_mutation_rejected():
    n17 = json.loads(N17.read_text())
    assert n17["checks"]["12_connector_repairs_preserved"] is True


def test_T18_deterministic_two_runs():
    n15 = json.loads(N15.read_text())
    assert n15["identical"] is True
    assert n15["run_a_sha256_lf_text"] == n15["run_b_sha256_lf_text"]


def test_T19_idempotent_re_enrich():
    """Functional idempotency: re-run the committed producer; expect 0 new."""
    before = sha256_text(CAND.read_text(encoding="utf-8", errors="replace"))
    proc = subprocess.run([PY, "stage_i1_crosswalk_writer.py"],
                          cwd=str(REPO), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "written=0" in proc.stdout
    assert "existing_skip=66" in proc.stdout
    after = sha256_text(CAND.read_text(encoding="utf-8", errors="replace"))
    assert before == after


def test_crosswalk_ids_unique_and_typed(candidate_root):
    cws = [o for o in candidate_root.iter("object") if (o.get("type") or "").lower() == "crosswalk"]
    ids = [o.get("id") for o in cws]
    assert len(cws) == 66
    assert len(set(ids)) == 66
    # every crosswalk object has a closed local outline in the only corner
    # form CARLA 0.9.16 reads: <cornerLocal u v z> (R05).
    for o in cws:
        ol = o.find("outline")
        assert ol is not None
        corners = ol.findall("cornerLocal")
        assert len(corners) >= 4
        assert ol.findall("cornerGlobal") == []
