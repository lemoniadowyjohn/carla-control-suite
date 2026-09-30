# ultimate_pipeline/tests/unit/test_v4_import_contracts.py
# -*- coding: utf-8 -*-
"""NEW-196: fail-closed CARLA 0.9.16 import/cook process contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ultimate_pipeline.tiling.carla_0916_import_process_contract import (
    ImportProcessError,
    run_import_sequence,
    run_mandatory_process,
)


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _ok_runner(cmd, **kwargs):
    return _Completed(returncode=0, stdout="ok", stderr="")


def _fail1_runner(cmd, **kwargs):
    return _Completed(returncode=1, stdout="", stderr="boom")


def _fail255_runner(cmd, **kwargs):
    return _Completed(returncode=255, stdout="", stderr="boom")


def _timeout_runner(cmd, **kwargs):
    raise subprocess.TimeoutExpired(cmd, timeout=kwargs.get("timeout", 1))


def _missing_runner(cmd, **kwargs):
    raise FileNotFoundError(f"No such file: {cmd[0]}")


def _exploding_runner(cmd, **kwargs):
    raise RuntimeError("unexpected spawn failure")


@pytest.mark.parametrize("platform", ["windows", "posix", "auto"])
def test_exit_0_continues(tmp_path, platform):
    result = run_mandatory_process(
        ["fake-import", "--map", "X"], cwd=str(tmp_path),
        log_dir=str(tmp_path / "logs"), platform=platform, runner=_ok_runner)
    assert result.status == "PASS"
    assert result.returncode == 0
    assert Path(result.stdout_path).is_file()
    assert Path(result.stderr_path).is_file()


@pytest.mark.parametrize("platform", ["windows", "posix"])
@pytest.mark.parametrize("runner", [_fail1_runner, _fail255_runner],
                         ids=["exit_1", "exit_255"])
def test_nonzero_exit_stops(tmp_path, platform, runner):
    with pytest.raises(ImportProcessError) as excinfo:
        run_mandatory_process(["fake-import"], cwd=str(tmp_path),
                              log_dir=str(tmp_path / "logs"),
                              platform=platform, runner=runner)
    assert excinfo.value.receipt["status"] == "FAIL"


@pytest.mark.parametrize("platform", ["windows", "posix"])
def test_timeout_stops(tmp_path, platform):
    with pytest.raises(ImportProcessError) as excinfo:
        run_mandatory_process(["fake-import"], cwd=str(tmp_path),
                              log_dir=str(tmp_path / "logs"),
                              platform=platform, runner=_timeout_runner,
                              timeout_s=1)
    assert excinfo.value.receipt["status"] == "TIMEOUT"


@pytest.mark.parametrize("platform", ["windows", "posix"])
def test_missing_executable_stops(tmp_path, platform):
    with pytest.raises(ImportProcessError) as excinfo:
        run_mandatory_process(["fake-import"], cwd=str(tmp_path),
                              log_dir=str(tmp_path / "logs"),
                              platform=platform, runner=_missing_runner)
    assert excinfo.value.receipt["status"] == "SPAWN_ERROR"


@pytest.mark.parametrize("platform", ["windows", "posix"])
def test_exception_stops(tmp_path, platform):
    with pytest.raises(ImportProcessError) as excinfo:
        run_mandatory_process(["fake-import"], cwd=str(tmp_path),
                              log_dir=str(tmp_path / "logs"),
                              platform=platform, runner=_exploding_runner)
    assert excinfo.value.receipt["status"] == "SPAWN_ERROR"


def test_success_missing_output_stops(tmp_path):
    with pytest.raises(ImportProcessError) as excinfo:
        run_mandatory_process(["fake-import"], cwd=str(tmp_path),
                              log_dir=str(tmp_path / "logs"),
                              platform="posix", runner=_ok_runner,
                              expected_outputs=[str(tmp_path / "nope.fbx")])
    assert excinfo.value.receipt["status"] == "FAIL"
    assert "required output absent" in str(excinfo.value)


def test_success_with_output_continues(tmp_path):
    produced = tmp_path / "tile.fbx"
    produced.write_text("fbx", encoding="utf-8")
    result = run_mandatory_process(
        ["fake-import"], cwd=str(tmp_path), log_dir=str(tmp_path / "logs"),
        platform="posix", runner=_ok_runner,
        expected_outputs=[str(produced)])
    assert result.status == "PASS"
    assert result.missing_outputs == []


def test_fake_output_content_mismatch_stops(tmp_path):
    import hashlib
    produced = tmp_path / "tile.fbx"
    produced.write_text("stale-content-from-previous-run", encoding="utf-8")
    want = hashlib.sha256(b"fresh-expected-content").hexdigest()
    with pytest.raises(ImportProcessError) as excinfo:
        run_mandatory_process(
            ["fake-import"], cwd=str(tmp_path),
            log_dir=str(tmp_path / "logs"),
            platform="posix", runner=_ok_runner,
            expected_output_hashes={str(produced): want})
    assert excinfo.value.receipt["status"] == "FAIL"
    assert "mismatch" in str(excinfo.value).lower()


def test_matching_hash_continues(tmp_path):
    import hashlib
    produced = tmp_path / "tile.fbx"
    produced.write_bytes(b"fresh-expected-content")
    want = hashlib.sha256(b"fresh-expected-content").hexdigest()
    result = run_mandatory_process(
        ["fake-import"], cwd=str(tmp_path), log_dir=str(tmp_path / "logs"),
        platform="posix", runner=_ok_runner,
        expected_output_hashes={str(produced): want})
    assert result.status == "PASS"


def test_absolute_missing_executable_no_spawn(tmp_path):
    with pytest.raises(ImportProcessError) as excinfo:
        run_mandatory_process([str(tmp_path / "does-not-exist.exe")],
                              cwd=str(tmp_path),
                              log_dir=str(tmp_path / "logs"))
    assert excinfo.value.receipt["status"] == "SPAWN_ERROR"


def test_sequence_stops_before_downstream(tmp_path):
    calls = []

    def counting_ok(cmd, **kwargs):
        calls.append(list(cmd))
        return _Completed(returncode=0, stdout="ok", stderr="")

    seq = run_import_sequence([
        {"name": "import", "command": ["fake-import"], "cwd": str(tmp_path),
         "runner": counting_ok},
        {"name": "cook", "command": ["fake-cook"], "cwd": str(tmp_path),
         "runner": _fail1_runner},
        {"name": "material", "command": ["fake-material"], "cwd": str(tmp_path),
         "runner": counting_ok},
    ], log_dir=str(tmp_path / "seq"))
    assert seq["status"] == "FAIL"
    assert seq["failed_step"] == "cook"
    assert [r["name"] for r in seq["receipts"]] == ["import", "cook"]
    # Downstream "material" step never executed.
    assert all("fake-material" not in c for c in calls)


def test_sequence_all_pass(tmp_path):
    seq = run_import_sequence([
        {"name": "import", "command": ["fake-import"], "cwd": str(tmp_path),
         "runner": _ok_runner},
        {"name": "cook", "command": ["fake-cook"], "cwd": str(tmp_path),
         "runner": _ok_runner},
    ], log_dir=str(tmp_path / "seq"))
    assert seq["status"] == "PASS"
    assert seq["failed_step"] is None


def test_receipt_schema(tmp_path):
    result = run_mandatory_process(["fake-import"], cwd=str(tmp_path),
                                   log_dir=str(tmp_path / "logs"),
                                   runner=_ok_runner)
    receipt = result.to_dict()
    for key in ("command", "cwd", "started_at_utc", "finished_at_utc",
                "returncode", "stdout_path", "stderr_path", "status"):
        assert key in receipt
    assert receipt["status"] == "PASS"
