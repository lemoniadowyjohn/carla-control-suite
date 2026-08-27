"""ultimate_pipeline/governance/inputs_manifest.py -- C11's fail-closed digest guard for
pinned generation inputs, relied on all session (via validate_thesis_claim_provenance.py's
_verify_inputs_manifest and the canonical regen path's _verify_manifest) but never directly
tested itself on this branch -- found while sweeping orphaned .pyc files with no matching .py
source. Small and pure enough to cover exhaustively.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ultimate_pipeline.governance.inputs_manifest import (
    InputsManifestError,
    InputsManifestMismatchError,
    sha256_file,
    compute_manifest_entry,
    load_manifest,
    verify_inputs_manifest,
)


def _write_manifest(path: Path, inputs: dict) -> None:
    path.write_text(json.dumps({"manifest": str(path), "inputs": inputs}), encoding="utf-8")


# ---------------------------------------------------------------------------
# sha256_file / compute_manifest_entry / load_manifest
# ---------------------------------------------------------------------------

def test_sha256_file_matches_known_hash(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world")
    assert sha256_file(p) == hashlib.sha256(b"hello world").hexdigest()


def test_sha256_file_streams_large_content_correctly(tmp_path: Path):
    # Exercise the chunked-read loop (1 MiB chunks) with content spanning multiple chunks.
    p = tmp_path / "big.bin"
    content = b"x" * (2 * (1 << 20) + 137)  # a bit over 2 MiB, not a clean chunk multiple
    p.write_bytes(content)
    assert sha256_file(p) == hashlib.sha256(content).hexdigest()


def test_compute_manifest_entry_returns_sha_and_bytes(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"real content")
    entry = compute_manifest_entry(p)
    assert entry["sha256"] == hashlib.sha256(b"real content").hexdigest()
    assert entry["bytes"] == len(b"real content")


def test_load_manifest_parses_json(tmp_path: Path):
    p = tmp_path / "manifest.json"
    _write_manifest(p, {"a": {"status": "pending"}})
    manifest = load_manifest(p)
    assert manifest["inputs"]["a"]["status"] == "pending"


# ---------------------------------------------------------------------------
# verify_inputs_manifest -- happy paths
# ---------------------------------------------------------------------------

def test_verify_all_pinned_entries_matching_passes(tmp_path: Path):
    data_file = tmp_path / "osm.osm"
    data_file.write_bytes(b"osm data")
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {
        "roads_osm": {
            "path": "osm.osm", "sha256": sha256_file(data_file),
            "bytes": data_file.stat().st_size, "status": "pinned",
        },
    })
    result = verify_inputs_manifest(manifest_path, base_dir=tmp_path)
    assert result["ok"] is True
    assert result["checked"] == ["roads_osm"]
    assert result["pending"] == []


def test_verify_pending_entries_never_digest_checked(tmp_path: Path):
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {
        "buildings": {"status": "pending", "note": "not yet pinned"},
    })
    # Deliberately no path/sha256/bytes at all, and no file on disk -- must NOT raise.
    result = verify_inputs_manifest(manifest_path, base_dir=tmp_path)
    assert result["ok"] is True
    assert result["pending"] == ["buildings"]
    assert result["checked"] == []


def test_verify_mixed_pinned_and_pending(tmp_path: Path):
    data_file = tmp_path / "dem.tif"
    data_file.write_bytes(b"dem raster")
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {
        "dem": {"path": "dem.tif", "sha256": sha256_file(data_file),
                "bytes": data_file.stat().st_size, "status": "pinned"},
        "buildings": {"status": "pending"},
    })
    result = verify_inputs_manifest(manifest_path, base_dir=tmp_path)
    assert result["checked"] == ["dem"]
    assert result["pending"] == ["buildings"]


def test_verify_absolute_path_used_as_is_not_joined_with_base_dir(tmp_path: Path):
    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()
    data_file = other_dir / "osm.osm"
    data_file.write_bytes(b"osm data")
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {
        "roads_osm": {
            "path": str(data_file.resolve()), "sha256": sha256_file(data_file),
            "bytes": data_file.stat().st_size, "status": "pinned",
        },
    })
    # base_dir is tmp_path, but the manifest's path is absolute (points into "elsewhere") --
    # must resolve to the absolute path directly, not tmp_path/<abs path> (which wouldn't exist).
    result = verify_inputs_manifest(manifest_path, base_dir=tmp_path)
    assert result["checked"] == ["roads_osm"]


# ---------------------------------------------------------------------------
# verify_inputs_manifest -- fail-closed ABORT paths (MismatchError)
# ---------------------------------------------------------------------------

def test_verify_missing_file_raises_mismatch(tmp_path: Path):
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {
        "roads_osm": {"path": "does_not_exist.osm", "sha256": "a" * 64,
                      "bytes": 100, "status": "pinned"},
    })
    with pytest.raises(InputsManifestMismatchError, match="not found on disk"):
        verify_inputs_manifest(manifest_path, base_dir=tmp_path)


def test_verify_size_mismatch_raises_mismatch(tmp_path: Path):
    data_file = tmp_path / "osm.osm"
    data_file.write_bytes(b"osm data")
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {
        "roads_osm": {"path": "osm.osm", "sha256": sha256_file(data_file),
                      "bytes": 999999, "status": "pinned"},
    })
    with pytest.raises(InputsManifestMismatchError, match="size mismatch"):
        verify_inputs_manifest(manifest_path, base_dir=tmp_path)


def test_verify_sha256_mismatch_raises_mismatch_even_when_size_matches(tmp_path: Path):
    data_file = tmp_path / "osm.osm"
    data_file.write_bytes(b"osm data - drifted since pinning")
    wrong_sha = hashlib.sha256(b"original pinned content!").hexdigest()
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {
        "roads_osm": {"path": "osm.osm", "sha256": wrong_sha,
                      "bytes": data_file.stat().st_size, "status": "pinned"},
    })
    with pytest.raises(InputsManifestMismatchError, match="sha256 mismatch"):
        verify_inputs_manifest(manifest_path, base_dir=tmp_path)


def test_verify_sha256_comparison_is_case_insensitive(tmp_path: Path):
    data_file = tmp_path / "osm.osm"
    data_file.write_bytes(b"osm data")
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {
        "roads_osm": {"path": "osm.osm", "sha256": sha256_file(data_file).upper(),
                      "bytes": data_file.stat().st_size, "status": "pinned"},
    })
    result = verify_inputs_manifest(manifest_path, base_dir=tmp_path)
    assert result["checked"] == ["roads_osm"]


# ---------------------------------------------------------------------------
# verify_inputs_manifest -- malformed-manifest paths (InputsManifestError)
# ---------------------------------------------------------------------------

def test_verify_missing_inputs_key_raises_error(tmp_path: Path):
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    manifest_path.write_text(json.dumps({"manifest": "x"}), encoding="utf-8")
    with pytest.raises(InputsManifestError, match="missing an 'inputs' object"):
        verify_inputs_manifest(manifest_path, base_dir=tmp_path)


def test_verify_entry_not_a_dict_raises_error(tmp_path: Path):
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {"roads_osm": "not an object"})
    with pytest.raises(InputsManifestError, match="is not an object"):
        verify_inputs_manifest(manifest_path, base_dir=tmp_path)


def test_verify_unrecognized_status_raises_error(tmp_path: Path):
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {"roads_osm": {"status": "maybe"}})
    with pytest.raises(InputsManifestError, match="unrecognized status"):
        verify_inputs_manifest(manifest_path, base_dir=tmp_path)


def test_verify_pinned_entry_missing_sha256_raises_error(tmp_path: Path):
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {
        "roads_osm": {"path": "osm.osm", "bytes": 100, "status": "pinned"},
    })
    with pytest.raises(InputsManifestError, match="missing path/sha256/bytes"):
        verify_inputs_manifest(manifest_path, base_dir=tmp_path)


def test_verify_pinned_entry_missing_bytes_raises_error(tmp_path: Path):
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    _write_manifest(manifest_path, {
        "roads_osm": {"path": "osm.osm", "sha256": "a" * 64, "status": "pinned"},
    })
    with pytest.raises(InputsManifestError, match="missing path/sha256/bytes"):
        verify_inputs_manifest(manifest_path, base_dir=tmp_path)


# ---------------------------------------------------------------------------
# Real repo integration: the actual campaign manifest this session relies on
# ---------------------------------------------------------------------------

def test_real_campaign_manifest_verifies_clean():
    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = (
        repo_root / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "INPUTS_MANIFEST.json"
    )
    if not manifest_path.is_file():
        pytest.skip("real campaign manifest not present in this environment")
    result = verify_inputs_manifest(manifest_path, base_dir=repo_root)
    assert result["ok"] is True
