"""Canonical evidence hashing, strict JSON and write-once receipts.

This package does not authenticate a filesystem or replace trusted CI signing.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

HEX_CHARS = frozenset('0123456789abcdef')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def canonical_bytes(value: Any) -> bytes:
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest_object(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def require_digest(value: str, field: str = 'sha256') -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX_CHARS for c in value):
        raise ValueError(f'{field} must be a complete lowercase 64-character SHA-256 digest')
    return value


def read_object(path: str | Path) -> dict[str, Any]:
    with Path(path).open('r', encoding='utf-8') as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f'Expected JSON object: {path}')
    return value


def write_immutable_json(path: str | Path, value: Any) -> str:
    """O_EXCL prevents overwriting an existing receipt; fsync file and directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(value) + b'\n'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass  # Directory fsync unsupported on some Windows filesystems.
    return sha256(payload).hexdigest()


def safe_artifact(root: Path, value: str) -> Path:
    """Require paths inside a declared artifact root, including resolved symlinks."""
    if not value or Path(value).is_absolute():
        raise ValueError(f'Artifact path must be relative to workspace: {value!r}')
    base = root.resolve()
    path = (base / value).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f'Artifact path escapes workspace: {value!r}')
    return path
