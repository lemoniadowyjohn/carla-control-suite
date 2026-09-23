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
from ultimate_pipeline.artifacts.model import Manifest


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


def _write_xodr_with_junction(path: Path, *, road_length: str = "10.0", extra_junction: str = "") -> None:
    path.write_text(
        f"""<OpenDRIVE>
  <road id="1" length="{road_length}" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="{road_length}"><line /></geometry>
    </planView>
  </road>
  <junction id="5" name="existing_junction">
    <connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start" />
  </junction>
  {extra_junction}
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


def test_forbidden_domain_unchanged_from_parent_is_not_blocked(tmp_path: Path) -> None:
    """End-to-end regression for the transaction.py wiring: propose_candidate
    must pass the parent ArtifactRef through to detect_undeclared_mutation
    (DIFF(parent, candidate)), not just the candidate's contents. A
    forbidden domain ("junction") that already existed, byte-for-byte
    unchanged, in the parent must not be reported as an undeclared
    mutation just because an unrelated attribute (road length) changed
    elsewhere -- that unrelated change is caught (correctly, and outside
    this audit's scope) by the separate, stricter "validation" gate, but
    the "undeclared_mutation" gate specifically must not fire.
    """
    parent = tmp_path / "parent.xodr"
    candidate = tmp_path / "candidate.xodr"
    _write_xodr_with_junction(parent, road_length="10.0")
    _write_xodr_with_junction(candidate, road_length="11.0")  # unrelated change

    store, tx = _transaction(tmp_path / "store")
    store.set_parent(parent, "xodr")

    result = tx.propose_candidate(
        "candidate-unchanged-junction",
        candidate,
        "xodr",
        tx.declare_mutation("road-length-tweak", forbidden_xml_domains=("junction",)),
    )

    assert result.status != "BLOCKED"
    assert "Undeclared mutation detected" not in result.blockers
    undeclared_gates = [g for g in result.gate_results if g.gate_name == "undeclared_mutation"]
    assert undeclared_gates == []


def test_forbidden_domain_genuinely_changed_is_blocked(tmp_path: Path) -> None:
    parent = tmp_path / "parent.xodr"
    candidate = tmp_path / "candidate.xodr"
    _write_xodr_with_junction(parent, road_length="10.0")
    _write_xodr_with_junction(
        candidate,
        road_length="10.0",
        extra_junction='<junction id="9" name="NEW_junction"><connection id="0" incomingRoad="1" connectingRoad="3" contactPoint="start" /></junction>',
    )

    store, tx = _transaction(tmp_path / "store")
    store.set_parent(parent, "xodr")

    result = tx.propose_candidate(
        "candidate-changed-junction",
        candidate,
        "xodr",
        tx.declare_mutation("road-length-tweak", forbidden_xml_domains=("junction",)),
    )

    assert result.status == "BLOCKED"
    assert "Undeclared mutation detected" in result.blockers


def test_candidate_manifest_roundtrip_reconstructs_mutation_declaration(tmp_path: Path) -> None:
    parent = tmp_path / "parent.xodr"
    candidate = tmp_path / "candidate.xodr"
    _write_xodr(parent)
    _write_xodr(candidate)
    store, tx = _transaction(tmp_path / "store")
    store.set_parent(parent, "xodr")
    assert tx.propose_candidate("candidate-roundtrip", candidate, "xodr", tx.declare_mutation("identity")).status == "PASS"
    path = store.root / "manifest.json"
    reloaded = Manifest.load(path)
    reloaded.save(path)
    assert Manifest.load(path).candidates["candidate-roundtrip"].mutation_declaration.operation == "identity"
