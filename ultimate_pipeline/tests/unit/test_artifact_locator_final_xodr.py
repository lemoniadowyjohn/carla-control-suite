# ultimate_pipeline/tools/artifact_locator.py::find_final_xodr() -- live via
# run_thesis_experiments.py (the default `--xodr-mode final` path), which
# feeds the selected XODR into CARLA-importability smoke tests and real
# perception capture (run_perception_safe.py). Zero prior test coverage.
#
# Real bug: a genuine pipeline run (stage_08_integrity.py) writes THREE
# 08_final*.xodr variants in this exact order:
#   1. 08_final_<ts>.xodr             -- pre-repair (save_xodr)
#   2. 08_final_<ts>_semantic.xodr    -- copy of #1
#   3. 08_final_<ts>_laneSectionFixed.xodr -- "AUTHORITATIVE MAP SWITCH":
#      repair_and_assert_lane_section_successors() output, exists
#      specifically to prevent CARLA MapBuilder.cpp asserts on load
#   4. 08_final_<ts>_semantic.xodr    -- re-copied from #3 (refreshed)
#
# find_final_xodr() used plain `sorted(glob("08_final*.xodr"))[0]` --
# lexicographic, not preference- or mtime-ordered. "." (0x2E) < "_" (0x5F)
# in ASCII, so the PLAIN pre-repair file (#1) always sorts first and was
# always picked -- the exact file the repair step exists to supersede.
# Directly reproduced: with all 4 writes applied in the real order, pre-fix
# find_final_xodr() returned the file containing "PRE-REPAIR (stale)"
# instead of "AUTHORITATIVE (repaired)".
#
# Fixed to match the already-established, already-correct convention used
# elsewhere in the codebase (export_thesis_tables.py::_latest_final_xodr,
# run_determinism_audit.py::_find_final_xodr, generate_n_runs.py's explicit
# "prefer semantic" branch): prefer the newest *_semantic.xodr, falling
# back to the newest 08_final*.xodr of any kind.
from __future__ import annotations

import time
from pathlib import Path

from ultimate_pipeline.tools.artifact_locator import find_final_xodr, find_xodr_artifact


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_prefers_semantic_variant_over_plain_pre_repair_file(tmp_path: Path):
    """Direct regression test for the confirmed real-world scenario."""
    _write(tmp_path / "08_final_20260901T000000Z.xodr", "PRE-REPAIR (stale)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_20260901T000000Z_semantic.xodr", "PRE-REPAIR (stale copy)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_20260901T000000Z_laneSectionFixed.xodr", "AUTHORITATIVE (repaired)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_20260901T000000Z_semantic.xodr", "AUTHORITATIVE (repaired, refreshed copy)")

    result, source = find_final_xodr(tmp_path)

    assert result.read_text(encoding="utf-8") == "AUTHORITATIVE (repaired, refreshed copy)"
    assert source == "08_final"


def test_picks_newest_semantic_variant_when_multiple_semantic_files_exist(tmp_path: Path):
    _write(tmp_path / "08_final_A_semantic.xodr", "older semantic")
    time.sleep(0.02)
    _write(tmp_path / "08_final_B_semantic.xodr", "newer semantic")

    result, _source = find_final_xodr(tmp_path)

    assert result.read_text(encoding="utf-8") == "newer semantic"


def test_falls_back_to_newest_plain_final_when_no_semantic_variant_exists(tmp_path: Path):
    _write(tmp_path / "08_final_A.xodr", "older")
    time.sleep(0.02)
    _write(tmp_path / "08_final_B.xodr", "newer")

    result, source = find_final_xodr(tmp_path)

    assert result.read_text(encoding="utf-8") == "newer"
    assert source == "08_final"


def test_falls_back_to_find_xodr_artifact_when_no_08_final_files_exist(tmp_path: Path):
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir()
    _write(tiles_dir / "tile_0_0.xodr", "tile map")

    result, source = find_final_xodr(tmp_path)

    assert result.read_text(encoding="utf-8") == "tile map"
    assert source == "run_dir"


def test_no_xodr_at_all_returns_none(tmp_path: Path):
    result, source = find_final_xodr(tmp_path)

    assert result is None
    assert source == "not_found"


# ---------------------------------------------------------------------------
# find_xodr_artifact -- shares the same underlying fix (_newest_final_xodr)
# ---------------------------------------------------------------------------


def test_find_xodr_artifact_prefers_tile_over_08_final(tmp_path: Path):
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir()
    _write(tiles_dir / "tile_0_0.xodr", "tile map")
    _write(tmp_path / "08_final_A_semantic.xodr", "authoritative final")

    result, _source = find_xodr_artifact(tmp_path)

    assert result.read_text(encoding="utf-8") == "tile map"


def test_find_xodr_artifact_prefers_semantic_08_final_when_no_tile(tmp_path: Path):
    _write(tmp_path / "08_final_A.xodr", "PRE-REPAIR (stale)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_A_semantic.xodr", "AUTHORITATIVE")

    result, _source = find_xodr_artifact(tmp_path)

    assert result.read_text(encoding="utf-8") == "AUTHORITATIVE"
