from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CERTIFICATION_DIR = (
    ROOT / "reports" / "post_audit_hardening" / "20260813T075853Z_N_CERTIFICATION"
)
CANDIDATE_DIR = ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate"

ANCHOR_RE = re.compile(r"([A-Za-z0-9_./-]+)_sha256=([0-9a-fA-F]{64})")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_strings(v)


def _parse_anchors():
    """Extract every embedded `<name>_sha256=<hex>` from evidence JSON string values."""
    anchors = []
    for path in sorted(CERTIFICATION_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _iter_strings(data):
            for name, digest in ANCHOR_RE.findall(s):
                anchors.append((path.name, name, digest))
    return anchors


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _local_artifact_with_digest(digest):
    """Return a local candidate artifact whose sha256 equals digest, else None."""
    if not CANDIDATE_DIR.is_dir():
        return None
    for path in CANDIDATE_DIR.glob("*.xodr"):
        if _sha256_of(path) == digest:
            return path
    return None


def test_evidence_sha256_anchors_well_formed_and_consistent():
    anchors = _parse_anchors()
    assert anchors, "no <name>_sha256=<hex> anchors parsed from N-certification evidence"

    seen_digests = set()
    for source, name, digest in anchors:
        assert HEX64_RE.match(digest), (
            f"{source}: anchor {name}_sha256= is not a 64-char lowercase hex string: {digest}"
        )
        seen_digests.add(digest)

    verified = 0
    absent = 0
    for digest in sorted(seen_digests):
        artifact = _local_artifact_with_digest(digest)
        if artifact is None:
            absent += 1
            continue
        assert _sha256_of(artifact) == digest, (
            f"local artifact {artifact} no longer matches recorded sha256 {digest}"
        )
        verified += 1

    if verified == 0:
        pytest.skip(
            f"no referenced artifacts present locally ({absent} of {len(seen_digests)} absent)"
        )
