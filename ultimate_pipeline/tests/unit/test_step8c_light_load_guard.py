# stage_08_integrity.py::_step8c_spawn_validation()'s FORCE_LIGHT_LOAD_IN_STEP_8
# guard used a bare `assert`, silently no-opping under python -O and allowing a
# forbidden full map load in STEP 8 to proceed. Same bare-assert-for-a-
# production-invariant defect class fixed several times this session. Fixed to
# an explicit if/raise. The guard is the first real logic in the function
# (right after _inject_main_pipeline_globals()), so it's testable without
# mocking the rest of the heavily CARLA-dependent function body. Zero prior
# coverage.
from __future__ import annotations

import types

import pytest

from ultimate_pipeline.pipeline_stages.stage_08_integrity import (
    _step8c_spawn_validation,
)


def _fake_self(*, force_light_load):
    self_obj = types.SimpleNamespace()
    self_obj.settings = types.SimpleNamespace(FORCE_LIGHT_LOAD_IN_STEP_8=force_light_load)
    return self_obj


def test_full_load_forbidden_raises(monkeypatch):
    monkeypatch.setattr(
        "ultimate_pipeline.pipeline_stages.stage_08_integrity._inject_main_pipeline_globals",
        lambda: None,
    )
    fake_self = _fake_self(force_light_load=False)

    with pytest.raises(RuntimeError, match="FULL map load in STEP 8 is forbidden"):
        _step8c_spawn_validation(fake_self, "final.xodr")


def test_light_load_true_does_not_raise_at_the_guard(monkeypatch):
    monkeypatch.setattr(
        "ultimate_pipeline.pipeline_stages.stage_08_integrity._inject_main_pipeline_globals",
        lambda: None,
    )
    fake_self = _fake_self(force_light_load=True)

    # Past the guard the function needs real CARLA/settings machinery; just
    # confirm it doesn't raise the guard's own error (any other exception
    # from deeper in the function, e.g. AttributeError on a missing settings
    # field, proves the guard itself let execution proceed).
    with pytest.raises(Exception) as exc_info:
        _step8c_spawn_validation(fake_self, "final.xodr")
    assert "FULL map load in STEP 8 is forbidden" not in str(exc_info.value)


def test_missing_setting_defaults_to_light_load_and_does_not_raise_at_guard():
    # getattr(s, "FORCE_LIGHT_LOAD_IN_STEP_8", True) -- defaults to True (safe)
    # when the setting attribute is entirely absent.
    import ultimate_pipeline.pipeline_stages.stage_08_integrity as mod

    fake_self = types.SimpleNamespace(settings=types.SimpleNamespace())
    real_inject = mod._inject_main_pipeline_globals
    mod._inject_main_pipeline_globals = lambda: None
    try:
        with pytest.raises(Exception) as exc_info:
            _step8c_spawn_validation(fake_self, "final.xodr")
        assert "FULL map load in STEP 8 is forbidden" not in str(exc_info.value)
    finally:
        mod._inject_main_pipeline_globals = real_inject
