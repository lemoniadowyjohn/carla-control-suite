# -*- coding: utf-8 -*-
"""Tests for the lane-width-invariants diagnostic log line in
ultimate_pipeline/pipeline_stages/stage_03_topology_repair.py's
_step3_topology_repair().

The bug: the printed line read
`_tot.get('missing_width_found', 0)` / `'missing_width_fixed'`, but
enforce_lane_width_invariants_on_root() (quality/lane_width_invariants.py)
actually returns totals keyed "missing_width_lanes_found" /
"missing_width_lanes_fixed" (with "_lanes_"). The mismatched key names
meant dict.get()'s default silently kicked in every time, so this
diagnostic line ALWAYS printed "found 0, fixed 0" regardless of the real
numbers -- purely a misleading log message (the actual repair, done
separately by enforce_lane_width_invariants itself, was unaffected;
this only broke what got printed about it).
"""
from __future__ import annotations

from unittest import mock

import ultimate_pipeline.pipeline_stages.stage_03_topology_repair as stage_mod


class _StopHere(Exception):
    pass


def test_lane_width_invariant_log_line_shows_real_counts(capsys, tmp_path):
    fake_settings = mock.Mock()
    fake_settings.ENABLE_CARLA_TEST_EARLY = True

    fake_self = mock.Mock()
    fake_self.settings = fake_settings
    fake_self.out_dir = str(tmp_path)
    fake_self._carla_isolation_enabled.side_effect = _StopHere()

    real_report = {
        "ok": True,
        "severity": "warn",
        "totals": {
            "missing_width_lanes_found": 7,
            "missing_width_lanes_fixed": 5,
            "missing_width_lanes_unfixed": 2,
        },
        "examples": [],
    }

    patches = {
        "load_xodr": lambda p: ("fake_tree", "fake_root"),
        "TopologyRepair": mock.Mock(run=mock.Mock()),
        "save_xodr": lambda tree, path: None,
        "MapPlotter": mock.Mock(save_preview=mock.Mock()),
        "default_report_path": lambda out_dir, stage: str(tmp_path / "report.json"),
        "enforce_lane_width_invariants": mock.Mock(return_value=real_report),
    }

    with mock.patch.multiple(stage_mod, create=True, **patches):
        try:
            stage_mod._step3_topology_repair(fake_self, "input.xodr", "topo_fixed.xodr")
        except _StopHere:
            pass

    out = capsys.readouterr().out
    assert "found 7, fixed 5" in out, (
        f"expected the real totals in the log line, got: {out!r}"
    )
    assert "found 0, fixed 0" not in out
