"""F11 RQ1 determinism/repeatability synthetic oracle (V135, test-only).

Uses research.rq1_normalization and research.rq1_structural_signature on tiny
synthetic XODR fixtures. Proves 5-repeat canonical/structural digest stability,
formatting/timestamp collapse, and mutation divergence. Does NOT constitute a
real RQ1 five-run authoritative result.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research.rq1_normalization import NORMALIZATION_VERSION, normalize_xodr
from research.rq1_structural_signature import (
    STRUCTURAL_SIGNATURE_VERSION,
    compute_structural_signature,
)

HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<OpenDRIVE>\n'
    '  <header revMajor="1" revMinor="4" name="" version="1.00" '
    'date="{date}" north="10.0" south="0.0" east="10.0" west="0.0"/>\n'
)


def _write_xodr(path: Path, body: str, *, date: str = "2024-01-01T00:00:00", pretty: bool = True) -> Path:
    doc = HEADER.format(date=date) + body + "</OpenDRIVE>\n"
    if not pretty:
        doc = doc.replace("\n  ", "").replace("\n", "")
    path.write_text(doc, encoding="utf-8")
    return path


BASE_BODY = (
    '<road name="R1" length="50.0" id="1" junction="-1">'
    '<link><successor elementType="road" elementId="2" contactPoint="start"/></link>'
    '<planView><geometry s="0" x="0" y="0" hdg="0" length="50.0"><line/></geometry></planView>'
    '<lanes><laneSection s="0">'
    '<center><lane id="0" type="none"/></center>'
    '<right><lane id="-1" type="driving">'
    '<width sOffset="0" a="3.5" b="0.0" c="0.0" d="0.0"/></lane></right>'
    '</laneSection></lanes></road>'
    '<road name="R2" length="50.0" id="2" junction="-1">'
    '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
    '<planView><geometry s="0" x="50" y="0" hdg="0" length="50.0"><line/></geometry></planView>'
    '<lanes><laneSection s="0">'
    '<center><lane id="0" type="none"/></center>'
    '<right><lane id="-1" type="driving">'
    '<width sOffset="0" a="3.5" b="0.0" c="0.0" d="0.0"/></lane></right>'
    '</laneSection></lanes></road>'
)


def test_five_repeats_canonical_and_structural_digests_stable(tmp_path):
    xodr = _write_xodr(tmp_path / "base.xodr", BASE_BODY)
    norm = [normalize_xodr(xodr) for _ in range(5)]
    sig = [compute_structural_signature(xodr) for _ in range(5)]
    assert len({n["sha256"] for n in norm}) == 1
    assert len({n["raw_sha256"] for n in norm}) == 1
    assert len({s["sha256"] for s in sig}) == 1
    assert all(n["normalization_version"] == NORMALIZATION_VERSION for n in norm)
    assert all(s["version"] == STRUCTURAL_SIGNATURE_VERSION for s in sig)


def test_formatting_and_timestamp_only_differences_collapse(tmp_path):
    a = _write_xodr(tmp_path / "a.xodr", BASE_BODY, date="2024-01-01T00:00:00", pretty=True)
    b = _write_xodr(tmp_path / "b.xodr", BASE_BODY, date="2026-11-19T12:34:56", pretty=False)
    na, nb = normalize_xodr(a), normalize_xodr(b)
    sa, sb = compute_structural_signature(a), compute_structural_signature(b)
    assert na["raw_sha256"] != nb["raw_sha256"]
    assert na["sha256"] == nb["sha256"]
    assert sa["sha256"] == sb["sha256"]


@pytest.mark.parametrize(
    "mutated_body,structural_changes",
    [
        # lane topology/connectivity change: both identities must diverge
        (BASE_BODY.replace('elementId="2"', 'elementId="99"'), True),
        # planView geometry numeric change: normalized diverges; structural signature
        # explicitly excludes planView/elevationProfile geometry numerics
        (BASE_BODY.replace('x="50"', 'x="51"'), False),
        # lane width change: width records are part of structural lane-section identity
        (BASE_BODY.replace('a="3.5"', 'a="3.2"', 1), True),
    ],
    ids=["topology", "geometry_excluded_from_structure", "lane_width"],
)
def test_semantic_mutations_diverge_according_to_frozen_contract(tmp_path, mutated_body, structural_changes):
    a = _write_xodr(tmp_path / "a.xodr", BASE_BODY)
    b = _write_xodr(tmp_path / "b.xodr", mutated_body)
    assert normalize_xodr(a)["sha256"] != normalize_xodr(b)["sha256"]
    if structural_changes:
        assert compute_structural_signature(a)["sha256"] != compute_structural_signature(b)["sha256"]
    else:
        assert compute_structural_signature(a)["sha256"] == compute_structural_signature(b)["sha256"]


def test_missing_evidence_fails_closed(tmp_path):
    missing = tmp_path / "does_not_exist.xodr"
    with pytest.raises(Exception):
        normalize_xodr(missing)
    with pytest.raises(Exception):
        compute_structural_signature(missing)


def test_synthetic_repeatability_is_not_authoritative_rq1_evidence(tmp_path):
    # Explicit non-claim marker: this test uses tiny synthetic fixtures only.
    xodr = _write_xodr(tmp_path / "synthetic.xodr", BASE_BODY)
    n = normalize_xodr(xodr)
    s = compute_structural_signature(xodr)
    assert len(n["sha256"]) == 64
    assert len(s["sha256"]) == 64
    assert s["road_count"] == 2
    # Authoritative RQ1 requires real 5-run pipeline receipts on governed inputs;
    # this synthetic fixture does not satisfy that requirement.
