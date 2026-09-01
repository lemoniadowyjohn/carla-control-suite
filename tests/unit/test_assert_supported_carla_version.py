# ultimate_pipeline/tools/run_perception_safe.py's _assert_supported_carla_version()
# used a bare `assert ver.startswith("0.9.")`, silently becoming a no-op under
# Python's -O flag (which strips asserts) -- the exact same "bare assert for a
# production invariant" defect class found and fixed multiple times earlier
# this session. Its only call site runs right before a real perception-capture
# route against a live CARLA server, so silently letting an incompatible CARLA
# API version through defeats the entire point of the check. Fixed to an
# explicit if/raise. Zero prior test coverage.
from __future__ import annotations

import sys
import types

import pytest

from ultimate_pipeline.tools.run_perception_safe import _assert_supported_carla_version


def _install_fake_carla(monkeypatch, version: str | None):
    fake = types.ModuleType("carla")
    if version is not None:
        fake.__version__ = version
    monkeypatch.setitem(sys.modules, "carla", fake)


def test_carla_not_importable_does_not_raise(monkeypatch):
    monkeypatch.setitem(sys.modules, "carla", None)  # forces ImportError on `import carla`
    _assert_supported_carla_version()  # must not raise


def test_supported_version_does_not_raise(monkeypatch):
    _install_fake_carla(monkeypatch, "0.9.16")
    _assert_supported_carla_version()  # must not raise


def test_unsupported_version_raises(monkeypatch):
    _install_fake_carla(monkeypatch, "0.10.0")
    with pytest.raises(RuntimeError, match="Unsupported CARLA version"):
        _assert_supported_carla_version()


def test_missing_version_attribute_does_not_raise(monkeypatch):
    _install_fake_carla(monkeypatch, None)  # no __version__ attribute at all
    _assert_supported_carla_version()  # must not raise (ver is falsy)


def test_empty_version_string_does_not_raise(monkeypatch):
    _install_fake_carla(monkeypatch, "")
    _assert_supported_carla_version()  # must not raise
