# ultimate_pipeline/tools/compare_runs_determinism.py::_pick_final_xodr() --
# a thesis byte-determinism comparison tool (referenced in
# BYTE_DETERMINISM_SECONDARY_SOURCES_INVESTIGATION_20260828.md), zero prior
# test coverage. Same bug class as artifact_locator.py::find_final_xodr()
# (fixed @a341f0e3) in the fallback path: when no *_laneSectionFixed.xodr
# exists, `sorted(run_dir.glob("08_final*.xodr"))[0]` is lexicographic, so
# it would pick the stale pre-repair file over a semantic copy if the
# laneSectionFixed repair variant is ever absent (e.g. an older run
# format). Fixed to mtime-newest at both tiers.
from __future__ import annotations

import time
from pathlib import Path

import pytest

from ultimate_pipeline.tools.compare_runs_determinism import _pick_final_xodr


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_prefers_lanesectionfixed_over_plain_variants(tmp_path: Path):
    _write(tmp_path / "08_final_X.xodr", "PRE-REPAIR")
    _write(tmp_path / "08_final_X_semantic.xodr", "semantic copy")
    _write(tmp_path / "08_final_X_laneSectionFixed.xodr", "AUTHORITATIVE")

    result = _pick_final_xodr(tmp_path, None)

    assert result.read_text(encoding="utf-8") == "AUTHORITATIVE"


def test_fallback_picks_newest_not_lexicographically_first_when_no_lanesectionfixed(
    tmp_path: Path,
):
    _write(tmp_path / "08_final_X.xodr", "PRE-REPAIR (stale)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_semantic.xodr", "newest semantic")

    result = _pick_final_xodr(tmp_path, None)

    assert result.read_text(encoding="utf-8") == "newest semantic"


def test_override_path_relative_to_run_dir(tmp_path: Path):
    _write(tmp_path / "custom.xodr", "custom content")

    result = _pick_final_xodr(tmp_path, "custom.xodr")

    assert result.read_text(encoding="utf-8") == "custom content"


def test_override_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        _pick_final_xodr(tmp_path, "does_not_exist.xodr")


def test_no_xodr_at_all_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        _pick_final_xodr(tmp_path, None)
