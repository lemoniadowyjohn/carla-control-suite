from __future__ import annotations

import math

import pytest

from tests.opendrive_geometry.adapters import (
    NON_BUGGY_ADAPTERS,
    ADAPTER_CANONICAL,
    EvalResult,
)



def _check_returned(result, x, y, hdg, tol=1e-12):
    assert abs(result.x - x) < tol, f"x: {result.x} != {x}"
    assert abs(result.y - y) < tol, f"y: {result.y} != {y}"
    assert abs(result.hdg - hdg) < tol, f"hdg: {result.hdg} != {hdg}"


# Canonical evaluator raises GeometryOutOfRangeError for s<0 or s>length
class TestCanonicalStrictRange:
    def test_s_negative_raises(self):
        with pytest.raises(Exception):
            ADAPTER_CANONICAL.evaluate(0.0, 0.0, 0.0, 100.0, 0.0, -1.0)

    def test_s_beyond_length_raises(self):
        with pytest.raises(Exception):
            ADAPTER_CANONICAL.evaluate(0.0, 0.0, 0.0, 100.0, 0.0, 101.0)

    def test_s_zero(self):
        result = ADAPTER_CANONICAL.evaluate(10.0, 20.0, 0.5, 100.0, 0.0, 0.0)
        _check_returned(result, 10.0, 20.0, 0.5)

    def test_s_equals_length(self):
        result = ADAPTER_CANONICAL.evaluate(10.0, 20.0, 0.5, 100.0, 0.0, 100.0)
        _check_returned(result, 10.0 + 100.0 * math.cos(0.5), 20.0 + 100.0 * math.sin(0.5), 0.5)


# Non-canonical adapters may clamp instead of raising
class TestClampingAdapters:
    @pytest.mark.parametrize("adapter", [a for a in NON_BUGGY_ADAPTERS if a.name != "canonical"])
    def test_s_negative_does_not_crash(self, adapter):
        result = adapter.evaluate(0.0, 0.0, 0.0, 100.0, 0.0, -1.0)
        assert isinstance(result, EvalResult)

    @pytest.mark.parametrize("adapter", [a for a in NON_BUGGY_ADAPTERS if a.name != "canonical"])
    def test_s_beyond_length_does_not_crash(self, adapter):
        result = adapter.evaluate(0.0, 0.0, 0.0, 100.0, 0.0, 101.0)
        assert isinstance(result, EvalResult)

    @pytest.mark.parametrize("adapter", NON_BUGGY_ADAPTERS)
    def test_s_zero_nonzero_origin(self, adapter):
        result = adapter.evaluate(10.0, 20.0, 0.5, 100.0, 0.0, 0.0)
        assert abs(result.x - 10.0) < 1e-12
        assert abs(result.y - 20.0) < 1e-12
        assert abs(result.hdg - 0.5) < 1e-12

    @pytest.mark.parametrize("adapter", NON_BUGGY_ADAPTERS)
    def test_s_mid_segment(self, adapter):
        result = adapter.evaluate(0.0, 0.0, 0.0, 100.0, 0.0, 50.0)
        assert abs(result.x - 50.0) < 1e-12
        assert abs(result.y - 0.0) < 1e-12
