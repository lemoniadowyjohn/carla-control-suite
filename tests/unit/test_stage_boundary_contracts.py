# tests/unit/test_stage_boundary_contracts.py
# -*- coding: utf-8 -*-
"""P13/NEW-222: pipeline stage-boundary contracts (04->05 ... 09->10).

Observed-behavior tests: every downstream step is invoked with a MISSING
upstream artifact and must fail closed (raise) or leave an explicit SKIP
receipt -- never silently produce a downstream artifact. Tiling is the only
legitimate optional skip, and step-10 skips now always write a status
receipt (NEW-212 fix). There is no resume/skip-stage mechanism in
MainPipeline (verified: only an env escape hatch for the capability
contract, which logs), so resume-skipping is not applicable.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from ultimate_pipeline.pipeline_stages import (
    stage_04_enrichment,
    stage_05_geometry,
    stage_06_links,
    stage_07_lanes,
    stage_08_hygiene,
    stage_08_integrity,
    stage_09_positional_semantics,
    stage_09_tiling,
    stage_10_tile_qa,
)


def _fake_self(**settings_overrides):
    fake = mock.Mock()
    settings = mock.Mock()
    for key, value in settings_overrides.items():
        setattr(settings, key, value)
    fake.settings = settings
    fake.vreport = mock.Mock()
    fake.qgate = mock.Mock()
    fake.out_dir = "MISSING_OUTDIR"
    return fake


def test_04_missing_upstream_blocks():
    with pytest.raises(Exception):
        stage_04_enrichment._step4_enrichment(_fake_self(), "MISSING_TOPO.xodr")


def test_05a_missing_upstream_blocks():
    with pytest.raises(Exception):
        stage_05_geometry._step5_geometry_elevation_continuity(_fake_self(), "MISSING_TOPO.xodr")


def test_05b_strict_dem_blocks_without_silent_continuation(monkeypatch):
    monkeypatch.setenv("THESIS_STRICT", "1")
    monkeypatch.setenv("DEM_STRICT_MODE", "1")
    with pytest.raises(Exception):
        stage_05_geometry._step5_dem_and_geometry(_fake_self(), "MISSING_TOPO.xodr", "MISSING_ELEV.xodr")


def test_06_missing_upstream_blocks():
    with pytest.raises(FileNotFoundError):
        stage_06_links._step6_planview_continuity(
            _fake_self(), "MISSING_ELEV.xodr", "MISSING_GEO.xodr", "OUT.xodr")


def test_07_missing_upstream_blocks():
    with pytest.raises(FileNotFoundError):
        stage_07_lanes._step7_lanes_sidewalks(_fake_self(), "MISSING_CONT.xodr", "OUT.xodr")


def test_08h_missing_upstream_blocks_with_explicit_message():
    with pytest.raises(FileNotFoundError, match="map hygiene"):
        stage_08_hygiene._step8h_map_hygiene(_fake_self(), "MISSING_FINAL.xodr")


def test_08m_missing_upstream_blocks():
    with pytest.raises(FileNotFoundError):
        stage_08_integrity._step8_markings_and_integrity(_fake_self(), "MISSING_LANES.xodr", "OUT.xodr")


def test_09pos_missing_upstream_blocks():
    with pytest.raises(FileNotFoundError):
        stage_09_positional_semantics._step9_positional_semantics(_fake_self(), "MISSING_FINAL.xodr")


def test_09tiling_disabled_returns_none_without_inputs():
    assert stage_09_tiling._step9_tiling(
        _fake_self(ENABLE_TILING=False), "MISSING_FINAL.xodr") is None


def test_09tiling_enabled_missing_upstream_blocks():
    with pytest.raises(FileNotFoundError):
        stage_09_tiling._step9_tiling(
            _fake_self(ENABLE_TILING=True), "MISSING_FINAL.xodr")


def test_10_sim_gate_off_writes_skip_receipt(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    fake = _fake_self(ENABLE_SIMULATION_GATE=False)
    fake.out_dir = str(out)
    assert stage_10_tile_qa._step10_tile_qa(fake, None, "MISSING_FINAL.xodr") is None
    receipt = json.loads((out / "step10_tile_qa_status.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "SKIP"


def test_10_tiling_disabled_writes_skip_receipt(tmp_path, monkeypatch):
    out = tmp_path / "run"
    out.mkdir()
    monkeypatch.setenv("UP_DISABLE_CARLA", "1")
    fake = _fake_self(ENABLE_SIMULATION_GATE=True, ENABLE_TILING=False)
    fake.out_dir = str(out)
    assert stage_10_tile_qa._step10_tile_qa(fake, None, "MISSING_FINAL.xodr") is None
    receipt = json.loads((out / "step10_tile_qa_status.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "SKIP"


def test_10_tiles_missing_writes_skip_receipt(tmp_path, monkeypatch):
    out = tmp_path / "run"
    out.mkdir()
    monkeypatch.setenv("UP_DISABLE_CARLA", "1")
    fake = _fake_self(ENABLE_SIMULATION_GATE=True, ENABLE_TILING=True)
    fake.out_dir = str(out)
    assert stage_10_tile_qa._step10_tile_qa(fake, None, "MISSING_FINAL.xodr") is None
    receipt = json.loads((out / "step10_tile_qa_status.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "SKIP"
    assert receipt["reason"] in ("carla_disabled_env", "tiles_dir_missing")
