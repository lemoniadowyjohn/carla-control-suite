"""V112: the paired RQ3 runner must not substitute explicit calibration."""
from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.experiments.thesis.run_perception_capture_pair import (
    _resolve_calib_path,
)


def test_missing_explicit_calib_is_terminal_even_if_default_exists(tmp_path):
    missing = tmp_path / "wrong_rig.json"
    with pytest.raises(FileNotFoundError, match="explicit --calib-json"):
        _resolve_calib_path(str(missing))


def test_existing_explicit_calibration_is_selected_exactly(tmp_path):
    expected = tmp_path / "chosen_rig.json"
    expected.write_text('{"cameras": {}, "lidars": {}}', encoding="utf-8")
    assert Path(_resolve_calib_path(str(expected))).resolve() == expected.resolve()


def test_missing_explicit_calibration_does_not_create_fallback_file(tmp_path):
    missing = tmp_path / "not_here.json"
    with pytest.raises(FileNotFoundError):
        _resolve_calib_path(str(missing))
    assert not missing.exists()
