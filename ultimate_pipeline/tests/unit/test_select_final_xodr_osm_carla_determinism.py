# ultimate_pipeline/tools/check_osm_to_carla_determinism.py::_select_final_xodr() --
# live via generate_n_runs.py (invoked as a subprocess to produce
# determinism_report.json). Zero prior test coverage.
#
# Already correctly prefers a "semantic" 08_final*.xodr variant. But its
# fallback (used only when no semantic variant exists at all -- e.g. that
# copy step failed) fell straight through to the lexicographically-first
# 08_final*.xodr, which would pick the stale pre-repair file over a
# *_laneSectionFixed.xodr repair output if that repair variant existed but
# no semantic copy did. Same defect class as
# artifact_locator.py::find_final_xodr() (fixed @a341f0e3). Fixed to also
# recognize "laneSectionFixed" as an authoritative marker before falling
# all the way back to the first (arbitrary) match.
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.tools.check_osm_to_carla_determinism import _select_final_xodr


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_prefers_semantic_variant(tmp_path: Path):
    _write(tmp_path / "08_final_X.xodr", "pre-repair")
    _write(tmp_path / "08_final_X_semantic.xodr", "semantic")
    _write(tmp_path / "08_final_X_laneSectionFixed.xodr", "fixed")

    result, finals = _select_final_xodr(tmp_path)

    assert result.read_text(encoding="utf-8") == "semantic"
    assert len(finals) == 3


def test_falls_back_to_lanesectionfixed_when_no_semantic_variant(tmp_path: Path):
    _write(tmp_path / "08_final_X.xodr", "pre-repair (stale)")
    _write(tmp_path / "08_final_X_laneSectionFixed.xodr", "AUTHORITATIVE (repaired)")

    result, _finals = _select_final_xodr(tmp_path)

    assert result.read_text(encoding="utf-8") == "AUTHORITATIVE (repaired)"


def test_falls_back_to_first_match_when_only_plain_variant_exists(tmp_path: Path):
    _write(tmp_path / "08_final_X.xodr", "only plain")

    result, _finals = _select_final_xodr(tmp_path)

    assert result.read_text(encoding="utf-8") == "only plain"


def test_no_candidates_returns_none(tmp_path: Path):
    result, finals = _select_final_xodr(tmp_path)

    assert result is None
    assert finals == []
