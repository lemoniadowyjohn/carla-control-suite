# tests/unit/test_regen_strict_preconditions.py
# -*- coding: utf-8 -*-
"""
OC-37: canonical regen preconditions.

- verify_inputs_manifest gains strict modes: require_pinned_keys (every key
  must be present AND digest-verified; a pending/missing required key blocks)
  and require_no_pending (any pending entry blocks canonical regeneration).
- regen_map_of_record._verify_manifest(profile) and _check_proj_env() must
  actually use the strict modes (the historical regen path used lenient
  warning-only checks that silently tolerated pending inputs and a foreign
  PROJ environment).
- check_proj_environment() supports reject_foreign_proj (foreign
  PROJ_LIB/PROJ_DATA env var flips ok) and require_layout_known (unknown
  layout minor flips ok) -- both defaulted off to preserve loud-warn mode.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.regen_map_of_record as regen
from ultimate_pipeline.governance.inputs_manifest import (
    InputsManifestError,
    load_manifest,
    verify_inputs_manifest,
)
from ultimate_pipeline.governance.proj_env_guard import (
    ProjEnvironmentError,
    check_proj_environment,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_file(tmp_path: Path, name: str, payload: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(payload)
    return p


def _make_manifest(tmp_path: Path, *, inputs: dict) -> Path:
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    manifest_path.write_text(
        json.dumps({"manifest": str(manifest_path), "campaign": "test", "inputs": inputs}),
        encoding="utf-8",
    )
    return manifest_path


def _pinned(path: Path) -> dict:
    return {
        "path": str(path),
        "sha256": _sha(path.read_bytes()),
        "bytes": path.stat().st_size,
        "status": "pinned",
    }


# ---------------------------------------------------------------------------
# A-D. verify_inputs_manifest strict modes (unit level)
# ---------------------------------------------------------------------------


def test_a_strict_pinned_keys_all_verified(tmp_path):
    osm = _write_file(tmp_path, "roads.osm", b"osm")
    dem = _write_file(tmp_path, "dem.tif", b"tif")
    buildings = _write_file(tmp_path, "b.json", b"{}")
    manifest = _make_manifest(
        tmp_path,
        inputs={
            "roads_osm": _pinned(osm),
            "dem": _pinned(dem),
            "buildings": _pinned(buildings),
        },
    )
    result = verify_inputs_manifest(
        manifest,
        base_dir=tmp_path,
        require_pinned_keys=["roads_osm", "buildings", "dem"],
    )
    assert result["ok"] is True
    assert set(result["checked"]) == {"roads_osm", "buildings", "dem"}
    assert result["required_keys"] == ["roads_osm", "buildings", "dem"]


def test_b_required_key_pending_blocks(tmp_path):
    osm = _write_file(tmp_path, "roads.osm", b"osm")
    manifest = _make_manifest(
        tmp_path,
        inputs={
            "roads_osm": _pinned(osm),
            "buildings": {"path": None, "sha256": None, "bytes": None, "status": "pending"},
        },
    )
    with pytest.raises(InputsManifestError, match="required inputs are not digest verified"):
        verify_inputs_manifest(
            manifest,
            base_dir=tmp_path,
            require_pinned_keys=["roads_osm", "buildings"],
        )


def test_c_required_key_missing_blocks(tmp_path):
    osm = _write_file(tmp_path, "roads.osm", b"osm")
    manifest = _make_manifest(tmp_path, inputs={"roads_osm": _pinned(osm)})
    with pytest.raises(InputsManifestError, match="missing from manifest"):
        verify_inputs_manifest(
            manifest,
            base_dir=tmp_path,
            require_pinned_keys=["roads_osm", "dem"],
        )


def test_d_require_no_pending_blocks_pending_entries(tmp_path):
    osm = _write_file(tmp_path, "roads.osm", b"osm")
    manifest = _make_manifest(
        tmp_path,
        inputs={
            "roads_osm": _pinned(osm),
            "future_input": {"status": "pending"},
        },
    )
    with pytest.raises(InputsManifestError, match="require_no_pending"):
        verify_inputs_manifest(manifest, base_dir=tmp_path, require_no_pending=True)


def test_d_lenient_mode_still_reports_pending(tmp_path):
    osm = _write_file(tmp_path, "roads.osm", b"osm")
    manifest = _make_manifest(
        tmp_path,
        inputs={"roads_osm": _pinned(osm), "future_input": {"status": "pending"}},
    )
    result = verify_inputs_manifest(manifest, base_dir=tmp_path, require_no_pending=False)
    assert result["ok"] is True
    assert result["pending"] == ["future_input"]


# ---------------------------------------------------------------------------
# E-F. regen._verify_manifest(profile) uses the strict modes
# ---------------------------------------------------------------------------


def test_e_regen_verify_manifest_requires_profile_keys(tmp_path, monkeypatch):
    osm = _write_file(tmp_path, "roads.osm", b"osm")
    dem = _write_file(tmp_path, "dem.tif", b"tif")
    buildings = _write_file(tmp_path, "b.json", b"{}")
    manifest = _make_manifest(
        tmp_path,
        inputs={
            "roads_osm": _pinned(osm),
            "dem": _pinned(dem),
            "buildings": _pinned(buildings),
        },
    )
    monkeypatch.setattr(regen, "MANIFEST_PATH", manifest)
    result = regen._verify_manifest("PERCEPTION_RELEASE")
    assert result["ok"] is True
    assert result["required_keys"] == ["roads_osm", "buildings", "dem"]
    assert set(result["checked"]) == {"roads_osm", "dem", "buildings"}
    assert result["unused_keys"] == []
    assert len(result["manifest_sha256"]) == 64


def test_e2_regen_verify_manifest_blocks_pending_buildings(tmp_path, monkeypatch):
    osm = _write_file(tmp_path, "roads.osm", b"osm")
    dem = _write_file(tmp_path, "dem.tif", b"tif")
    manifest = _make_manifest(
        tmp_path,
        inputs={
            "roads_osm": _pinned(osm),
            "dem": _pinned(dem),
            "buildings": {"status": "pending"},
        },
    )
    monkeypatch.setattr(regen, "MANIFEST_PATH", manifest)
    with pytest.raises(RuntimeError, match="required inputs are not digest verified"):
        regen._verify_manifest("PERCEPTION_RELEASE")


def test_f_required_keys_by_profile():
    assert regen._required_input_keys("PERCEPTION_RELEASE") == ["roads_osm", "buildings", "dem"]
    assert regen._required_input_keys("STRUCTURAL_RELEASE") == ["roads_osm"]
    assert regen._required_input_keys("UNKNOWN_PROFILE") == ["roads_osm"]


# ---------------------------------------------------------------------------
# G. regen._check_proj_env must be fail-closed via the probe params
# ---------------------------------------------------------------------------


def test_g_regen_check_proj_env_uses_fail_closed_probe(monkeypatch):
    from ultimate_pipeline.governance import proj_env_guard

    captured = {}

    def _fake_check(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(ok=True, proj_db_layout_version=6.0)

    monkeypatch.setattr(
        "ultimate_pipeline.governance.proj_env_guard.check_proj_environment",
        _fake_check,
    )
    regen._check_proj_env()  # must not raise
    assert captured.get("min_layout_minor") == 6
    assert captured.get("fail_closed") is True
    assert captured.get("reject_foreign_proj") is True
    assert captured.get("require_layout_known") is True


def test_g_regen_check_proj_env_propagates_fail_closed_raise(monkeypatch, tmp_path):
    class _BadReject(ProjEnvironmentError):
        pass

    def _fake_check(**kwargs):
        raise _BadReject("PROJ environment check failed")

    monkeypatch.setattr(
        "ultimate_pipeline.governance.proj_env_guard.check_proj_environment",
        _fake_check,
    )
    with pytest.raises(ProjEnvironmentError, match="PROJ environment check failed"):
        regen._check_proj_env()


# ---------------------------------------------------------------------------
# H-J. check_proj_environment strict flags
# ---------------------------------------------------------------------------


def test_h_reject_foreign_proj_flips_ok(monkeypatch, tmp_path):
    foreign_dir = tmp_path / "foreign_proj"
    foreign_dir.mkdir()
    monkeypatch.setenv("PROJ_LIB", str(foreign_dir))

    report = check_proj_environment(min_layout_minor=0, fail_closed=False)
    # default remains loud-warn: foreign env var is a warning, not a hard fail
    assert report.ok is True
    assert "PROJ_LIB" in report.foreign_proj_vars

    strict = check_proj_environment(
        min_layout_minor=0, fail_closed=False, reject_foreign_proj=True
    )
    assert strict.ok is False
    assert "PROJ_LIB" in strict.foreign_proj_vars
    assert any("reject_foreign_proj" in w for w in strict.warnings)


def test_i_require_layout_known_flips_ok_on_unknown(monkeypatch):
    from ultimate_pipeline.governance import proj_env_guard

    monkeypatch.setattr(proj_env_guard, "_read_proj_db_layout_version", lambda _p: None)

    report = check_proj_environment(min_layout_minor=0, fail_closed=False)
    assert report.ok is True  # unknown layout is still tolerable in loud-warn mode

    strict = check_proj_environment(
        min_layout_minor=0, fail_closed=False, require_layout_known=True
    )
    assert strict.ok is False
    assert any("require_layout_known" in w for w in strict.warnings)


def test_j_require_layout_known_fail_closed_raises(monkeypatch):
    from ultimate_pipeline.governance import proj_env_guard

    monkeypatch.setattr(proj_env_guard, "_read_proj_db_layout_version", lambda _p: None)
    with pytest.raises(ProjEnvironmentError, match="fail_closed=True"):
        check_proj_environment(
            min_layout_minor=0, fail_closed=True, require_layout_known=True
        )


# ---------------------------------------------------------------------------
# K. Provenance: emit_candidate records the strict manifest verification block
# ---------------------------------------------------------------------------


def test_k_emit_candidate_records_manifest_verification(tmp_path, monkeypatch):
    final = _write_file(tmp_path, "final_rebased.xodr", b"<OpenDRIVE/>")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(regen, "CANDIDATE_DIR", tmp_path / "candidate")
    monkeypatch.setattr(regen, "MANIFEST_PATH", Path("unused"))
    monkeypatch.setattr(regen, "compute_structural_signature", lambda _p: {"num_roads": 1})
    monkeypatch.setattr(regen, "_resolve_osm_from_manifest", lambda: final)
    monkeypatch.setattr(regen, "_git_dirty", lambda: [])
    monkeypatch.setattr(regen.subprocess, "check_output", lambda *a, **k: b"deadbeef")

    hashes = {str(final): _sha(b"<OpenDRIVE/>")}

    def _fake_sha(p: Path) -> str:
        return hashes.get(str(p), _sha(p.read_bytes()))

    monkeypatch.setattr(regen, "_sha256_file", _fake_sha)

    manifest_verification = {
        "manifest_sha256": "a" * 64,
        "manifest_schema_version": "C11",
        "profile": "PERCEPTION_RELEASE",
        "required_keys": ["roads_osm", "buildings", "dem"],
        "checked": ["roads_osm", "buildings", "dem"],
        "pending": [],
        "unused_keys": [],
    }
    regen._emit_candidate(
        final,
        out_dir,
        "candidate.xodr",
        {"valid_for_experiments": True},
        manifest_verification=manifest_verification,
    )
    provenance = json.loads((out_dir / "regen_provenance.json").read_text(encoding="utf-8"))
    mv = provenance["manifest_verification"]
    assert mv["manifest_sha256"] == "a" * 64
    assert mv["profile"] == "PERCEPTION_RELEASE"
    assert mv["required"] == ["buildings", "dem", "roads_osm"]
    assert mv["checked"] == ["buildings", "dem", "roads_osm"]
    assert mv["require_no_pending"] is True
    assert (out_dir / "manifest_verification.json").is_file()


# ---------------------------------------------------------------------------
# L. Real manifest integration: the committed campaign manifest must satisfy
#    the strict PERCEPTION_RELEASE requirements on disk (read-only check).
# ---------------------------------------------------------------------------


def test_l_real_campaign_manifest_satisfies_strict_profile():
    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = repo_root / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "INPUTS_MANIFEST.json"
    if not manifest_path.is_file():
        pytest.skip("real campaign manifest not present in this environment")
    manifest = load_manifest(manifest_path)
    assert set(manifest["inputs"]) >= {"roads_osm", "buildings", "dem"}
    result = verify_inputs_manifest(
        manifest_path,
        base_dir=repo_root,
        require_pinned_keys=["roads_osm", "buildings", "dem"],
        require_no_pending=True,
    )
    assert result["ok"] is True