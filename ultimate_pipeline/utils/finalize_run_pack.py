#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed run-pack finalization: signature.json and SUCCESS.txt.

V5 / NEW-202 (closure D16).

Historical contract (V4 and earlier) was *best effort*: a requested artifact that
was missing, unreadable, outside the release root, or that raised during hashing
was silently dropped, and ``SUCCESS.txt`` could be published independently of
whether the manifest was complete. That allowed a success marker to be emitted
for an incomplete evidence package.

The contract is now **fail closed**:

* every requested artifact is classified into exactly one explicit category
  (``requested``/``present``/``hashed``/``missing``/``unreadable``/
  ``outside_release_root``/``duplicate``/``unexpected``);
* any mandatory artifact that is missing, unreadable, out of root, duplicated or
  fails to hash forces ``status = FAIL`` and suppresses ``SUCCESS.txt``;
* ``signature.json`` is written first and atomically, so the state
  "SUCCESS.txt exists but signature.json is missing/incomplete" is unreachable;
* ``SUCCESS.txt`` is cryptographically bound to the manifest (it carries the
  manifest digest, the aggregate signature digest, the finalization status and a
  timestamp) and can only be written after a PASS finalization.

This module is the single canonical owner for run-pack finalization. No parallel
``*_v2`` module exists or may be introduced.

Backward compatibility: ``write_signature_json`` and ``write_success_txt`` are
retained for existing callers (``main_pipeline.py``,
``run_full_domain_gap.py``), but ``write_success_txt`` is now gated on a
recorded PASS finalization state for the same release root. The preferred
single-call entry point is :func:`finalize_run_pack`.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "FINALIZATION_SCHEMA",
    "STATE_SCHEMA",
    "STATUS_PASS",
    "STATUS_FAIL",
    "CATEGORY_REQUESTED",
    "CATEGORY_PRESENT",
    "CATEGORY_HASHED",
    "CATEGORY_MISSING",
    "CATEGORY_UNREADABLE",
    "CATEGORY_OUTSIDE_ROOT",
    "CATEGORY_DUPLICATE",
    "CATEGORY_UNEXPECTED",
    "hash_file_sha256",
    "classify_requested_paths",
    "finalize_run_pack",
    "verify_run_pack",
    "write_signature_json",
    "write_success_txt",
]

FINALIZATION_SCHEMA = "RUN_PACK_FINALIZATION/v2"
STATE_SCHEMA = "RUN_PACK_FINALIZATION_STATE/v2"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"

CATEGORY_REQUESTED = "requested"
CATEGORY_PRESENT = "present"
CATEGORY_HASHED = "hashed"
CATEGORY_MISSING = "missing"
CATEGORY_UNREADABLE = "unreadable"
CATEGORY_OUTSIDE_ROOT = "outside_release_root"
CATEGORY_DUPLICATE = "duplicate"
CATEGORY_UNEXPECTED = "unexpected"

#: Categories that are acceptable for a *mandatory* artifact.
HASHABLE_CATEGORIES = frozenset({CATEGORY_HASHED})
#: Categories that are benign (a non-mandatory / optional request, an empty
#: request slot). They never force FAIL on their own.
OPTIONAL_CATEGORIES = frozenset({CATEGORY_REQUESTED, CATEGORY_UNEXPECTED})

SIGNATURE_FILENAME = "signature.json"
SUCCESS_FILENAME = "SUCCESS.txt"
_STATE_FILENAME = ".run_pack_finalization_state.json"

_CHUNK = 1024 * 1024


class FinalizationError(RuntimeError):
    """Raised when finalization cannot complete fail-closed.

    Carries the failure receipt so callers never have to guess whether a partial
    write happened.
    """

    def __init__(self, message: str, receipt: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.receipt = receipt or {}


# ---------------------------------------------------------------------------
# filesystem helpers
# ---------------------------------------------------------------------------


def hash_file_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``.

    Raises on any filesystem error. Callers must translate the exception into an
    explicit failure state; this function never swallows.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_within(base: Path, target: Path) -> bool:
    """True when ``target`` resolves to a location inside ``base``.

    Both sides are fully resolved first, so symlink escapes and ``..`` traversal
    are rejected rather than normalized into a false "inside" answer. The
    comparison is case-folded on Windows to tolerate case-insensitive volumes.
    """
    try:
        base_resolved = base.resolve()
        target_resolved = target.resolve()
    except (OSError, RuntimeError):
        return False
    if os.name == "nt":
        try:
            base_resolved = Path(os.path.normcase(str(base_resolved)))
            target_resolved = Path(os.path.normcase(str(target_resolved)))
        except (OSError, ValueError):
            return False
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError:
        return False
    return True


def _relative_key(root: Path, path: Path) -> str:
    """POSIX-style key for ``path`` relative to ``root``."""
    return path.relative_to(root).as_posix()


def _atomic_write_text(target: Path, text: str) -> None:
    """Write ``text`` to ``target`` atomically via same-directory temp + replace.

    ``os.replace`` is atomic on POSIX and Windows, so a reader can never observe
    a partially written manifest.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp), str(target))
    except BaseException:
        # Never leave a stray temp file behind on failure.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------


def _normalize_request(entry: Any) -> Optional[str]:
    """Normalize one requested entry to a non-empty string, or None if blank."""
    if entry is None:
        return None
    if isinstance(entry, (bytes, bytearray)):
        try:
            entry = entry.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(entry, str):
        entry = str(entry)
    entry = entry.strip()
    return entry or None


def classify_requested_paths(
    out_dir: str | os.PathLike[str],
    key_paths: Iterable[Any],
    *,
    mandatory: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """Classify every requested artifact against the release root.

    Never raises for a *classified* artifact failure: each problem becomes an
    explicit category on the artifact plus an entry in ``failures``. Returns a
    dict with ``root``, ``artifacts`` (ordered list) and ``failures``.
    """
    root = Path(out_dir).expanduser().resolve()
    mandatory_norm = {m for m in (_normalize_request(e) for e in (mandatory or ())) if m}

    artifacts: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    seen_keys: Dict[str, str] = {}
    # Track every observed relative key so already-written files (signature.json
    # from a previous run) can be reported as `unexpected` when re-requested.
    for raw in key_paths or ():
        request = _normalize_request(raw)
        if request is None:
            # Blank / None slots are not requested artifacts at all.
            continue

        artifact: Dict[str, Any] = {
            "requested": request,
            "mandatory": request in mandatory_norm or not mandatory_norm,
            "category": CATEGORY_REQUESTED,
            "key": None,
            "sha256": None,
            "detail": None,
        }

        candidate = Path(request)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:  # pragma: no cover - platform edge
            artifact["category"] = CATEGORY_UNREADABLE
            artifact["detail"] = f"resolve failed: {type(exc).__name__}: {exc}"
            artifacts.append(artifact)
            failures.append(_failure(artifact, "requested path could not be resolved"))
            continue

        if not _is_within(root, resolved):
            artifact["category"] = CATEGORY_OUTSIDE_ROOT
            artifact["detail"] = f"resolves outside release root {root.as_posix()}"
            artifacts.append(artifact)
            failures.append(
                _failure(artifact, "requested artifact resolves outside the release root")
            )
            continue

        try:
            rel_key = _relative_key(root, resolved)
        except ValueError:  # pragma: no cover - guarded by _is_within
            artifact["category"] = CATEGORY_OUTSIDE_ROOT
            artifact["detail"] = "relative key computation failed"
            artifacts.append(artifact)
            failures.append(_failure(artifact, "requested artifact is outside the release root"))
            continue

        artifact["key"] = rel_key

        if rel_key in seen_keys:
            artifact["category"] = CATEGORY_DUPLICATE
            artifact["detail"] = f"already requested as {seen_keys[rel_key]!r}"
            artifacts.append(artifact)
            failures.append(
                _failure(artifact, f"duplicate request for release-relative key {rel_key!r}")
            )
            continue
        seen_keys[rel_key] = request

        if not resolved.exists():
            artifact["category"] = CATEGORY_MISSING
            artifact["detail"] = "no such file"
            artifacts.append(artifact)
            failures.append(_failure(artifact, f"required artifact is missing: {rel_key}"))
            continue

        if not resolved.is_file():
            artifact["category"] = CATEGORY_UNEXPECTED
            artifact["detail"] = "not a regular file"
            artifacts.append(artifact)
            failures.append(
                _failure(artifact, f"requested artifact is not a regular file: {rel_key}")
            )
            continue

        try:
            digest = hash_file_sha256(resolved)
        except PermissionError as exc:
            artifact["category"] = CATEGORY_UNREADABLE
            artifact["detail"] = f"permission denied: {exc}"
            artifacts.append(artifact)
            failures.append(_failure(artifact, f"required artifact is unreadable: {rel_key}"))
            continue
        except OSError as exc:
            artifact["category"] = CATEGORY_UNREADABLE
            artifact["detail"] = f"{type(exc).__name__}: {exc}"
            artifacts.append(artifact)
            failures.append(_failure(artifact, f"required artifact is unreadable: {rel_key}"))
            continue

        artifact["category"] = CATEGORY_HASHED
        artifact["sha256"] = digest
        artifacts.append(artifact)

    return {"root": root, "artifacts": artifacts, "failures": failures}


def _failure(artifact: Dict[str, Any], message: str) -> Dict[str, Any]:
    return {
        "requested": artifact.get("requested"),
        "key": artifact.get("key"),
        "category": artifact.get("category"),
        "mandatory": artifact.get("mandatory", True),
        "message": message,
    }


def _counts(artifacts: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {
        CATEGORY_REQUESTED: 0,
        CATEGORY_PRESENT: 0,
        CATEGORY_HASHED: 0,
        CATEGORY_MISSING: 0,
        CATEGORY_UNREADABLE: 0,
        CATEGORY_OUTSIDE_ROOT: 0,
        CATEGORY_DUPLICATE: 0,
        CATEGORY_UNEXPECTED: 0,
    }
    for artifact in artifacts:
        category = artifact.get("category", CATEGORY_REQUESTED)
        counts[category] = counts.get(category, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# state recording (what authorizes SUCCESS.txt)
# ---------------------------------------------------------------------------


def _record_state(out_dir: Path, receipt: Dict[str, Any]) -> None:
    payload = {
        "schema": STATE_SCHEMA,
        "status": receipt["status"],
        "manifest_sha256": receipt.get("manifest_sha256"),
        "signature_sha256": receipt.get("signature_sha256"),
        "generated_at_utc": receipt.get("generated_at_utc"),
    }
    _atomic_write_text(
        out_dir / _STATE_FILENAME,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


def _read_state(out_dir: Path) -> Dict[str, Any]:
    path = out_dir / _STATE_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


# ---------------------------------------------------------------------------
# finalization
# ---------------------------------------------------------------------------


def _build_receipt(
    classification: Dict[str, Any],
    failures: List[Dict[str, Any]],
) -> Dict[str, Any]:
    artifacts = classification["artifacts"]
    files: Dict[str, str] = {
        a["key"]: a["sha256"]
        for a in artifacts
        if a.get("key") and a.get("category") == CATEGORY_HASHED
    }
    blocking = [f for f in failures if f.get("mandatory", True)]
    status = STATUS_FAIL if blocking else STATUS_PASS

    # Aggregate signature digest: a stable digest over the sorted (key, sha256)
    # pairs. This is what SUCCESS.txt binds to.
    digest = hashlib.sha256()
    for key in sorted(files):
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[key].encode("utf-8"))
        digest.update(b"\n")
    signature_sha256 = digest.hexdigest()

    requested_count = len(artifacts)
    return {
        "schema": FINALIZATION_SCHEMA,
        "status": status,
        "hash_algorithm": "sha256",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "release_root": classification["root"].as_posix(),
        "requested_count": requested_count,
        "hashed_count": len(files),
        "counts": _counts(artifacts),
        "signature_sha256": signature_sha256,
        "manifest_sha256": None,  # filled in once the manifest bytes are known
        "failures": failures,
        "artifacts": artifacts,
        "files": files,
    }


def finalize_run_pack(
    out_dir: str | os.PathLike[str],
    key_paths: Iterable[Any],
    *,
    summary: str = "",
    mandatory: Optional[Iterable[Any]] = None,
    emit_success: bool = True,
) -> Dict[str, Any]:
    """Fail-closed finalization of a run pack.

    Writes ``signature.json`` atomically, then -- only if the finalization
    status is ``PASS`` -- ``SUCCESS.txt`` bound to the manifest digest.

    Returns the finalization receipt. Raises :class:`FinalizationError` (with
    ``.receipt``) only when the *manifest itself* could not be written; in that
    case ``SUCCESS.txt`` is never emitted.
    """
    root = Path(out_dir).expanduser().resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FinalizationError(
            f"release root could not be created: {root.as_posix()}: {exc}"
        )

    classification = classify_requested_paths(root, key_paths, mandatory=mandatory)
    receipt = _build_receipt(classification, classification["failures"])

    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    # The manifest is written first, so the "SUCCESS.txt exists but
    # signature.json is missing/incomplete" state is structurally unreachable.
    try:
        _atomic_write_text(root / SIGNATURE_FILENAME, text)
    except OSError as exc:
        raise FinalizationError(
            f"signature manifest could not be written: {exc}", receipt
        )

    # Bind to the digest of the manifest *as it exists on disk*. Defining the
    # field as "sha256 of signature.json bytes" (rather than a self-referential
    # digest embedded inside those bytes) keeps it independently verifiable by
    # any third party.
    receipt["manifest_sha256"] = hash_file_sha256(root / SIGNATURE_FILENAME)

    # Record state only now: SUCCESS authorization exists only if the manifest
    # is durably on disk.
    try:
        _record_state(root, receipt)
    except OSError as exc:
        raise FinalizationError(f"finalization state could not be written: {exc}", receipt)

    if receipt["status"] == STATUS_PASS and emit_success:
        _write_success_bound(root, receipt, summary)

    return receipt


def _write_success_bound(out_dir: Path, receipt: Dict[str, Any], summary: str) -> None:
    """Write SUCCESS.txt bound to the finalized manifest."""
    ts = receipt["generated_at_utc"]
    body = (
        f"OK {ts}\n"
        f"status={receipt['status']}\n"
        f"schema={receipt['schema']}\n"
        f"manifest_sha256={receipt['manifest_sha256']}\n"
        f"signature_sha256={receipt['signature_sha256']}\n"
        f"requested_count={receipt['requested_count']}\n"
        f"hashed_count={receipt['hashed_count']}\n"
    )
    if summary:
        body += f"summary={summary.strip()}\n"
    _atomic_write_text(out_dir / SUCCESS_FILENAME, body)


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------


def verify_run_pack(out_dir: str | os.PathLike[str]) -> Dict[str, Any]:
    """Re-verify a finalized run pack against its manifest.

    Detects post-finalization tampering of a hashed artifact and any attempt to
    publish SUCCESS.txt without a complete, PASS manifest.
    """
    root = Path(out_dir).expanduser().resolve()
    sig_path = root / SIGNATURE_FILENAME
    success_path = root / SUCCESS_FILENAME

    result: Dict[str, Any] = {
        "schema": "RUN_PACK_VERIFICATION/v2",
        "release_root": root.as_posix(),
        "signature_present": sig_path.is_file(),
        "success_present": success_path.is_file(),
        "status": STATUS_FAIL,
        "problems": [],
    }
    if not result["signature_present"]:
        result["problems"].append("signature.json is missing")
        if result["success_present"]:
            result["problems"].append("SUCCESS.txt present without signature.json")
        return result

    try:
        manifest = json.loads(sig_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result["problems"].append(f"signature.json is unreadable/corrupt: {exc}")
        return result
    if not isinstance(manifest, dict):
        result["problems"].append("signature.json is not a JSON object")
        return result
    result["manifest"] = manifest

    if manifest.get("status") != STATUS_PASS:
        result["problems"].append(f"manifest status is {manifest.get('status')!r}, not PASS")

    files = manifest.get("files")
    if not isinstance(files, dict):
        result["problems"].append("manifest has no `files` mapping")
        files = {}

    # Recompute the aggregate signature digest and compare.
    digest = hashlib.sha256()
    for key in sorted(files):
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(files[key]).encode("utf-8"))
        digest.update(b"\n")
    recomputed = digest.hexdigest()
    result["signature_sha256_recomputed"] = recomputed
    if manifest.get("signature_sha256") != recomputed:
        result["problems"].append("manifest `signature_sha256` does not match its own file map")

    # Recompute the manifest digest from the bytes actually on disk. This is the
    # exact value SUCCESS.txt is bound to, so tampering with either file shows up
    # as a mismatch rather than being silently accepted.
    try:
        actual_manifest_digest = hash_file_sha256(sig_path)
    except OSError as exc:  # pragma: no cover - file vanished mid-verify
        result["problems"].append(f"signature.json unreadable during verification: {exc}")
        actual_manifest_digest = None
    result["manifest_sha256_recomputed"] = actual_manifest_digest

    for key, expected in sorted(files.items()):
        target = root / key
        if not _is_within(root, target):
            result["problems"].append(f"manifest key escapes release root: {key!r}")
            continue
        if not target.is_file():
            result["problems"].append(f"hashed artifact now missing: {key!r}")
            continue
        try:
            actual = hash_file_sha256(target)
        except OSError as exc:
            result["problems"].append(f"hashed artifact unreadable: {key!r}: {exc}")
            continue
        if actual != expected:
            result["problems"].append(f"hashed artifact tampered: {key!r}")

    if result["success_present"]:
        try:
            success_text = success_path.read_text(encoding="utf-8")
        except OSError as exc:
            result["problems"].append(f"SUCCESS.txt unreadable: {exc}")
        else:
            if not success_text.startswith("OK "):
                result["problems"].append("SUCCESS.txt does not carry an OK header")
            bound_manifest = _success_field(success_text, "manifest_sha256")
            if bound_manifest is None:
                result["problems"].append("SUCCESS.txt is not bound to a manifest digest")
            elif bound_manifest != actual_manifest_digest:
                result["problems"].append(
                    "SUCCESS.txt manifest digest does not match signature.json on disk"
                )
            bound_signature = _success_field(success_text, "signature_sha256")
            if bound_signature != recomputed:
                result["problems"].append(
                    "SUCCESS.txt signature digest does not match the manifest file map"
                )
            if _success_field(success_text, "status") != STATUS_PASS:
                result["problems"].append("SUCCESS.txt does not assert finalization status PASS")

    result["status"] = STATUS_PASS if not result["problems"] else STATUS_FAIL
    return result


def _success_field(text: str, field: str) -> Optional[str]:
    for line in text.splitlines():
        if line.startswith(f"{field}="):
            return line.split("=", 1)[1].strip()
    return None


# ---------------------------------------------------------------------------
# backward-compatible entry points
# ---------------------------------------------------------------------------


def write_signature_json(out_dir: str, key_paths: Iterable[Any]) -> Dict[str, Any]:
    """Backwards-compatible signature writer, now fail-closed.

    Returns the finalization receipt, which keeps the historical ``files`` and
    ``hash_algorithm`` keys so existing readers keep working, and adds the
    explicit status/counts/failures fields. ``SUCCESS.txt`` is *not* written
    here; :func:`finalize_run_pack` or :func:`write_success_txt` performs that
    step, and only on PASS.
    """
    receipt = finalize_run_pack(out_dir, key_paths, emit_success=False)
    return receipt


def write_success_txt(out_dir: str, summary: str = "") -> None:
    """Write SUCCESS.txt, but only for a recorded PASS finalization.

    Retained for existing callers. It is now a *gated* operation: without a
    PASS state recorded by :func:`finalize_run_pack` for the same release root
    it raises rather than publishing an unbound success marker.
    """
    root = Path(out_dir).expanduser().resolve()
    sig_path = root / SIGNATURE_FILENAME
    if not sig_path.is_file():
        raise FinalizationError(
            "refusing to write SUCCESS.txt: no signature.json has been finalized"
        )
    try:
        manifest = json.loads(sig_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FinalizationError(
            f"refusing to write SUCCESS.txt: signature.json unreadable ({exc})"
        )
    if not isinstance(manifest, dict) or manifest.get("status") != STATUS_PASS:
        got = manifest.get("status") if isinstance(manifest, dict) else "non-object"
        raise FinalizationError(
            f"refusing to write SUCCESS.txt: finalization status is {got!r}, not PASS"
        )
    state = _read_state(root)
    if state.get("status") != STATUS_PASS:
        raise FinalizationError(
            "refusing to write SUCCESS.txt: no recorded PASS finalization state"
        )
    # Re-read the manifest from disk and recompute its digest rather than trusting
    # the in-memory receipt: the digest is a property of the emitted bytes.
    # (The manifest cannot embed its own digest, so the on-disk value is the
    # authority, exactly as verify_run_pack recomputes it.)
    receipt = manifest
    try:
        receipt["manifest_sha256"] = hash_file_sha256(sig_path)
    except OSError as exc:
        raise FinalizationError(
            f"refusing to write SUCCESS.txt: cannot digest manifest ({exc})"
        )
    _write_success_bound(root, receipt, summary)
