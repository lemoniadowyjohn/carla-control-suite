# ultimate_pipeline/utils/file_hashing.py
# -*- coding: utf-8 -*-
"""
Unified file hashing utilities for thesis-grade provenance.

This module provides a single source of truth for file hashing across the pipeline.
Use sha256_file for cryptographic integrity; md5_file only for legacy compatibility.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional, Union

# Default chunk size: 1 MB for efficient streaming of large files
DEFAULT_CHUNK_SIZE = 1024 * 1024


def sha256_file(
    path: Union[str, Path],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> str:
    """
    Compute SHA-256 hash of a file.

    This is the preferred hashing algorithm for provenance and integrity.

    Parameters
    ----------
    path : str or Path
        Path to the file to hash.
    chunk_size : int
        Read buffer size in bytes (default: 1 MB).

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_file(
    path: Union[str, Path],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> str:
    """
    Compute MD5 hash of a file.

    NOTE: MD5 is provided ONLY for legacy compatibility (e.g., existing field names
    like snapshot_md5). For new code, prefer sha256_file.

    Parameters
    ----------
    path : str or Path
        Path to the file to hash.
    chunk_size : int
        Read buffer size in bytes (default: 1 MB).

    Returns
    -------
    str
        Lowercase hexadecimal MD5 digest.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    """
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_file(
    path: Union[str, Path],
    algorithm: str = "sha256",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> str:
    """
    Compute hash of a file with specified algorithm.

    Parameters
    ----------
    path : str or Path
        Path to the file to hash.
    algorithm : str
        Hash algorithm name (e.g., "sha256", "md5", "sha1").
    chunk_size : int
        Read buffer size in bytes (default: 1 MB).

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_sha256_file(
    path: Union[str, Path, None],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Optional[str]:
    """
    Compute SHA-256 hash of a file, returning None on any error.

    Use this in best-effort contexts where missing files should not crash.

    Parameters
    ----------
    path : str, Path, or None
        Path to the file to hash. Returns None if path is None.
    chunk_size : int
        Read buffer size in bytes (default: 1 MB).

    Returns
    -------
    str or None
        Lowercase hexadecimal SHA-256 digest, or None if file cannot be read.
    """
    if path is None:
        return None
    try:
        return sha256_file(path, chunk_size=chunk_size)
    except Exception:
        return None


def safe_md5_file(
    path: Union[str, Path, None],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Optional[str]:
    """
    Compute MD5 hash of a file, returning None on any error.

    NOTE: MD5 is for legacy compatibility only. Prefer safe_sha256_file.

    Parameters
    ----------
    path : str, Path, or None
        Path to the file to hash. Returns None if path is None.
    chunk_size : int
        Read buffer size in bytes (default: 1 MB).

    Returns
    -------
    str or None
        Lowercase hexadecimal MD5 digest, or None if file cannot be read.
    """
    if path is None:
        return None
    try:
        return md5_file(path, chunk_size=chunk_size)
    except Exception:
        return None
