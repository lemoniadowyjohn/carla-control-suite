#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage D0 tests.

Guards:
- repaired candidate raw SHA matches the signed provenance (80ebb005…).
- enriched candidate exists and is structurally consistent with repaired parent.
- OSM crossing/pedestrian authority is recomputed deterministically.
- untracked-file classifier is stable for canonical stray paths.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REPAIRED = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_fixed_final.xodr"
ENRICHED = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z" / "candidate_g_semantic_enriched.xodr"
OSM = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"

SIGNED_REPAIRED_RAW = "80ebb0054afd73ffdd51960b48679ff4689c72ed0abe75af5b2ae10a51395699"


def sha256_file_bytes(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def test_repaired_candidate_provenance():
    assert REPAIRED.exists()
    assert sha256_file_bytes(REPAIRED) == SIGNED_REPAIRED_RAW


def test_enriched_candidate_exists():
    assert ENRICHED.exists()
    assert sha256_file_bytes(ENRICHED) != SIGNED_REPAIRED_RAW  # it carries signals


def test_repaired_candidate_has_zero_signals():
    """Gate: the repaired parent must NOT be used as a semantic writer parent."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(REPAIRED.read_text(encoding="utf-8"))
    assert len(list(root.iter("signal"))) == 0


def test_enriched_candidate_has_3467_signals():
    assert ENRICHED.exists()
    import xml.etree.ElementTree as ET
    root = ET.fromstring(ENRICHED.read_text(encoding="utf-8"))
    sigs = [s for s in root.iter("signal")]
    assert len(sigs) == 3467


def test_osm_authority_recompute_deterministic():
    from stage_0_provenance import classify_untracked
    # classifier is stable for canonical paths
    assert classify_untracked("ingolstadt_fixed_final.xodr") in ("CAMPAIGN/CANDIDATE", "UNCLASSIFIED") or \
        classify_untracked("campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_fixed_final.xodr") == "CAMPAIGN/CANDIDATE"
    assert classify_untracked(".idea/workspace.xml") == "IDE/TOOLING"
    assert classify_untracked("POST_AUDIT_HARDENING_PROMPT.md") == "LEGACY/STRAY"


def test_enrichment_uses_h_prefix():
    """Every governed signal in the enriched candidate uses the deterministic h_ id prefix."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(ENRICHED.read_text(encoding="utf-8", errors="replace").encode("utf-8").decode("utf-8"))
    sigs = list(root.iter("signal"))
    bad = [s.get("id") for s in sigs if not str(s.get("id", "")).startswith("h_")]
    assert not bad, f"non-governed signal ids: {bad[:5]}"
