#!/usr/bin/env python3
"""
RQ3 Evidence Gate — strict separation of synthetic-fixture validity from
experimental evidence authority. Never promotes synthetic to authoritative.
Follows frozen RQ3 protocol; no fabricated protocol replacement.
"""
from __future__ import annotations
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from pathlib import Path
import hashlib, json, os

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
        # Compute artifact_id early for error messages
        artifact_id = str(art.get("member_id", art.get("id", rel_path)))

        if not rel_path:
            reasons.append(f"missing_path:{artifact_id}")
            continue
        sha_declared = str(art.get("sha256", art.get("digest", "")))
        if not sha_declared:
            reasons.append(f"missing_sha256:{artifact_id}")
            continue

        # C1 addendum: Reject missing modality (was defaulting to rgb)
        if "modality" not in art and "kind" not in art:
            reasons.append(f"missing_modality:{artifact_id}")
            continue
        modality = str(art.get("modality", art.get("kind", "rgb")))

        # C1 addendum: Reject missing committed (was defaulting to True)
        if "committed" not in art:
            reasons.append(f"missing_committed:{artifact_id}")
            continue
        raw_committed = art["committed"]
        # Reviewer B1: a string-encoded "false"/"no"/"0" survives bool() and must
        # not count as committed evidence -- the field must be a JSON boolean.
        if type(raw_committed) is not bool:
            reasons.append(f"committed_invalid:{artifact_id}:not_bool")
            continue
        committed = raw_committed

        # C1 addendum: Reject empty session_id (was skipping stale check)
        session_ref = str(art.get("session_id", art.get("run_id", "")))
        if has_session and not session_ref:
            reasons.append(f"missing_session_id:{artifact_id}")
            continue

        if not committed:
            reasons.append(f"staging_uncommitted:{artifact_id}:{modality}:{rel_path}")
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
        if has_session and session_ref and session_ref != expected_session_id:
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
    review_receipt_identity: Optional[str] = None,
    capture_identity: Optional[str] = None,
    implementer_identity: Optional[str] = None,
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

    # Independent review must be bound to a review receipt inside the
    # verified evidence set; a bare "APPROVED" string proves nothing.
    if independent_review_status not in ("APPROVED",):
        reasons.append("independent_review_not_approved")
    else:
        declared_review = _normalize_sha(review_receipt_sha256)
        if not declared_review:
            reasons.append("independent_review_receipt_missing")
        else:
            evidence_shas = {_normalize_sha(v.get("sha256")) for v in verified}
            evidence_member_map = {_normalize_sha(v.get("sha256")): v for v in verified}
            if declared_review not in evidence_shas:
                reasons.append("independent_review_receipt_not_in_evidence_set")
            else:
                # C1: review receipt must be a dedicated artifact with role "review_receipt"
                review_member = evidence_member_map.get(declared_review)
                if review_member is not None:
                    rmod = str(review_member.get("modality") or review_member.get("kind") or review_member.get("role") or "")
                    # also check role in member
                    if str(review_member.get("role") or "") != "review_receipt" and rmod != "review_receipt":
                        reasons.append("review_receipt_role_missing")
                    # must not share digest with any capture member
                    capture_member_shas = set()
                    for v in verified:
                        vmod = str(v.get("modality") or v.get("kind") or v.get("role") or "")
                        if vmod in ("rgb", "semantic", "lidar", "capture"):
                            # capture modalities are rgb/semantic/lidar; also be strict
                            pass
                    for v in verified:
                        vmod = str(v.get("modality") or v.get("kind") or "")
                        if vmod in ("rgb", "semantic", "lidar"):
                            capture_member_shas.add(_normalize_sha(v.get("sha256")))
                    if declared_review in capture_member_shas:
                        reasons.append("review_receipt_digest_shares_capture_member")
                else:
                    reasons.append("review_receipt_role_missing")
                # must not equal dataset/capture digests
                ds_n = _normalize_sha(dataset_content_sha256)
                cap_n = _normalize_sha(capture_receipt_sha256)
                if declared_review == ds_n and ds_n:
                    reasons.append("dataset_capture_review_digest_collision")
                if declared_review == cap_n and cap_n:
                    reasons.append("dataset_capture_review_digest_collision")
                if ds_n and cap_n and ds_n == cap_n:
                    reasons.append("dataset_capture_review_digest_collision")
                # pairwise distinct among the three
                if ds_n and cap_n and declared_review:
                    if len({ds_n, cap_n, declared_review}) != 3:
                        reasons.append("dataset_capture_review_digest_collision")
                # Parse receipt content
                try:
                    if review_member is None:
                        raise ValueError("no member")
                    rpath = review_member.get("path")
                    if not rpath:
                        raise ValueError("no path")
                    rtarget = _resolve_approved_path(rpath, root, approved_roots)
                    if rtarget is None:
                        # try resolve_artifact style
                        rtarget = resolve_artifact(root, rpath, approved_roots) if rpath else None
                    if rtarget is None or not rtarget.exists():
                        reasons.append("review_receipt_parse_error")
                    else:
                        try:
                            data = json.loads(rtarget.read_text(encoding="utf-8"))
                        except Exception:
                            reasons.append("review_receipt_parse_error")
                        else:
                            verdict = str(data.get("verdict") or data.get("status") or data.get("review") or data.get("decision") or "").strip().upper()
                            if verdict != "APPROVED":
                                reasons.append("review_receipt_verdict_not_approved")
                            # reviewer identity
                            reviewer_id = str(data.get("reviewer_id") or data.get("reviewer") or data.get("reviewer_identity") or data.get("independent_reviewer") or data.get("reviewer_role") or "").strip()
                            cap_id = str(capture_identity or data.get("capture_identity") or data.get("capture_reviewer") or "").strip()
                            impl_id = str(implementer_identity or data.get("implementer_identity") or data.get("author") or "").strip()
                            if not reviewer_id or reviewer_id == cap_id or reviewer_id == impl_id:
                                reasons.append("review_receipt_reviewer_identity_missing_or_equal")
                            # reviewed SHA
                            reviewed = str(data.get("reviewed_sha256") or data.get("reviewed_sha") or data.get("dataset_content_sha256") or data.get("dataset_sha") or data.get("implementation_sha") or data.get("implementation_sha256") or data.get("bound_implementation_sha") or "").strip().lower()
                            if not reviewed or (ds_n and reviewed != ds_n and reviewed != _normalize_sha(data.get("implementation_sha256") or data.get("bound_implementation_sha") or "")):
                                # also allow if equals implementation sha if passed differently? but requirement says equals dataset_content_sha256 or implementation SHA per schema
                                pass
                            # must equal dataset_content_sha256 (or impl sha per schema) - prefer dataset_content_sha256
                            target_reviewed = ds_n if ds_n else _normalize_sha(data.get("implementation_sha256") or data.get("bound_implementation_sha") or "")
                            if not reviewed or reviewed != target_reviewed:
                                reasons.append("review_receipt_reviewed_sha_mismatch")
                except Exception:
                    reasons.append("review_receipt_parse_error")

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
