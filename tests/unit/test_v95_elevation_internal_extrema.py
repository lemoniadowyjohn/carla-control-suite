"""Adversarial regression: continuous profiles can hide large peaks between samples.

Source base: PR #33 cf24666edae14943969c0f32d1266f5916a6e542.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.quality.check_elevation_seams import check_elevation_seams


def _map(tmp_path: Path, length: float, segments: list[tuple[float, float, float, float, float]]) -> Path:
    xml = "".join(
        f'<elevation s="{s}" a="{a}" b="{b}" c="{c}" d="{d}"/>'
        for s, a, b, c, d in segments
    )
    p = tmp_path / 'map.xodr'
    p.write_text(
        f'<OpenDRIVE><header revMajor="1" revMinor="6"/><road id="77" junction="-1" length="{length}">'
        f'<elevationProfile>{xml}</elevationProfile>'
        f'<planView><geometry s="0" x="0" y="0" hdg="0" length="{length}"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><center><lane id="0" type="none"/></center></laneSection></lanes>'
        '</road></OpenDRIVE>', encoding='utf-8'
    )
    return p


def test_single_quadratic_hidden_peak(tmp_path: Path) -> None:
    # z(s)=10s-2s^2 for 0 <=s <5, z(0)=z(5)=0, z(2.5)=12.5.
    p = _map(tmp_path, 10, [(0, 0, 10, -2, 0), (5, 0, 0, 0, 0)])
    rep = check_elevation_seams(str(p))
    assert rep['ok'] is False, rep
    assert rep['seam_stats']['max_jump'] >= 12.5
    assert rep['per_road']['77']['extrema_samples'] >= 1


def test_single_cubic_hidden_positive_and_negative_peaks(tmp_path: Path) -> None:
    # z = 0.4 * s * (s-5) * (s-10). At s=0,5,10, z=0.
    # Magnitude peaks near s=2.11 and 7.89, missed by the old 5m sampler.
    p = _map(tmp_path, 10, [(0, 0, 20, -6, 0.4)])
    rep = check_elevation_seams(str(p))
    assert rep['ok'] is False, rep
    assert rep['seam_stats']['max_jump'] > 10.0
    assert rep['per_road']['77']['extrema_samples'] == 2


def test_continuous_piecewise_linear_peak_at_boundary(tmp_path: Path) -> None:
    # z(0)=z(5)=z(10)=0, but peak at s=2.5 is 10m. This is not a polynomial jump.
    p = _map(tmp_path, 10, [(0, 0, 4, 0, 0), (2.5, 10, -4, 0, 0), (5, 0, 0, 0, 0)])
    rep = check_elevation_seams(str(p))
    assert rep['ok'] is False, rep
    assert rep['seam_stats']['max_jump'] >= 10.0
    assert rep['seam_stats']['max_boundary_jump'] == 0
    assert rep['per_road']['77']['extrema_samples'] == 0


def test_flat_profile_control_unchanged(tmp_path: Path) -> None:
    p = _map(tmp_path, 10, [(0, 0, 0, 0, 0)])
    rep = check_elevation_seams(str(p))
    assert rep['ok'] is True, rep
    assert rep['per_road']['77']['extrema_samples'] == 0
    assert rep['total_samples'] == 3


def test_smooth_low_grade_profile_control(tmp_path: Path) -> None:
    p = _map(tmp_path, 10, [(0, 2, 0.02, 0, 0)])
    rep = check_elevation_seams(str(p))
    assert rep['ok'] is True, rep
    assert rep['seam_stats']['max_jump'] == pytest.approx(0.1)
    assert rep['per_road']['77']['extrema_samples'] == 0


def test_negative_quadratic_hidden_valley(tmp_path: Path) -> None:
    p = _map(tmp_path, 10, [(0, 0, -10, 2, 0), (5, 0, 0, 0, 0)])
    rep = check_elevation_seams(str(p))
    assert rep['ok'] is False, rep
    assert rep['seam_stats']['max_jump'] >= 12.5


def test_nonzero_cubic_second_derivative_without_extremum_does_not_spuriously_fail(tmp_path: Path) -> None:
    p = _map(tmp_path, 10, [(0, 0, 0.01, 0, 0.00001)])
    rep = check_elevation_seams(str(p))
    assert rep['ok'] is True, rep
    assert rep['per_road']['77']['extrema_samples'] == 0


def test_extrema_inside_partial_interval_detected(tmp_path: Path) -> None:
    # z(s) = 8s-2s^2, 4m road with no internal 5m regular sample.
    p = _map(tmp_path, 4, [(0, 0, 8, -2, 0)])
    rep = check_elevation_seams(str(p))
    assert rep['ok'] is False, rep
    assert rep['seam_stats']['max_jump'] == pytest.approx(8.0)


def test_large_nonfinite_derivative_fails_closed(tmp_path: Path) -> None:
    p = _map(tmp_path, 10, [(0, 0, 1e308, 1e308, 1e308)])
    rep = check_elevation_seams(str(p))
    assert rep['ok'] is False, rep
    assert rep['invalid_roads']


def test_profile_boundary_overshoot_same_interval(tmp_path: Path) -> None:
    p = _map(tmp_path, 10, [(0, 0, 0, 0, 0), (2, 0, 0, 0, 0), (4, 0, 0, 0, 0)])
    assert check_elevation_seams(str(p))['ok'] is True
