# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/utils/map_fingerprint.py and
ultimate_pipeline/utils/environment_snapshot.py. Both zero prior test
coverage, both small and defensive; no bugs found on review.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from unittest import mock

from ultimate_pipeline.utils.environment_snapshot import write_environment_snapshot
from ultimate_pipeline.utils.map_fingerprint import write_map_content_fingerprint


# ---------------------------------------------------------------------------
# write_map_content_fingerprint
# ---------------------------------------------------------------------------


def test_writes_fingerprint_with_real_sha256_for_existing_file(tmp_path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")

    out_path = write_map_content_fingerprint(str(tmp_path), str(xodr))

    assert out_path == str(tmp_path / "map_content_fingerprint.json")
    data = json.loads(Path(out_path).read_text(encoding="utf-8"))
    expected_sha = hashlib.sha256(xodr.read_bytes()).hexdigest()
    assert data["final_xodr_sha256"] == expected_sha
    assert data["final_xodr_path"] == str(xodr)


def test_missing_xodr_file_records_null_sha256(tmp_path):
    missing = tmp_path / "does_not_exist.xodr"
    out_path = write_map_content_fingerprint(str(tmp_path), str(missing))
    data = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert data["final_xodr_sha256"] is None


def test_includes_quarantine_hash_when_present(tmp_path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    quarantine = tmp_path / "roads_quarantined.json"
    quarantine.write_text('{"roads": []}', encoding="utf-8")

    out_path = write_map_content_fingerprint(str(tmp_path), str(xodr))
    data = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert data["roads_quarantined_sha256"] == hashlib.sha256(
        quarantine.read_bytes()
    ).hexdigest()


def test_omits_quarantine_key_when_absent(tmp_path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    out_path = write_map_content_fingerprint(str(tmp_path), str(xodr))
    data = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert "roads_quarantined_sha256" not in data


def test_returns_none_for_missing_out_dir_or_xodr_path():
    assert write_map_content_fingerprint("", "x.xodr") is None
    assert write_map_content_fingerprint("out", "") is None


def test_returns_none_when_write_fails(tmp_path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    # out_dir points at a file, not a directory -- os.path.join'd write path
    # cannot be opened.
    not_a_dir = tmp_path / "not_a_dir"
    not_a_dir.write_text("x", encoding="utf-8")
    assert write_map_content_fingerprint(str(not_a_dir), str(xodr)) is None


# ---------------------------------------------------------------------------
# write_environment_snapshot
# ---------------------------------------------------------------------------


def test_writes_python_version_and_platform(tmp_path):
    out_path = tmp_path / "env.json"
    write_environment_snapshot(out_path)
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert "python_version" in data
    assert "platform" in data
    assert data["python_version"]


def test_pip_freeze_captured_and_hashed(tmp_path):
    out_path = tmp_path / "env.json"
    with mock.patch(
        "subprocess.check_output", return_value="pkg-a==1.0\npkg-b==2.0\n"
    ):
        write_environment_snapshot(out_path)
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["pip_freeze"] == ["pkg-a==1.0", "pkg-b==2.0"]
    expected = hashlib.sha256(b"pkg-a==1.0\npkg-b==2.0\n").hexdigest()
    assert data["pip_freeze_sha256"] == expected


def test_pip_freeze_failure_is_handled_gracefully(tmp_path):
    out_path = tmp_path / "env.json"
    with mock.patch(
        "subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, ["pip", "freeze"]),
    ):
        write_environment_snapshot(out_path)  # must not raise
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["pip_freeze"] == []
    assert data["pip_freeze_sha256"] == ""
