"""C11 (HIGH) — fail-closed digest guard for pinned generation inputs.

The map-of-record must be reproducible from digest-pinned inputs. This
module reads an ``INPUTS_MANIFEST.json`` (path + sha256 + bytes per input)
and verifies each *pinned* entry's file on disk still matches its recorded
digest. Any mismatch, missing file, or size mismatch ABORTS (raises) rather
than silently continuing with drifted inputs.

Entries may instead be marked ``status="pending"`` (no path/sha256/bytes
yet) to document an input that is known but not yet pinned — e.g. the
building source, which depends on C7 landing first. Pending entries are
reported but never digest-checked, and never block verification.

Schema (``INPUTS_MANIFEST.json``)::

    {
      "manifest": "campaigns/.../source/INPUTS_MANIFEST.json",
      "campaign": "ingolstadt_cooked_perception_v1",
      "inputs": {
        "<key>": {
          "path": "<repo-relative path>" | null,
          "sha256": "<64-hex>" | null,
          "bytes": <int> | null,
          "status": "pinned" | "pending",
          "note": "<optional free text>"
        },
        ...
      }
    }
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Union

PathLike = Union[str, Path]

_CHUNK = 1 << 20  # 1 MiB streaming reads; DEM/OSM inputs can be tens of MB+.


class InputsManifestError(Exception):
    """Base class for manifest-related failures."""


class InputsManifestMismatchError(InputsManifestError):
    """Raised when a pinned input's on-disk state no longer matches the manifest.

    This is the fail-closed ABORT path: callers must not proceed with a
    build/generation run when this is raised.
    """


def sha256_file(path: PathLike) -> str:
    """Streaming sha256 of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def compute_manifest_entry(path: PathLike) -> Dict[str, Any]:
    """Compute a ``{"sha256": ..., "bytes": ...}`` pair for a file on disk."""
    p = Path(path)
    return {"sha256": sha256_file(p), "bytes": p.stat().st_size}


def load_manifest(manifest_path: PathLike) -> Dict[str, Any]:
    """Load and parse an INPUTS_MANIFEST.json file."""
    p = Path(manifest_path)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_inputs_manifest(
    manifest_path: PathLike,
    *,
    base_dir: PathLike,
) -> Dict[str, List[str]]:
    """Fail-closed verification of every pinned entry in an inputs manifest.

    Args:
        manifest_path: path to the INPUTS_MANIFEST.json file.
        base_dir: directory that each entry's ``path`` is resolved relative
            to (e.g. the repo root, or a fixture tmp_path in tests). Absolute
            paths in the manifest are used as-is.

    Returns:
        ``{"ok": True, "checked": [keys verified as pinned+matching],
           "pending": [keys marked status="pending"]}``

    Raises:
        InputsManifestMismatchError: if any pinned entry's file is missing,
            or its sha256/byte size no longer matches the manifest.
        InputsManifestError: if the manifest itself is malformed (e.g. a
            pinned entry missing a required field).
    """
    manifest = load_manifest(manifest_path)
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise InputsManifestError(
            f"{manifest_path}: manifest missing an 'inputs' object"
        )

    base = Path(base_dir)
    checked: List[str] = []
    pending: List[str] = []

    for key, entry in inputs.items():
        if not isinstance(entry, dict):
            raise InputsManifestError(f"{manifest_path}: input {key!r} is not an object")

        status = str(entry.get("status") or "").strip().lower()
        if status == "pending":
            pending.append(key)
            continue
        if status != "pinned":
            raise InputsManifestError(
                f"{manifest_path}: input {key!r} has unrecognized status "
                f"{entry.get('status')!r} (expected 'pinned' or 'pending')"
            )

        rel_path = entry.get("path")
        expected_sha256 = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not rel_path or not expected_sha256 or expected_bytes is None:
            raise InputsManifestError(
                f"{manifest_path}: pinned input {key!r} is missing path/sha256/bytes"
            )

        file_path = Path(rel_path)
        if not file_path.is_absolute():
            file_path = base / rel_path

        if not file_path.is_file():
            raise InputsManifestMismatchError(
                f"ABORT: pinned input {key!r} not found on disk: {file_path} "
                f"(expected sha256={expected_sha256})"
            )

        actual_bytes = file_path.stat().st_size
        if actual_bytes != int(expected_bytes):
            raise InputsManifestMismatchError(
                f"ABORT: pinned input {key!r} size mismatch: "
                f"expected {expected_bytes} bytes, found {actual_bytes} bytes "
                f"at {file_path}"
            )

        actual_sha256 = sha256_file(file_path)
        if actual_sha256.lower() != str(expected_sha256).strip().lower():
            raise InputsManifestMismatchError(
                f"ABORT: pinned input {key!r} sha256 mismatch at {file_path}: "
                f"expected {expected_sha256}, found {actual_sha256}. "
                "Input has drifted since it was pinned; regenerate or re-pin "
                "the manifest deliberately, do not proceed with a mismatched "
                "input."
            )

        checked.append(key)

    return {"ok": True, "checked": checked, "pending": pending}
