# -*- coding: utf-8 -*-
"""Tests for the per-tile gap extraction in
ultimate_pipeline/pipeline_stages/stage_12_domain_gap.py's
_step12_domain_gap().

The bug: `pt = combined_gap.get("per_tile_structural_gap", {})` is a dict
KEYED BY TILE NAME (per run_full_domain_gap.py's real
_combine_per_tile_structural_gap: {"tile_0_0.xodr": {"geometry": {...},
"curvature": {...}}, ...}) -- but the code did
`pt.get("geometry", {})` / `pt.get("curvature", {})`, treating pt as if
its TOP-LEVEL keys were "geometry"/"curvature" directly. Since no real
tile is ever named "geometry" or "curvature", this always evaluated to
the empty-dict default, so domain_gap_summary.json's
"per_tile_geometry_gap" and "per_tile_curvature_gap" fields were ALWAYS
empty regardless of how many tiles were actually compared.

No real domain_gap_summary.json artifact exists anywhere on disk for any
campaign (this stage has apparently never run to completion for a real
regen) -- RQ1's authoritative evidence comes from a separate, dedicated
C14_RQ1_STRUCTURAL_GAP/ path, not this main_pipeline.py orchestration
step -- so this bug has not corrupted any reported thesis number. Still
a real, provable defect in a step whose whole purpose is producing this
exact summary.
"""
from __future__ import annotations

import json
from unittest import mock

import ultimate_pipeline.pipeline_stages.stage_12_domain_gap as stage_mod


def _fake_combined_gap():
    return {
        "structural_domain_gap": {
            "geometry": {"gap": 0.1},
            "curvature": {"gap": 0.2},
            "intersection": {"gap": 0.3},
            "semantics": {"gap": 0.4},
            "road_classification": {"gap": 0.5},
            "connectivity": {"gap": 0.6},
        },
        "per_tile_structural_gap": {
            "tile_0_0.xodr": {"geometry": {"gap": 0.05}, "curvature": {"gap": 0.15}},
            "tile_0_1.xodr": {"geometry": {"gap": 0.08}, "curvature": {"gap": 0.12}},
        },
    }


def test_per_tile_geometry_and_curvature_gaps_are_extracted_per_tile(tmp_path):
    fake_settings = mock.Mock()
    fake_settings.ENABLE_DOMAIN_GAP = True
    fake_settings.MANUAL_MAP_XODR = str(tmp_path / "manual.xodr")
    fake_settings.MANUAL_REFERENCE_XODR = None
    fake_settings.MANUAL_TILES_DIR = None
    fake_settings.MANUAL_TILES_ROOT = None
    fake_settings.PERCEPTION_MANUAL_JSON = None
    fake_settings.PERCEPTION_AUTO_JSON = None
    fake_settings.DOMAIN_GAP_OUT_DIR = "domain_gap"
    (tmp_path / "manual.xodr").write_text("<OpenDRIVE/>", encoding="utf-8")

    fake_self = mock.Mock()
    fake_self.settings = fake_settings
    fake_self.out_dir = str(tmp_path)
    fake_self.vreport = mock.Mock()
    fake_self.vreport.data = {}
    del fake_self.artifact_recorder  # hasattr(...) must be False

    patches = {
        "os": __import__("os"),
        "json": __import__("json"),
        "Path": __import__("pathlib").Path,
        "TileMetadata": mock.Mock(),
        "run_full_domain_gap": mock.Mock(return_value=_fake_combined_gap()),
    }

    with mock.patch.multiple(stage_mod, create=True, **patches), mock.patch(
        "subprocess.run", return_value=mock.Mock(returncode=0)
    ):
        stage_mod._step12_domain_gap(fake_self, str(tmp_path / "auto.xodr"))

    summary_path = tmp_path / "domain_gap" / "domain_gap_summary.json"
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["per_tile_geometry_gap"] == {
        "tile_0_0.xodr": {"gap": 0.05},
        "tile_0_1.xodr": {"gap": 0.08},
    }, "per-tile geometry gap must be keyed by tile name with the real per-tile values"
    assert summary["per_tile_curvature_gap"] == {
        "tile_0_0.xodr": {"gap": 0.15},
        "tile_0_1.xodr": {"gap": 0.12},
    }, "per-tile curvature gap must be keyed by tile name with the real per-tile values"

    # Whole-map gaps (unaffected by this bug) still correctly pass through.
    assert summary["whole_geometry_gap"] == {"gap": 0.1}
    assert summary["whole_curvature_gap"] == {"gap": 0.2}
