#!/usr/bin/env python3
"""
G02b / CHAT-01 — signed, bound, independent review receipt.

Confirms (and closes) the false-admission class where ``evaluate_strict_evidence``
treated a bare digest as an "independent review receipt" without ever reading
or verifying the receipt's content:

  (a) review_receipt_sha256 == sha256 of a plain rgb capture frame (no receipt
      file at all);
  (b) review/dataset/capture digests == the rgb/semantic/lidar member frame
      digests, content_index=None;
  (c) a member file whose content is ``{"review": "REJECTED"}`` used as the
      receipt;
  (d) a member with no "modality" key (previously defaulted to "rgb");
  (e) a member with no "committed" key (previously defaulted to True);
  (f) with expected_session_id="S1", a member whose session_id is "" or
      missing (previously skipped the stale-session check).

Then verifies the new G02b design: the review receipt is a dedicated,
modality="review_receipt" evidence member carrying a signed JSON body that
is bound (by digest) to the exact dataset/capture evidence being admitted,
reviewed by someone other than the capture operator, and signed by a key
present (and not revoked) in the caller-supplied trust root.

All fixtures are synthetic and use tmp_path; nothing here touches the real
RQ3 evidence tree or any frozen protocol file.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ultimate_pipeline.perception.rq3_evidence_gate import (
    REVIEW_RECEIPT_MAX_BYTES,
    REVIEW_RECEIPT_SCHEMA,
    canonical_receipt_message,
    ed25519_verifier,
    evaluate_strict_evidence,
    verify_artifact_set,
)

CLAIM_AUTHORITATIVE = "EXPERIMENTAL_EVIDENCE_AUTHORITATIVE"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write(root: Path, name: str, payload: bytes) -> str:
    (root / name).write_bytes(payload)
    return _sha(payload)


def _capture_members(root: Path, session_id: str = "s1"):
    """Write real rgb/semantic/lidar capture files and return (members, digests)."""
    digests = {
        "rgb": _write(root, "rgb.bin", b"rgb-frame-bytes"),
        "semantic": _write(root, "semantic.bin", b"semantic-frame-bytes"),
        "lidar": _write(root, "lidar.bin", b"lidar-frame-bytes"),
    }
    members = [
        {"path": f"{name}.bin", "sha256": digests[name], "modality": name,
         "committed": True, "session_id": session_id, "member_id": name}
        for name in ("rgb", "semantic", "lidar")
    ]
    return members, digests


def _dataset_and_capture_receipt(root: Path, session_id: str = "s1"):
    dataset_sha = _write(root, "dataset.bin", b"dataset-content-bytes")
    capture_sha = _write(root, "capture_receipt.bin", b"capture-completion-receipt-bytes")
    members = [
        {"path": "dataset.bin", "sha256": dataset_sha, "modality": "dataset",
         "committed": True, "session_id": session_id, "member_id": "dataset"},
        {"path": "capture_receipt.bin", "sha256": capture_sha, "modality": "capture_receipt",
         "committed": True, "session_id": session_id, "member_id": "capture_receipt"},
    ]
    return members, dataset_sha, capture_sha


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    return priv, pub_bytes


def _write_review_receipt_member(
    root: Path,
    name: str,
    *,
    priv,
    key_id: str,
    dataset_sha: str,
    capture_sha: str,
    reviewer_id: str = "independent-reviewer-1",
    session_id: str = "s1",
    verdict: str = "APPROVED",
    schema: str = REVIEW_RECEIPT_SCHEMA,
    expires_utc: str = None,
    extra_fields: dict = None,
    corrupt_signature: bool = False,
    omit_signature: bool = False,
    omit_signer_key_id: bool = False,
    skip_signing: bool = False,
    pad_to_bytes: int = None,
):
    """Build + write a review-receipt evidence member. Returns (member, sha, receipt)."""
    receipt = {
        "schema": schema,
        "verdict": verdict,
        "reviewer_id": reviewer_id,
        "reviewed_dataset_content_sha256": dataset_sha,
        "reviewed_capture_receipt_sha256": capture_sha,
        "session_id": session_id,
    }
    if not omit_signer_key_id:
        receipt["signer_key_id"] = key_id
    if expires_utc is not None:
        receipt["expires_utc"] = expires_utc
    if extra_fields:
        receipt.update(extra_fields)

    if not omit_signature:
        if skip_signing:
            signature_bytes = b"\x00" * 64
        else:
            message = canonical_receipt_message(receipt)
            signature_bytes = priv.sign(message)
            if corrupt_signature:
                signature_bytes = bytes([signature_bytes[0] ^ 0xFF]) + signature_bytes[1:]
        receipt["signature"] = base64.b64encode(signature_bytes).decode("ascii")

    payload = json.dumps(receipt, sort_keys=True).encode("utf-8")
    if pad_to_bytes is not None and len(payload) < pad_to_bytes:
        # G02c: pad *after* signing so the receipt grows past the size cap;
        # the signature need not stay valid -- the size cap must reject the
        # receipt before signature verification is ever reached.
        receipt["_test_padding"] = "A" * (pad_to_bytes - len(payload) + 64)
        payload = json.dumps(receipt, sort_keys=True).encode("utf-8")
    sha = _write(root, name, payload)
    member = {
        "path": name, "sha256": sha, "modality": "review_receipt",
        "committed": True, "session_id": session_id, "member_id": name,
    }
    return member, sha, receipt


# ---------------------------------------------------------------------------
# (a)-(f): the 6 confirmed defects, now rejected with specific reason codes
# ---------------------------------------------------------------------------


def test_defect_a_review_receipt_is_bare_rgb_frame_digest_rejected(tmp_path):
    """(a) review_receipt_sha256 = sha256 of the rgb capture frame; no receipt file exists."""
    root = tmp_path / "evidence"
    root.mkdir()
    capture_members, digests = _capture_members(root)
    receipt_members, dataset_sha, capture_sha = _dataset_and_capture_receipt(root)
    members = capture_members + receipt_members

    v = evaluate_strict_evidence(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        dataset_content_sha256=dataset_sha,
        capture_receipt_sha256=capture_sha,
        review_receipt_sha256=digests["rgb"],  # <- no receipt, just the rgb frame's own digest
        artifact_members=members,
        root=root,
        approved_roots=[root],
        session_id="s1",
    )
    assert v["dataset_admitted"] is False, v
    assert v["claim_level"] != CLAIM_AUTHORITATIVE, v
    assert "independent_review_receipt_not_in_evidence_set" in v["reasons"], v["reasons"]
    print("PASS: defect_a_review_receipt_is_bare_rgb_frame_digest_rejected")


def test_defect_b_all_three_digests_are_capture_member_frames_rejected(tmp_path):
    """(b) review/dataset/capture digests = rgb/semantic/lidar frame digests, content_index=None."""
    root = tmp_path / "evidence"
    root.mkdir()
    capture_members, digests = _capture_members(root)

    v = evaluate_strict_evidence(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        dataset_content_sha256=digests["rgb"],
        capture_receipt_sha256=digests["semantic"],
        review_receipt_sha256=digests["lidar"],
        artifact_members=capture_members,
        content_index=None,
        root=root,
        approved_roots=[root],
        session_id="s1",
    )
    assert v["dataset_admitted"] is False, v
    assert v["claim_level"] != CLAIM_AUTHORITATIVE, v
    assert any(r.startswith("admission_digest_reuses_capture_member:") for r in v["reasons"]), v["reasons"]
    assert "independent_review_receipt_not_in_evidence_set" in v["reasons"], v["reasons"]
    print("PASS: defect_b_all_three_digests_are_capture_member_frames_rejected")


def test_defect_c_rejected_review_content_used_as_receipt_rejected(tmp_path):
    """(c) a member file whose content is {"review": "REJECTED"} used as the receipt."""
    root = tmp_path / "evidence"
    root.mkdir()
    capture_members, digests = _capture_members(root)
    receipt_members, dataset_sha, capture_sha = _dataset_and_capture_receipt(root)
    fake_sha = _write(root, "fake_review.bin", b'{"review":"REJECTED"}')
    fake_member = {
        "path": "fake_review.bin", "sha256": fake_sha, "modality": "review_receipt",
        "committed": True, "session_id": "s1", "member_id": "fake_review",
    }
    members = capture_members + receipt_members + [fake_member]

    v = evaluate_strict_evidence(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        dataset_content_sha256=dataset_sha,
        capture_receipt_sha256=capture_sha,
        review_receipt_sha256=fake_sha,
        artifact_members=members,
        root=root,
        approved_roots=[root],
        session_id="s1",
    )
    assert v["dataset_admitted"] is False, v
    assert v["claim_level"] != CLAIM_AUTHORITATIVE, v
    assert "review_receipt_schema_invalid" in v["reasons"], v["reasons"]
    print("PASS: defect_c_rejected_review_content_used_as_receipt_rejected")


def test_defect_d_missing_modality_rejected(tmp_path):
    """(d) a member with no "modality" key must not default to "rgb"."""
    root = tmp_path / "evidence"
    root.mkdir()
    sha = _write(root, "no_modality.bin", b"no-modality-bytes")
    art = [{"path": "no_modality.bin", "sha256": sha, "committed": True,
            "session_id": "s1", "member_id": "no_mod"}]
    ok, reasons, verified = verify_artifact_set(art, root=root, approved_roots=[root])
    assert ok is False, (ok, reasons, verified)
    assert verified == [], verified
    assert "artifact_modality_missing:no_mod" in reasons, reasons
    print("PASS: defect_d_missing_modality_rejected")


def test_defect_e_missing_committed_flag_rejected(tmp_path):
    """(e) a member with no "committed" key must not default to True."""
    root = tmp_path / "evidence"
    root.mkdir()
    sha = _write(root, "no_committed.bin", b"no-committed-bytes")
    art = [{"path": "no_committed.bin", "sha256": sha, "modality": "rgb",
            "session_id": "s1", "member_id": "no_committed"}]
    ok, reasons, verified = verify_artifact_set(art, root=root, approved_roots=[root])
    assert ok is False, (ok, reasons, verified)
    assert verified == [], verified
    assert "artifact_committed_flag_missing:no_committed" in reasons, reasons
    print("PASS: defect_e_missing_committed_flag_rejected")


def test_defect_f_missing_session_id_rejected(tmp_path):
    """(f) expected_session_id="S1", member session_id missing -> must not skip staleness."""
    root = tmp_path / "evidence"
    root.mkdir()
    sha = _write(root, "no_session.bin", b"no-session-bytes")
    art = [{"path": "no_session.bin", "sha256": sha, "modality": "rgb",
            "committed": True, "member_id": "no_session"}]  # no session_id key at all
    ok, reasons, verified = verify_artifact_set(art, root=root, approved_roots=[root], expected_session_id="S1")
    assert ok is False, (ok, reasons, verified)
    assert verified == [], verified
    assert "artifact_session_missing:no_session" in reasons, reasons
    print("PASS: defect_f_missing_session_id_rejected")


def test_defect_f_empty_session_id_rejected(tmp_path):
    """(f) variant: session_id present but an empty string must also be rejected."""
    root = tmp_path / "evidence"
    root.mkdir()
    sha = _write(root, "empty_session.bin", b"empty-session-bytes")
    art = [{"path": "empty_session.bin", "sha256": sha, "modality": "rgb",
            "committed": True, "session_id": "", "member_id": "empty_session"}]
    ok, reasons, verified = verify_artifact_set(art, root=root, approved_roots=[root], expected_session_id="S1")
    assert ok is False, (ok, reasons, verified)
    assert verified == [], verified
    assert "artifact_session_missing:empty_session" in reasons, reasons
    print("PASS: defect_f_empty_session_id_rejected")


# ---------------------------------------------------------------------------
# Full admission scenario helper (for the signature/binding tests below)
# ---------------------------------------------------------------------------


def _full_scenario(tmp_path, *, receipt_kwargs_overrides=None, capture_operator_id="capture-operator-1",
                    trust_root_overrides=None, revoked_key_ids=(), session_id="s1",
                    evidence_overrides=None):
    root = tmp_path / "evidence"
    root.mkdir()
    priv, pub_bytes = _keypair()
    key_id = "review-key-1"

    capture_members, digests = _capture_members(root, session_id=session_id)
    receipt_members, dataset_sha, capture_sha = _dataset_and_capture_receipt(root, session_id=session_id)

    kwargs = dict(
        priv=priv, key_id=key_id, dataset_sha=dataset_sha, capture_sha=capture_sha,
        session_id=session_id,
    )
    if receipt_kwargs_overrides:
        kwargs.update(receipt_kwargs_overrides)
    review_member, review_sha, receipt = _write_review_receipt_member(root, "review_receipt.json", **kwargs)

    members = capture_members + receipt_members + [review_member]

    trust_root = {key_id: ed25519_verifier(pub_bytes)}
    if trust_root_overrides is not None:
        trust_root = trust_root_overrides

    call_kwargs = dict(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        dataset_content_sha256=dataset_sha,
        capture_receipt_sha256=capture_sha,
        review_receipt_sha256=review_sha,
        artifact_members=members,
        root=root,
        approved_roots=[root],
        session_id=session_id,
        capture_operator_id=capture_operator_id,
        review_trust_root=trust_root,
        revoked_key_ids=revoked_key_ids,
    )
    if evidence_overrides:
        call_kwargs.update(evidence_overrides)

    return evaluate_strict_evidence(**call_kwargs)


def test_positive_control_signed_bound_independent_receipt_admitted(tmp_path):
    """Positive control: a properly signed, bound, independent receipt admits."""
    v = _full_scenario(tmp_path)
    assert v["dataset_admitted"] is True, v
    assert v["experimental_evidence_authoritative"] is True, v
    assert v["claim_level"] == CLAIM_AUTHORITATIVE, v
    assert v["reasons"] == [], v["reasons"]
    print("PASS: positive_control_signed_bound_independent_receipt_admitted")


def test_unsigned_receipt_rejected(tmp_path):
    v = _full_scenario(tmp_path, receipt_kwargs_overrides={"omit_signature": True})
    assert v["dataset_admitted"] is False, v
    assert "review_signature_unverifiable" in v["reasons"], v["reasons"]
    print("PASS: unsigned_receipt_rejected")


def test_unknown_signer_key_rejected(tmp_path):
    # Receipt signed/declared under a key id that is not present in the trust root.
    root_trust_override = {"some-other-key": lambda m, s: True}
    v = _full_scenario(tmp_path, trust_root_overrides=root_trust_override)
    assert v["dataset_admitted"] is False, v
    assert "review_signature_unverifiable" in v["reasons"], v["reasons"]
    print("PASS: unknown_signer_key_rejected")


def test_no_trust_root_rejected(tmp_path):
    v = _full_scenario(tmp_path, trust_root_overrides={})
    assert v["dataset_admitted"] is False, v
    assert "review_signature_unverifiable" in v["reasons"], v["reasons"]
    print("PASS: no_trust_root_rejected")


def test_bad_signature_rejected(tmp_path):
    v = _full_scenario(tmp_path, receipt_kwargs_overrides={"corrupt_signature": True})
    assert v["dataset_admitted"] is False, v
    assert "review_signature_invalid" in v["reasons"], v["reasons"]
    print("PASS: bad_signature_rejected")


def test_expired_receipt_rejected(tmp_path):
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    v = _full_scenario(tmp_path, receipt_kwargs_overrides={"expires_utc": expired})
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_expired" in v["reasons"], v["reasons"]
    print("PASS: expired_receipt_rejected")


def test_unexpired_receipt_not_rejected_for_expiry(tmp_path):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    v = _full_scenario(tmp_path, receipt_kwargs_overrides={"expires_utc": future})
    assert "review_receipt_expired" not in v["reasons"], v["reasons"]
    assert v["dataset_admitted"] is True, v
    print("PASS: unexpired_receipt_not_rejected_for_expiry")


def test_revoked_signer_rejected(tmp_path):
    v = _full_scenario(tmp_path, revoked_key_ids=("review-key-1",))
    assert v["dataset_admitted"] is False, v
    assert "review_signer_revoked" in v["reasons"], v["reasons"]
    print("PASS: revoked_signer_rejected")


def test_reviewer_equals_capture_operator_rejected(tmp_path):
    v = _full_scenario(
        tmp_path,
        receipt_kwargs_overrides={"reviewer_id": "same-person"},
        capture_operator_id="same-person",
    )
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_reviewer_not_independent" in v["reasons"], v["reasons"]
    print("PASS: reviewer_equals_capture_operator_rejected")


def test_reviewer_independence_case_differs_rejected(tmp_path):
    """G02c: "ALICE" vs "alice" must still be treated as the same person."""
    v = _full_scenario(
        tmp_path,
        receipt_kwargs_overrides={"reviewer_id": "ALICE"},
        capture_operator_id="alice",
    )
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_reviewer_not_independent" in v["reasons"], v["reasons"]
    print("PASS: reviewer_independence_case_differs_rejected")


def test_reviewer_independence_whitespace_rejected(tmp_path):
    """G02c: "alice " vs "alice" must still be treated as the same person."""
    v = _full_scenario(
        tmp_path,
        receipt_kwargs_overrides={"reviewer_id": "alice "},
        capture_operator_id="alice",
    )
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_reviewer_not_independent" in v["reasons"], v["reasons"]
    print("PASS: reviewer_independence_whitespace_rejected")


def test_reviewer_independence_unicode_casefold_rejected(tmp_path):
    """G02c: "Straße" vs "STRASSE" must still be treated as the same person
    (str.casefold() normalizes German sharp-s / eszett the same as "ss")."""
    v = _full_scenario(
        tmp_path,
        receipt_kwargs_overrides={"reviewer_id": "Straße"},
        capture_operator_id="STRASSE",
    )
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_reviewer_not_independent" in v["reasons"], v["reasons"]
    print("PASS: reviewer_independence_unicode_casefold_rejected")


def test_whitespace_only_reviewer_id_treated_as_missing(tmp_path):
    """G02c: a whitespace-only reviewer_id must not count as a non-empty id."""
    v = _full_scenario(tmp_path, receipt_kwargs_overrides={"reviewer_id": "   "})
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_reviewer_missing" in v["reasons"], v["reasons"]
    print("PASS: whitespace_only_reviewer_id_treated_as_missing")


def test_whitespace_only_capture_operator_id_treated_as_missing(tmp_path):
    """G02c: a whitespace-only capture_operator_id must not count as a real id."""
    v = _full_scenario(tmp_path, capture_operator_id="   ")
    assert v["dataset_admitted"] is False, v
    assert "capture_operator_id_missing" in v["reasons"], v["reasons"]
    print("PASS: whitespace_only_capture_operator_id_treated_as_missing")


def test_oversized_review_receipt_rejected(tmp_path):
    """G02c: a receipt larger than REVIEW_RECEIPT_MAX_BYTES must be rejected
    before it is ever json-parsed."""
    v = _full_scenario(
        tmp_path,
        receipt_kwargs_overrides={"pad_to_bytes": REVIEW_RECEIPT_MAX_BYTES + 1},
    )
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_too_large" in v["reasons"], v["reasons"]
    print("PASS: oversized_review_receipt_rejected")


def test_receipt_at_or_under_size_cap_not_rejected_for_size(tmp_path):
    """Control: a receipt comfortably under the cap is never flagged too-large."""
    v = _full_scenario(tmp_path)
    assert "review_receipt_too_large" not in v["reasons"], v["reasons"]
    assert v["dataset_admitted"] is True, v
    print("PASS: receipt_at_or_under_size_cap_not_rejected_for_size")


def test_missing_capture_operator_id_rejected(tmp_path):
    v = _full_scenario(tmp_path, capture_operator_id=None)
    assert v["dataset_admitted"] is False, v
    assert "capture_operator_id_missing" in v["reasons"], v["reasons"]
    print("PASS: missing_capture_operator_id_rejected")


def test_missing_reviewer_id_rejected(tmp_path):
    v = _full_scenario(tmp_path, receipt_kwargs_overrides={"reviewer_id": ""})
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_reviewer_missing" in v["reasons"], v["reasons"]
    print("PASS: missing_reviewer_id_rejected")


def test_verdict_not_approved_rejected(tmp_path):
    v = _full_scenario(tmp_path, receipt_kwargs_overrides={"verdict": "REJECTED"})
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_verdict_not_approved" in v["reasons"], v["reasons"]
    print("PASS: verdict_not_approved_rejected")


def test_schema_mismatch_rejected(tmp_path):
    v = _full_scenario(tmp_path, receipt_kwargs_overrides={"schema": "some_other_schema/v1"})
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_schema_invalid" in v["reasons"], v["reasons"]
    print("PASS: schema_mismatch_rejected")


def test_dataset_binding_mismatch_rejected(tmp_path):
    """Receipt claims to review a different dataset digest than is being admitted."""
    v = _full_scenario(
        tmp_path,
        receipt_kwargs_overrides={"extra_fields": {"reviewed_dataset_content_sha256": "0" * 64}},
    )
    assert v["dataset_admitted"] is False, v
    assert any("review_receipt_binding_mismatch:dataset_content_sha256" in r for r in v["reasons"]), v["reasons"]
    print("PASS: dataset_binding_mismatch_rejected")


def test_capture_binding_mismatch_rejected(tmp_path):
    """Receipt claims to review a different capture-receipt digest than is being admitted."""
    v = _full_scenario(
        tmp_path,
        receipt_kwargs_overrides={"extra_fields": {"reviewed_capture_receipt_sha256": "0" * 64}},
    )
    assert v["dataset_admitted"] is False, v
    assert any("review_receipt_binding_mismatch:capture_receipt_sha256" in r for r in v["reasons"]), v["reasons"]
    print("PASS: capture_binding_mismatch_rejected")


def test_session_mismatch_rejected(tmp_path):
    """Receipt's own session_id differs from the session being admitted."""
    v = _full_scenario(
        tmp_path,
        receipt_kwargs_overrides={"extra_fields": {"session_id": "OTHER_SESSION"}},
    )
    # NOTE: the receipt member's artifact-level session_id (used by
    # verify_artifact_set) still matches; only the JSON-body session_id,
    # checked by the review-receipt validator, is wrong.
    assert v["dataset_admitted"] is False, v
    assert "review_receipt_session_mismatch" in v["reasons"], v["reasons"]
    print("PASS: session_mismatch_rejected")


def test_admission_digests_not_distinct_rejected(tmp_path):
    """dataset_content_sha256 and capture_receipt_sha256 must not collide."""
    root = tmp_path / "evidence"
    root.mkdir()
    priv, pub_bytes = _keypair()
    key_id = "review-key-1"
    capture_members, digests = _capture_members(root)
    shared_sha = _write(root, "shared.bin", b"shared-dataset-and-receipt-bytes")
    shared_member = {
        "path": "shared.bin", "sha256": shared_sha, "modality": "dataset",
        "committed": True, "session_id": "s1", "member_id": "shared",
    }
    review_member, review_sha, _ = _write_review_receipt_member(
        root, "review_receipt.json", priv=priv, key_id=key_id,
        dataset_sha=shared_sha, capture_sha=shared_sha,
    )
    members = capture_members + [shared_member, review_member]

    v = evaluate_strict_evidence(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        dataset_content_sha256=shared_sha,
        capture_receipt_sha256=shared_sha,  # <- same digest as dataset_content_sha256
        review_receipt_sha256=review_sha,
        artifact_members=members,
        root=root,
        approved_roots=[root],
        session_id="s1",
        capture_operator_id="capture-operator-1",
        review_trust_root={key_id: ed25519_verifier(pub_bytes)},
    )
    assert v["dataset_admitted"] is False, v
    assert "admission_digests_not_distinct" in v["reasons"], v["reasons"]
    print("PASS: admission_digests_not_distinct_rejected")


def test_admission_digest_reuses_capture_member_rejected(tmp_path):
    """dataset_content_sha256 must not be a verified rgb/semantic/lidar member's own digest."""
    root = tmp_path / "evidence"
    root.mkdir()
    priv, pub_bytes = _keypair()
    key_id = "review-key-1"
    capture_members, digests = _capture_members(root)
    _, dataset_sha_unused, capture_sha = _dataset_and_capture_receipt(root)
    review_member, review_sha, _ = _write_review_receipt_member(
        root, "review_receipt.json", priv=priv, key_id=key_id,
        dataset_sha=digests["rgb"], capture_sha=capture_sha,
    )
    members = capture_members + [
        {"path": "capture_receipt.bin", "sha256": capture_sha, "modality": "capture_receipt",
         "committed": True, "session_id": "s1", "member_id": "capture_receipt"},
        review_member,
    ]

    v = evaluate_strict_evidence(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        dataset_content_sha256=digests["rgb"],  # <- reuses the rgb member's own digest
        capture_receipt_sha256=capture_sha,
        review_receipt_sha256=review_sha,
        artifact_members=members,
        root=root,
        approved_roots=[root],
        session_id="s1",
        capture_operator_id="capture-operator-1",
        review_trust_root={key_id: ed25519_verifier(pub_bytes)},
    )
    assert v["dataset_admitted"] is False, v
    assert "admission_digest_reuses_capture_member:dataset_content_sha256" in v["reasons"], v["reasons"]
    print("PASS: admission_digest_reuses_capture_member_rejected")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
