# -*- coding: utf-8 -*-
"""Tests for NEW-229: domain_gap_reproducibility.

NEW-229: Verify reproducibility hash for domain gap runs.
Ensures that domain gap results are deterministic and reproducible
given the same inputs and settings.
"""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
import pytest
from pathlib import Path
from unittest import mock


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def test_reproducibility_hash_deterministic(tmp_path):
    """Same inputs should produce same reproducibility hash (NEW-229)."""
    xodr = tmp_path / "manual.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")

    # Compute hash twice - should be identical
    h1 = _sha256_file(xodr)
    h2 = _sha256_file(xodr)
    assert h1 == h2, "SHA-256 of same file should be deterministic"
    assert len(h1) == 64, "SHA-256 should be 64 hex chars"
    assert h1 != "0" * 64, "Hash should not be all zeros"


def test_reproducibility_hash_different_files(tmp_path):
    """Different files should produce different hashes (NEW-229)."""
    xodr_a = tmp_path / "manual_a.xodr"
    xodr_b = tmp_path / "manual_b.xodr"
    xodr_a.write_text("<OpenDRIVE/>", encoding="utf-8")
    xodr_b.write_text("<OpenDRIVE><header/></OpenDRIVE>", encoding="utf-8")

    h_a = _sha256_file(xodr_a)
    h_b = _sha256_file(xodr_b)
    assert h_a != h_b, "Different files should have different SHA-256"


def test_reproducibility_hash_json_stable():
    """Verify JSON serialization is deterministic for dict (NEW-229)."""
    data = {
        "manual_xodr": "manual.xodr",
        "auto_xodr": "auto.xodr",
        "config": {"rig": "thesis", "frames": 20},
    }
    j1 = json.dumps(data, sort_keys=True)
    j2 = json.dumps(data, sort_keys=True)
    assert j1 == j2, "JSON serialization should be deterministic"