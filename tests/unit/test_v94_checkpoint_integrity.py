"""V94 RQ4: content-bound GNN checkpoints and restricted deserialization.

CPU-only, offline. Every negative case asserts a concrete refusal instead of
merely checking that some exception occurred.
"""
from __future__ import annotations

import json

import pytest
torch = pytest.importorskip("torch")

from ultimate_pipeline.domain_gap_gnn import gnn_provenance as prov


def _meta():
    return prov.build_checkpoint_metadata(
        graph_schema_sha256="schema-test",
        training_dataset_manifest_sha256="dataset-test",
        tile_selection_sha256="tiles-test",
        source_tile_hashes=[{"tile": "a.xodr", "tile_sha256": "source-test"}],
        selection_seed=11,
        training_seed=12,
        model_config={"node_dim": 12, "hidden_dim": 8},
        training_config={"epochs": 2, "width_mode": "legacy"},
        git_sha="synthetic-test",
        torch_version=str(torch.__version__),
        torch_geometric_version="test",
    )


def _checkpoint(tmp_path):
    path = tmp_path / "encoder.pt"
    prov.save_checkpoint(path, {"weight": torch.ones(2, 2)}, _meta())
    return path


def _sidecar(path):
    return path.with_suffix(path.suffix + ".manifest.json")


def test_verified_roundtrip_binds_checkpoint_bytes_and_metadata(tmp_path, monkeypatch):
    ckpt = _checkpoint(tmp_path)
    manifest = prov.verify_checkpoint_file(ckpt)
    assert manifest["checkpoint_file_sha256"] == prov.sha256_file(ckpt)
    original = torch.load
    def restricted(*args, **kwargs):
        assert kwargs.get("weights_only") is True
        return original(*args, **kwargs)
    monkeypatch.setattr(torch, "load", restricted)
    state, meta, label = prov.load_checkpoint(
        ckpt, expected_schema_hash="schema-test", expected_node_dim=12
    )
    assert torch.equal(state["weight"], torch.ones(2, 2))
    assert meta is not None and meta["training_seed"] == 12
    assert label == prov.VERIFIED_CRYPTOGRAPHIC_PROVENANCE


def test_checkpoint_bytes_changed_fails_before_deserializing(tmp_path, monkeypatch):
    ckpt = _checkpoint(tmp_path)
    with ckpt.open("ab") as out:
        out.write(b"altered")
    def unsafe_to_reach(*args, **kwargs):
        raise AssertionError("deserialization occurred before checksum verification")
    monkeypatch.setattr(torch, "load", unsafe_to_reach)
    with pytest.raises(ValueError, match="checkpoint file SHA-256 mismatch"):
        prov.load_checkpoint(ckpt)


def test_absent_manifest_rejected_for_metadata_checkpoint(tmp_path):
    ckpt = _checkpoint(tmp_path)
    _sidecar(ckpt).unlink()
    with pytest.raises(ValueError, match="missing manifest sidecar"):
        prov.load_checkpoint(ckpt)


def test_missing_checkpoint_rejected_with_existing_manifest(tmp_path):
    ckpt = _checkpoint(tmp_path)
    ckpt.unlink()
    with pytest.raises(ValueError, match="checkpoint file missing"):
        prov.load_checkpoint(ckpt)


def test_sidecar_identity_change_rejected(tmp_path):
    ckpt = _checkpoint(tmp_path)
    manifest = json.loads(_sidecar(ckpt).read_text(encoding="utf-8"))
    manifest["training_seed"] = 99
    _sidecar(ckpt).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="metadata differs from manifest"):
        prov.load_checkpoint(ckpt)


def test_metadata_hash_is_checked_even_if_both_files_are_rehashed(tmp_path):
    ckpt = _checkpoint(tmp_path)
    raw = torch.load(ckpt, map_location="cpu", weights_only=True)
    raw["metadata"]["checkpoint_sha256"] = "0" * 64
    torch.save(raw, ckpt)
    manifest = dict(raw["metadata"])
    manifest["checkpoint_file_sha256"] = prov.sha256_file(ckpt)
    _sidecar(ckpt).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="metadata SHA-256 mismatch"):
        prov.load_checkpoint(ckpt)


def test_checkpoint_replacement_between_verification_and_load_rejected(
    tmp_path, monkeypatch
):
    ckpt = _checkpoint(tmp_path)
    original = prov.verify_checkpoint_file
    def replace_after_verify(path, **kwargs):
        result = original(path, **kwargs)
        ckpt.write_bytes(b"replaced concurrently")
        return result
    monkeypatch.setattr(prov, "verify_checkpoint_file", replace_after_verify)
    with pytest.raises(ValueError, match="changed while loading"):
        prov.load_checkpoint(ckpt)


def test_interrupted_save_preserves_previous_committed_pair(tmp_path, monkeypatch):
    ckpt = _checkpoint(tmp_path)
    prior_checkpoint = ckpt.read_bytes()
    prior_manifest = _sidecar(ckpt).read_bytes()
    def interrupted_save(_payload, handle):
        handle.write(b"incomplete")
        raise OSError("simulated interrupted write")
    monkeypatch.setattr(torch, "save", interrupted_save)
    with pytest.raises(OSError, match="simulated interrupted write"):
        prov.save_checkpoint(ckpt, {"weight": torch.zeros(2, 2)}, _meta())
    assert ckpt.read_bytes() == prior_checkpoint
    assert _sidecar(ckpt).read_bytes() == prior_manifest
    assert not list(tmp_path.glob(".gnn-ckpt-*"))
    assert not list(tmp_path.glob(".gnn-manifest-*"))


def test_legacy_checkpoint_cannot_satisfy_requested_identity(tmp_path):
    ckpt = tmp_path / "legacy.pt"
    torch.save({"model_state": {"w": torch.ones(1)}, "cfg": {"node_dim": 1}}, ckpt)
    _, meta, label = prov.load_checkpoint(ckpt)
    assert meta is None and label == prov.LEGACY_UNBOUND_CHECKPOINT
    with pytest.raises(ValueError, match="legacy checkpoint cannot satisfy expected identity"):
        prov.load_checkpoint(ckpt, expected_schema_hash="schema-test")


def test_strong_manifest_validation_rejects_missing_file_digest(tmp_path):
    ckpt = _checkpoint(tmp_path)
    manifest = json.loads(_sidecar(ckpt).read_text(encoding="utf-8"))
    manifest.pop("checkpoint_file_sha256")
    _sidecar(ckpt).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="missing valid checkpoint_file_sha256"):
        prov.load_checkpoint(ckpt)
