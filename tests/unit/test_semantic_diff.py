from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.artifacts.model import (
    ArtifactRef,
    MutationDeclaration,
    compute_semantic_sha256,
    sha256_of,
)
from ultimate_pipeline.artifacts.semantic_diff import SemanticDiffEngine

PARENT_XML = """<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="10.0"><line /></geometry>
    </planView>
  </road>
  <junction id="5" name="existing_junction">
    <connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start" />
  </junction>
</OpenDRIVE>
"""

# Forbidden domain ("junction") is UNCHANGED relative to the parent; only an
# unrelated attribute (road length) was touched.
CANDIDATE_UNCHANGED_JUNCTION = """<OpenDRIVE>
  <road id="1" length="11.0" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="11.0"><line /></geometry>
    </planView>
  </road>
  <junction id="5" name="existing_junction">
    <connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start" />
  </junction>
</OpenDRIVE>
"""

# Forbidden domain ("junction") IS genuinely changed: a new junction was
# added that did not exist in the parent.
CANDIDATE_CHANGED_JUNCTION = """<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="10.0"><line /></geometry>
    </planView>
  </road>
  <junction id="5" name="existing_junction">
    <connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start" />
  </junction>
  <junction id="9" name="NEW_junction">
    <connection id="0" incomingRoad="1" connectingRoad="3" contactPoint="start" />
  </junction>
</OpenDRIVE>
"""


def _ref(path: Path) -> ArtifactRef:
    return ArtifactRef(
        path=path,
        sha256=sha256_of(path),
        semantic_sha256=compute_semantic_sha256(path),
        parent_sha256=None,
        configuration_sha256="cfg",
        git_sha="abc",
        artifact_type="xodr",
    )


def _declaration() -> MutationDeclaration:
    return MutationDeclaration(
        operation="road-length-tweak",
        allowed_xml_domains=("road",),
        forbidden_xml_domains=("junction",),
        affected_ids=("1",),
    )


def test_unchanged_forbidden_domain_is_not_flagged(tmp_path: Path) -> None:
    """DIFF(parent, candidate) contract: a forbidden domain that already
    existed, unchanged, in the parent must NOT be treated as a mutation --
    nothing actually changed there. Flagging mere presence in the
    candidate (CONTENTS(candidate)) is a false positive.
    """
    parent_path = tmp_path / "parent.xodr"
    candidate_path = tmp_path / "candidate.xodr"
    parent_path.write_text(PARENT_XML, encoding="utf-8")
    candidate_path.write_text(CANDIDATE_UNCHANGED_JUNCTION, encoding="utf-8")

    engine = SemanticDiffEngine("cfg")
    flagged = engine.detect_undeclared_mutation(
        _ref(parent_path), _ref(candidate_path), _declaration()
    )
    assert flagged is False


def test_genuinely_changed_forbidden_domain_is_flagged(tmp_path: Path) -> None:
    parent_path = tmp_path / "parent.xodr"
    candidate_path = tmp_path / "candidate.xodr"
    parent_path.write_text(PARENT_XML, encoding="utf-8")
    candidate_path.write_text(CANDIDATE_CHANGED_JUNCTION, encoding="utf-8")

    engine = SemanticDiffEngine("cfg")
    flagged = engine.detect_undeclared_mutation(
        _ref(parent_path), _ref(candidate_path), _declaration()
    )
    assert flagged is True


def test_no_forbidden_domains_declared_never_flags(tmp_path: Path) -> None:
    parent_path = tmp_path / "parent.xodr"
    candidate_path = tmp_path / "candidate.xodr"
    parent_path.write_text(PARENT_XML, encoding="utf-8")
    candidate_path.write_text(CANDIDATE_CHANGED_JUNCTION, encoding="utf-8")

    engine = SemanticDiffEngine("cfg")
    declaration = MutationDeclaration(
        operation="anything",
        allowed_xml_domains=(),
        forbidden_xml_domains=(),
        affected_ids=(),
    )
    assert engine.detect_undeclared_mutation(_ref(parent_path), _ref(candidate_path), declaration) is False


def test_unparseable_candidate_fails_closed(tmp_path: Path) -> None:
    parent_path = tmp_path / "parent.xodr"
    candidate_path = tmp_path / "candidate.xodr"
    parent_path.write_text(PARENT_XML, encoding="utf-8")
    candidate_path.write_text("not valid xml <<<", encoding="utf-8")

    engine = SemanticDiffEngine("cfg")
    assert engine.detect_undeclared_mutation(_ref(parent_path), _ref(candidate_path), _declaration()) is True


def test_unparseable_parent_fails_closed(tmp_path: Path) -> None:
    parent_path = tmp_path / "parent.xodr"
    candidate_path = tmp_path / "candidate.xodr"
    parent_path.write_text("not valid xml <<<", encoding="utf-8")
    candidate_path.write_text(CANDIDATE_UNCHANGED_JUNCTION, encoding="utf-8")

    engine = SemanticDiffEngine("cfg")
    assert engine.detect_undeclared_mutation(_ref(parent_path), _ref(candidate_path), _declaration()) is True


def test_compute_semantic_sha256_is_a_raw_byte_hash_not_structure_aware(tmp_path: Path) -> None:
    """Characterization test: compute_semantic_sha256() is NOT a
    structure-aware hash despite its name -- it is a plain byte hash
    (identical to sha256_of()). Two XML files that are semantically
    identical (same structure/attributes, different attribute order and
    whitespace) get DIFFERENT 'semantic' hashes.
    """
    a = tmp_path / "a.xodr"
    b = tmp_path / "b.xodr"
    a.write_text('<OpenDRIVE><road id="1" length="10.0" junction="-1"/></OpenDRIVE>', encoding="utf-8")
    b.write_text('<OpenDRIVE>\n  <road junction="-1" length="10.0" id="1"/>\n</OpenDRIVE>\n', encoding="utf-8")

    assert compute_semantic_sha256(a) == sha256_of(a)
    assert compute_semantic_sha256(a) != compute_semantic_sha256(b)
