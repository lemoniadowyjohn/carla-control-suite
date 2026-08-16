# C11 (HIGH) reproducibility fix, step 3: decouple Phase-1 auto-map
# GENERATION from the Phase-2 manual-map COMPARISON.
#
# Previously, MainPipeline._write_crs_comparability() raised RuntimeError
# whenever THESIS_STRICT was set and no manual reference XODR was present.
# That means an ordinary auto-generation run configured with THESIS_STRICT
# (a research-integrity setting, not something specific to the comparison
# step) could not complete stage 02 without also having a manual map on
# disk -- coupling generation to a downstream comparison input it doesn't
# actually need.
#
# Fix: when THESIS_STRICT and no manual map is present, write
# crs_comparability.json with status="manual_deferred" instead of raising.
# The hard-fail behavior is preserved, but only when explicitly requested via
# a new REQUIRE_MANUAL_FOR_CRS flag (default False for generation runs).
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ultimate_pipeline.config.settings import Settings
from ultimate_pipeline.main_pipeline import MainPipeline

_MINIMAL_XODR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="" version="1.00" north="0" south="0" east="0" west="0">
  </header>
</OpenDRIVE>
"""


def _make_pipeline(tmp_path: Path, *, thesis_strict: bool, require_manual: bool) -> MainPipeline:
    pipeline = MainPipeline.__new__(MainPipeline)
    settings = Settings()
    settings.THESIS_STRICT = thesis_strict
    settings.REQUIRE_MANUAL_FOR_CRS = require_manual
    settings.MANUAL_MAP_XODR = ""
    pipeline.settings = settings
    pipeline.out_dir = str(tmp_path)
    return pipeline


def _write_auto_xodr(tmp_path: Path) -> str:
    p = tmp_path / "auto.xodr"
    p.write_text(_MINIMAL_XODR, encoding="utf-8")
    return str(p)


def test_default_require_manual_for_crs_is_false() -> None:
    assert Settings.REQUIRE_MANUAL_FOR_CRS is False


def test_strict_without_manual_and_default_flag_does_not_raise(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UP_MANUAL_XODR_GRID0828", raising=False)
    monkeypatch.delenv("UP_MANUAL_XODR", raising=False)
    monkeypatch.delenv("UP_REQUIRE_MANUAL_FOR_CRS", raising=False)

    auto_xodr = _write_auto_xodr(tmp_path)
    pipeline = _make_pipeline(tmp_path, thesis_strict=True, require_manual=False)

    out_path = pipeline._write_crs_comparability(
        auto_xodr=auto_xodr,
        policy_used="preserve",
        georef_decision={"action": "kept", "reason": "test"},
    )

    assert out_path, "must write a crs_comparability.json rather than raise"
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["status"] == "manual_deferred"
    assert payload["manual"]["present"] is False


def test_strict_with_require_manual_flag_still_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UP_MANUAL_XODR_GRID0828", raising=False)
    monkeypatch.delenv("UP_MANUAL_XODR", raising=False)
    monkeypatch.delenv("UP_REQUIRE_MANUAL_FOR_CRS", raising=False)

    auto_xodr = _write_auto_xodr(tmp_path)
    pipeline = _make_pipeline(tmp_path, thesis_strict=True, require_manual=True)

    with pytest.raises(RuntimeError):
        pipeline._write_crs_comparability(
            auto_xodr=auto_xodr,
            policy_used="preserve",
            georef_decision={"action": "kept", "reason": "test"},
        )


def test_require_manual_for_crs_env_override(tmp_path, monkeypatch) -> None:
    """UP_REQUIRE_MANUAL_FOR_CRS=1 must force the hard-fail path even if the
    settings object's attribute says False, matching the env-override
    convention used elsewhere in settings (e.g. UP_THESIS_STRICT)."""
    monkeypatch.delenv("UP_MANUAL_XODR_GRID0828", raising=False)
    monkeypatch.delenv("UP_MANUAL_XODR", raising=False)
    monkeypatch.setenv("UP_REQUIRE_MANUAL_FOR_CRS", "1")

    auto_xodr = _write_auto_xodr(tmp_path)
    pipeline = _make_pipeline(tmp_path, thesis_strict=True, require_manual=False)

    with pytest.raises(RuntimeError):
        pipeline._write_crs_comparability(
            auto_xodr=auto_xodr,
            policy_used="preserve",
            georef_decision={"action": "kept", "reason": "test"},
        )


def test_non_strict_without_manual_still_succeeds_as_before(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UP_MANUAL_XODR_GRID0828", raising=False)
    monkeypatch.delenv("UP_MANUAL_XODR", raising=False)
    monkeypatch.delenv("UP_REQUIRE_MANUAL_FOR_CRS", raising=False)

    auto_xodr = _write_auto_xodr(tmp_path)
    pipeline = _make_pipeline(tmp_path, thesis_strict=False, require_manual=False)

    out_path = pipeline._write_crs_comparability(
        auto_xodr=auto_xodr,
        policy_used="preserve",
        georef_decision={"action": "kept", "reason": "test"},
    )
    assert out_path
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    # Non-strict path never needed manual_deferred; comparability report is
    # written as before with manual.present=False and no "status" hard-fail.
    assert payload["manual"]["present"] is False
