# -*- coding: utf-8 -*-
"""Tests for the SUMO-repair None-handling branch in
ultimate_pipeline/pipeline_stages/stage_02_topology_semantics.py's
_step2_topology_semantics().

The bug: `sumo_fixed_path = str(sumo_fixed_result)` ran BEFORE
`if sumo_fixed_path is None:`. str(None) is the 4-character string
"None", never the None object, so the None-check could never fire
regardless of what SUMORepair.repair() actually returns -- the intended
"fall back to the sanitized file" path was structurally unreachable.

Confirmed SUMORepair.repair()'s real implementation never actually
returns None today (every code path returns a RepairResult, a str
subclass) -- not currently exploitable -- but this is still a genuinely
broken safety net (checking the wrong value, post-transformation) that
would silently mishandle a None return from any future/alternate
implementation. Fixed to check sumo_fixed_result (the raw return value)
before any str() coercion, matching this session's established pattern
of fixing defense-in-depth gaps even when not currently exploited.

This function has a very large dependency surface (georeference
handling, provenance writing, CRS comparability, junction repair,
topology linting, structure scanning, semantic verification) -- this
test mocks all of it except what's needed to exercise the SUMO-repair
branch specifically, then short-circuits immediately after via a marker
exception raised from the very next call (load_xodr on sumo_fixed_path),
capturing what path was actually passed.
"""
from __future__ import annotations

from unittest import mock

import pytest

import ultimate_pipeline.pipeline_stages.stage_02_topology_semantics as stage_mod


class _StopHere(Exception):
    """Raised to short-circuit the function once we've captured what we need."""


def _run_step2_and_capture_post_sumo_path(sumo_repair_return_value, out_dir):
    calls = {}

    def _fake_load_xodr(path):
        if "sanitized" not in calls:
            calls["sanitized"] = path
            return ("fake_tree", "fake_root")
        # Second call is `load_xodr(sumo_fixed_path)` -- capture and stop.
        calls["post_sumo_path"] = path
        raise _StopHere()

    fake_settings = mock.Mock()
    out_dir_str = str(out_dir)
    fake_settings.INPUT_XODR = "input.xodr"
    fake_settings.COORDINATES_JSON = "coords.json"
    fake_settings.ENABLE_SUMO_REPAIR = True
    fake_settings.QA_AUTOVIS = False
    fake_settings.output_dir.return_value = out_dir_str
    fake_settings.logs_dir.return_value = out_dir_str

    fake_self = mock.Mock()
    fake_self.settings = fake_settings
    fake_self.vreport = mock.Mock()
    fake_self.out_dir = out_dir_str
    fake_self._write_crs_comparability.return_value = None

    import os as real_os

    patches = {
        "load_xodr": _fake_load_xodr,
        "check_original_has_valid_georeference": lambda p: True,
        "handle_georeference": lambda root, policy: {"action": "kept", "reason": "test"},
        "save_xodr": lambda tree, path: None,
        "write_georeference_provenance": lambda **kw: "provenance.json",
        "TopologyLinter": mock.Mock(run=mock.Mock()),
        "SUMORepair": mock.Mock(repair=mock.Mock(return_value=sumo_repair_return_value)),
        # Real os.path.join (not mocked) -- the function does a real
        # `open(sumo_meta_path, "w")` write, which must land inside the
        # tmp_path-based out_dir, never the actual repo working directory.
        "os": mock.Mock(path=real_os.path, makedirs=real_os.makedirs),
        "json": mock.Mock(),
    }

    with mock.patch.multiple(stage_mod, create=True, **patches), mock.patch(
        "ultimate_pipeline.topology.missing_junction_link_repair.repair_missing_junction_links",
        return_value={"num_removed": 0, "num_roads_affected": 0, "missing_junction_ids_referenced": []},
    ):
        try:
            stage_mod._step2_topology_semantics(fake_self, "sanitized.xodr", "sumo_fixed.xodr")
        except _StopHere:
            pass

    return calls.get("post_sumo_path")


def test_sumo_repair_none_result_falls_back_to_sanitized_path(tmp_path):
    path = _run_step2_and_capture_post_sumo_path(None, tmp_path)
    assert path == "sanitized.xodr", (
        "when SUMORepair.repair() signals failure via None, the pipeline "
        "must fall back to the sanitized input, not pass the literal "
        "string 'None' downstream as if it were a real file path"
    )


def test_sumo_repair_real_result_is_used_as_is(tmp_path):
    fake_result = mock.Mock()
    fake_result.__str__ = mock.Mock(return_value="sumo_fixed.xodr")
    path = _run_step2_and_capture_post_sumo_path(fake_result, tmp_path)
    assert path == "sumo_fixed.xodr"
