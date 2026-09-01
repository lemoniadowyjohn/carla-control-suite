# ultimate_pipeline/optional/carla_api.py -- live via 7+ importers (core/carla_utils.py,
# carla_tools/runtime_enrichments.py, several tools/*.py). Zero prior test coverage.
#
# Real (if not currently reproducible on this machine, where `import carla`
# succeeds cleanly) fix: _probe_carla_module() only caught ModuleNotFoundError,
# not the broader ImportError family. A CARLA install that's present but
# unloadable (DLL load failure, native-extension ABI mismatch against the
# running Python build -- both real, documented CARLA Python API failure
# modes, not hypothetical) surfaces as a plain ImportError, not
# ModuleNotFoundError -- the narrower except let that propagate uncaught,
# contradicting get_carla()'s own docstring ("raises a friendly RuntimeError
# when CARLA is missing"). Widened to `except ImportError` (which
# ModuleNotFoundError is already a subclass of).
from __future__ import annotations

import sys
import types

import pytest

import ultimate_pipeline.optional.carla_api as carla_api_module
from ultimate_pipeline.optional.carla_api import carla_available, get_carla


@pytest.fixture(autouse=True)
def _reset_carla_probe_cache(monkeypatch):
    """_probe_carla_module() caches its result in module-level globals for
    the lifetime of the process -- reset them around every test so tests
    don't leak state into each other."""
    monkeypatch.setattr(carla_api_module, "_CARLA_MODULE", None)
    monkeypatch.setattr(carla_api_module, "_CARLA_CHECKED", False)
    yield


def test_get_carla_returns_module_when_importable(monkeypatch):
    fake_carla = types.ModuleType("carla")
    monkeypatch.setitem(sys.modules, "carla", fake_carla)

    assert get_carla() is fake_carla


def test_get_carla_raises_friendly_error_when_module_not_found(monkeypatch):
    monkeypatch.setitem(sys.modules, "carla", None)  # forces ModuleNotFoundError

    with pytest.raises(RuntimeError, match="CARLA Python API is not installed"):
        get_carla()


def test_get_carla_raises_friendly_error_on_broader_import_error(monkeypatch):
    """Regression test: a present-but-unloadable CARLA install (DLL load
    failure, ABI mismatch) raises plain ImportError, not
    ModuleNotFoundError. Simulated by making the import machinery itself
    raise ImportError for this specific module name."""
    real_import = __import__

    def _failing_import(name, *args, **kwargs):
        if name == "carla":
            raise ImportError("DLL load failed while importing carla")
        return real_import(name, *args, **kwargs)

    monkeypatch.setitem(sys.modules, "carla", None)
    del sys.modules["carla"]
    monkeypatch.setattr("builtins.__import__", _failing_import)

    with pytest.raises(RuntimeError, match="CARLA Python API is not installed"):
        get_carla()


def test_carla_available_true_when_importable(monkeypatch):
    fake_carla = types.ModuleType("carla")
    monkeypatch.setitem(sys.modules, "carla", fake_carla)

    assert carla_available() is True


def test_carla_available_false_when_not_importable(monkeypatch):
    monkeypatch.setitem(sys.modules, "carla", None)

    assert carla_available() is False


def test_probe_result_is_cached_across_calls(monkeypatch):
    fake_carla = types.ModuleType("carla")
    monkeypatch.setitem(sys.modules, "carla", fake_carla)

    first = get_carla()
    # Even if sys.modules changes afterward, the cached result must be reused.
    monkeypatch.setitem(sys.modules, "carla", None)
    second = get_carla()

    assert first is second is fake_carla
