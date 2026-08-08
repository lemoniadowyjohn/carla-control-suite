#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R13 - mutation allowlist + parent hard gate tests (offline).

Fail-closed semantics of phase_q/mutation_allowlist.py: the frozen semantic
parent passes the gate; a differently-signed document (negative control) and
the empty allowlist must be rejected. R13N evidence verdict must be OK.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
R13 = REPO / "reports" / "post_audit_hardening" / "20260808T000000Z_C0_REMEDIATION"
SRC = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z"

sys.path.insert(0, str(REPO))
from phase_q.mutation_allowlist import (  # noqa: E402
    ALLOWED_MUTATIONS, PROTECTED_CATEGORIES, effective_allowlist,
    parent_hard_gate)


def _tiny_doc() -> str:
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<OpenDRIVE>\n  <header revMajor=\"1\" revMinor=\"4\"/>\n"
            "  <road id=\"1\">\n    <planView/>\n" + "  </road>\n</OpenDRIVE>\n")


def _frozen(expected_sha: str) -> dict:
    """Minimal frozen authority for the tiny doc: counts + sha (+ null TC)."""
    small = _tiny_doc()
    root = ET.fromstring(small)
    return {
        "counts": {
            "roads": len(root.findall("road")),
            "junctions": len(root.findall("junction")),
            "signals": len(root.findall(".//signal")),
        },
        "semantic_parent": {"sha256_lf_text": expected_sha},
        "traffic_control": {"combined_traffic_control_digest": None},
    }


def test_allowlist_is_single_mutation():
    eff = effective_allowlist()
    assert eff == ["object:INSERT_OBJECT_CROSSWALK"]
    assert ALLOWED_MUTATIONS["object"] == ["INSERT_OBJECT_CROSSWALK"]
    for cat in PROTECTED_CATEGORIES:
        assert ALLOWED_MUTATIONS[cat] == []


def test_empty_allowlist_rejected():
    small = _tiny_doc()
    gate = parent_hard_gate(small, _frozen(""), allowlist=[])
    assert gate.allowed is False
    assert any("MUTATION_ALLOWLIST_EMPTY" in r for r in gate.reasons)


def test_sha_mismatch_rejected():
    small = _tiny_doc()
    gate = parent_hard_gate(small, _frozen("deadbeef" * 8))
    assert gate.allowed is False
    assert any("PARENT_SHA256_MISMATCH" in r for r in gate.reasons)


def test_parse_failure_rejected():
    gate = parent_hard_gate("<OpenDRIVE><road id=\"1\"", _frozen("x" * 64))
    assert gate.allowed is False
    assert any("PARSE_FAILURE" in r for r in gate.reasons)


def test_r13n_evidence_ok():
    ev = json.loads((R13 / "R13N_MUTATION_ALLOWLIST_AND_PARENT_GATE.json").read_text())
    assert ev["verdict"] == "MUTATION_ALLOWLIST_AND_PARENT_GATE_OK"
    assert ev["effective_allowlist"] == ["object:INSERT_OBJECT_CROSSWALK"]
    pos = ev["positive_control"]
    assert pos["allowed"] is True
    neg = ev["negative_control"]
    assert neg["allowed"] is False
    assert neg["hard_fail"] is True
    assert neg["expected_hard_fail"] is True