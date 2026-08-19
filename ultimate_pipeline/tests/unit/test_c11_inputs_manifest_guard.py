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
    pinned inputs (roads OSM, DEM, buildings) must verify against the actual
    repo files. The buildings entry was deliberately re-pinned (C11) after
    its earlier pending state, since a manual diff showed the on-disk file
    matches the captured Overpass response byte-for-byte.
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
    assert manifest["inputs"]["buildings"]["status"] == "pinned"
    assert manifest["inputs"]["buildings"]["sha256"] is not None

    result = verify_inputs_manifest(manifest_path, base_dir=PROJECT_ROOT)
    assert result["ok"] is True
    assert "roads_osm" in result["checked"]
    assert "dem" in result["checked"]
    assert "buildings" in result["checked"]
    assert not result["pending"]


# ---------------------------------------------------------------------------
# Pipeline wrapper: MainPipeline._verify_pinned_inputs
# 1. no-op when no INPUTS_MANIFEST is configured,
# 2. verifies every 'pinned' entry when a manifest is configured,
# 3. ABORTs (raises) on any mismatch — a drifted input must never be
#    silently regenerated from.
# ---------------------------------------------------------------------------

class _DummySettings:
    """Minimal settings stand-in (only the fields the guard touches)."""

    def __init__(self, manifest: str = ""):
        self.INPUTS_MANIFEST = manifest

    def output_dir(self) -> str:
        return "."

    def logs_dir(self) -> str:
        return "."


def _make_wrapper_manifest(tmp_path, *, inputs: dict | None = None) -> str:
    manifest = {
        "manifest": "tmp/INPUTS_MANIFEST.json",
        "campaign": "test",
        "inputs": inputs
        or {
            "road_a": {
                "path": str(tmp_path / "road_a.osm"),
                "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                "bytes": 0,
                "status": "pinned",
            },
        },
    }
    path = tmp_path / "INPUTS_MANIFEST.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return str(path)


def test_guard_is_noop_without_manifest(tmp_path) -> None:
    from ultimate_pipeline.main_pipeline import MainPipeline

    mp = MainPipeline(settings=_DummySettings(manifest=""))
    mp._verify_pinned_inputs()  # must not raise


def test_guard_verifies_pinned_inputs(tmp_path) -> None:
    from ultimate_pipeline.main_pipeline import MainPipeline

    payload = b"same bytes"
    (tmp_path / "road_a.osm").write_bytes(payload)
    manifest_path = _make_wrapper_manifest(
        tmp_path,
        inputs={
            "road_a": {
                "path": str(tmp_path / "road_a.osm"),
                "sha256": _sha256_bytes(payload),
                "bytes": len(payload),
                "status": "pinned",
            },
        },
    )
    mp = MainPipeline(settings=_DummySettings(manifest=manifest_path))
    mp._verify_pinned_inputs()  # must not raise


def test_guard_aborts_on_drifted_input(tmp_path) -> None:
    from ultimate_pipeline.main_pipeline import MainPipeline

    (tmp_path / "road_a.osm").write_bytes(b"drifted bytes")
    manifest_path = _make_wrapper_manifest(
        tmp_path,
        inputs={
            "road_a": {
                "path": str(tmp_path / "road_a.osm"),
                "sha256": _sha256_bytes(b"same bytes"),
                "bytes": 10,
                "status": "pinned",
            },
        },
    )
    mp = MainPipeline(settings=_DummySettings(manifest=manifest_path))
    with pytest.raises(RuntimeError, match="ABORT"):
        mp._verify_pinned_inputs()


def test_guard_aborts_on_missing_pinned_input(tmp_path) -> None:
    from ultimate_pipeline.main_pipeline import MainPipeline

    manifest_path = _make_wrapper_manifest(tmp_path)  # road_a.osm never created
    mp = MainPipeline(settings=_DummySettings(manifest=manifest_path))
    with pytest.raises(RuntimeError, match="ABORT"):
        mp._verify_pinned_inputs()


def test_guard_aborts_when_manifest_missing(tmp_path) -> None:
    from ultimate_pipeline.main_pipeline import MainPipeline

    mp = MainPipeline(settings=_DummySettings(manifest=str(tmp_path / "nope.json")))
    with pytest.raises(FileNotFoundError):
        mp._verify_pinned_inputs()


def test_guard_tolerates_pending_entries(tmp_path) -> None:
    from ultimate_pipeline.main_pipeline import MainPipeline

    payload = b"same bytes"
    (tmp_path / "road_a.osm").write_bytes(payload)
    manifest_path = _make_wrapper_manifest(
        tmp_path,
        inputs={
            "road_a": {
                "path": str(tmp_path / "road_a.osm"),
                "sha256": _sha256_bytes(payload),
                "bytes": len(payload),
                "status": "pinned",
            },
            "future_input": {
                "path": None,
                "sha256": None,
                "bytes": None,
                "status": "pending",
            },
        },
    )
    mp = MainPipeline(settings=_DummySettings(manifest=manifest_path))
    mp._verify_pinned_inputs()  # pending entries are reported, never checked
