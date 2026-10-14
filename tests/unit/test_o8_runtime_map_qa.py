"""Tests for O8 runtime QA harness."""
from __future__ import annotations

from tools.runtime_map_qa import run_runtime_qa


def test_missing_carla_is_blocked_runtime(monkeypatch):
    import builtins
    real_import = builtins.__import__
    def blocked(name, *args, **kwargs):
        if name == "carla":
            raise ImportError("offline")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", blocked)
    report = run_runtime_qa()
    assert report["status"] == "BLOCKED_RUNTIME"
    assert report["checks"]["connect"] == "NOT_RUN"
    assert "production-ready" in report["claim_boundary"]


def test_no_map_name_is_incomplete_when_carla_available(monkeypatch):
    import sys, types
    module = types.ModuleType("carla")
    class Client:
        def __init__(self, host, port): pass
        def set_timeout(self, timeout): pass
        def get_available_maps(self): return ["Ingolstadt"]
    module.Client = Client
    monkeypatch.setitem(sys.modules, "carla", module)
    report = run_runtime_qa(map_name=None)
    assert report["status"] == "INCOMPLETE"
    assert report["checks"]["list_maps"] == "PASS"
