"""Q15 - Run-local evidence manifest, external-evidence pointer manifest,
and archive manifest.

The run-local manifest contains ONLY artifacts used to support the current
verdict.  For every external artifact record: path, SHA-256, producer run ID,
producer commit, reason for reuse, validation performed.

Manifests are generated LAST.  Extracting the archive into a clean directory
and verifying every hash is provided as a single function.
"""
from __future__ import annotations

import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from phase_q.common import make_run_id, save_json, save_text, sha256_file, utcnow_iso


def build_run_local_manifest(
    run_dir: str,
    *,
    used_paths: Iterable[str],
    verdict: str,
) -> Dict[str, Any]:
    """Manifest of exactly the artifacts used by the current verdict."""
    entries = []
    for rel in used_paths:
        p = os.path.join(run_dir, rel)
        if os.path.isfile(p):
            entries.append({
                "path": rel,
                "size_bytes": os.path.getsize(p),
                "sha256": sha256_file(p),
            })
    entries.sort(key=lambda e: e["path"])
    return {
        "schema": "RUN_LOCAL_MANIFEST/v1",
        "generated_at": utcnow_iso(),
        "verdict": verdict,
        "scope": "run-local: only artifacts supporting this verdict",
        "entries": entries,
    }


def build_external_pointer_manifest(
    external: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Pointer manifest for reused external artifacts.

    Each entry: {path, sha256, producer_run_id, producer_commit,
                 reason_for_reuse, validation_performed}
    """
    return {
        "schema": "EXTERNAL_EVIDENCE_POINTER_MANIFEST/v1",
        "generated_at": utcnow_iso(),
        "entries": external,
    }


def build_archive_manifest(files: List[str], archive_path: str) -> Dict[str, Any]:
    entries = []
    for p in files:
        if os.path.isfile(p):
            entries.append({
                "path": os.path.basename(p),
                "size_bytes": os.path.getsize(p),
                "sha256": sha256_file(p),
            })
    entries.sort(key=lambda e: e["path"])
    return {
        "schema": "ARCHIVE_MANIFEST/v1",
        "archive": archive_path,
        "archive_sha256": sha256_file(archive_path),
        "entries": entries,
    }


def extract_and_verify(archive_path: str, dest_dir: str,
                       manifest: Dict[str, Any]) -> Dict[str, str]:
    """Extract the archive into a clean directory and verify every hash."""
    dest = Path(dest_dir)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive_path) as t:
            t.extractall(dest)

    bad = []
    for e in manifest.get("entries", []):
        f = dest / e["path"]
        if not f.is_file():
            bad.append({"path": e["path"], "error": "missing after extract"})
            continue
        actual = sha256_file(f)
        if actual != e["sha256"]:
            bad.append({"path": e["path"], "error": "hash mismatch"})

    return {
        "extract_dir": str(dest),
        "verified_count": len(manifest.get("entries", [])) - len(bad),
        "mismatch_count": len(bad),
        "mismatches": bad,
        "all_hashes_verified": not bad,
    }