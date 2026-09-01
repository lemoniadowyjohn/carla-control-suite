# ultimate_pipeline/tools/stage_gate_regression.py -- confirmed dead-to-pipeline
# (zero real imports, only a string-literal mention in an old planning
# script) but a human-runnable diagnostic CLI
# (`python -m ultimate_pipeline.tools.stage_gate_regression`) that runs
# real quality gates against each pipeline stage's XODR output, including
# "08_final". Same bug class already found and fixed in
# artifact_locator.py::find_final_xodr() (see
# test_artifact_locator_final_xodr.py): _find_stage_xodr() used plain
# `sorted(glob(f"{prefix}*.xodr"))[0]` -- lexicographic, so for the
# "08_final" prefix specifically (the only one with multiple real-world
# variants: plain/semantic/laneSectionFixed) it always picked the stale
# pre-repair file, meaning this tool's quality-gate check for the "08_final"
# stage always evaluated the wrong map -- the exact one the repair step
# exists to supersede because it can trip CARLA MapBuilder.cpp asserts.
# Fixed to mtime-newest, matching the already-established convention.
from __future__ import annotations

import time
from pathlib import Path

from ultimate_pipeline.tools.stage_gate_regression import _find_stage_xodr


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_08_final_prefix_picks_newest_not_lexicographically_first(tmp_path: Path):
    _write(tmp_path / "08_final_X.xodr", "PRE-REPAIR (stale)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_semantic.xodr", "PRE-REPAIR (stale copy)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_laneSectionFixed.xodr", "AUTHORITATIVE (repaired)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_semantic.xodr", "AUTHORITATIVE (repaired, refreshed copy)")

    result = _find_stage_xodr(tmp_path, "08_final")

    assert result.read_text(encoding="utf-8") == "AUTHORITATIVE (repaired, refreshed copy)"


def test_single_candidate_prefix_still_works(tmp_path: Path):
    _write(tmp_path / "03_topology_20260101.xodr", "topology output")

    result = _find_stage_xodr(tmp_path, "03_topology")

    assert result.read_text(encoding="utf-8") == "topology output"


def test_no_matching_candidate_returns_none(tmp_path: Path):
    result = _find_stage_xodr(tmp_path, "08_final")

    assert result is None
