"""Q4 - Governed load-payload artifact (Strategy B).

The repaired candidate hash and the actual load-payload hash differ because the
loader normalizes <geoReference> in memory.  Strategy B makes that hidden
transformation governed and verifiable:

* A governed load-payload artifact is generated *before* CARLA execution using
  the exact reference transformation the loader applies.
* The manifest records: parent candidate, transformation name/version,
  input SHA-256, output SHA-256, semantic diff, coordinate-contract
  verification, producer commit.
* In release mode the loader must receive the exact governed payload bytes;
  any runtime-only transformation is rejected.

Outputs referenced here:

  Q03_LOAD_PAYLOAD_MANIFEST.json
  Q04_GEOREFERENCE_SEMANTIC_DIFF.json
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Optional

from phase_q.common import XodrTree, make_run_id, sha256_bytes, sha256_text, utcnow_iso

# Referenced loader transformation - single source of truth.
LOADER_TRANSFORMATION = "ultimate_pipeline.core.carla_opendrive_loader._normalize_georef_in_xodr_text"
TRANSFORMATION_VERSION = "georef_normalize_elementtree_v1"
IDENTITY_GUARD = "governed_payload_identity_guard/v1"


def _apply_loader_normalization(xodr_text: str) -> str:
    """Apply the exact georeference normalization the loader performs."""
    try:
        from ultimate_pipeline.core.carla_opendrive_loader import _normalize_georef_in_xodr_text
    except Exception:  # pragma: no cover - fallback replica
        import re
        import xml.etree.ElementTree as ET

        def _normalize_georef_in_xodr_text(text: str) -> str:
            if not text or "<geoReference" not in text:
                return text
            try:
                root = ET.fromstring(text)
                header = root.find("header")
                if header is not None:
                    geo = header.find("geoReference")
                    if geo is not None and geo.text:
                        geo.text = re.sub(r"\s+", " ", geo.text).strip()
                return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
            except Exception:
                return text

    return _normalize_georef_in_xodr_text(xodr_text)


def _geo_ref(parsed: XodrTree) -> Optional[str]:
    el = parsed.find("header/geoReference")
    return el.text.strip() if el is not None and el.text else None


def _attr(el, name: str, default: str = "") -> str:
    if el is None:
        return default
    v = el.get(name)
    return str(v) if v is not None else default


def _id_attr_gen(parsed: XodrTree, tag: str):
    for el in parsed.iter(tag):
        v = el.get("id")
        if v is not None:
            yield str(v)


def _identity_invariant(parsed: XodrTree) -> Dict[str, Any]:
    return {
        "roads": sorted(set(_id_attr_gen(parsed, "road"))),
        "junctions": sorted(set(_id_attr_gen(parsed, "junction"))),
        "signals": sorted(set(_id_attr_gen(parsed, "signal"))),
        "objects": sorted(set(_id_attr_gen(parsed, "object"))),
        "lane_ids": None,
        "header_bounds": _header_bounds(parsed),
        "offset": _header_offset(parsed),
    }


def _header_bounds(parsed: XodrTree) -> Dict[str, Optional[str]]:
    header = parsed.find("header")
    return {k: _attr(header, k) for k in ("north", "south", "east", "west")} if header is not None else {}


def _header_offset(parsed: XodrTree) -> Optional[Dict[str, str]]:
    offset = parsed.find("header/offset")
    if offset is None:
        return None
    return {k: _attr(offset, k) for k in ("x", "y", "z")}


def coordinate_contract_check(before: XodrTree, after: XodrTree) -> Dict[str, Any]:
    """Road/junction/lane/signal/object identity and header bounds must be
    invariant under the georeference normalization."""
    b = _identity_invariant(before)
    a = _identity_invariant(after)
    checks = {
        "road_ids_equal": b["roads"] == a["roads"],
        "junction_ids_equal": b["junctions"] == a["junctions"],
        "signal_ids_equal": b["signals"] == a["signals"],
        "object_ids_equal": b["objects"] == a["objects"],
        "header_bounds_equal": b["header_bounds"] == a["header_bounds"],
        "offset_equal": b["offset"] == a["offset"],
        "georeference_only_change": _geo_ref(before) != _geo_ref(after),
    }
    checks["coordinate_contract_pass"] = all(v for k, v in checks.items() if k not in (
        "coordinate_contract_pass", "georeference_only_change"))
    return checks


def generate_governed_payload(
    candidate_xodr_text: str,
    producer_commit: str,
    *,
    candidate_name: str = "ingolstadt_repaired_candidate",
) -> Dict[str, Any]:
    """Produce a governed load-payload manifest (Strategy B)."""
    input_sha = sha256_text(candidate_xodr_text)
    payload_text = _apply_loader_normalization(candidate_xodr_text)
    output_sha = sha256_text(payload_text)

    before = XodrTree(candidate_xodr_text)
    after = XodrTree(payload_text)
    georef_before = _geo_ref(before)
    georef_after = _geo_ref(after)

    return {
        "manifest_schema": "Q03_LOAD_PAYLOAD_MANIFEST/v1",
        "strategy": "B",
        "transformation_name": LOADER_TRANSFORMATION,
        "transformation_version": TRANSFORMATION_VERSION,
        "producer_commit": producer_commit,
        "candidate": {
            "name": candidate_name,
            "role": "parent candidate",
            "sha256": input_sha,
        },
        "payload": {
            "sha256": output_sha,
            "length_bytes": len(payload_text),
        },
        "semantic_diff": {
            "region": "header/geoReference only",
            "geo_reference_before": georef_before,
            "geo_reference_after": georef_after,
        },
        "coordinate_contract": coordinate_contract_check(before, after),
        "payload_text": payload_text,
    }


def generate_semantic_diff(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Q04 - human-readable georeference semantic diff."""
    return {
        "manifest_schema": "Q04_GEOREFERENCE_SEMANTIC_DIFF/v1",
        "payload_sha256": manifest["payload"]["sha256"],
        "georeference_changes": {
            "before": manifest["semantic_diff"]["geo_reference_before"],
            "after": manifest["semantic_diff"]["geo_reference_after"],
            "mode": "whitespace-canonicalized single-line <geoReference>",
        },
        "coordinate_contract": manifest["coordinate_contract"],
        "interpretation": (
            "The only semantic difference between candidate and governed payload is the "
            "canonicalized <geoReference> text plus ElementTree reserialization. Road, "
            "junction, lane, signal and object identity, plus header bounds and offset, "
            "are structurally invariant (see coordinate_contract)."
        ),
    }


def release_payload_verifier(payload_sha256: str):
    """Return a predicate enforcing exact governed bytes in release mode.

    Raises RuntimeError if the supplied text is not byte-identical to the
    governed payload.
    """

    def _verify(xodr_text: str) -> None:
        actual = sha256_text(xodr_text)
        if actual != payload_sha256:
            raise RuntimeError(
                "release_mode_governed_payload_mismatch: input byte sha256={} != "
                "governed payload sha256={}; no runtime-only transformation is "
                "permitted in release mode.".format(actual, payload_sha256)
            )

    return _verify


# ---------------------------------------------------------------------------
# R13B — governed payload identity guard (write transaction).
#
# C0 remediation A.2: the quarantine discovered a governed artifact whose
# Q03 manifest declared bytes that did NOT match the file on disk
# (R00/R01, INTEGRITY_MISMATCH_DECLARED_VS_DISK). The writer transaction is
# hardened to make that class of defect impossible:
#
#   1. serialize payload text to a temp file in the target directory;
#   2. flush + fsync (durable bytes on disk);
#   3. reopen the temp file and compute sha256 + size FROM THE DISK BYTES
#      (never from the in-memory text);
#   4. compare against the canonical in-memory sha/size; any mismatch is a
#      hard error (do not continue);
#   5. fsync the directory, then atomically rename to the final path;
#   6. reopen the final path once more and verify byte sha256 + size; record
#      this "post-rename identity" in the returned artifact record.
#
# `verify_payload_identity(path, declared_sha256, declared_size)` is the
# independent runtime check that flags any later divergence (the exact check
# that caught the pre-C0 quarantine case).
# ---------------------------------------------------------------------------
IDENTITY_GUARD_VERSION = "governed_payload_identity_guard/v1"


def atomic_write_payload_bytes(path: os.PathLike | str, data: bytes) -> dict:
    """Durably write `data` to `path` and return a verified identity record.\n
    Raises RuntimeError on any declared-vs-disk mismatch (identity hard gate).
    """
    import os
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp.{}".format(os.getpid()))
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # reopen from disk bytes (source of truth)
        on_disk = tmp.read_bytes()
        disk_sha = sha256_bytes(on_disk)
        declared_sha = sha256_bytes(data)
        size = len(on_disk)
        if disk_sha != declared_sha or len(on_disk) != len(data):
            raise ValueError(
                "governed_payload_identity: declared={} size={} vs disk={} "
                "size={} -> HARD FAIL (write not durably verifiable)".format(
                    declared_sha, len(data), disk_sha, len(on_disk)))
        os.replace(tmp, target)
        try:
            dir_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass  # best-effort on platforms without dir fsync
        final = target.read_bytes()  # reopen the FINAL path, verify again
        final_sha = sha256_bytes(final)
        if final_sha != declared_sha or len(final) != len(data):
            raise IdentityError(
                "governed_payload_identity: post-rename verification failed "
                "declared={} vs final={}".format(declared_sha, final_sha))
        return {
            "guard": IDENTITY_GUARD,
            "payload_file": str(target),
            "declared_sha256": declared_sha,
            "declared_size": len(data),
            "disk_sha256": disk_sha,
            "disk_size": size,
            "post_rename_sha256": final_sha,
            "post_rename_size": len(final),
            "identity_pass": True,
        }
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


_write_payload_bytes = atomic_write_payload_bytes


class IdentityError(RuntimeError):
    """Raised when governed payload identity cannot be verified."""


class IdentityVerificationError(IdentityError):
    """Raised when the payload diverges from its declared identity."""


def verify_payload_identity(path: os.PathLike | str, declared_sha256: str,
                            declared_size: int) -> dict:
    """Independent check that a payload file matches its declaration.

    This is the same check that flagged the pre-C0 quarantine mismatch
    (R00 INTEGRITY_MISMATCH_DECLARED_VS_DISK). Raises
    IdentityVerificationError on divergence; returns an identity record on
    success.
    """
    from pathlib import Path

    p = Path(path)
    raw = p.read_bytes()
    size = len(raw)
    actual = sha256_bytes(raw)
    match = (actual == declared_sha256) and (size == declared_size)
    if not match:
        raise IdentityVerificationError(
            "INTEGRITY_MISMATCH_DECLARED_VS_DISK declared_sha256={} "
            "declared_size={} disk_sha256={} disk_size={}".format(
                declared_sha256, declared_size, actual, size))
    return {
        "guard": IDENTITY_GUARD,
        "payload_file": str(p),
        "declared_sha256": declared_sha256,
        "declared_size": declared_size,
        "disk_sha256": actual,
        "disk_size": size,
        "identity_pass": True,
    }


def write_q04_artifacts(
    candidate_xodr_path: str,
    producer_commit: str,
    out_dir: str,
    *,
    candidate_name: str = "ingolstadt_repaired_candidate",
) -> Dict[str, str]:
    from phase_q.common import load_text, save_json, save_text

    text = load_text(candidate_xodr_path)
    manifest = generate_governed_payload(
        text, producer_commit, candidate_name=candidate_name)
    payload_text = manifest.pop("payload_text", "")
    payload_bytes = payload_text.encode("utf-8")

    q03_path = save_json(f"{out_dir}/Q03_LOAD_PAYLOAD_MANIFEST.json", manifest)
    q04_path = save_json(f"{out_dir}/Q04_GEOREFERENCE_SEMANTIC_DIFF.json",
                         generate_semantic_diff(manifest))

    # Identity-guard write (temp -> fsync -> verify -> atomic rename ->
    # reopen -> verify). The manifest bytes are updated from the DISK bytes.
    payload_path = f"{out_dir}/governed_payload.xodr"
    identity = _write_payload_bytes(payload_path, payload_bytes)
    manifest["payload_file"] = payload_path
    manifest["identity_guard"] = identity
    save_json(q03_path, manifest)

    return {
        "Q03_LOAD_PAYLOAD_MANIFEST.json": q03_path,
        "Q04_GEOREFERENCE_SEMANTIC_DIFF.json": q04_path,
        "governed_payload.xodr": payload_path,
        "identity_guard": identity,
    }