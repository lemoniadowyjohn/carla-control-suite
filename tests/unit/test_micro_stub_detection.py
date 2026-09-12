from ultimate_pipeline.quality.micro_stub_detection import (
    is_micro_stub_segment,
    MICRO_STUB_THRESHOLD_M,
)


def test_short_segment_is_a_micro_stub():
    assert is_micro_stub_segment(0.1) is True
    assert is_micro_stub_segment(0.2) is True
    assert is_micro_stub_segment(MICRO_STUB_THRESHOLD_M) is True


def test_ordinary_length_segment_is_not_a_micro_stub():
    assert is_micro_stub_segment(5.0) is False
    assert is_micro_stub_segment(50.0) is False


def test_zero_or_negative_length_is_not_a_micro_stub():
    """Degenerate (<= 0) lengths are a distinct defect class handled by
    zero_length_connector_repair.py, not this helper."""
    assert is_micro_stub_segment(0.0) is False
    assert is_micro_stub_segment(-0.1) is False


def test_custom_threshold_is_respected():
    assert is_micro_stub_segment(0.8, threshold_m=1.0) is True
    assert is_micro_stub_segment(1.2, threshold_m=1.0) is False
