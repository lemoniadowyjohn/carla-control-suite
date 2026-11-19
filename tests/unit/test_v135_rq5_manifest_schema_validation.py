"""V135: manifest schema validation must be consistent for file and Mapping inputs.

Covers: unsupported schema, missing schema, malformed nested objects, valid v1,
valid v2, missing v2 receipts; equivalent acceptance/rejection behavior across
file-loaded and in-memory Mapping manifests. No training/eval is performed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ultimate_pipeline.perception import rq5_provenance as prov


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ckpt(tmp_path: Path, data: bytes = b"checkpoint-bytes") -> tuple[Path, str]:
    p = tmp_path / "model.pt"
    p.write_bytes(data)
    return p, _sha(data)


def _base_manifest(sha: str, schema: str = "rq5_model_manifest_v2") -> dict:
    m = {
        "schema": schema,
        "checkpoint": {"sha256": sha},
        "dataset": {"train_identity_sha256": "d" * 64},
        "code": {"commit": "c" * 40},
        "seed": {"seed": 7},
    }
    if schema == "rq5_model_manifest_v2":
        m["split"] = {"split_manifest_sha256": "s" * 64}
        m["pretraining_contract"] = {"type": "random_initialization", "receipt": "r"}
    return m


def _verify_both(ckpt: Path, manifest: dict, *, require_provenance: bool = True):
    mapping_res = prov.verify_checkpoint_manifest(
        ckpt, manifest, require_provenance=require_provenance
    )
    path = ckpt.parent / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        file_res = prov.verify_checkpoint_manifest(
            ckpt, path, require_provenance=require_provenance
        )
        file_exc = None
    except Exception as e:  # noqa: BLE001
        file_res = None
        file_exc = e
    return mapping_res, file_res, file_exc


class TestSchemaConsistency:
    def test_unsupported_schema_rejected_file_and_mapping(self, tmp_path):
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha)
        m["schema"] = "rq5_model_manifest_v3"
        # Remove v2 fields to prove schema is rejected (no bypass via unsupported schema).
        m.pop("split", None)
        m.pop("pretraining_contract", None)
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        with pytest.raises(ValueError):
            prov.verify_checkpoint_manifest(ckpt, dict(m), require_provenance=True)
        with pytest.raises(ValueError):
            prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)
        with pytest.raises(ValueError):
            prov.load_model_manifest(path)

    def test_missing_schema_rejected_file_and_mapping(self, tmp_path):
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha)
        del m["schema"]
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        with pytest.raises(ValueError):
            prov.verify_checkpoint_manifest(ckpt, m, require_provenance=True)
        with pytest.raises(ValueError):
            prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)

    def test_manifest_not_object_rejected_file_and_mapping(self, tmp_path):
        ckpt, _ = _ckpt(tmp_path)
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
        with pytest.raises(ValueError):
            prov.verify_checkpoint_manifest(ckpt, ["not", "an", "object"], require_provenance=True)
        with pytest.raises(ValueError):
            prov.load_model_manifest(path)


class TestBackwardCompatibilityAndV2:
    def test_valid_v1_accepted_file_and_mapping(self, tmp_path):
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha, schema="rq5_model_manifest_v1")
        res_map = prov.verify_checkpoint_manifest(ckpt, m, require_provenance=True)
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        res_file = prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)
        assert res_map["ok"] is True, res_map
        assert res_file["ok"] is True, res_file
        assert res_map["manifest_schema"] == "rq5_model_manifest_v1"

    def test_valid_v2_accepted_file_and_mapping(self, tmp_path):
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha, schema="rq5_model_manifest_v2")
        res_map = prov.verify_checkpoint_manifest(ckpt, m, require_provenance=True)
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        res_file = prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)
        assert res_map["ok"] is True, res_map
        assert res_file["ok"] is True, res_file

    def test_v2_missing_split_receipt_rejected_file_and_mapping(self, tmp_path):
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha)
        m["split"] = {"split_manifest_sha256": ""}
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        res_map = prov.verify_checkpoint_manifest(ckpt, m, require_provenance=True)
        res_file = prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)
        for res in (res_map, res_file):
            assert res["ok"] is False
            assert any("split_manifest_sha256" in f for f in res["failures"])

    def test_v2_missing_pretraining_contract_rejected_file_and_mapping(self, tmp_path):
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha)
        m["pretraining_contract"] = ""
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        res_map = prov.verify_checkpoint_manifest(ckpt, m, require_provenance=True)
        res_file = prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)
        for res in (res_map, res_file):
            assert res["ok"] is False
            assert any("pretraining_contract" in f for f in res["failures"])

    def test_v2_missing_both_receipts_rejected_file_and_mapping(self, tmp_path):
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha)
        m["split"] = None
        m["pretraining_contract"] = None
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        res_map = prov.verify_checkpoint_manifest(ckpt, m, require_provenance=True)
        res_file = prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)
        for res in (res_map, res_file):
            assert res["ok"] is False
            joined = " ".join(res["failures"])
            assert "split_manifest_sha256" in joined
            assert "pretraining_contract" in joined

    def test_unsupported_schema_cannot_bypass_v2_receipts(self, tmp_path):
        # An attacker/bug might try schema 'v3' with missing receipts to dodge v2 checks.
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha)
        m["schema"] = "rq5_model_manifest_v3"
        m["split"] = {}
        m["pretraining_contract"] = None
        with pytest.raises(ValueError):
            prov.verify_checkpoint_manifest(ckpt, m, require_provenance=True)
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        with pytest.raises(ValueError):
            prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)


class TestMalformedNestedObjects:
    def test_malformed_checkpoint_field_fails_equivalently(self, tmp_path):
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha)
        m["checkpoint"] = "not-an-object"
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        res_map = prov.verify_checkpoint_manifest(ckpt, m, require_provenance=True)
        res_file = prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)
        for res in (res_map, res_file):
            assert res["ok"] is False
            assert any("checkpoint" in f for f in res["failures"])

    def test_malformed_dataset_code_seed_fail_equivalently(self, tmp_path):
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha)
        m["dataset"] = "bad"
        m["code"] = ["bad"]
        m["seed"] = 7  # should be an object carrying seed
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        res_map = prov.verify_checkpoint_manifest(ckpt, m, require_provenance=True)
        res_file = prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)
        for res in (res_map, res_file):
            assert res["ok"] is False
            joined = " ".join(res["failures"]).lower()
            assert "dataset" in joined
            assert "code" in joined
            assert "seed" in joined

    def test_malformed_split_object_fails_v2(self, tmp_path):
        ckpt, sha = _ckpt(tmp_path)
        m = _base_manifest(sha)
        m["split"] = "not-an-object"
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(m), encoding="utf-8")
        res_map = prov.verify_checkpoint_manifest(ckpt, m, require_provenance=True)
        res_file = prov.verify_checkpoint_manifest(ckpt, path, require_provenance=True)
        for res in (res_map, res_file):
            assert res["ok"] is False
            assert any("split_manifest_sha256" in f for f in res["failures"])
