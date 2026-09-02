# ultimate_pipeline/pipeline_stages/stage_10_tile_qa.py::_step10c_road_perception_screenshots
# -- zero prior test coverage on this specific safety behavior (a stale
# __pycache__ .pyc from March 2026 named
# "test_main_pipeline_step10c_respects_carla_disable" exists with no
# corresponding .py anywhere in history, suggesting a similar test once
# existed and was lost without replacement -- this restores it).
#
# Live: called from main_pipeline.py's step10 orchestration. The function
# is heavily CARLA-API-coupled overall (spawns worker subprocesses,
# screenshots, etc.), but its FIRST responsibility -- refusing to touch
# CARLA at all when it's disabled -- is pure settings/env logic and must
# hold for offline runs to stay CARLA-free. Verified: ENABLE_STEP10C=False
# short-circuits before any disable-status is even written; ENABLE_CARLA=False
# (settings) and UP_DISABLE_CARLA=1 (env) both short-circuit AFTER writing
# step10c_status.json with reason="carla_disabled"; neither disabled means
# the function proceeds past both checks (verified by making the next
# real step, _carla_isolation_enabled(), raise a sentinel so we can detect
# it was reached without actually touching CARLA). No bug found.
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from ultimate_pipeline.config.settings import Settings
from ultimate_pipeline.main_pipeline import MainPipeline


def _make_pipeline(tmp_path: Path) -> MainPipeline:
    settings = Settings()
    mp = MainPipeline(settings=settings)
    mp.out_dir = str(tmp_path)
    os.makedirs(mp.out_dir, exist_ok=True)
    return mp


def test_enable_step10c_false_short_circuits_before_any_status_file(tmp_path, monkeypatch, capsys):
    mp = _make_pipeline(tmp_path)
    mp.settings.ENABLE_STEP10C = False

    mp._step10c_road_perception_screenshots(str(tmp_path / "final.xodr"))

    assert "Skipping STEP 10C" in capsys.readouterr().out
    assert not (tmp_path / "step10c_status.json").exists()


def test_enable_carla_false_setting_skips_with_status_file(tmp_path):
    mp = _make_pipeline(tmp_path)
    mp.settings.ENABLE_CARLA = False

    mp._step10c_road_perception_screenshots(str(tmp_path / "final.xodr"))

    status_path = tmp_path / "step10c_status.json"
    assert status_path.is_file()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "SKIP"
    assert status["reason"] == "carla_disabled"
    assert status["ENABLE_CARLA"] is False


def test_up_disable_carla_env_skips_with_status_file(tmp_path, monkeypatch):
    mp = _make_pipeline(tmp_path)
    monkeypatch.setenv("UP_DISABLE_CARLA", "1")

    mp._step10c_road_perception_screenshots(str(tmp_path / "final.xodr"))

    status_path = tmp_path / "step10c_status.json"
    assert status_path.is_file()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "SKIP"
    assert status["reason"] == "carla_disabled"


def test_up_disable_carla_env_accepts_common_truthy_spellings(tmp_path, monkeypatch):
    for spelling in ("true", "YES", "On", "1"):
        mp = _make_pipeline(tmp_path)
        monkeypatch.setenv("UP_DISABLE_CARLA", spelling)

        mp._step10c_road_perception_screenshots(str(tmp_path / "final.xodr"))

        status = json.loads((tmp_path / "step10c_status.json").read_text(encoding="utf-8"))
        assert status["reason"] == "carla_disabled", f"spelling={spelling!r} did not disable CARLA"
        (tmp_path / "step10c_status.json").unlink()


def test_neither_disabled_proceeds_past_the_disable_checks(tmp_path, monkeypatch):
    mp = _make_pipeline(tmp_path)
    monkeypatch.delenv("UP_DISABLE_CARLA", raising=False)
    mp.settings.ENABLE_CARLA = True

    sentinel = RuntimeError("reached past disable checks")
    with mock.patch.object(mp, "_carla_isolation_enabled", side_effect=sentinel):
        with pytest.raises(RuntimeError, match="reached past disable checks"):
            mp._step10c_road_perception_screenshots(str(tmp_path / "final.xodr"))

    # Must NOT have written the carla_disabled status -- it legitimately
    # tried to proceed and failed for an unrelated (mocked) reason.
    status_path = tmp_path / "step10c_status.json"
    if status_path.is_file():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert status.get("reason") != "carla_disabled"
