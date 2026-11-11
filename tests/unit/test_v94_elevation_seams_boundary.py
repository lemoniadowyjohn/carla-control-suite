"""V94: failures the legacy 5 m-only seam sampler could not detect."""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.quality.check_elevation_seams import check_elevation_seams


def _xodr(tmp_path: Path, *, length: str = "10", elevations: str = '<elevation s="0" a="0" b="0" c="0" d="0"/>', root_tag: str = "OpenDRIVE") -> Path:
    p = tmp_path / "micro.xodr"
    p.write_text(
        f'<{root_tag}><road id="R" junction="-1" length="{length}">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        f'<elevationProfile>{elevations}</elevationProfile></road></{root_tag}>',
        encoding="utf-8",
    )
    return p


def test_unsampled_spike_at_two_internal_boundaries_fails(tmp_path: Path) -> None:
    # 0 at s=0, 8 at s=2, back to 0 at s=4; 5 m grid sees 0, 0, 0.
    p = _xodr(tmp_path, elevations=(
        '<elevation s="0" a="0" b="0" c="0" d="0"/>'
        '<elevation s="2" a="8" b="0" c="0" d="0"/>'
        '<elevation s="4" a="0" b="0" c="0" d="0"/>'
    ))
    rep = check_elevation_seams(str(p))
    assert rep["ok"] is False, rep
    assert rep["seam_stats"]["max_jump"] == 8.0
    assert rep["per_road"]["R"]["boundary_discontinuities"] >= 2


def test_sub_sampling_interval_road_includes_endpoint(tmp_path: Path) -> None:
    p = _xodr(tmp_path, length="3", elevations='<elevation s="0" a="0" b="2" c="0" d="0"/>')
    rep = check_elevation_seams(str(p))
    assert rep["ok"] is False, rep
    assert rep["seam_stats"]["max_jump"] == 6.0
    assert rep["per_road"]["R"]["samples"] == 2


def test_partial_final_interval_is_sampled(tmp_path: Path) -> None:
    # At 5m, z=0; between s=5 and 7, the smooth profile increases by 6m.
    p = _xodr(tmp_path, length="7", elevations=(
        '<elevation s="0" a="0" b="0" c="0" d="0"/>'
        '<elevation s="5" a="0" b="3" c="0" d="0"/>'
    ))
    rep = check_elevation_seams(str(p))
    assert rep["ok"] is False, rep
    assert rep["seam_stats"]["max_jump"] == 6.0
    assert rep["per_road"]["R"]["samples"] == 3


def test_nonfinite_profile_coefficient_fails_closed(tmp_path: Path) -> None:
    p = _xodr(tmp_path, elevations='<elevation s="0" a="nan" b="0" c="0" d="0"/>')
    rep = check_elevation_seams(str(p))
    assert rep["ok"] is False, rep
    assert rep["invalid_roads"]


def test_invalid_road_length_does_not_pass_as_empty_map(tmp_path: Path) -> None:
    p = _xodr(tmp_path, length="NaN")
    rep = check_elevation_seams(str(p))
    assert rep["ok"] is False, rep
    assert rep["invalid_roads"]


def test_empty_map_is_not_clean_by_vacuous_success(tmp_path: Path) -> None:
    p = tmp_path / "empty.xodr"
    p.write_text('<OpenDRIVE><header revMajor="1" revMinor="6"/></OpenDRIVE>', encoding="utf-8")
    rep = check_elevation_seams(str(p))
    assert rep["ok"] is False, rep
    assert rep["num_roads"] == 0


def test_invalid_sampling_parameter_fails_without_loop(tmp_path: Path) -> None:
    p = _xodr(tmp_path)
    rep = check_elevation_seams(str(p), sample_step_m=0)
    assert rep["ok"] is False, rep
    assert any("sample_step_m" in w for w in rep["warnings"])


def test_smooth_profile_is_not_falsely_rejected(tmp_path: Path) -> None:
    p = _xodr(tmp_path, length="7", elevations='<elevation s="0" a="1" b="0.1" c="0" d="0"/>')
    rep = check_elevation_seams(str(p))
    assert rep["ok"] is True, rep
    assert rep["total_samples"] == 3
    assert rep["seam_stats"]["max_jump"] < 1.0


def test_boundary_mutation_from_spike_to_continuous_passes(tmp_path: Path) -> None:
    p = _xodr(tmp_path, elevations=(
        '<elevation s="0" a="0" b="0" c="0" d="0"/>'
        '<elevation s="2" a="0" b="0" c="0" d="0"/>'
        '<elevation s="4" a="0" b="0" c="0" d="0"/>'
    ))
    rep = check_elevation_seams(str(p))
    assert rep["ok"] is True, rep
    assert rep["per_road"]["R"]["boundary_discontinuities"] == 0


def test_duplicate_segment_positions_fail_closed(tmp_path: Path) -> None:
    p = _xodr(tmp_path, elevations=(
        '<elevation s="0" a="0" b="0" c="0" d="0"/>'
        '<elevation s="0" a="0" b="0" c="0" d="0"/>'
    ))
    rep = check_elevation_seams(str(p))
    assert rep["ok"] is False, rep
    assert rep["invalid_roads"]
