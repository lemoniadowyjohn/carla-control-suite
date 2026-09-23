from __future__ import annotations
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence

from ultimate_pipeline.artifacts.model import (
    ArtifactRef,
    GateResult,
    MutationDeclaration,
    sha256_of,
    compute_semantic_sha256,
)


class SemanticDiffEngine:
    def __init__(self, config_sha256: str):
        self.config_sha256 = config_sha256

    def compare(self, parent: Path, candidate: Path) -> GateResult:
        if not parent.exists():
            return GateResult("semantic_diff", False, "Parent artifact does not exist")
        if not candidate.exists():
            return GateResult("semantic_diff", False, "Candidate artifact does not exist")
        parent_sha = compute_semantic_sha256(parent)
        candidate_sha = compute_semantic_sha256(candidate)
        if parent_sha == candidate_sha:
            return GateResult("semantic_diff", True, "Identical binary content")
        if self._xml_content_equivalent(parent, candidate):
            return GateResult(
                "semantic_diff", True,
                "Semantically equivalent (XML structure + attributes match, non-semantic whitespace ignored)",
            )
        return GateResult(
            "semantic_diff", False,
            "Semantic difference detected",
        )

    def detect_undeclared_mutation(
        self,
        parent_ref: ArtifactRef,
        candidate_ref: ArtifactRef,
        declaration: MutationDeclaration,
    ) -> bool:
        """Flag a forbidden XML domain only if it actually CHANGED between
        parent and candidate -- DIFF(parent, candidate), not
        CONTENTS(candidate). A forbidden domain that already existed,
        unchanged, in the parent is not a mutation: nothing changed there.
        """
        if not declaration.forbidden_xml_domains:
            return False
        try:
            parent_root = ET.parse(parent_ref.path).getroot()
            candidate_root = ET.parse(candidate_ref.path).getroot()
        except ET.ParseError:
            return True
        for domain in declaration.forbidden_xml_domains:
            parent_signatures = sorted(
                self._canonical_signature(elem)
                for elem in parent_root.iter()
                if self._matches_domain(elem, domain)
            )
            candidate_signatures = sorted(
                self._canonical_signature(elem)
                for elem in candidate_root.iter()
                if self._matches_domain(elem, domain)
            )
            if parent_signatures != candidate_signatures:
                return True
        return False

    def _matches_domain(self, elem: ET.Element, domain: str) -> bool:
        return domain in elem.tag or domain in (
            elem.attrib.get("name", ""),
            elem.attrib.get("id", ""),
        )

    def _canonical_signature(self, elem: ET.Element) -> tuple:
        """A structure-aware, order-independent signature of an element's
        full subtree (tag, normalized attributes, normalized text, and
        child signatures), used to detect whether a matched domain
        element's actual content changed -- not just whether an element
        matching the domain merely exists.
        """
        return (
            elem.tag,
            self._normalize_attrib(elem.attrib),
            self._normalize_text(elem.text),
            tuple(self._canonical_signature(child) for child in elem),
        )

    def _xml_content_equivalent(self, a: Path, b: Path) -> bool:
        try:
            ta = ET.parse(a)
            tb = ET.parse(b)
        except ET.ParseError:
            return False
        return self._elements_equivalent(ta.getroot(), tb.getroot())

    def _elements_equivalent(self, ea: ET.Element, eb: ET.Element) -> bool:
        if ea.tag != eb.tag:
            return False
        if self._normalize_attrib(ea.attrib) != self._normalize_attrib(eb.attrib):
            return False
        if self._normalize_text(ea.text) != self._normalize_text(eb.text):
            return False
        if len(ea) != len(eb):
            return False
        return all(self._elements_equivalent(ca, cb) for ca, cb in zip(ea, eb))

    def _normalize_attrib(self, attrib: dict) -> tuple:
        return tuple(sorted((k, v.strip() if isinstance(v, str) else v) for k, v in attrib.items()))

    def _normalize_text(self, text: str | None) -> str:
        return " ".join(text.strip().split()) if text else ""
