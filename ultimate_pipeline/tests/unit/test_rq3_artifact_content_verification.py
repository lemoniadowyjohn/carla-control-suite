#!/usr/bin/env python3
"""
P0-4 — Artifact bytes verification (offline synthetic fixtures).
Every route must reject bad content; synthetic fixtures keep NOT_ADMITTED.
"""
import hashlib
from pathlib import Path

from ultimate_pipeline.perception.rq3_evidence_gate import (
    evaluate_strict_evidence, verify_artifact_set, resolve_artifact,
)

ROOT = Path(r"E:\wt\repair-map-realism-p0-837a8504")
DELIV = ROOT / "reports" / "phase5_deliverables"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_artifact_integrity_checks():
    files = [
        ("RQ3_PATCH_MANIFEST.json", "rgb"),
        ("RQ3_BUILDER_FALSE_PASS_REMEDIATION.json", "semantic"),
        ("RQ3_CROSS_ARM_23_TEST_RECEIPT.json", "lidar"),
    ]
    artifacts = []
    for name, mod in files:
        a = {
            "path": f"reports/phase5_deliverables/{name}",
            "sha256": _sha(ROOT / name),
            "modality": mod,
            "committed": True,
            "session_id": "s1",
            "member_id": name[:12],
        }
        artifacts.append(a)

    # 1. Correct digest passes all modalities
    ok, reasons, verified = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT])
    assert ok is True and len(reasons) == 0, f"correct digest rejected: {reasons}"
    print("PASS: correct_digest")

    # 2. Wrong digest rejects
    for a in artifacts:
        a["sha256"] = "0" * 64
    ok, reasons, _ = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT])
    assert ok is False and any("digest_mismatch" in r for r in reasons), f"wrong digest accepted: {reasons}"
    print("PASS: wrong_digest")

    # 3. Missing file rejects
    artifacts[0]["path"] = "nonexistent_file_12345.json"
    artifacts[0]["sha256"] = _sha(ROOT / "RQ3_PATCH_MANIFEST.json")
    ok, reasons, _ = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT])
    assert ok is False and any("unresolved" in r for r in reasons), f"missing file accepted: {reasons}"
    print("PASS: missing_file")

    # 4. Path traversal rejects
    artifacts[0] = {"path": "../../../etc/passwd", "sha256": _sha(ROOT / "RQ3_PATCH_MANIFEST.json"),
                    "modality": "rgb", "committed": True, "session_id": "s1", "member_id": "trav"}
    ok, reasons, _ = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT])
    assert ok is False and any("unresolved" in r for r in reasons), f"traversal accepted: {reasons}"
    print("PASS: path_traversal")

    # 5. Uncommitted staging rejects
    artifacts[0] = {"path": "reports/phase5_deliverables/RQ3_PATCH_MANIFEST.json", "sha256": _sha(ROOT / "RQ3_PATCH_MANIFEST.json"),
                    "modality": "rgb", "committed": False, "session_id": "s1", "member_id": "staging"}
    ok, reasons, _ = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT])
    assert ok is False and any("staging_uncommitted" in r for r in reasons), f"staging accepted: {reasons}"
    print("PASS: staging_uncommitted")

    # 6. Modified after manifest creation rejects
    tmp = Path(r"E:\temp\rq3_truncated_test.json")
    tmp.write_text("{}", encoding="utf-8")
    artifacts[0] = {"path": str(tmp.relative_to(ROOT)), "sha256": hashlib.sha256(b"{}").hexdigest(),
                   "modality": "rgb", "committed": True, "session_id": "s1", "member_id": "mod"}
    tmp.write_bytes(b"MODIFIED")  # content changed after manifest declared
    artifacts[0]["sha256"] = hashlib.sha256(b"{}").hexdigest()  # stale declaration
    ok, reasons, _ = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT])
    assert ok is False and any("digest_mismatch" in r for r in reasons), f"modified after manifest accepted: {reasons}"
    tmp.unlink()
    print("PASS: modified_after_manifest")

    # 7. Duplicate identity different content
    dup = {"path": "reports/phase5_deliverables/RQ3_BUILDER_FALSE_PASS_REMEDIATION.json",
           "sha256": _sha(ROOT / "RQ3_PATCH_MANIFEST.json"),
           "modality": "semantic", "committed": True, "session_id": "s1", "member_id": "dup"}
    ok, reasons, _ = verify_artifact_set(artifacts + [dup], root=ROOT, approved_roots=[ROOT])
    assert ok is False and any("duplicate_identity" in r for r in reasons), f"dup id accepted: {reasons}"
    print("PASS: duplicate_identity_different_content")

    # 8. Stale session id
    artifacts = [{"path": "reports/phase5_deliverables/RQ3_PATCH_MANIFEST.json", "sha256": _sha(ROOT / "RQ3_PATCH_MANIFEST.json"),
                  "modality": "rgb", "committed": True, "session_id": "OTHER_SESSION", "member_id": "stale"}]
    ok, reasons, _ = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT], expected_session_id="S1")
    assert ok is False and any("stale_session_id" in r for r in reasons), f"stale session accepted: {reasons}"
    print("PASS: stale_session_id")

    # 9. Synthetic valid fixture: structural pass, never authoritative
    v = evaluate_strict_evidence(
        synthetic=True, independent_review_status="NOT_RUN", terminal_status="COMPLETED",
        dataset_content_sha256="ds_sha", capture_receipt_sha256="r_sha")
    assert v["structural_test_valid"] is True
    assert v["synthetic_fixture_valid"] is True
    assert v["experimental_evidence_authoritative"] is False
    assert v["claim_level"] == "SYNTHETIC_TEST_ONLY"
    assert "independent_review_not_approved" in v["reasons"]
    print("PASS: synthetic_fixture_structural_valid_not_authoritative")

    # 10. Non-synthetic-shaped without live artifacts → not admitted
    v2 = evaluate_strict_evidence(
        synthetic=False, independent_review_status="APPROVED", terminal_status="COMPLETED",
        dataset_content_sha256="ds_sha", capture_receipt_sha256="r_sha", artifact_members=[])
    assert v2["structural_test_valid"] is True
    assert v2["experimental_evidence_authoritative"] is False
    assert v2["dataset_admitted"] is False
    print("PASS: non_synthetic_without_live_artifacts_not_admitted")


if __name__ == "__main__":
    test_artifact_integrity_checks()
    print("\n=== P0-4 ARTIFACT CONTENT VERIFICATION: 10/10 PASS ===")
