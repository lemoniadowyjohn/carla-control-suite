"""V111 regression: a valid seed must not bypass RQ5 v2 provenance gates."""
from __future__ import annotations

import hashlib

import pytest

from ultimate_pipeline.perception.rq5_provenance import verify_checkpoint_manifest


def _manifest(path, *, schema="rq5_model_manifest_v2", split=None, pretraining=None):
    return {
        "schema": schema,
        "checkpoint": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        "dataset": {"train_identity_sha256": "a" * 64},
        "code": {"commit": "b" * 40},
        "seed": {"seed": 42},  # nonempty on purpose: bypassed old indentation
        "split": split,
        "pretraining_contract": pretraining,
    }


@pytest.mark.parametrize(
    ("split", "pretraining", "expected"),
    [
        (None, None, ("split_manifest_sha256", "pretraining_contract")),
        ({"split_manifest_sha256": "c" * 64}, None, ("pretraining_contract",)),
        (None, {"initialization": "verified"}, ("split_manifest_sha256",)),
    ],
)
def test_v2_requires_split_and_pretraining_independently_of_seed(
    tmp_path, split, pretraining, expected
):
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"fake valid fixed test checkpoint")
    result = verify_checkpoint_manifest(
        checkpoint, _manifest(checkpoint, split=split, pretraining=pretraining),
        require_provenance=True,
    )
    assert result["ok"] is False
    for marker in expected:
        assert any(marker in failure for failure in result["failures"])
    assert not any("seed" in failure for failure in result["failures"])


def test_v2_with_both_contracts_passes(tmp_path):
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"checkpoint with bound evidence")
    result = verify_checkpoint_manifest(
        checkpoint,
        _manifest(
            checkpoint,
            split={"split_manifest_sha256": "c" * 64},
            pretraining={"initialization": "verified"},
        ),
        require_provenance=True,
    )
    assert result["ok"] is True, result["failures"]


def test_v1_compatibility_not_affected(tmp_path):
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"v1 checkpoint")
    result = verify_checkpoint_manifest(
        checkpoint, _manifest(checkpoint, schema="rq5_model_manifest_v1"),
        require_provenance=True,
    )
    assert result["ok"] is True, result["failures"]


def test_optional_provenance_mode_keeps_legacy_diagnostic_compatibility(tmp_path):
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"diagnostic checkpoint")
    result = verify_checkpoint_manifest(
        checkpoint, _manifest(checkpoint), require_provenance=False,
    )
    assert result["ok"] is True, result["failures"]
