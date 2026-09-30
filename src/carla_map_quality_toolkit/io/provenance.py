from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Return a stable SHA-256 digest for an input artifact."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def file_provenance(path: str | Path, label: str = "input") -> dict[str, str]:
    source = Path(path)
    return {
        f"{label}_name": source.name,
        f"{label}_sha256": sha256_file(source),
    }
