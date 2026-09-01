# ultimate_pipeline/tools/carla_smoke_suite.py::_find_xodr_in_run() -- live
# via a direct subprocess call from main_pipeline.py itself (a CARLA
# smoke-test step), plus tools/run_experiments.py and
# tools/run_thesis_final_experiments.py. Zero prior test coverage.
#
# Same defect class as artifact_locator.py::find_xodr_artifact() (fixed
# @a341f0e3, both were near-identical: [tile_0_0] + sorted(glob(
# "08_final*.xodr")) + sorted(rglob("*.xodr")), first-existing-wins).
# Lexicographic sort of 08_final*.xodr candidates always picked the stale
# pre-repair file ("." < "_" in ASCII) over the semantic/laneSectionFixed
# repair output -- directly relevant here since this IS a CARLA smoke
# test, and the repair step exists specifically to prevent CARLA
# MapBuilder.cpp asserts on load. Fixed to mtime-newest.
from __future__ import annotations

import time
from pathlib import Path

from ultimate_pipeline.tools.carla_smoke_suite import _find_xodr_in_run


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_prefers_tile_0_0_over_08_final(tmp_path: Path):
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir()
    _write(tiles_dir / "tile_0_0.xodr", "tile map")
    _write(tmp_path / "08_final_X_semantic.xodr", "authoritative final")

    result, _src = _find_xodr_in_run(tmp_path)

    assert result.read_text(encoding="utf-8") == "tile map"


def test_picks_newest_08_final_variant_not_lexicographically_first(tmp_path: Path):
    _write(tmp_path / "08_final_X.xodr", "PRE-REPAIR (stale)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_semantic.xodr", "PRE-REPAIR (stale copy)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_laneSectionFixed.xodr", "AUTHORITATIVE (repaired)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_semantic.xodr", "AUTHORITATIVE (repaired, refreshed copy)")

    result, _src = _find_xodr_in_run(tmp_path)

    assert result.read_text(encoding="utf-8") == "AUTHORITATIVE (repaired, refreshed copy)"


def test_falls_back_to_any_xodr_when_no_tile_or_08_final(tmp_path: Path):
    nested = tmp_path / "misc"
    nested.mkdir()
    _write(nested / "something.xodr", "fallback map")

    result, _src = _find_xodr_in_run(tmp_path)

    assert result.read_text(encoding="utf-8") == "fallback map"


def test_no_xodr_at_all_returns_not_found(tmp_path: Path):
    result, src = _find_xodr_in_run(tmp_path)

    assert result is None
    assert src == "not_found"
