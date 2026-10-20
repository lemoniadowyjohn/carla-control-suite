# -*- coding: utf-8 -*-
"""Deterministic tests for RQ1 identity machinery and hermetic execution.

Covers:
  * canonical OpenDRIVE normalization (formatting-only / timestamp
    collapses; lane-topology, geometry and lane-width changes diverge)
  * structural signature (structural mutation detection + serialization
    invariance)
  * five-run driver environment whitelist (leak prevention)
  * rq1b child failure propagation (non-zero exit with FAILED receipt)
  * RQ2 pinned pair identity (SHA-pinned registry resolution)
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from research.rq1_normalization import NORMALIZATION_VERSION, normalize_xodr
from research.rq1_structural_signature import (
    STRUCTURAL_SIGNATURE_VERSION,
    compute_structural_signature,
)

# ---------------------------------------------------------------------------
# XODR fixture factory
# ---------------------------------------------------------------------------
HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<OpenDRIVE>\n'
    '  <header revMajor="1" revMinor="4" name="" version="1.00" '
    'date="{date}" north="10.0" south="0.0" east="10.0" west="0.0">\n'
    '    <geoReference>+proj=tmerc</geoReference>\n'
    '  </header>\n'
)


def _road(rid, junction="-1", pred=None, succ=None, width_d="0.0", sections=1, x="100.0"):
    links = ""
    if pred:
        links += f'<predecessor elementType="{pred[0]}" elementId="{pred[1]}" contactPoint="{pred[2]}"/>'
    if succ:
        links += f'<successor elementType="{succ[0]}" elementId="{succ[1]}" contactPoint="{succ[2]}"/>'
    secs = ""
    for si in range(sections):
        s = si * 50.0
        secs += (
            f'<laneSection s="{s}">'
            '<center><lane id="0" type="driving"/></center>'
            f'<right><lane id="-1" type="driving">'
            f'<width sOffset="0" a="3.5" b="0.0" c="0.0" d="{width_d}"/>'
            "</lane></right>"
            "</laneSection>"
        )
    return (
        f'<road name="R{rid}" length="100.0" id="{rid}" junction="{junction}">'
        f"<link>{links}</link>"
        '<type s="0" type="town"/>'
        f'<planView><geometry s="0" x="{x}" y="200.0" hdg="0.0" length="100.0">'
        '<line/></geometry></planView>'
        "<lanes>" + secs + "</lanes>"
        "</road>"
    )


def _junction(jid, incoming="1"):
    return (
        f'<junction id="{jid}" name="J{jid}" type="default">'
        f'<connection id="0" incomingRoad="{incoming}" connectingRoad="9" '
        f'contactPoint="start"><laneLink from="-1" to="-1"/></connection>'
        "</junction>"
    )


def write_xodr(tmp_path: Path, name: str, body: str, *, date="Mon Jan 01 00:00:00 2024",
               pretty=True, comment=None):
    doc = HEADER.format(date=date)
    if comment:
        doc += f"<!-- {comment} -->\n"
    doc += body
    doc += "</OpenDRIVE>"
    if not pretty:
        doc = doc.replace(">\n    ", ">").replace("\n  ", " ").replace("\n", "")
    p = tmp_path / name
    p.write_text(doc, encoding="utf-8")
    return p


ROAD_BODY = (
    _road(2, succ=("junction", "5", "start")) + _road(1, pred=("road", "2", "start")) + _junction(5)
)


class TestCanonicalNormalization:
    def test_version_pin(self):
        assert NORMALIZATION_VERSION == "rq1-xodr-normalization/v1"

    def test_formatting_only_differences_normalize_identically(self, tmp_path):
        a = write_xodr(tmp_path, "a.xodr", ROAD_BODY, date="Mon Jan 01 00:00:00 2024")
        b = write_xodr(
            tmp_path, "b.xodr", ROAD_BODY, date="Tue Feb 02 03:04:05 2025",
            pretty=False, comment="LAST COMMIT",
        )
        assert normalize_xodr(a)["sha256"] == normalize_xodr(b)["sha256"]
        # proof that the RAW bytes actually differ
        assert normalize_xodr(a)["raw_sha256"] != normalize_xodr(b)["raw_sha256"]

    def test_lane_topology_change_changes_normalized_identity(self, tmp_path):
        a = write_xodr(tmp_path, "a.xodr", ROAD_BODY)
        changed = (
            _road(2, succ=("junction", "5", "start"))
            + _road(1)  # predecessor link removed (topology change)
            + _junction(5)
        )
        b = write_xodr(tmp_path, "b.xodr", changed, date="Mon Jan 01 00:00:00 2024")
        assert normalize_xodr(a)["sha256"] != normalize_xodr(b)["sha256"]

    def test_geometry_change_changes_normalized_identity(self, tmp_path):
        a = write_xodr(tmp_path, "a.xodr", ROAD_BODY)
        b = write_xodr(tmp_path, "b.xodr", _road(2, succ=("junction", "5", "start"), x="100.1")
                       + _road(1, pred=("road", "2", "start")) + _junction(5))
        assert normalize_xodr(a)["sha256"] != normalize_xodr(b)["sha256"]

    def test_lane_width_change_changes_normalized_identity(self, tmp_path):
        a = write_xodr(tmp_path, "a.xodr", ROAD_BODY)
        b = write_xodr(
            tmp_path, "b.xodr",
            _road(2, succ=("junction", "5", "start"), width_d="0.5")
            + _road(1, pred=("road", "2", "start")) + _junction(5),
        )
        assert normalize_xodr(a)["sha256"] != normalize_xodr(b)["sha256"]

    def test_road_order_normalization(self, tmp_path):
        a = write_xodr(
            tmp_path, "a.xodr",
            _road(2, succ=("junction", "5", "start")) + _road(1, pred=("road", "2", "start")) + _junction(5),
        )
        b = write_xodr(
            tmp_path, "b.xodr",
            _road(1, pred=("road", "2", "start")) + _road(2, succ=("junction", "5", "start")) + _junction(5),
        )
        assert normalize_xodr(a)["sha256"] == normalize_xodr(b)["sha256"]

    def test_unknown_header_fields_never_normalized_away(self, tmp_path):
        a = write_xodr(tmp_path, "a.xodr", ROAD_BODY)
        # custom attribute preserved: removing is never allowed
        doc = (tmp_path / "a.xodr").read_text(encoding="utf-8")
        doc2 = doc.replace('west="0.0"', 'west="0.0" vendorNote="keepme"')
        b = tmp_path / "c.xodr"
        b.write_text(doc2, encoding="utf-8")
        assert "vendorNote" not in (tmp_path / "a.xodr").read_text(encoding="utf-8")
        # normalization must not silently drop the unknown attribute: the
        # canonical hash differs from the base one (preservation, not eats)
        assert normalize_xodr(a)["sha256"] != normalize_xodr(b)["sha256"]


class TestStructuralSignature:
    def test_version_pin(self):
        assert STRUCTURAL_SIGNATURE_VERSION == "rq1-structural-signature/v1"

    def test_semantic_equivalent_serializations_same_signature(self, tmp_path):
        a = write_xodr(tmp_path, "a.xodr", ROAD_BODY, date="D1")
        b = write_xodr(tmp_path, "b.xodr", ROAD_BODY, date="D2", pretty=False,
                       comment="serialization difference")
        assert (
            compute_structural_signature(a)["sha256"]
            == compute_structural_signature(b)["sha256"]
        )

    def test_road_count_change_detected(self, tmp_path):
        a = write_xodr(tmp_path, "a.xodr", ROAD_BODY)
        b = write_xodr(
            tmp_path, "b.xodr",
            _road(2, succ=("junction", "5", "start")) + _road(1, pred=("road", "2", "start"))
            + _road(7) + _junction(5),
        )
        sig_a, sig_b = compute_structural_signature(a), compute_structural_signature(b)
        assert sig_a["road_count"] + 1 == sig_b["road_count"]
        assert sig_a["sha256"] != sig_b["sha256"]

    def test_lane_topology_mutation_detected(self, tmp_path):
        a = write_xodr(tmp_path, "a.xodr", ROAD_BODY)
        b = write_xodr(
            tmp_path, "b.xodr",
            _road(2, succ=("junction", "5", "start")) + _road(1, pred=("road", "3", "end"))
            + _junction(5),
        )
        assert (
            compute_structural_signature(a)["sha256"]
            != compute_structural_signature(b)["sha256"]
        )

    def test_lane_section_change_detected(self, tmp_path):
        a = write_xodr(tmp_path, "a.xodr", ROAD_BODY)
        b = write_xodr(
            tmp_path, "b.xodr",
            _road(2, succ=("junction", "5", "start"), sections=2)
            + _road(1, pred=("road", "2", "start")) + _junction(5),
        )
        assert (
            compute_structural_signature(a)["sha256"]
            != compute_structural_signature(b)["sha256"]
        )

    def test_lane_width_mutation_detected(self, tmp_path):
        a = write_xodr(tmp_path, "a.xodr", ROAD_BODY)
        b = write_xodr(
            tmp_path, "b.xodr",
            _road(2, succ=("junction", "5", "start"), width_d="0.9")
            + _road(1, pred=("road", "2", "start")) + _junction(5),
        )
        assert (
            compute_structural_signature(a)["sha256"]
            != compute_structural_signature(b)["sha256"]
        )


# ---------------------------------------------------------------------------
# hermetic environment whitelist
# ---------------------------------------------------------------------------
from tools.rq1b_five_run_driver import GOVERNED_VARS, SYSTEM_WHITELIST, build_child_env


class TestEnvironmentWhitelist:
    def test_arbitrary_overrides_cannot_leak(self, tmp_path, monkeypatch):
        poison = {
            "UP_OUTPUT_DIR": "/evil/out",
            "UP_CITY_NAME": "Town10HD",
            "UP_ENABLE_MUTATIONS": "1",
            "UP_ALLOW_NETWORK_FALLBACK": "1",
            "UP_CACHE_DIR": "/evil/cache",
            "UP_TMPDIR_OVERRIDE": "/evil/tmp",
            "UP_MANUAL_TILES_DIR": "/evil/tiles",
            "HOME": "/evil/home",
            "PYTHONPATH": "/evil/site-packages",
        }
        for k, v in poison.items():
            monkeypatch.setenv(k, v)
        env = build_child_env(tmp_path, 3)
        for k in poison:
            assert k not in env, f"{k} leaked into the child env"

    def test_governed_var_values_always_pinned(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UP_OSM_FILE", "/evil/other.osm")
        monkeypatch.setenv("UP_RUN_TAG", "attacker_tag")
        env = build_child_env(tmp_path, 3)
        assert env["UP_OSM_FILE"].endswith("ingolstadt_authoritative.osm")
        assert env["UP_RUN_TAG"] == "rq1b_run03"

    def test_governed_pins_explicit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UP_OSM_FILE", "/evil/other.osm")
        env = build_child_env(tmp_path, 0)
        assert env["UP_OSM_FILE"].endswith("ingolstadt_authoritative.osm")
        assert env["UP_PINNED_BUILDINGS_SOURCE"].endswith("ingolstadt_buildings_overpass.json")
        assert env["UP_DISABLE_OSM_DOWNLOAD"] == "1"
        assert env["UP_OFFLINE_ONLY"] == "1"
        assert env["UP_CARLA_SAFE_MODE"] == "1"
        assert env["UP_RELEASE_PROFILE"] == "DEVELOPMENT"
        assert env["UP_RUN_TAG"] == "rq1b_run00"
        assert env["PYTHONHASHSEED"] == "0"
        assert env["PYTHONPYCACHEPREFIX"] == str(tmp_path / "pycache")
        assert env["TEMP"] == str(tmp_path / "tmp")
        assert env["TMP"] == str(tmp_path / "tmp")

    def test_no_alternate_map_or_city_or_network_flag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UP_MAP", "Grid0821")
        monkeypatch.setenv("UP_DISABLE_OFFLINE", "1")
        monkeypatch.setenv("UP_OVERRIDE_SOURCE_INPUT", "x")
        env = build_child_env(tmp_path, 1)
        assert "UP_MAP" not in env
        assert "UP_DISABLE_OFFLINE" not in env
        assert "UP_OVERRIDE_SOURCE_INPUT" not in env


# ---------------------------------------------------------------------------
# child failure propagation (RQ1B exit code)
# ---------------------------------------------------------------------------
import tools.rq1b_full_pipeline as rq1b_mod


class TestChildFailurePropagation:
    def test_pipeline_failure_exits_nonzero_but_writes_failed_receipt(self, tmp_path, monkeypatch):
        class Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("governed failure for regression test")

        monkeypatch.setattr(rq1b_mod, "MainPipeline", Boom)
        monkeypatch.setattr(sys, "argv", ["prog", "9", str(tmp_path)])
        rc = rq1b_mod.main()
        assert rc == 1
        receipt_path = tmp_path / "run_09" / "rq1b_run_09_receipt.json"
        assert receipt_path.is_file()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["status"] == "FAILED"
        assert "governed failure" in receipt["error"]

    def test_unverified_pin_exits_nonzero(self, tmp_path, monkeypatch):
        def fail():
            raise RuntimeError("pin verify failure")

        monkeypatch.setattr(
            rq1b_mod, "verify_pinned_map",
            lambda *a, **k: {"verification_status": "DRIFT"},
        )
        monkeypatch.setattr(sys, "argv", ["prog", "0", str(tmp_path)])
        rc = rq1b_mod.main()
        assert rc != 0


# ---------------------------------------------------------------------------
# RQ2 pinned pair identity
# ---------------------------------------------------------------------------
from ultimate_pipeline.carla_tools.map_registry import PINNED_MAP_REGISTRY

HIST_AUTO_SHA = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"
HIST_MANUAL_SHA = "5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c"


class TestRQ2PinnedPairIdentity:
    def test_auto_pin_is_historical_map_of_record(self):
        entry = PINNED_MAP_REGISTRY["auto_map_of_record"]
        assert entry["sha256"] == HIST_AUTO_SHA
        assert entry["bytes"] == 149799632

    def test_manual_pin_is_pinned_grid0828(self):
        entry = PINNED_MAP_REGISTRY["manual_grid0828"]
        assert entry["sha256"] == HIST_MANUAL_SHA
        assert entry["bytes"] == 66530869
        assert entry["path"].endswith("source/manual/Grid0828.xodr")

    def test_replay_tool_pins_constants_match_registry(self):
        import tools.rq2_current_replay as replay

        assert replay.HISTORICAL_AUTO_SHA == PINNED_MAP_REGISTRY["auto_map_of_record"]["sha256"]
        assert replay.HISTORICAL_MANUAL_SHA == PINNED_MAP_REGISTRY["manual_grid0828"]["sha256"]
        assert replay.HISTORICAL_VALIDATION_PATH.is_file()
        assert replay.FROZEN_ORACLE_PATH.is_file()
