from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.artifacts import (
    ArtifactStore,
    ArtifactTransaction,
    PromotionEngine,
    RecoveryEngine,
    SemanticDiffEngine,
)
from ultimate_pipeline.artifacts.errors import CandidateValidationError
from ultimate_pipeline.artifacts.model import sha256_of


def _write_xodr(path: Path, *, road_id: str = "1") -> None:
    path.write_text(
        f"""<OpenDRIVE>
  <road id="{road_id}" length="10.0" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="10.0"><line /></geometry>
    </planView>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def _transaction(root: Path) -> tuple[ArtifactStore, ArtifactTransaction]:
    store = ArtifactStore(root, git_sha="abc123", configuration_sha256="cfg123")
    store.create_run()
    tx = ArtifactTransaction(
        store=store,
        semantic_diff=SemanticDiffEngine("cfg123"),
        promotion=PromotionEngine(),
    )
    return store, tx


def test_parent_is_persisted_and_candidate_promotes_atomically(tmp_path: Path) -> None:
    parent = tmp_path / "parent.xodr"
    candidate = tmp_path / "candidate.xodr"
    _write_xodr(parent)
    _write_xodr(candidate)

    store, tx = _transaction(tmp_path / "store")
    parent_ref = store.set_parent(parent, "xodr")

    result = tx.propose_candidate(
        "candidate-001",
        candidate,
        "xodr",
        tx.declare_mutation("identity-roundtrip"),
    )

    manifest = store.current_manifest
    assert result.status == "PASS"
    assert manifest is not None
    assert manifest.accepted is not None
    assert manifest.accepted.path.exists()
    assert "accepted" in manifest.accepted.path.parts
    assert manifest.accepted.parent_sha256 == parent_ref.sha256
    assert sha256_of(manifest.accepted.path) == manifest.accepted.sha256
    RecoveryEngine().require_integrity(store)


def test_failed_candidate_does_not_move_accepted_pointer(tmp_path: Path) -> None:
    parent = tmp_path / "parent.xodr"
    candidate = tmp_path / "candidate.xodr"
    _write_xodr(parent, road_id="1")
    _write_xodr(candidate, road_id="2")

    store, tx = _transaction(tmp_path / "store")
    parent_ref = store.set_parent(parent, "xodr")

    result = tx.propose_candidate(
        "candidate-002",
        candidate,
        "xodr",
        tx.declare_mutation("unexpected-road-change"),
    )

    manifest = store.current_manifest
    assert result.status == "FAIL"
    assert manifest is not None
    assert manifest.accepted is not None
    assert manifest.accepted.sha256 == parent_ref.sha256
    assert "candidate-002" in manifest.rejected
    assert "candidate-002" not in manifest.candidates


def test_candidate_id_must_be_path_safe(tmp_path: Path) -> None:
    parent = tmp_path / "parent.xodr"
    candidate = tmp_path / "candidate.xodr"
    _write_xodr(parent)
    _write_xodr(candidate)

    store, tx = _transaction(tmp_path / "store")
    store.set_parent(parent, "xodr")

    with pytest.raises(CandidateValidationError, match="path-safe"):
        tx.propose_candidate("../escape", candidate, "xodr", tx.declare_mutation("bad-id"))
