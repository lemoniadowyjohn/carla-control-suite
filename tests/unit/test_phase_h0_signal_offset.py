from __future__ import annotations

import math

import pytest

from ultimate_pipeline.tools.phase_h0_osm_signal_extract import (
    _project_native_to_planview_frame,
)


def test_project_native_to_planview_subtracts_header_offset_without_rotation() -> None:
    assert _project_native_to_planview_frame(
        110.0,
        220.0,
        {"x": 100.0, "y": 200.0, "hdg": 0.0},
    ) == pytest.approx((10.0, 20.0))


def test_project_native_to_planview_inverts_header_heading_rotation() -> None:
    # Forward offset convention rotates local (10, 0) by +90 deg, then translates.
    native_x = 100.0
    native_y = 210.0

    assert _project_native_to_planview_frame(
        native_x,
        native_y,
        {"x": 100.0, "y": 200.0, "hdg": math.pi / 2.0},
    ) == pytest.approx((10.0, 0.0), abs=1e-12)
