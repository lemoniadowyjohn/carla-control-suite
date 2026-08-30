# -*- coding: utf-8 -*-
"""Tests for the pure-logic helper methods of
ultimate_pipeline/enrichment/osm2world_runner.py.

Live: main_pipeline.py / pipeline_stages/stage_04_enrichment.py invoke
this via run_osm2world_stage / is_osm2world_enabled. This is a strictly
optional, non-gating enrichment stage per its own docstring ("does NOT
affect OpenDRIVE generation or CARLA loadability") for perceptual
clutter, not road truth. Zero prior test coverage.

Scope: covers the pure/file-based helper methods (_hash_file,
_compute_cache_key, _check_cache, _validate_osm_input, _validate_glb's
header check, _write_config, _find_osm2world_entrypoint,
is_osm2world_enabled). The heavy subprocess orchestration (run(),
_run_osm2world_for_output, _check_java, Blender-import validation)
requires real Java/OSM2World/Blender installs to meaningfully exercise
and is deliberately left uncovered here, matching this session's
established precedent for orchestration that needs a live external tool.

One dead-code observation, not fixed (zero observable behavior impact):
_validate_osm_input's special-case `if str(self.osm_path).lower().
endswith(".osm.xml"): return True, ""` is unreachable -- Path.suffix on
any "*.osm.xml" file is already ".xml", which is in the general allowed
list and returns True before ever reaching that branch.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from ultimate_pipeline.enrichment.osm2world_runner import (
    OSM2WorldResult,
    OSM2WorldRunner,
    is_osm2world_enabled,
)


def _make_runner(tmp_path, osm_name="input.osm", **kwargs) -> OSM2WorldRunner:
    osm_path = tmp_path / osm_name
    if not osm_path.exists():
        osm_path.write_text("<osm></osm>", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    return OSM2WorldRunner(osm_path=str(osm_path), output_dir=str(out_dir), **kwargs)


# ---------------------------------------------------------------------------
# is_osm2world_enabled
# ---------------------------------------------------------------------------


def test_is_enabled_false_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_OSM2WORLD", raising=False)
    monkeypatch.delenv("UP_ENABLE_OSM2WORLD", raising=False)
    assert is_osm2world_enabled() is False


def test_is_enabled_true_via_legacy_env(monkeypatch):
    monkeypatch.setenv("ENABLE_OSM2WORLD", "1")
    monkeypatch.delenv("UP_ENABLE_OSM2WORLD", raising=False)
    assert is_osm2world_enabled() is True


def test_is_enabled_true_via_up_prefixed_env(monkeypatch):
    monkeypatch.delenv("ENABLE_OSM2WORLD", raising=False)
    monkeypatch.setenv("UP_ENABLE_OSM2WORLD", "true")
    assert is_osm2world_enabled() is True


# ---------------------------------------------------------------------------
# _hash_file
# ---------------------------------------------------------------------------


def test_hash_file_returns_real_sha256(tmp_path):
    runner = _make_runner(tmp_path)
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")
    import hashlib

    assert runner._hash_file(f) == hashlib.sha256(b"hello world").hexdigest()


def test_hash_file_missing_file_returns_empty_string(tmp_path):
    runner = _make_runner(tmp_path)
    assert runner._hash_file(tmp_path / "does_not_exist.bin") == ""


# ---------------------------------------------------------------------------
# _compute_cache_key
# ---------------------------------------------------------------------------


def test_compute_cache_key_is_deterministic(tmp_path):
    runner = _make_runner(tmp_path)
    k1 = runner._compute_cache_key("osmhash", "confighash")
    k2 = runner._compute_cache_key("osmhash", "confighash")
    assert k1 == k2
    assert len(k1) == 16


def test_compute_cache_key_differs_for_different_inputs(tmp_path):
    runner = _make_runner(tmp_path)
    k1 = runner._compute_cache_key("osmhash1", "confighash")
    k2 = runner._compute_cache_key("osmhash2", "confighash")
    assert k1 != k2


# ---------------------------------------------------------------------------
# _check_cache
# ---------------------------------------------------------------------------


def test_check_cache_returns_none_when_status_file_missing(tmp_path):
    runner = _make_runner(tmp_path)
    assert runner._check_cache("anykey") is None


def test_check_cache_returns_none_when_key_mismatch(tmp_path):
    runner = _make_runner(tmp_path)
    status_path = runner.output_dir / "osm2world_status.json"
    status_path.write_text(json.dumps({"cache_key": "old_key", "status": "ok"}), encoding="utf-8")
    assert runner._check_cache("new_key") is None


def test_check_cache_returns_none_when_referenced_output_missing(tmp_path):
    runner = _make_runner(tmp_path)
    status_path = runner.output_dir / "osm2world_status.json"
    status_path.write_text(
        json.dumps(
            {
                "cache_key": "k1",
                "status": "ok",
                "outputs": {"obj": str(tmp_path / "does_not_exist.obj")},
            }
        ),
        encoding="utf-8",
    )
    assert runner._check_cache("k1") is None


def test_check_cache_returns_cached_result_when_valid(tmp_path):
    runner = _make_runner(tmp_path)
    output_obj = tmp_path / "scene.obj"
    output_obj.write_text("o Scene", encoding="utf-8")
    status_path = runner.output_dir / "osm2world_status.json"
    status_path.write_text(
        json.dumps(
            {
                "cache_key": "k1",
                "status": "ok",
                "outputs": {"obj": str(output_obj)},
                "reason": "original run",
            }
        ),
        encoding="utf-8",
    )
    result = runner._check_cache("k1")
    assert result is not None
    assert result.status == "cached"
    assert result.outputs == {"obj": str(output_obj)}


def test_check_cache_returns_none_for_non_ok_status(tmp_path):
    runner = _make_runner(tmp_path)
    status_path = runner.output_dir / "osm2world_status.json"
    status_path.write_text(
        json.dumps({"cache_key": "k1", "status": "failed"}), encoding="utf-8"
    )
    assert runner._check_cache("k1") is None


def test_check_cache_returns_none_for_corrupted_json(tmp_path):
    runner = _make_runner(tmp_path)
    status_path = runner.output_dir / "osm2world_status.json"
    status_path.write_text("{not valid json", encoding="utf-8")
    assert runner._check_cache("k1") is None


# ---------------------------------------------------------------------------
# _validate_osm_input
# ---------------------------------------------------------------------------


def test_validate_osm_input_missing_file(tmp_path):
    runner = _make_runner(tmp_path)
    runner.osm_path = tmp_path / "does_not_exist.osm"
    ok, reason = runner._validate_osm_input()
    assert ok is False
    assert "not found" in reason


def test_validate_osm_input_accepts_osm_extension(tmp_path):
    runner = _make_runner(tmp_path, osm_name="map.osm")
    ok, reason = runner._validate_osm_input()
    assert ok is True


def test_validate_osm_input_rejects_unsupported_extension(tmp_path):
    runner = _make_runner(tmp_path, osm_name="map.geojson")
    ok, reason = runner._validate_osm_input()
    assert ok is False
    assert "Unsupported" in reason


def test_validate_osm_input_rejects_oversized_file(tmp_path):
    runner = _make_runner(tmp_path, osm_name="huge.osm")
    with mock.patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 501 * 1024 * 1024
        ok, reason = runner._validate_osm_input()
    assert ok is False
    assert "too large" in reason


# ---------------------------------------------------------------------------
# _validate_glb (header-only path; Blender validation skipped since
# blender_exe won't exist on this test machine's default path check)
# ---------------------------------------------------------------------------


def test_validate_glb_missing_file(tmp_path):
    runner = _make_runner(tmp_path)
    ok, reason = runner._validate_glb(tmp_path / "missing.glb")
    assert ok is False
    assert "does not exist" in reason


def test_validate_glb_empty_file(tmp_path):
    runner = _make_runner(tmp_path)
    glb = tmp_path / "empty.glb"
    glb.write_bytes(b"")
    ok, reason = runner._validate_glb(glb)
    assert ok is False
    assert "empty" in reason


def test_validate_glb_wrong_header(tmp_path):
    runner = _make_runner(tmp_path)
    glb = tmp_path / "bad.glb"
    glb.write_bytes(b"NOTGLTF_REST_OF_FILE")
    ok, reason = runner._validate_glb(glb)
    assert ok is False
    assert "Invalid GLB header" in reason


def test_validate_glb_valid_header_and_no_blender_available(tmp_path):
    runner = _make_runner(tmp_path)
    runner.blender_exe = tmp_path / "no_such_blender.exe"  # force Blender check to skip
    glb = tmp_path / "good.glb"
    glb.write_bytes(b"glTF" + b"\x00" * 20)
    ok, reason = runner._validate_glb(glb)
    assert ok is True


# ---------------------------------------------------------------------------
# _write_config
# ---------------------------------------------------------------------------


def test_write_config_uses_default_when_no_external_config(tmp_path):
    runner = _make_runner(tmp_path)
    runner.external_config = None
    config_path = runner._write_config()
    assert config_path.exists()
    content = config_path.read_text(encoding="ascii")
    assert "createTerrain=false" in content


def test_write_config_uses_external_config_when_present(tmp_path):
    runner = _make_runner(tmp_path)
    ext_config = tmp_path / "custom.properties"
    ext_config.write_text("customKey=customValue\n", encoding="utf-8")
    runner.external_config = ext_config
    config_path = runner._write_config()
    assert config_path.read_text(encoding="ascii") == "customKey=customValue\n"


def test_write_config_writes_without_bom(tmp_path):
    runner = _make_runner(tmp_path)
    runner.external_config = None
    config_path = runner._write_config()
    raw = config_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")


# ---------------------------------------------------------------------------
# _find_osm2world_entrypoint
# ---------------------------------------------------------------------------


def test_find_entrypoint_returns_none_when_home_missing(tmp_path):
    runner = _make_runner(tmp_path, osm2world_home=str(tmp_path / "no_such_home"))
    cmd, jar_path, hint = runner._find_osm2world_entrypoint()
    assert cmd is None
    assert "not found" in hint


def test_find_entrypoint_prefers_platform_script_over_jar(tmp_path):
    home = tmp_path / "osm2world_home"
    home.mkdir()
    (home / "OSM2World.jar").write_bytes(b"fake jar")
    runner = _make_runner(tmp_path, osm2world_home=str(home))

    import sys as _sys

    if _sys.platform.startswith("win"):
        script = home / "osm2world.bat"
        script.write_text("@echo off\n", encoding="utf-8")
        cmd, jar_path, hint = runner._find_osm2world_entrypoint()
        assert cmd[0] == "cmd.exe"
        assert str(script.resolve()) in cmd
    else:
        script = home / "osm2world.sh"
        script.write_text("#!/bin/sh\n", encoding="utf-8")
        cmd, jar_path, hint = runner._find_osm2world_entrypoint()
        assert cmd == [str(script)]


def test_find_entrypoint_falls_back_to_java_jar_when_no_script(tmp_path):
    home = tmp_path / "osm2world_home"
    home.mkdir()
    (home / "OSM2World-0.3.1.jar").write_bytes(b"fake jar")
    runner = _make_runner(tmp_path, osm2world_home=str(home))
    cmd, jar_path, hint = runner._find_osm2world_entrypoint()
    assert cmd == ["java", "-jar", jar_path]
    assert "OSM2World" in jar_path


def test_find_entrypoint_no_jar_no_script_reports_not_found(tmp_path):
    home = tmp_path / "osm2world_home"
    home.mkdir()
    runner = _make_runner(tmp_path, osm2world_home=str(home))
    cmd, jar_path, hint = runner._find_osm2world_entrypoint()
    assert cmd is None
    assert jar_path == ""


# ---------------------------------------------------------------------------
# OSM2WorldResult.to_dict
# ---------------------------------------------------------------------------


def test_result_to_dict_round_trips_status_and_reason():
    result = OSM2WorldResult(status="ok", reason="all good")
    d = result.to_dict()
    assert d["status"] == "ok"
    assert d["reason"] == "all good"
    assert d["outputs"] == {}
