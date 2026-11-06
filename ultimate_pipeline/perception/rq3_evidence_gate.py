#!/usr/bin/env python3
"""
RQ3 Evidence Gate — strict separation of synthetic-fixture validity from
experimental evidence authority. Never promotes synthetic to authoritative.
Follows frozen RQ3 protocol; no fabricated protocol replacement.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from pathlib import Path
from datetime import datetime, timezone
import base64, hashlib, json, os

CLAIM_SYNTHETIC_TEST_ONLY = "SYNTHETIC_TEST_ONLY"
CLAIM_DATASET_ADMITTED = "DATASET_ADMITTED"
CLAIM_EXPERIMENTAL_EVIDENCE_AUTHORITATIVE = "EXPERIMENTAL_EVIDENCE_AUTHORITATIVE"
CLAIM_UNPAIRED_CAPTURE = "UNPAIRED_CAPTURE"
CLAIM_PAIRED_INGOLSTADT_CAPTURE = "PAIRED_INGOLSTADT_CAPTURE"

#: Environment variable that overrides the approved artifact root.
#:
#: G05: the gate must not hardcode a machine-specific absolute path. The
#: resolution order is: explicit ``root`` argument -> ``RQ3_APPROVED_ROOT``
#: environment variable -> the repository root that contains this module.
RQ3_APPROVED_ROOT_ENV = "RQ3_APPROVED_ROOT"


def resolve_approved_root(root: Optional[Path] = None) -> Path:
    """Resolve the approved artifact root without hardcoded absolute paths.

    Order:
      1. explicit ``root`` argument (caller wins),
      2. ``RQ3_APPROVED_ROOT`` environment variable,
      3. the repository root containing this module (portable default).
    """
    if root is not None:
        return Path(root)
    env = os.environ.get(RQ3_APPROVED_ROOT_ENV, "").strip()
    if env:
        return Path(env).expanduser()
    # ultimate_pipeline/perception/rq3_evidence_gate.py -> repository root
    return Path(__file__).resolve().parents[2]


#: Backwards-compatible module constant. New code should call
#: ``resolve_approved_root()`` so the environment override stays live.
APPROVED_ROOT = resolve_approved_root()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _normalize_sha(value: Any) -> str:
    """Normalize a declared digest for comparison (lower-case hex string)."""
    return str(value or "").strip().lower()


def resolve_artifact(root: Path, relative: str, approved_roots: Sequence[Path]) -> Optional[Path]:
    """Resolve relative artifact; reject traversal outside approved root."""
    try:
        root = Path(root).resolve()
        target = (root / relative).resolve()
        # Prevent traversal
        allowed = False
        for a in approved_roots:
            a_path = Path(a).resolve()
            try:
                target.relative_to(a_path)
                allowed = True
                break
            except ValueError:
                pass
        if not allowed:
            return None
        if target.exists() and target.is_file() and target.stat().st_size > 0:
            return target
        return None
    except Exception:
        return None


def verify_artifact_set(
    artifacts: Sequence[Mapping[str, Any]],
    root: Path,
    approved_roots: Sequence[Path],
    expected_session_id: Optional[str] = None,
    required_modalities: Tuple[str, ...] = ("rgb", "semantic", "lidar"),
) -> Tuple[bool, List[str], List[dict]]:
    reasons: List[str] = []
    verified: List[dict] = []
    seen_ids: dict = {}
    has_session = expected_session_id is not None

    for art in artifacts:
        rel_path = str(art.get("path", ""))
        sha_declared = str(art.get("sha256", art.get("digest", "")))
        artifact_id = str(art.get("member_id", art.get("id", rel_path)))

        # G02b: fail closed on a missing modality -- no silent "rgb" default.
        modality_raw = art.get("modality", art.get("kind"))
        if not modality_raw:
            reasons.append(f"artifact_modality_missing:{artifact_id}")
            continue
        modality = str(modality_raw)

        # G02b: fail closed on a missing committed flag -- only an explicit
        # ``True`` counts as committed; a missing key is never silently
        # trusted (that previously defaulted to committed=True).
        if "committed" not in art:
            reasons.append(f"artifact_committed_flag_missing:{artifact_id}")
            continue
        if art.get("committed") is not True:
            reasons.append(f"staging_uncommitted:{artifact_id}:{modality}:{rel_path}")
            continue

        session_ref = str(art.get("session_id", art.get("run_id", "")))
        # G02b: fail closed on a missing/empty session id when a session is
        # expected -- a blank session_ref used to silently skip staleness.
        if has_session and not session_ref:
            reasons.append(f"artifact_session_missing:{artifact_id}")
            continue

        target = resolve_artifact(root, rel_path, approved_roots)
        if target is None:
            reasons.append(f"artifact_unresolved_or_traversal:{artifact_id}:{modality}:{rel_path}")
            continue
        try:
            actual_sha = _sha256_file(target)
        except Exception as exc:
            reasons.append(f"artifact_unreadable:{artifact_id}:{modality}:{rel_path}:{exc}")
            continue
        if actual_sha != sha_declared:
            reasons.append(f"artifact_digest_mismatch:{artifact_id}:{modality}:{rel_path}:{actual_sha}!={sha_declared}")
            continue
        # Duplicate identity mapping to different content
        if artifact_id in seen_ids:
            if seen_ids[artifact_id] != actual_sha:
                reasons.append(f"duplicate_identity_different_content:{artifact_id}")
                continue
        else:
            seen_ids[artifact_id] = actual_sha
        # Stale session id
        if has_session and session_ref != expected_session_id:
            reasons.append(f"stale_session_id:{artifact_id}:{session_ref}!={expected_session_id}")
            continue
        verified.append({
            "artifact_id": artifact_id,
            "path": str(target),
            "sha256": actual_sha,
            "modality": modality,
            "session_ref": session_ref,
            "committed": True,
        })

    # Coverage: must have all required modalities with committed verified members
    verified_modalities = set(v["modality"] for v in verified)
    for m in required_modalities:
        if m not in verified_modalities:
            reasons.append(f"missing_verified_modality:{m}")

    ok = len(reasons) == 0 and len(verified) > 0
    return (ok, reasons, verified)


def _resolve_approved_path(
    path_like: Any,
    root: Path,
    approved_roots: Sequence[Path],
) -> Optional[Path]:
    """Resolve a path to an existing, non-empty file inside an approved root.

    Relative paths are interpreted against ``root``; absolute paths must still
    live inside one of the approved roots (traversal is rejected).
    """
    try:
        candidate = Path(path_like)
        if not candidate.is_absolute():
            candidate = Path(root) / candidate
        resolved = candidate.resolve()
    except Exception:
        return None
    try:
        if not resolved.exists() or not resolved.is_file():
            return None
        if resolved.stat().st_size <= 0:
            return None
    except OSError:
        return None
    for a in approved_roots:
        try:
            resolved.relative_to(Path(a).resolve())
            return resolved
        except ValueError:
            continue
    return None


def build_content_index(
    verified_artifacts: Sequence[Mapping[str, Any]] = (),
    content_index: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Path]:
    """Map declared sha256 -> filesystem path for the whole evidence set.

    The verified artifacts come first: their paths were already resolved
    against the approved roots and their bytes were already hashed, so they
    are the strongest binding available. Caller-supplied ``content_index``
    entries (sha256 -> path) are added for files that are referenced by a
    digest but are not themselves capture members.
    """
    index: Dict[str, Path] = {}
    for art in verified_artifacts or ():
        sha = _normalize_sha(art.get("sha256", art.get("digest", "")))
        path = art.get("path")
        if sha and path:
            index.setdefault(sha, Path(path))
    for sha, path in (content_index or {}).items():
        key = _normalize_sha(sha)
        if key and path:
            index.setdefault(key, Path(path))
    return index


def resolve_digest_to_bytes(
    sha256: str,
    index: Mapping[str, Path],
    *,
    root: Path,
    approved_roots: Sequence[Path],
) -> Tuple[bool, Optional[Path], str]:
    """Resolve a declared digest to a file whose real bytes hash to it.

    Returns ``(ok, resolved_path, failure_reason)``. A declared digest that
    cannot be tied to actual file bytes is never treated as satisfied.
    """
    key = _normalize_sha(sha256)
    if not key:
        return False, None, "digest_missing"
    path = index.get(key)
    if path is None:
        return False, None, "digest_not_in_evidence_set"
    target = _resolve_approved_path(path, root, approved_roots)
    if target is None:
        return False, None, "digest_path_not_approved_or_missing"
    try:
        actual = _sha256_file(target)
    except Exception as exc:
        return False, None, f"digest_unreadable:{type(exc).__name__}"
    if actual != key:
        return False, None, f"digest_bytes_mismatch:{actual}!={key}"
    return True, target, ""


#: Modality reserved for the independent review receipt. It is a dedicated
#: evidence member and must never count toward the required capture
#: modalities (rgb/semantic/lidar).
REVIEW_RECEIPT_MODALITY = "review_receipt"
REVIEW_RECEIPT_SCHEMA = "rq3_independent_review_receipt/v1"

#: G02c (review fix round): a review receipt is a small, fixed-shape JSON
#: document. Reject anything larger than this before ever attempting to
#: decode/parse it (defense against unbounded-read / parser-pressure via a
#: maliciously large "receipt" file).
REVIEW_RECEIPT_MAX_BYTES = 64 * 1024


def _normalize_identity(value: Any) -> str:
    """Normalize an identity string (reviewer id / capture operator id) for
    an independence comparison: strip surrounding whitespace and casefold.

    G02c: a bare ``==`` comparison let a self-approval through whenever the
    two ids merely differed in case ("ALICE" vs "alice"), surrounding
    whitespace ("alice " vs "alice"), or Unicode case form (e.g. German
    "Straße" vs "STRASSE", which casefold() normalizes identically). A
    whitespace-only string normalizes to empty, so it is treated the same
    as a genuinely missing id by the callers below.
    """
    return str(value or "").strip().casefold()


def canonical_receipt_message(receipt: Mapping[str, Any]) -> bytes:
    """Canonical signed message for a review receipt: sorted-key JSON with
    the ``signature`` field excluded (the signature covers everything else).
    """
    payload = {k: v for k, v in dict(receipt).items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def ed25519_verifier(public_key_bytes: bytes) -> Callable[[bytes, bytes], bool]:
    """Build a ``verifier(message_bytes, signature_bytes) -> bool`` using the
    installed ``cryptography`` package's Ed25519 primitives. Any failure
    (bad key bytes, bad signature, library error) verifies as False -- it
    never raises out to the caller.
    """
    def _verify(message: bytes, signature: bytes) -> bool:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            pk = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            pk.verify(signature, message)
            return True
        except Exception:
            return False
    return _verify


def _parse_iso8601_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (``Z`` suffix supported) as UTC-aware."""
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _validate_review_receipt(
    *,
    declared_review: str,
    receipt_member: Optional[Mapping[str, Any]],
    dataset_content_sha256: str,
    capture_receipt_sha256: str,
    session_id: Optional[str],
    capture_operator_id: Optional[str],
    review_trust_root: Optional[Mapping[str, Callable[[bytes, bytes], bool]]],
    revoked_key_ids: Sequence[str],
) -> List[str]:
    """Validate a signed, bound, independent review receipt (CHAT-01 / G02b).

    A receipt is only trusted when: it is itself a verified evidence-set
    member with modality ``review_receipt`` whose digest matches the
    declared ``review_receipt_sha256``; its JSON content binds it to the
    exact dataset/capture digests and (optionally) session being admitted;
    its reviewer is not the capture operator; and it carries a valid
    signature from a key present (and not revoked) in ``review_trust_root``.
    No trust root or an unknown signer key is never treated as verified.
    """
    reasons: List[str] = []
    if not declared_review:
        reasons.append("independent_review_receipt_missing")
        return reasons
    if receipt_member is None:
        reasons.append("independent_review_receipt_not_in_evidence_set")
        return reasons

    try:
        raw = Path(receipt_member["path"]).read_bytes()
    except Exception:
        reasons.append("review_receipt_schema_invalid")
        return reasons

    # G02c: reject an oversized receipt before ever attempting to decode or
    # json.loads() it.
    if len(raw) > REVIEW_RECEIPT_MAX_BYTES:
        reasons.append("review_receipt_too_large")
        return reasons

    try:
        receipt = json.loads(raw.decode("utf-8"))
        if not isinstance(receipt, dict):
            raise ValueError("review receipt content is not a JSON object")
    except Exception:
        reasons.append("review_receipt_schema_invalid")
        return reasons

    if receipt.get("schema") != REVIEW_RECEIPT_SCHEMA:
        reasons.append("review_receipt_schema_invalid")

    if receipt.get("verdict") != "APPROVED":
        reasons.append("review_receipt_verdict_not_approved")

    # G02c: normalize both sides (strip + casefold) before the independence
    # comparison so case/whitespace/Unicode-case-form variants of the same
    # identity cannot be used to self-approve.
    reviewer_id_norm = _normalize_identity(receipt.get("reviewer_id"))
    if not reviewer_id_norm:
        reasons.append("review_receipt_reviewer_missing")

    capture_operator_norm = _normalize_identity(capture_operator_id)
    if not capture_operator_norm:
        reasons.append("capture_operator_id_missing")
    elif reviewer_id_norm and reviewer_id_norm == capture_operator_norm:
        reasons.append("review_receipt_reviewer_not_independent")

    if _normalize_sha(receipt.get("reviewed_dataset_content_sha256")) != _normalize_sha(dataset_content_sha256):
        reasons.append("review_receipt_binding_mismatch:dataset_content_sha256")

    if _normalize_sha(receipt.get("reviewed_capture_receipt_sha256")) != _normalize_sha(capture_receipt_sha256):
        reasons.append("review_receipt_binding_mismatch:capture_receipt_sha256")

    if session_id is not None and str(receipt.get("session_id") or "") != str(session_id):
        reasons.append("review_receipt_session_mismatch")

    # Signature verification against the supplied trust root (CHAT-01).
    signer_key_id = receipt.get("signer_key_id")
    signature_b64 = receipt.get("signature")
    verifier = review_trust_root.get(signer_key_id) if (review_trust_root and signer_key_id) else None
    if not signer_key_id or not signature_b64 or verifier is None:
        reasons.append("review_signature_unverifiable")
    else:
        try:
            message = canonical_receipt_message(receipt)
            signature_bytes = base64.b64decode(signature_b64)
            signature_ok = bool(verifier(message, signature_bytes))
        except Exception:
            signature_ok = False
        if not signature_ok:
            reasons.append("review_signature_invalid")

    expires_utc = receipt.get("expires_utc")
    if expires_utc:
        try:
            if _parse_iso8601_utc(str(expires_utc)) < datetime.now(timezone.utc):
                reasons.append("review_receipt_expired")
        except Exception:
            reasons.append("review_receipt_expired")

    if signer_key_id and signer_key_id in (revoked_key_ids or ()):
        reasons.append("review_signer_revoked")

    return reasons


def evaluate_strict_evidence(
    *,
    synthetic: bool = True,
    independent_review_status: str = "NOT_RUN",
    terminal_status: str = "",
    dataset_content_sha256: str = "",
    capture_receipt_sha256: str = "",
    review_receipt_sha256: str = "",
    artifact_members: Sequence[Mapping[str, Any]] = (),
    content_index: Optional[Mapping[str, Any]] = None,
    root: Optional[Path] = None,
    approved_roots: Sequence[Path] = None,
    session_id: Optional[str] = None,
    capture_operator_id: Optional[str] = None,
    review_trust_root: Optional[Mapping[str, Callable[[bytes, bytes], bool]]] = None,
    revoked_key_ids: Sequence[str] = (),
) -> dict:
    """
    Strict evidence predicate. Never promotes synthetic fixtures.
    Returns a verdict dict; claim is never PAIRED_INGOLSTADT_CAPTURE unless
    experimental_evidence_authoritative is True.

    G01: admission requires ``terminal_status == "COMPLETED"`` AND an empty
    ``reasons`` list. Previously a non-completed terminal only produced a
    reason string while the admission branch ignored it, so a failed capture
    could still be admitted.

    G02: the self-attested admission inputs are bound to real bytes.
      * ``independent_review_status == "APPROVED"`` additionally requires
        ``review_receipt_sha256`` naming a receipt that is present in the
        verified evidence set.
      * ``dataset_content_sha256`` / ``capture_receipt_sha256`` must resolve
        to files whose real bytes hash to the declared digest.

    G02b / CHAT-01: the review receipt is a dedicated evidence member
    (modality ``review_receipt``, excluded from the required rgb/semantic/
    lidar capture modalities) carrying a JSON body with
    ``schema == "rq3_independent_review_receipt/v1"``. Approval additionally
    requires: the receipt's own ``verdict == "APPROVED"``; a non-empty
    ``reviewer_id`` that differs from ``capture_operator_id``; the receipt's
    ``reviewed_dataset_content_sha256`` / ``reviewed_capture_receipt_sha256``
    matching the digests being admitted (and ``session_id`` matching, when
    given); a valid Ed25519 signature from a key present in
    ``review_trust_root`` and not in ``revoked_key_ids``; and, when present,
    an ``expires_utc`` that has not passed. ``dataset_content_sha256`` /
    ``capture_receipt_sha256`` / ``review_receipt_sha256`` must also be
    pairwise distinct and may never alias a verified rgb/semantic/lidar
    capture-member digest.
    """
    root = resolve_approved_root(root)
    if approved_roots is None:
        approved_roots = [root, root / "datasets", root / "records"]
    structural = True
    fixture_valid = True
    dataset_admitted = False
    evidence_authoritative = False
    claim = CLAIM_SYNTHETIC_TEST_ONLY
    reasons: List[str] = []

    # Verify artifacts (only when artifacts provided — offline tests may omit)
    artifact_ok = True
    verified: List[dict] = []
    if artifact_members:
        artifact_ok, artifact_reasons, verified = verify_artifact_set(
            artifact_members, root=root, approved_roots=approved_roots, expected_session_id=session_id
        )
        if not artifact_ok:
            structural = False
            reasons.extend(artifact_reasons)

    # --- G02: bind the self-attested admission inputs to real bytes -------
    index = build_content_index(verified, content_index)

    content_binding_ok = True
    for label, declared in (
        ("dataset_content_sha256", dataset_content_sha256),
        ("capture_receipt_sha256", capture_receipt_sha256),
    ):
        if not _normalize_sha(declared):
            continue
        ok, _target, why = resolve_digest_to_bytes(
            declared, index, root=root, approved_roots=approved_roots
        )
        if not ok:
            content_binding_ok = False
            reasons.append(f"{label}_unresolved:{why}")

    # G02b / CHAT-01: the three self-attested admission digests (dataset,
    # capture receipt, review receipt) must be pairwise distinct, and none of
    # them may alias a real rgb/semantic/lidar capture-member digest. This
    # closes the "receipt == a capture frame's own digest" false-admission
    # class independent of the review-receipt content checks below.
    _digest_labels = (
        ("dataset_content_sha256", _normalize_sha(dataset_content_sha256)),
        ("capture_receipt_sha256", _normalize_sha(capture_receipt_sha256)),
        ("review_receipt_sha256", _normalize_sha(review_receipt_sha256)),
    )
    _present_digests = [(label, d) for label, d in _digest_labels if d]
    _seen_digest_values: Dict[str, str] = {}
    _digests_distinct = True
    for label, d in _present_digests:
        if d in _seen_digest_values:
            _digests_distinct = False
        else:
            _seen_digest_values[d] = label
    if not _digests_distinct:
        reasons.append("admission_digests_not_distinct")

    _capture_member_digests = {
        _normalize_sha(v.get("sha256"))
        for v in verified
        if v.get("modality") in ("rgb", "semantic", "lidar")
    }
    for label, d in _present_digests:
        if d in _capture_member_digests:
            reasons.append(f"admission_digest_reuses_capture_member:{label}")

    # Independent review must be bound to a signed, independent review
    # receipt inside the verified evidence set (modality "review_receipt");
    # a bare "APPROVED" string, or a receipt that is really just a capture
    # member's digest, proves nothing (G02b / CHAT-01).
    if independent_review_status not in ("APPROVED",):
        reasons.append("independent_review_not_approved")
    else:
        declared_review = _normalize_sha(review_receipt_sha256)
        receipt_member = None
        for v in verified:
            if v.get("modality") == REVIEW_RECEIPT_MODALITY and _normalize_sha(v.get("sha256")) == declared_review:
                receipt_member = v
                break
        reasons.extend(_validate_review_receipt(
            declared_review=declared_review,
            receipt_member=receipt_member,
            dataset_content_sha256=dataset_content_sha256,
            capture_receipt_sha256=capture_receipt_sha256,
            session_id=session_id,
            capture_operator_id=capture_operator_id,
            review_trust_root=review_trust_root,
            revoked_key_ids=revoked_key_ids,
        ))

    # Terminal must be COMPLETED
    if terminal_status != "COMPLETED":
        reasons.append("terminal_capture_not_completed")

    # Synthetic fixtures are structurally valid by design, but never authoritative.
    # Real capture requires non-synthetic evidence origin + independent review
    # and digests that resolve to actual file bytes.
    real_capture = (
        not synthetic
        and bool(dataset_content_sha256)
        and bool(capture_receipt_sha256)
        and content_binding_ok
    )

    # Real dataset must have content digest verified against actual bytes
    if real_capture and dataset_content_sha256:
        # For full admission, dataset content must match verified artifacts
        # (checked separately; if artifacts not provided, structural stays true
        # but evidence_authoritative stays false because no live proof)
        dataset_admitted = False
    else:
        if not dataset_content_sha256:
            reasons.append("dataset_content_sha256_missing")
        else:
            # Content digest declared but no verified artifacts → not authoritative
            reasons.append("dataset_content_not_verified_by_artifacts")

    if synthetic:
        claim = CLAIM_SYNTHETIC_TEST_ONLY
        dataset_admitted = False
        evidence_authoritative = False
        if structural and fixture_valid:
            claim = CLAIM_SYNTHETIC_TEST_ONLY  # structural pass, but not evidence
    else:
        # G01: admission requires a COMPLETED terminal AND an empty reason
        # list. A non-completed terminal previously only produced a reason
        # string that the admission branch ignored, so a failed/aborted
        # capture could still be admitted as authoritative evidence.
        admissible = (
            structural
            and fixture_valid
            and real_capture
            and independent_review_status == "APPROVED"
            and artifact_ok
            and len(verified) > 0
            and terminal_status == "COMPLETED"
            and not reasons
        )
        if admissible:
            evidence_authoritative = True
            dataset_admitted = True  # only when fully verified
            claim = CLAIM_EXPERIMENTAL_EVIDENCE_AUTHORITATIVE
        else:
            claim = CLAIM_UNPAIRED_CAPTURE
            evidence_authoritative = False
            dataset_admitted = False
            if not real_capture:
                reasons.append("real_capture_evidence_absent")

    return {
        "structural_test_valid": structural,
        "synthetic_fixture_valid": fixture_valid,
        "real_capture_complete": real_capture,
        "dataset_admitted": dataset_admitted,
        "experimental_evidence_authoritative": evidence_authoritative,
        "claim_level": claim,
        "reasons": reasons,
        "verified_artifacts": verified if artifact_members else [],
        "synthetic": synthetic,
        "independent_review_status": independent_review_status,
        "review_receipt_sha256": _normalize_sha(review_receipt_sha256),
        "approved_root": str(root),
    }
