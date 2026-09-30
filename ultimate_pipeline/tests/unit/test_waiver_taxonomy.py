# ultimate_pipeline/tests/unit/test_waiver_taxonomy.py
# -*- coding: utf-8 -*-
"""NEW-210 / GAP-037: non-waivable gate taxonomy tests."""

from __future__ import annotations

import pytest

from ultimate_pipeline.contracts.stage_contracts import (
    GATE_CLASS_REGISTRY,
    NON_WAIVABLE_CLASSES,
    GateClass,
    QualityStatus,
    classify_gate,
    governed_waiver_allowed,
    production_gate_waiver_allowed,
    promote_aggregate,
)


def test_taxonomy_values():
    assert GateClass.IDENTITY_INTEGRITY.value == "identity_integrity"
    assert GateClass.STRUCTURAL_INTEGRITY.value == "structural_integrity"
    assert GateClass.QUALITY_DEVIATION.value == "quality_deviation"
    assert GateClass.HEURISTIC_ADVISORY.value == "heuristic_advisory"
    assert GateClass.RUNTIME_DEPENDENT.value == "runtime_dependent"


def test_non_waivable_set():
    assert GateClass.IDENTITY_INTEGRITY in NON_WAIVABLE_CLASSES
    assert GateClass.STRUCTURAL_INTEGRITY in NON_WAIVABLE_CLASSES
    assert GateClass.RUNTIME_DEPENDENT in NON_WAIVABLE_CLASSES
    assert GateClass.QUALITY_DEVIATION not in NON_WAIVABLE_CLASSES
    assert GateClass.HEURISTIC_ADVISORY not in NON_WAIVABLE_CLASSES


def test_minimum_classification_present():
    for gate in ("map_registry_identity", "artifact_fingerprint",
                 "repository_sha", "manifest_digest", "candidate_identity",
                 "package_identity", "deterministic_provenance",
                 "xodr_xml_integrity", "junction_integrity",
                 "lane_link_targets_exist", "lane_section_successors"):
        assert gate in GATE_CLASS_REGISTRY, gate
    assert GATE_CLASS_REGISTRY["component_reachability"] == GateClass.QUALITY_DEVIATION


def test_quality_deviation_waivable():
    assert governed_waiver_allowed(
        {"component_reachability": "island lanes reviewed, accepted"},
        "component_reachability") is True
    assert production_gate_waiver_allowed(
        {"component_reachability": "island lanes reviewed, accepted"},
        "component_reachability") is True


def test_identity_gate_not_waivable():
    assert governed_waiver_allowed(
        {"repository_sha": "please waive"}, "repository_sha",
        GateClass.IDENTITY_INTEGRITY) is False
    assert production_gate_waiver_allowed(
        {"artifact_fingerprint": "please waive"}, "artifact_fingerprint") is False
    assert production_gate_waiver_allowed(
        {"repository_sha": "please waive"}, "repository_sha") is False


def test_structural_gate_not_waivable():
    assert governed_waiver_allowed(
        {"junction_integrity": "please waive"}, "junction_integrity",
        GateClass.STRUCTURAL_INTEGRITY) is False
    assert production_gate_waiver_allowed(
        {"junction_integrity": "please waive"}, "junction_integrity") is False
    assert production_gate_waiver_allowed(
        {"xodr_xml_integrity": "please waive"}, "xodr_xml_integrity") is False


def test_runtime_gate_not_waivable():
    assert governed_waiver_allowed(
        {"some_runtime_gate": "please waive"}, "some_runtime_gate",
        GateClass.RUNTIME_DEPENDENT) is False


def test_unknown_class_fails_closed():
    assert classify_gate("totally_unknown_gate_xyz") is None
    assert production_gate_waiver_allowed(
        {"totally_unknown_gate_xyz": "please waive"},
        "totally_unknown_gate_xyz") is False
    # Unknown explicit class string never defaults to waivable.
    assert governed_waiver_allowed(
        {"totally_unknown_gate_xyz": "please waive"},
        "totally_unknown_gate_xyz", "not_a_real_class") is False


def test_blank_justification_no_waiver():
    assert governed_waiver_allowed(
        {"component_reachability": "   "}, "component_reachability") is False
    assert governed_waiver_allowed({}, "component_reachability") is False
    assert governed_waiver_allowed(None, "component_reachability") is False


def test_wrong_child_no_waiver():
    assert governed_waiver_allowed(
        {"other_gate": "justification"}, "component_reachability") is False


def test_aggregate_quality_waiver_stays_waived():
    agg = promote_aggregate(
        [QualityStatus.FAIL],
        mandatory_children=["component_reachability"],
        waivers={"component_reachability": "reviewed, accepted"},
        child_names=["component_reachability"])
    assert agg == QualityStatus.WAIVED
    strict = promote_aggregate(
        [QualityStatus.FAIL],
        mandatory_children=["component_reachability"],
        waivers={"component_reachability": "reviewed, accepted"},
        child_names=["component_reachability"],
        enforce_taxonomy=True)
    assert strict == QualityStatus.WAIVED


def test_aggregate_identity_waiver_stays_fail():
    strict = promote_aggregate(
        [QualityStatus.FAIL],
        mandatory_children=["repository_sha"],
        waivers={"repository_sha": "please waive"},
        child_names=["repository_sha"],
        enforce_taxonomy=True)
    assert strict == QualityStatus.FAIL


def test_aggregate_unknown_waiver_stays_fail():
    strict = promote_aggregate(
        [QualityStatus.FAIL],
        mandatory_children=["mystery_gate"],
        waivers={"mystery_gate": "please waive"},
        child_names=["mystery_gate"],
        enforce_taxonomy=True)
    assert strict == QualityStatus.FAIL


def test_no_fail_to_pass_via_waiver():
    # A waived quality gate is WAIVED, never PASS; mixed with a hard FAIL
    # the aggregate stays FAIL.
    agg = promote_aggregate(
        [QualityStatus.FAIL, QualityStatus.FAIL],
        mandatory_children=["component_reachability", "repository_sha"],
        waivers={"component_reachability": "ok", "repository_sha": "nope"},
        child_names=["component_reachability", "repository_sha"],
        enforce_taxonomy=True)
    assert agg == QualityStatus.FAIL
