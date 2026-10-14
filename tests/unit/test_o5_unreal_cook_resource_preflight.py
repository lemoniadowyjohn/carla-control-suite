"""Tests for O5 Unreal cook resource preflight."""
from __future__ import annotations

from pathlib import Path

from tools import unreal_cook_resource_preflight as p


def test_disk_check_reports_required_and_remediation(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(p.shutil, "disk_usage", lambda path: type("U", (), {"free": int(1 * p.GIB)})())
    result = p.disk_check("disk", tmp_path, 5.0)
    assert result["status"] == "BLOCKED"
    assert result["required_gib"] == 5.0
    assert "no files were deleted" in result["remediation"]


def test_ram_check_with_psutil(monkeypatch):
    import sys
    module = type(sys)("psutil")
    module.virtual_memory = lambda: type("M", (), {"available": int(16 * p.GIB), "total": int(32 * p.GIB)})()
    monkeypatch.setitem(sys.modules, "psutil", module)
    result = p.ram_check(8.0)
    assert result["status"] == "PASS"
    assert result["available_gib"] == 16.0


def test_vram_unknown_is_incomplete(monkeypatch):
    monkeypatch.setattr(p.shutil, "which", lambda name: None)
    result = p.vram_check(8.0)
    assert result["status"] == "INCOMPLETE"
    assert result["available_gib"] is None
    assert "no exact VRAM requirement" in result["reason"]


def test_executable_missing_is_blocked(monkeypatch):
    monkeypatch.delenv("CARLA_ROOT", raising=False)
    monkeypatch.setattr(p.shutil, "which", lambda name: None)
    result = p.executable_check("carla_root", None, ["CarlaUE4.exe"])
    assert result["status"] == "BLOCKED"
    assert "no files were changed" in result["remediation"]


def test_preflight_does_not_delete_or_terminate(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(p, "disk_check", lambda *args, **kwargs: {"check": "disk", "status": "PASS"})
    monkeypatch.setattr(p, "ram_check", lambda *args, **kwargs: {"check": "ram", "status": "PASS"})
    monkeypatch.setattr(p, "vram_check", lambda *args, **kwargs: {"check": "vram", "status": "INCOMPLETE"})
    monkeypatch.setattr(p, "executable_check", lambda *args, **kwargs: {"check": "env", "status": "PASS"})
    result = p.preflight(tmp_path, None, None, 1, 1, 1, 1, None)
    assert result["status"] == "INCOMPLETE"
    assert "no files are deleted" in result["remediation_policy"]
