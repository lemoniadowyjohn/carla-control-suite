"""ultimate_pipeline/utils/file_hashing.py -- the single source of truth for file hashing
across the pipeline (per its own module docstring). Widely depended on by provenance-critical
modules: xodr_hash_gate.py, run_manifest.py, map_acceptance.py, artifact_integrity_check.py,
quarantine_bad_roads.py, and 9 others. Found untested via the orphaned-.pyc sweep.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ultimate_pipeline.utils.file_hashing import (
    hash_file,
    md5_file,
    safe_md5_file,
    safe_sha256_file,
    sha256_file,
)


# ---------------------------------------------------------------------------
# sha256_file / md5_file
# ---------------------------------------------------------------------------

def test_sha256_file_matches_known_digest(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world")
    assert sha256_file(p) == hashlib.sha256(b"hello world").hexdigest()


def test_md5_file_matches_known_digest(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world")
    assert md5_file(p) == hashlib.md5(b"hello world").hexdigest()


def test_sha256_file_streams_across_multiple_chunks(tmp_path: Path):
    p = tmp_path / "big.bin"
    content = b"y" * (3 * (1 << 20) + 7)  # >3 MiB, not a clean multiple of the 1 MiB chunk size
    p.write_bytes(content)
    assert sha256_file(p, chunk_size=1024 * 1024) == hashlib.sha256(content).hexdigest()


def test_sha256_file_respects_custom_chunk_size(tmp_path: Path):
    p = tmp_path / "f.bin"
    content = b"abcdefghij" * 100
    p.write_bytes(content)
    assert sha256_file(p, chunk_size=7) == hashlib.sha256(content).hexdigest()


def test_sha256_file_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        sha256_file("does_not_exist_anywhere.bin")


def test_sha256_file_empty_file_matches_known_empty_digest(tmp_path: Path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    assert sha256_file(p) == hashlib.sha256(b"").hexdigest()


def test_sha256_and_md5_differ_for_the_same_content(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"same content")
    assert sha256_file(p) != md5_file(p)


# ---------------------------------------------------------------------------
# hash_file (algorithm-parameterized)
# ---------------------------------------------------------------------------

def test_hash_file_defaults_to_sha256(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"content")
    assert hash_file(p) == sha256_file(p)


def test_hash_file_md5_algorithm(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"content")
    assert hash_file(p, algorithm="md5") == md5_file(p)


def test_hash_file_sha1_algorithm(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"content")
    assert hash_file(p, algorithm="sha1") == hashlib.sha1(b"content").hexdigest()


def test_hash_file_unknown_algorithm_raises():
    with pytest.raises(ValueError):
        hash_file("whatever", algorithm="not_a_real_algo")


# ---------------------------------------------------------------------------
# safe_sha256_file / safe_md5_file -- best-effort, never raise
# ---------------------------------------------------------------------------

def test_safe_sha256_file_none_path_returns_none():
    assert safe_sha256_file(None) is None


def test_safe_sha256_file_missing_file_returns_none_not_raise():
    assert safe_sha256_file("does_not_exist_anywhere.bin") is None


def test_safe_sha256_file_matches_sha256_file_on_success(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"content")
    assert safe_sha256_file(p) == sha256_file(p)


def test_safe_md5_file_none_path_returns_none():
    assert safe_md5_file(None) is None


def test_safe_md5_file_missing_file_returns_none_not_raise():
    assert safe_md5_file("does_not_exist_anywhere.bin") is None


def test_safe_md5_file_matches_md5_file_on_success(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"content")
    assert safe_md5_file(p) == md5_file(p)
