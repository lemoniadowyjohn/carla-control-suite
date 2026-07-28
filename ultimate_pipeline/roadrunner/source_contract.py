"""Source-data contract helpers for RoadRunner workflows."""

from __future__ import annotations

from .models import PathKind, PathRef, SourceDataContract


def governed_xodr_source(source_id: str, path: str, sha256: str) -> SourceDataContract:
    return SourceDataContract(
        source_id=source_id,
        path=PathRef(path=path, kind=PathKind.FILE),
        sha256=sha256,
    )


__all__ = ["governed_xodr_source", "SourceDataContract"]
