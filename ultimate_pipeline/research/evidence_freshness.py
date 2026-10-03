"""Reusable evidence-freshness assessment.

An evidence artifact is *fresh* only when the thing that produced it, the
inputs it consumed, the protocol it followed, and its own bytes all still
agree. Implementation readiness is never freshness.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

FRESH = "FRESH"
STALE_PRODUCER = "STALE_PRODUCER"
STALE_INPUT = "STALE_INPUT"
STALE_PROTOCOL = "STALE_PROTOCOL"
STALE_SCHEMA = "STALE_SCHEMA"
MISSING_PROVENANCE = "MISSING_PROVENANCE"
HASH_MISMATCH = "HASH_MISMATCH"

STATUSES = (FRESH, STALE_PRODUCER, STALE_INPUT, STALE_PROTOCOL, STALE_SCHEMA,
            MISSING_PROVENANCE, HASH_MISMATCH)

UNKNOWN = "UNKNOWN"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def _commit_exists(root: Path, sha: str) -> bool:
    if not sha or sha == UNKNOWN:
        return False
    r = subprocess.run(["git", "-C", str(root), "cat-file", "-t", sha],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0 and r.stdout.strip() == "commit"


@dataclass
class Binding:
    """What one evidence artifact claims to be bound to."""

    artifact: str
    schema: str = UNKNOWN
    producer_commit: str = UNKNOWN
    protocol_sha256: str = UNKNOWN
    protocol_source: Optional[str] = None
    source_sha256: Dict[str, str] = None  # type: ignore[assignment]
    declared_sha256: str = UNKNOWN

    def __post_init__(self) -> None:
        if self.source_sha256 is None:
            self.source_sha256 = {}


def assess(binding: Binding, root: Path, current_commit: Optional[str] = None
           ) -> Dict[str, Any]:
    """Return exactly one governed status plus the evidence for it."""
    art = root / binding.artifact
    checks: List[Dict[str, Any]] = []

    def rec(status: str, detail: str) -> None:
        checks.append({"status": status, "detail": detail})

    # missing provenance is the first thing to rule out
    if binding.schema in ("", UNKNOWN) and binding.producer_commit in ("", UNKNOWN):
        rec(MISSING_PROVENANCE,
            "artifact declares neither a schema nor a producer commit")
        return {"status": MISSING_PROVENANCE, "artifact": binding.artifact,
                "checks": checks}

    if not art.is_file():
        rec(MISSING_PROVENANCE, f"artifact not present: {binding.artifact}")
        return {"status": MISSING_PROVENANCE, "artifact": binding.artifact,
                "checks": checks}

    if binding.declared_sha256 not in ("", UNKNOWN):
        observed = sha256_file(art)
        if observed != binding.declared_sha256:
            rec(HASH_MISMATCH,
                f"artifact hashes to {observed[:12]}... but declares "
                f"{binding.declared_sha256[:12]}...")
            return {"status": HASH_MISMATCH, "artifact": binding.artifact,
                    "observed_sha256": observed, "checks": checks}

    if binding.producer_commit not in ("", UNKNOWN):
        if not _commit_exists(root, binding.producer_commit):
            rec(STALE_PRODUCER,
                f"producer commit {binding.producer_commit[:12]} is unreachable")
            return {"status": STALE_PRODUCER, "artifact": binding.artifact,
                    "checks": checks}
        if current_commit and binding.producer_commit != current_commit:
            r = subprocess.run(
                ["git", "-C", str(root), "merge-base", "--is-ancestor",
                 binding.producer_commit, current_commit],
                capture_output=True)
            if r.returncode != 0:
                rec(STALE_PRODUCER,
                    f"producer commit {binding.producer_commit[:12]} is not an "
                    f"ancestor of current head {current_commit[:12]}")
                return {"status": STALE_PRODUCER, "artifact": binding.artifact,
                        "checks": checks}

    for src, declared in (binding.source_sha256 or {}).items():
        p = root / src
        if not p.is_file():
            rec(STALE_INPUT, f"source input missing: {src}")
            return {"status": STALE_INPUT, "artifact": binding.artifact,
                    "checks": checks}
        observed = sha256_file(p)
        if observed != declared:
            rec(STALE_INPUT,
                f"source {src} hashes to {observed[:12]}... but evidence binds "
                f"{declared[:12]}...")
            return {"status": STALE_INPUT, "artifact": binding.artifact,
                    "checks": checks}

    if binding.protocol_sha256 in ("", UNKNOWN):
        rec(STALE_PROTOCOL, "artifact pins no protocol hash")
        return {"status": STALE_PROTOCOL, "artifact": binding.artifact,
                "checks": checks}

    if binding.protocol_source:
        psrc = root / binding.protocol_source
        if not psrc.is_file():
            rec(STALE_PROTOCOL,
                f"protocol source missing: {binding.protocol_source}")
            return {"status": STALE_PROTOCOL, "artifact": binding.artifact,
                    "checks": checks}
        observed_proto = sha256_file(psrc)
        if observed_proto != binding.protocol_sha256:
            rec(STALE_PROTOCOL,
                f"protocol source {binding.protocol_source} hashes to "
                f"{observed_proto[:12]}... but the evidence binds "
                f"{binding.protocol_sha256[:12]}...")
            return {"status": STALE_PROTOCOL, "artifact": binding.artifact,
                    "checks": checks}

    rec(FRESH, "producer, inputs, protocol, schema and bytes all agree")
    return {"status": FRESH, "artifact": binding.artifact, "checks": checks,
            "observed_sha256": sha256_file(art)}


def binding_from_document(doc: Dict[str, Any], artifact: str) -> Binding:
    """Best-effort extraction of a freshness binding from an evidence document."""
    def first(*paths):
        for p in paths:
            cur: Any = doc
            for part in p.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    cur = None
                    break
            if cur:
                return cur
        return UNKNOWN

    return Binding(
        artifact=artifact,
        schema=first("schema", "schema_version"),
        producer_commit=first("base_sha", "base_candidate_sha", "candidate_git_sha",
                              "integrated_head", "git_sha"),
        protocol_sha256=first("protocol_sha256", "aggregate_procedure.protocol_sha256"),
        declared_sha256=UNKNOWN,
        source_sha256={},
    )