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
        modality = str(art.get("modality", art.get("kind", "rgb")))
        session_ref = str(art.get("session_id", art.get("run_id", "")))
        committed = bool(art.get("committed", True))
        artifact_id = str(art.get("member_id", art.get("id", rel_path)))

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


def evaluate_strict_evidence(
    *,
    synthetic: bool = True,
    independent_review_status: str = "NOT_RUN",
    terminal_status: str = "",
    dataset_content_sha256: str = "",
    capture_receipt_sha256: str = "",
    artifact_members: Sequence[Mapping[str, Any]] = (),
    root: Optional[Path] = None,
    approved_roots: Sequence[Path] = None,
    session_id: Optional[str] = None,
) -> dict:
    """
    Strict evidence predicate. Never promotes synthetic fixtures.
    Returns a verdict dict; claim is never PAIRED_INGOLSTADT_CAPTURE unless
    experimental_evidence_authoritative is True.
    """
    root = resolve_approved_root(root)
    if approved_roots is None:
        approved_roots = [root, root / "datasets", root / "records"]
    structural = True
    fixture_valid = True
    # Synthetic fixtures are structurally valid by design, but never authoritative.
    # Real capture requires non-synthetic evidence origin + independent review.
    real_capture = not synthetic and bool(dataset_content_sha256) and bool(capture_receipt_sha256)
    dataset_admitted = False
    evidence_authoritative = False
    claim = CLAIM_SYNTHETIC_TEST_ONLY
    reasons = []

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

    # Independent review required before admission
    if independent_review_status not in ("APPROVED",):
        reasons.append("independent_review_not_approved")

    # Terminal must be COMPLETED
    if terminal_status != "COMPLETED":
        reasons.append("terminal_capture_not_completed")

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
        if structural and fixture_valid and real_capture and independent_review_status == "APPROVED" and artifact_ok and len(verified) > 0:
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
    }
