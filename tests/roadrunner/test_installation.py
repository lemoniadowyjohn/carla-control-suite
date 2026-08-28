"""ultimate_pipeline/roadrunner/installation.py -- offline-safe RoadRunner/MATLAB installation
detection (filesystem probes + Windows registry queries only; the module's own docstring states
importing/using it must never require RoadRunner or MATLAB to actually be installed). Found
untested while auditing tests/roadrunner/ coverage against ultimate_pipeline/roadrunner/'s
actual module list. This machine has neither RoadRunner nor MATLAB installed, which makes it a
good real-world check of the "gracefully returns not-found" claim rather than a mocked one.
"""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.roadrunner.installation import (
    InstallationReport,
    _detect_roadrunner_release,
    _find_executable,
    _find_proto_files,
    _read_file_safe,
    probe_installation,
)


# ---------------------------------------------------------------------------
# _find_executable
# ---------------------------------------------------------------------------

def test_find_executable_missing_name_returns_none():
    assert _find_executable("definitely_not_a_real_executable_xyz123") is None


def test_find_executable_finds_via_extra_paths(tmp_path: Path):
    exe = tmp_path / "myroadrunner"
    exe.write_text("stub", encoding="utf-8")
    found = _find_executable("myroadrunner", extra_paths=(str(tmp_path),))
    assert found is not None
    assert Path(found).name == "myroadrunner"


def test_find_executable_extra_paths_missing_dir_no_crash(tmp_path: Path):
    assert _find_executable("nope", extra_paths=(str(tmp_path / "does_not_exist"),)) is None


# ---------------------------------------------------------------------------
# _read_file_safe
# ---------------------------------------------------------------------------

def test_read_file_safe_missing_file_returns_none():
    assert _read_file_safe("C:/definitely/not/a/real/path.txt") is None


def test_read_file_safe_reads_real_file(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("hello", encoding="utf-8")
    assert _read_file_safe(str(f)) == "hello"


# ---------------------------------------------------------------------------
# _detect_roadrunner_release
# ---------------------------------------------------------------------------

def test_detect_roadrunner_release_none_path_returns_none():
    assert _detect_roadrunner_release(None) is None


def test_detect_roadrunner_release_from_release_info_json(tmp_path: Path):
    rr_dir = tmp_path / "RoadRunner"
    rr_dir.mkdir()
    (rr_dir / "release_info.json").write_text('{"version": "2024a"}', encoding="utf-8")
    exe = rr_dir / "roadrunner.exe"
    exe.write_text("stub", encoding="utf-8")
    assert _detect_roadrunner_release(str(exe)) == "2024a"


def test_detect_roadrunner_release_from_version_txt_fallback(tmp_path: Path):
    rr_dir = tmp_path / "RoadRunner"
    rr_dir.mkdir()
    (rr_dir / "version.txt").write_text("2024b\nextra line\n", encoding="utf-8")
    exe = rr_dir / "roadrunner.exe"
    exe.write_text("stub", encoding="utf-8")
    assert _detect_roadrunner_release(str(exe)) == "2024b"


def test_detect_roadrunner_release_malformed_json_falls_through(tmp_path: Path):
    rr_dir = tmp_path / "RoadRunner"
    rr_dir.mkdir()
    (rr_dir / "release_info.json").write_text("{not valid json", encoding="utf-8")
    (rr_dir / "version.txt").write_text("2024c", encoding="utf-8")
    exe = rr_dir / "roadrunner.exe"
    exe.write_text("stub", encoding="utf-8")
    assert _detect_roadrunner_release(str(exe)) == "2024c"


def test_detect_roadrunner_release_nothing_found_returns_none(tmp_path: Path):
    rr_dir = tmp_path / "RoadRunner"
    rr_dir.mkdir()
    exe = rr_dir / "roadrunner.exe"
    exe.write_text("stub", encoding="utf-8")
    assert _detect_roadrunner_release(str(exe)) is None


# ---------------------------------------------------------------------------
# _find_proto_files
# ---------------------------------------------------------------------------

def test_find_proto_files_none_when_no_roots_exist():
    assert _find_proto_files(("C:/definitely/not/a/real/dir",)) == ()


def test_find_proto_files_finds_and_sorts(tmp_path: Path):
    (tmp_path / "b.proto").write_text("", encoding="utf-8")
    (tmp_path / "a.proto").write_text("", encoding="utf-8")
    (tmp_path / "not_a_proto.txt").write_text("", encoding="utf-8")
    found = _find_proto_files((str(tmp_path),))
    assert len(found) == 2
    assert found == tuple(sorted(found))  # sorted output guaranteed


# ---------------------------------------------------------------------------
# probe_installation -- end-to-end, confirms the "offline-safe" claim
# ---------------------------------------------------------------------------

def test_probe_installation_does_not_raise_on_a_machine_without_roadrunner():
    # This machine genuinely has neither RoadRunner nor MATLAB installed -- exercising the
    # real, unmocked code path is a stronger check of the module's own "must never require
    # RoadRunner or MATLAB to be installed" docstring claim than a mocked test would be.
    report = probe_installation()
    assert isinstance(report, InstallationReport)


def test_probe_installation_reports_not_found_when_absent():
    report = probe_installation()
    assert report.roadrunner_executable is None
    assert report.matlab_executable is None
    assert report.roadrunner_api_available is False


def test_probe_installation_supported_imports_exports_always_populated():
    # These are static capability lists, independent of whether RoadRunner is installed.
    report = probe_installation()
    assert "xodr" in report.supported_imports
    assert "xodr" in report.supported_exports
