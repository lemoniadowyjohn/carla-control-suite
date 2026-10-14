"""Tests for O11 GAP-026 checker bias matrix."""
from __future__ import annotations

from tools.gap026_checker_bias_matrix import run_matrix


def test_matrix_has_analytical_cases():
    rows = {row["case"]: row for row in run_matrix()["rows"]}
    assert {"equal_width", "unequal_width", "lane_offset", "contact_start", "contact_end", "line_endpoint"} <= set(rows)
    assert rows["equal_width"]["status"] == "PASS"
    assert rows["contact_end"]["status"] == "PASS"


def test_lane_offset_gap_is_explicit():
    rows = {row["case"]: row for row in run_matrix()["rows"]}
    assert rows["lane_offset"]["expected_failed"] == 1
    assert rows["lane_offset"]["production_failed"] == 0
    assert rows["lane_offset"]["status"] == "INCONCLUSIVE"


def test_matrix_does_not_modify_checker():
    matrix = run_matrix()
    assert matrix["production_checker"].endswith("sanitize_junction_lane_links")
    assert "does not authorize checker implementation changes" in matrix["limitations"][0]
