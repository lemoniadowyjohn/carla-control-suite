# C11 (HIGH) reproducibility fix, step 2: pin generation inputs by digest.
#
# campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json pins
# each generation input's path + sha256 + byte size. A build-time fail-closed
# guard (verify_inputs_manifest) must ABORT (raise) if any pinned input's
# sha256 on disk no longer matches the manifest, so silent input drift can
# never produce an unreproducible "map of record" again.
#
# The building source is NOT yet pinned (C7 hasn't landed / no digest exists
# yet); the manifest documents that key as pending without fabricating a
# digest, and the schema must not need to change once it lands.
from __future__ import annotations

import hashlib
import json

import pytest

from ultimate_pipeline.governance.inputs_manifest import (
    InputsManifestMismatchError,
    compute_manifest_entry,
    load_manifest,
    verify_inputs_manifest,
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_compute_manifest_entry_matches_real_hash(tmp_path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world")
    entry = compute_manifest_entry(f)
    assert entry["sha256"] == _sha256_bytes(b"hello world")
    assert entry["bytes"] == len(b"hello world")


def test_verify_inputs_manifest_passes_when_digests_match(tmp_path) -> None:
    f = tmp_path / "roads.osm"
    f.write_bytes(b"osm-payload")
    manifest = {
        "manifest": "INPUTS_MANIFEST.json",
        "inputs": {
            "roads_osm": {
                "path": "roads.osm",
                "sha256": _sha256_bytes(b"osm-payload"),
                "bytes": len(b"osm-payload"),
                "status": "pinned",
            }
        },
    }
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_inputs_manifest(manifest_path, base_dir=tmp_path)
    assert result["ok"] is True
    assert result["checked"] == ["roads_osm"]


def test_verify_inputs_manifest_fails_closed_on_mismatch(tmp_path) -> None:
    f = tmp_path / "roads.osm"
    f.write_bytes(b"osm-payload-ORIGINAL")
    manifest = {
        "manifest": "INPUTS_MANIFEST.json",
        "inputs": {
            "roads_osm": {
                "path": "roads.osm",
                "sha256": _sha256_bytes(b"osm-payload-ORIGINAL"),
                "bytes": len(b"osm-payload-ORIGINAL"),
                "status": "pinned",
            }
        },
    }
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # Simulate drift: file changes after the manifest was pinned.
    f.write_bytes(b"osm-payload-TAMPERED")

    with pytest.raises(InputsManifestMismatchError):
        verify_inputs_manifest(manifest_path, base_dir=tmp_path)


def test_verify_inputs_manifest_fails_closed_on_missing_file(tmp_path) -> None:
    manifest = {
        "manifest": "INPUTS_MANIFEST.json",
        "inputs": {
            "dem": {
                "path": "does_not_exist.tif",
                "sha256": "0" * 64,
                "bytes": 123,
                "status": "pinned",
            }
        },
    }
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InputsManifestMismatchError):
        verify_inputs_manifest(manifest_path, base_dir=tmp_path)


def test_verify_inputs_manifest_skips_pending_entries(tmp_path) -> None:
    """
    Entries explicitly marked status="pending" (e.g. buildings, awaiting C7)
    must NOT be digest-checked and must NOT block verification — they simply
    document that the input is not yet pinned.
    """
    f = tmp_path / "roads.osm"
    f.write_bytes(b"osm-payload")
    manifest = {
        "manifest": "INPUTS_MANIFEST.json",
        "inputs": {
            "roads_osm": {
                "path": "roads.osm",
                "sha256": _sha256_bytes(b"osm-payload"),
                "bytes": len(b"osm-payload"),
                "status": "pinned",
            },
            "buildings": {
                "path": None,
                "sha256": None,
                "bytes": None,
                "status": "pending",
                "note": "pending C7 (building source not yet available)",
            },
        },
    }
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_inputs_manifest(manifest_path, base_dir=tmp_path)
    assert result["ok"] is True
    assert result["checked"] == ["roads_osm"]
    assert result["pending"] == ["buildings"]


def test_load_manifest_roundtrip(tmp_path) -> None:
    manifest_path = tmp_path / "INPUTS_MANIFEST.json"
    manifest_path.write_text(json.dumps({"inputs": {}}), encoding="utf-8")
    loaded = load_manifest(manifest_path)
    assert loaded == {"inputs": {}}


def test_real_campaign_inputs_manifest_verifies_against_repo(tmp_path) -> None:
    """
    Integration-flavored check against the real, committed manifest: the
    pinned roads OSM and DEM must verify against the actual repo files, and
    the buildings entry must be present but explicitly pending (not
    fabricated).
    """
    from ultimate_pipeline.config.settings import PROJECT_ROOT

    manifest_path = (
        PROJECT_ROOT
        / "campaigns"
        / "ingolstadt_cooked_perception_v1"
        / "source"
        / "INPUTS_MANIFEST.json"
    )
    assert manifest_path.is_file(), f"missing {manifest_path}"

    manifest = load_manifest(manifest_path)
    assert "buildings" in manifest["inputs"]
    assert manifest["inputs"]["buildings"]["status"] == "pending"
    assert manifest["inputs"]["buildings"]["sha256"] is None

    result = verify_inputs_manifest(manifest_path, base_dir=PROJECT_ROOT)
    assert result["ok"] is True
    assert "roads_osm" in result["checked"]
    assert "dem" in result["checked"]
    assert "buildings" in result["pending"]
