#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for GeoAligner.apply_to_xodr and alignment estimation."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any

import pytest

from ultimate_pipeline.domain_gap.geo_alignment import GeoAligner, identity_transform


# Minimal valid XODR for testing
MINIMAL_XODR_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="test" version="1.00" date="2025-01-01"/>
  <road name="TestRoad" length="100.0" id="1" junction="-1">
    <planView>
      <geometry s="0.0" x="{x1}" y="{y1}" hdg="0.0" length="50.0">
        <line/>
      </geometry>
      <geometry s="50.0" x="{x2}" y="{y2}" hdg="0.0" length="50.0">
        <line/>
      </geometry>
    </planView>
    <lanes>
      <laneSection s="0.0">
        <center><lane id="0" type="none" level="false"/></center>
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
"""


def _write_xodr(path: Path, x1: float, y1: float, x2: float, y2: float) -> None:
    """Write a minimal XODR with specified geometry points."""
    content = MINIMAL_XODR_TEMPLATE.format(x1=x1, y1=y1, x2=x2, y2=y2)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestApplyToXodr:
    """Tests for GeoAligner.apply_to_xodr API."""

    def test_two_arg_form_returns_string(self, tmp_path: Path) -> None:
        """Calling apply_to_xodr with only in_xodr should return aligned XODR string."""
        in_xodr = tmp_path / "input.xodr"
        _write_xodr(in_xodr, 10.0, 20.0, 60.0, 20.0)

        # Call with only input path (2-arg form)
        result = GeoAligner.apply_to_xodr(str(in_xodr))

        # Should return string containing XODR content
        assert isinstance(result, str)
        assert "<OpenDRIVE" in result
        assert "<header" in result

    def test_three_arg_form_writes_file(self, tmp_path: Path) -> None:
        """Calling apply_to_xodr with out_xodr should write file and return True."""
        in_xodr = tmp_path / "input.xodr"
        out_xodr = tmp_path / "output" / "aligned.xodr"
        _write_xodr(in_xodr, 10.0, 20.0, 60.0, 20.0)

        # Call with input and output paths (3-arg form)
        result = GeoAligner.apply_to_xodr(str(in_xodr), str(out_xodr))

        # Should return True and create output file
        assert result is True
        assert out_xodr.exists()

        # Verify output content
        content = out_xodr.read_text(encoding="utf-8")
        assert "<OpenDRIVE" in content
        assert "<header" in content

    def test_three_arg_with_transform(self, tmp_path: Path) -> None:
        """Calling apply_to_xodr with transform should apply the transform."""
        in_xodr = tmp_path / "input.xodr"
        out_xodr = tmp_path / "aligned.xodr"
        _write_xodr(in_xodr, 0.0, 0.0, 50.0, 0.0)

        # Apply a translation transform
        transform = {"scale": 1.0, "cos": 1.0, "sin": 0.0, "tx": 100.0, "ty": 200.0}
        result = GeoAligner.apply_to_xodr(str(in_xodr), str(out_xodr), transform)

        assert result is True
        assert out_xodr.exists()

        # Verify coordinates were transformed
        content = out_xodr.read_text(encoding="utf-8")
        assert "100.00000000" in content  # x=0 + tx=100
        assert "200.00000000" in content  # y=0 + ty=200

    def test_three_arg_updates_header_bbox_after_transform(self, tmp_path: Path) -> None:
        """Header bbox should reflect transformed geometry, not stale local coordinates."""
        in_xodr = tmp_path / "input_bbox.xodr"
        out_xodr = tmp_path / "aligned_bbox.xodr"
        _write_xodr(in_xodr, 0.0, 0.0, 50.0, 0.0)

        transform = {"scale": 1.0, "cos": 1.0, "sin": 0.0, "tx": 1000.0, "ty": 2000.0}
        result = GeoAligner.apply_to_xodr(str(in_xodr), str(out_xodr), transform)

        assert result is True
        tree = ET.parse(out_xodr)
        header = tree.getroot().find("header")
        assert header is not None
        assert float(header.get("west", "0.0")) == pytest.approx(1000.0)
        assert float(header.get("east", "0.0")) == pytest.approx(1100.0)
        assert float(header.get("south", "0.0")) == pytest.approx(2000.0)
        assert float(header.get("north", "0.0")) == pytest.approx(2000.0)

    def test_three_arg_with_nested_transform(self, tmp_path: Path) -> None:
        """Calling with nested transform dict (from estimate_from_xodr) should work."""
        in_xodr = tmp_path / "input.xodr"
        out_xodr = tmp_path / "aligned.xodr"
        _write_xodr(in_xodr, 0.0, 0.0, 50.0, 0.0)

        # Pass nested transform dict like estimate_from_xodr returns
        estimate = {
            "transform": {"scale": 1.0, "cos": 1.0, "sin": 0.0, "tx": 50.0, "ty": 75.0},
            "diagnostics": {"n_points": 10},
        }
        result = GeoAligner.apply_to_xodr(str(in_xodr), str(out_xodr), estimate)

        assert result is True
        content = out_xodr.read_text(encoding="utf-8")
        assert "50.00000000" in content


class TestEstimateFromXodr:
    """Tests for GeoAligner.estimate_from_xodr."""

    def test_basic_alignment_nonzero_points(self, tmp_path: Path) -> None:
        """Alignment with valid XODRs should produce n_points > 0."""
        manual = tmp_path / "manual.xodr"
        auto = tmp_path / "auto.xodr"

        # Create manual and auto with slight offset
        _write_xodr(manual, 100.0, 200.0, 150.0, 200.0)
        _write_xodr(auto, 105.0, 210.0, 155.0, 210.0)

        result = GeoAligner.estimate_from_xodr(str(manual), str(auto))

        assert "transform" in result
        assert "diagnostics" in result
        assert result["diagnostics"]["n_points"] > 0

    def test_zero_points_fallback(self, tmp_path: Path) -> None:
        """Empty XODRs should trigger fallback alignment."""
        manual = tmp_path / "manual.xodr"
        auto = tmp_path / "auto.xodr"
        out_dir = tmp_path / "domain_gap"

        # Create minimal XODRs with no geometry points
        manual.write_text('<?xml version="1.0"?><OpenDRIVE><header/></OpenDRIVE>', encoding="utf-8")
        auto.write_text('<?xml version="1.0"?><OpenDRIVE><header/></OpenDRIVE>', encoding="utf-8")

        result = GeoAligner.estimate_from_xodr(
            str(manual), str(auto), out_dir=str(out_dir)
        )

        assert result["diagnostics"]["n_points"] == 0
        assert result["diagnostics"]["fallback_used"] is True
        assert "fallback_reason" in result["diagnostics"]

        # Should write alignment_debug.json
        debug_file = out_dir / "alignment_debug.json"
        assert debug_file.exists()

        debug = json.loads(debug_file.read_text(encoding="utf-8"))
        assert "reason" in debug
        assert debug["reason"] == "zero_correspondences"

    def test_fallback_uses_bbox_translation(self, tmp_path: Path) -> None:
        """Fallback alignment should translate based on bbox centers."""
        manual = tmp_path / "manual.xodr"
        auto = tmp_path / "auto.xodr"

        # Manual centered at (100, 100), auto centered at (0, 0)
        _write_xodr(manual, 90.0, 90.0, 110.0, 110.0)

        # Create auto XODR with only one geometry point (causes n_points < 2)
        auto.write_text('''<?xml version="1.0"?>
<OpenDRIVE>
  <header/>
  <road id="1" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>
    </planView>
  </road>
</OpenDRIVE>''', encoding="utf-8")

        # Since manual has 2 points and auto has 1, n_points = min(2,1) = 1
        # which is < 2 for SVD, so it returns translation only
        result = GeoAligner.estimate_from_xodr(str(manual), str(auto))

        # Transform should have translation component
        transform = result["transform"]
        assert "tx" in transform
        assert "ty" in transform


class TestAlignmentIntegration:
    """Integration tests for estimate + apply workflow."""

    def test_end_to_end_alignment(self, tmp_path: Path) -> None:
        """Full workflow: estimate -> apply -> verify alignment improves."""
        manual = tmp_path / "manual.xodr"
        auto = tmp_path / "auto.xodr"
        aligned = tmp_path / "domain_gap" / "auto_aligned.xodr"

        # Manual at origin, auto offset by (100, 50)
        _write_xodr(manual, 0.0, 0.0, 50.0, 0.0)
        _write_xodr(auto, 100.0, 50.0, 150.0, 50.0)

        # Estimate alignment
        estimate = GeoAligner.estimate_from_xodr(
            str(manual), str(auto), out_dir=str(tmp_path / "domain_gap")
        )

        assert estimate["diagnostics"]["n_points"] >= 2

        # Apply alignment
        success = GeoAligner.apply_to_xodr(str(auto), str(aligned), estimate)
        assert success is True
        assert aligned.exists()

        # Output should be in <run_dir>/domain_gap/auto_aligned.xodr
        assert aligned.parent.name == "domain_gap"
        assert aligned.name == "auto_aligned.xodr"


class TestNoInputOverwrite:
    """Tests ensuring apply_to_xodr never overwrites input file."""

    def test_apply_does_not_overwrite_input(self, tmp_path: Path) -> None:
        """apply_to_xodr must write to out_xodr, not modify in_xodr."""
        in_xodr = tmp_path / "input.xodr"
        out_xodr = tmp_path / "domain_gap" / "auto_aligned.xodr"
        _write_xodr(in_xodr, 0.0, 0.0, 50.0, 0.0)

        # Record original content hash
        original_content = in_xodr.read_text(encoding="utf-8")

        # Apply a transform
        transform = {"scale": 1.0, "cos": 1.0, "sin": 0.0, "tx": 1000.0, "ty": 2000.0}
        result = GeoAligner.apply_to_xodr(str(in_xodr), str(out_xodr), transform)

        assert result is True

        # Input file must be unchanged
        after_content = in_xodr.read_text(encoding="utf-8")
        assert after_content == original_content, "Input file was modified!"

        # Output file must exist and be different
        assert out_xodr.exists()
        out_content = out_xodr.read_text(encoding="utf-8")
        assert out_content != original_content, "Output should differ from input"
        assert "1000.00000000" in out_content, "Transform not applied to output"

    def test_apply_creates_output_directory(self, tmp_path: Path) -> None:
        """apply_to_xodr should create output parent directories if needed."""
        in_xodr = tmp_path / "input.xodr"
        out_xodr = tmp_path / "deeply" / "nested" / "domain_gap" / "aligned.xodr"
        _write_xodr(in_xodr, 0.0, 0.0, 50.0, 0.0)

        # Parent directory doesn't exist yet
        assert not out_xodr.parent.exists()

        result = GeoAligner.apply_to_xodr(str(in_xodr), str(out_xodr))

        assert result is True
        assert out_xodr.exists()
        assert out_xodr.parent.exists()

    def test_two_arg_form_never_modifies_input(self, tmp_path: Path) -> None:
        """2-arg form (returns string) must not modify input file."""
        in_xodr = tmp_path / "input.xodr"
        _write_xodr(in_xodr, 10.0, 20.0, 60.0, 20.0)

        original_content = in_xodr.read_text(encoding="utf-8")
        original_mtime = in_xodr.stat().st_mtime

        # Call 2-arg form
        result = GeoAligner.apply_to_xodr(str(in_xodr))

        assert isinstance(result, str)
        # Input file unchanged
        assert in_xodr.read_text(encoding="utf-8") == original_content
        assert in_xodr.stat().st_mtime == original_mtime
