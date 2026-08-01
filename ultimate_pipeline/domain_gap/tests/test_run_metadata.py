#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for domain gap run_metadata consistency."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# Minimal XODR for testing — must include geoReference so strict CRS mode does not hard-stop
MINIMAL_XODR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="test" north="5405000" south="5402000" east="682000" west="678000">
    <geoReference><![CDATA[+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs]]></geoReference>
  </header>
  <road name="TestRoad" length="100.0" id="1" junction="-1">
    <planView>
      <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="100.0"><line/></geometry>
    </planView>
    <lanes>
      <laneSection s="0.0">
        <center><lane id="0" type="none" level="false"/></center>
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0.0" a="3.5" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
"""


def test_run_metadata_records_resolved_paths(tmp_path: Path, monkeypatch) -> None:
    """Verify run_metadata.json records resolved paths when provided.

    The auto-tiler subprocess is mocked because the MINIMAL_XODR fixture road
    (100 m) is too short to produce spatial tiles; rc=6 would occur otherwise.
    The test's purpose is path-recording, not tiling correctness.
    """
    # Skip if dependencies not available
    pytest.importorskip("numpy")

    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    out_dir = tmp_path / "domain_gap"

    manual.write_text(MINIMAL_XODR, encoding="utf-8")
    auto.write_text(MINIMAL_XODR, encoding="utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Create a minimal fake tiles directory so the tiler mock has something to return
    fake_tiles = tmp_path / "fake_auto_tiles"
    fake_tiles.mkdir(parents=True, exist_ok=True)
    (fake_tiles / "tile_0_0.xodr").write_text(MINIMAL_XODR, encoding="utf-8")

    # Mock SETTINGS to avoid side effects
    monkeypatch.setenv("UP_DISABLE_INPUT_XODR_FALLBACK", "1")

    from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap

    # Mock the auto-tiler so the 100m MINIMAL_XODR road doesn't cause rc=6.
    # We patch at the module level so both call-sites in run_full_domain_gap use it.
    with patch(
        "ultimate_pipeline.run_full_domain_gap._auto_generate_tiles_from_xodr",
        return_value=str(fake_tiles),
    ):
        result = run_full_domain_gap(
            manual_xodr=str(manual),
            auto_xodr=str(auto),
            manual_tiles="",
            auto_tiles="",
            output_dir=str(out_dir),
            manual_missing=False,
        )

        # Check run_metadata.json
        meta_path = out_dir / "run_metadata.json"
        assert meta_path.exists(), "run_metadata.json should be created"

        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        # Verify manual_xodr_resolved is set and non-empty
        assert "manual_xodr_resolved" in meta
        assert meta["manual_xodr_resolved"], "manual_xodr_resolved should not be empty"
        assert str(manual.resolve()) in meta["manual_xodr_resolved"]

        # Verify auto_xodr_resolved is set
        assert "auto_xodr_resolved" in meta
        assert meta["auto_xodr_resolved"], "auto_xodr_resolved should not be empty"

        # Verify source is recorded
        assert "manual_xodr_source" in meta
        assert meta["manual_xodr_source"] != "none", "source should not be 'none' when path provided"
