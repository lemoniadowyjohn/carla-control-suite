"""Tests for O12 current-map static release matrix."""
from __future__ import annotations

import json
from pathlib import Path

from tools.current_map_static_release_matrix import build_matrix, CURRENT_SHA


def test_matrix_binds_registry_pin() -> None:
    matrix = build_matrix()
    assert matrix["map_registry"]["sha256"] == CURRENT_SHA
    assert matrix["map_registry"]["verification_status"] == "VERIFIED"


def test_matrix_includes_required_gates() -> None:
    matrix = build_matrix()
    names = {row["gate"] for row in matrix["gates"]}
    required = {
        "xml_validity", "planview_completeness", "geometry_validation",
        "lane_topology", "road_links", "junction_links",
        "lane_count_classification", "component_reachability", "crs_checks",
        "map_acceptance", "artifact_fingerprint", "tile_readiness",
        "gap026", "waivers",
    }
    assert required <= names


def test_unbound_evidence_is_not_pass() -> None:
    matrix = build_matrix()
    for row in matrix["gates"]:
        if row["evidence_path"] and row["source_map_sha256"]:
            assert not (
                row["source_map_sha256"].lower() != CURRENT_SHA
                and row["status"] == "PASS"
            )


def test_matrix_is_json_serializable() -> None:
    json.dumps(build_matrix(), sort_keys=True)
