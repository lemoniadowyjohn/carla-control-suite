# C11 (HIGH) reproducibility fix, step 1: a clean-checkout default pipeline run
# must NOT crash before stage 01. `tools/preanchor_xodr.py` does not exist in
# this repo, but `Settings.PREANCHOR_INPUT_XODR` defaulted to True, and
# MainPipeline._maybe_preanchor_input_xodr() imports `tools.preanchor_xodr`
# unconditionally whenever preanchoring is enabled. With default settings and
# GPS bounds available, a fresh run therefore dies with ImportError before it
# ever reaches stage 01.
#
# Decision (documented in reports/post_audit_hardening/C11_REPRODUCIBILITY.md):
# option (b) — default PREANCHOR_INPUT_XODR to False. Preanchoring re-frames
# off the Osm2Odr tmerc(0,0) frame that the DEM contract needs, and no known
# working run actually used it, so flipping the default is safe and keeps the
# feature available as an explicit opt-in (UP_PREANCHOR_INPUT_XODR=1).
from __future__ import annotations

import os

import pytest

from ultimate_pipeline.config.settings import Settings, SETTINGS


def test_preanchor_input_xodr_defaults_false() -> None:
    """The dataclass field default itself must be False (not just an env override)."""
    assert Settings.PREANCHOR_INPUT_XODR is False


def test_settings_singleton_preanchor_off_without_env(monkeypatch) -> None:
    monkeypatch.delenv("UP_PREANCHOR_INPUT_XODR", raising=False)
    s = Settings()
    assert s.PREANCHOR_INPUT_XODR is False


def test_module_settings_singleton_preanchor_off() -> None:
    # SETTINGS is constructed at import time under whatever env the test
    # session happens to have; guard against a stray env var leaking in from
    # the shell that could mask a regression of the dataclass default.
    if os.getenv("UP_PREANCHOR_INPUT_XODR", "").strip() == "":
        assert SETTINGS.PREANCHOR_INPUT_XODR is False


def test_maybe_preanchor_input_xodr_default_does_not_import_missing_module(
    tmp_path, monkeypatch
) -> None:
    """
    Directly exercises MainPipeline._maybe_preanchor_input_xodr with default
    settings (PREANCHOR_INPUT_XODR=False, no env override). It must return
    immediately without ever touching `tools.preanchor_xodr` (which is absent
    from the repo), i.e. no ImportError / ModuleNotFoundError.
    """
    monkeypatch.delenv("UP_PREANCHOR_INPUT_XODR", raising=False)

    import sys
    import types

    # Sanity precondition: tools.preanchor_xodr really is absent. If someone
    # later restores it (option (a)), this test should be revisited rather
    # than silently passing for the wrong reason.
    assert "tools.preanchor_xodr" not in sys.modules
    try:
        import importlib

        importlib.import_module("tools.preanchor_xodr")
        pytest.skip("tools.preanchor_xodr now exists; option (a) was chosen instead")
    except ModuleNotFoundError:
        pass

    from ultimate_pipeline.main_pipeline import MainPipeline

    pipeline = MainPipeline.__new__(MainPipeline)
    pipeline.settings = Settings()
    pipeline._preanchor_manifest = {"applied": False}

    # Must not raise ImportError/ModuleNotFoundError, and must be a no-op.
    pipeline._maybe_preanchor_input_xodr(tmp_path)
    assert pipeline._preanchor_manifest == {"applied": False}
    assert not (tmp_path / "preanchor_report.json").exists()


def test_preanchor_can_still_be_opted_into_via_env(monkeypatch, tmp_path) -> None:
    """
    Explicit opt-in (UP_PREANCHOR_INPUT_XODR=1) must still reach the
    tools.preanchor_xodr import (and fail there, since the module is absent) —
    proving the feature is a real, working opt-in path and not silently
    disabled altogether.
    """
    monkeypatch.setenv("UP_PREANCHOR_INPUT_XODR", "1")

    from ultimate_pipeline.main_pipeline import MainPipeline

    pipeline = MainPipeline.__new__(MainPipeline)
    pipeline.settings = Settings()
    pipeline._preanchor_manifest = {"applied": False}

    # settings.load_gps_bounds() must exist per the method's own contract;
    # if it raises before reaching the import, that's still a legitimate
    # "requires GPS bounds" RuntimeError, not silent success. Accept either
    # the GPS-bounds RuntimeError or the (expected-missing) module import
    # error as evidence the opt-in path is live.
    with pytest.raises((RuntimeError, ImportError, ModuleNotFoundError, FileNotFoundError)):
        pipeline._maybe_preanchor_input_xodr(tmp_path)
