#!/usr/bin/env python3
"""
P0-4 — Artifact bytes verification (offline synthetic fixtures).
Every route must reject bad content; synthetic fixtures keep NOT_ADMITTED.
"""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from ultimate_pipeline.perception.rq3_evidence_gate import (
    evaluate_strict_evidence, verify_artifact_set, resolve_artifact,
)

# G05: no machine-specific absolute path. The repository root is derived from
# this file's location and may be overridden with RQ3_TEST_ROOT.
_ROOT_ENV = "RQ3_TEST_ROOT"
_ENV_ROOT = os.environ.get(_ROOT_ENV, "").strip()
ROOT = Path(_ENV_ROOT).expanduser() if _ENV_ROOT else Path(__file__).resolve().parents[3]
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
            "sha256": _sha(DELIV / name),
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
    artifacts[0]["sha256"] = _sha(DELIV / "RQ3_PATCH_MANIFEST.json")
    ok, reasons, _ = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT])
    assert ok is False and any("unresolved" in r for r in reasons), f"missing file accepted: {reasons}"
    print("PASS: missing_file")

    # 4. Path traversal rejects
    artifacts[0] = {"path": "../../../etc/passwd", "sha256": _sha(DELIV / "RQ3_PATCH_MANIFEST.json"),
                    "modality": "rgb", "committed": True, "session_id": "s1", "member_id": "trav"}
    ok, reasons, _ = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT])
    assert ok is False and any("unresolved" in r for r in reasons), f"traversal accepted: {reasons}"
    print("PASS: path_traversal")

    # 5. Uncommitted staging rejects
    artifacts[0] = {"path": "reports/phase5_deliverables/RQ3_PATCH_MANIFEST.json", "sha256": _sha(DELIV / "RQ3_PATCH_MANIFEST.json"),
                    "modality": "rgb", "committed": False, "session_id": "s1", "member_id": "staging"}
    ok, reasons, _ = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT])
    assert ok is False and any("staging_uncommitted" in r for r in reasons), f"staging accepted: {reasons}"
    print("PASS: staging_uncommitted")

    # 6. Modified after manifest creation rejects
    # G05: the scratch file must live inside the approved root (so that the
    # relative artifact path resolves) and must not be a machine-specific
    # absolute path. A throwaway directory keeps the repository clean.
    tmp_dir = Path(tempfile.mkdtemp(dir=str(ROOT), prefix=".rq3_test_tmp_"))
    try:
        tmp = tmp_dir / "rq3_truncated_test.json"
        tmp.write_text("{}", encoding="utf-8")
        artifacts[0] = {"path": str(tmp.relative_to(ROOT)), "sha256": hashlib.sha256(b"{}").hexdigest(),
                       "modality": "rgb", "committed": True, "session_id": "s1", "member_id": "mod"}
        tmp.write_bytes(b"MODIFIED")  # content changed after manifest declared
        artifacts[0]["sha256"] = hashlib.sha256(b"{}").hexdigest()  # stale declaration
        ok, reasons, _ = verify_artifact_set(artifacts, root=ROOT, approved_roots=[ROOT])
        assert ok is False and any("digest_mismatch" in r for r in reasons), f"modified after manifest accepted: {reasons}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    print("PASS: modified_after_manifest")

    # 7. Duplicate identity different content
    # Same member_id bound to two different real files whose declared digests
    # are each correct for their own path: only the duplicate-identity rule
    # (same id, different verified content) can reject this pair.
    member_a = {"path": "reports/phase5_deliverables/RQ3_BUILDER_FALSE_PASS_REMEDIATION.json",
                "sha256": _sha(DELIV / "RQ3_BUILDER_FALSE_PASS_REMEDIATION.json"),
                "modality": "semantic", "committed": True, "session_id": "s1", "member_id": "dup"}
    member_b = {"path": "reports/phase5_deliverables/RQ3_PATCH_MANIFEST.json",
                "sha256": _sha(DELIV / "RQ3_PATCH_MANIFEST.json"),
                "modality": "semantic", "committed": True, "session_id": "s1", "member_id": "dup"}
    ok, reasons, _ = verify_artifact_set([member_a, member_b], root=ROOT, approved_roots=[ROOT])
    assert ok is False and any("duplicate_identity" in r for r in reasons), f"dup id accepted: {reasons}"
    print("PASS: duplicate_identity_different_content")

    # 8. Stale session id
    artifacts = [{"path": "reports/phase5_deliverables/RQ3_PATCH_MANIFEST.json", "sha256": _sha(DELIV / "RQ3_PATCH_MANIFEST.json"),
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


def test_approved_root_is_configurable_not_hardcoded(monkeypatch, tmp_path):
    """G05: no machine-specific absolute path may survive in the gate.

    The approved root must be resolvable from the environment or derived
    from the repository layout, never pinned to one workstation.
    """
    import ultimate_pipeline.perception.rq3_evidence_gate as gate

    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "E:\\wt" not in source, "gate still hardcodes a workstation path"
    assert "E:/wt" not in source, "gate still hardcodes a workstation path"

    # Default resolution: the repository root that contains the module.
    assert gate.resolve_approved_root() == Path(gate.__file__).resolve().parents[2]
    # An explicit root always wins.
    assert gate.resolve_approved_root(tmp_path) == tmp_path
    # The environment override is honoured (configuration, not hardcoding).
    monkeypatch.setenv(gate.RQ3_APPROVED_ROOT_ENV, str(tmp_path))
    assert gate.resolve_approved_root() == tmp_path
    print("PASS: approved_root_configurable_not_hardcoded")


def test_test_module_paths_are_portable():
    """G05: this test module must not pin itself to one workstation."""
    source = Path(__file__).read_text(encoding="utf-8")
    assert "E:\\wt" not in source, "test module still hardcodes a workstation path"
    assert ROOT == Path(__file__).resolve().parents[3], "repository root is not derived from this file"
    assert DELIV == ROOT / "reports" / "phase5_deliverables"
    print("PASS: test_module_paths_portable")


def test_committed_field_requires_real_bool():
    """Reviewer B1 (G02a): string-encoded false values must not count as committed.

    The member's bytes satisfy their declaration (real tracked file with a
    matching sha256), so only the committed-type rule (bool required) can
    reject these artifacts.
    """
    real = ROOT / "ultimate_pipeline" / "perception" / "rq3_evidence_gate.py"
    sha = hashlib.sha256(real.read_bytes()).hexdigest()
    relp = "ultimate_pipeline/perception/rq3_evidence_gate.py"

    for bad in ("false", "False", "no", "0", 0, 1, None):
        art = [{"path": relp, "sha256": sha, "modality": "rgb",
                "committed": bad, "session_id": "s1", "member_id": "cbdemo"}]
        ok, reasons, _ = verify_artifact_set(art, root=ROOT, approved_roots=[ROOT], required_modalities=())
        assert ok is False, (bad, ok)
        assert any("committed_invalid" in r or "missing_committed" in r for r in reasons), (bad, reasons)

    # control: a real bool True stays admitted (same artifact, positive check)
    ok, reasons, _ = verify_artifact_set(
        [{"path": relp, "sha256": sha, "modality": "rgb", "committed": True,
          "session_id": "s1", "member_id": "cbtrue"}],
        root=ROOT, approved_roots=[ROOT], required_modalities=())
    assert ok is True, reasons
    print("PASS: committed_field_requires_real_bool")


# ---------------------------------------------------------------------------
# Shared synthetic evidence-set fixture (clearly synthetic, never real RQ3)
# ---------------------------------------------------------------------------

_EVIDENCE_PAYLOADS = {
    "rgb": b"synthetic-rgb-frames",
    "semantic": b"synthetic-semantic-frames",
    "lidar": b"synthetic-lidar-frames",
    "dataset": b"synthetic-dataset-content",
    "capture_receipt": b"synthetic-capture-receipt",
    "review_receipt": b'{"verdict":"APPROVED","reviewer_id":"indep-reviewer-001","reviewed_sha256":"__DATASET__"}',
}


def _write_evidence_set(root: Path):
    """Write a synthetic evidence set on disk; return {name: sha256}."""
    root.mkdir(parents=True, exist_ok=True)
    digests = {}
    # write dataset first to get its sha for review receipt
    dataset_payload = _EVIDENCE_PAYLOADS["dataset"]
    (root / "dataset.bin").write_bytes(dataset_payload)
    digests["dataset"] = hashlib.sha256(dataset_payload).hexdigest()
    for name, payload in _EVIDENCE_PAYLOADS.items():
        if name == "dataset":
            continue
        if name == "review_receipt":
            payload = json.dumps({
                "verdict": "APPROVED",
                "reviewer_id": "indep-reviewer-001",
                "reviewed_sha256": digests["dataset"],
            }).encode("utf-8")
        (root / f"{name}.bin").write_bytes(payload)
        digests[name] = hashlib.sha256(payload).hexdigest()
    return digests


def _artifact_members(digests, names=("rgb", "semantic", "lidar")):
    """Build artifact members whose digests match the written files."""
    members = []
    for name in names:
        members.append({
            "path": f"{name}.bin",
            "sha256": digests[name],
            "modality": name,
            "committed": True,
            "session_id": "s1",
            "member_id": name,
        })
    return members


def _full_evidence_members(digests):
    """Capture members plus the dataset / capture / review receipts.

    The receipts are part of the verified evidence set, so their digests are
    byte-checked by verify_artifact_set() and are therefore usable as the
    content binding for dataset_content_sha256 / capture_receipt_sha256 and
    as the independent-review receipt.
    """
    members = _artifact_members(digests)
    for name in ("dataset", "capture_receipt"):
        members.append({
            "path": f"{name}.bin",
            "sha256": digests[name],
            "modality": "receipt",
            "committed": True,
            "session_id": "s1",
            "member_id": name,
        })
    members.append({
        "path": "review_receipt.bin",
        "sha256": digests["review_receipt"],
        "modality": "review_receipt",
        "committed": True,
        "session_id": "s1",
        "member_id": "review_receipt",
    })
    return members


def test_admission_requires_completed_terminal(tmp_path):
    """G01: a terminal status other than COMPLETED must never be admitted.

    Before the fix the terminal status only produced a reason string that the
    admission branch ignored, so an aborted capture that carried a full
    verified artifact set was still promoted to authoritative evidence.
    """
    root = tmp_path / "evidence"
    digests = _write_evidence_set(root)
    members = _full_evidence_members(digests)

    kwargs = dict(
        synthetic=False,
        independent_review_status="APPROVED",
        dataset_content_sha256=digests["dataset"],
        capture_receipt_sha256=digests["capture_receipt"],
        review_receipt_sha256=digests["review_receipt"],
        artifact_members=members,
        root=root,
        approved_roots=[root],
    )

    # Control: a COMPLETED terminal is admitted.
    admitted = evaluate_strict_evidence(terminal_status="COMPLETED", **kwargs)
    assert admitted["experimental_evidence_authoritative"] is True, admitted
    assert admitted["dataset_admitted"] is True, admitted
    assert admitted["reasons"] == [], admitted["reasons"]

    # Regression: every other terminal status must block admission.
    for bad in ("FAILED", "ABORTED", "", "RUNNING", "completed"):
        v = evaluate_strict_evidence(terminal_status=bad, **kwargs)
        assert v["experimental_evidence_authoritative"] is False, (bad, v)
        assert v["dataset_admitted"] is False, (bad, v)
        assert v["claim_level"] == "UNPAIRED_CAPTURE", (bad, v)
        assert "terminal_capture_not_completed" in v["reasons"], (bad, v)
    print("PASS: admission_requires_completed_terminal")


def test_review_approval_requires_bound_receipt(tmp_path):
    """G02: a bare independent_review_status="APPROVED" must not admit.

    The approval used to be a self-attested string with no binding at all;
    it now requires a review receipt digest that is present in the verified
    evidence set.
    """
    root = tmp_path / "evidence"
    digests = _write_evidence_set(root)
    members = _full_evidence_members(digests)
    base = dict(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        dataset_content_sha256=digests["dataset"],
        capture_receipt_sha256=digests["capture_receipt"],
        artifact_members=members,
        root=root,
        approved_roots=[root],
    )

    # (a) APPROVED without any review receipt -> blocked
    v = evaluate_strict_evidence(**base)
    assert v["experimental_evidence_authoritative"] is False, v
    assert v["dataset_admitted"] is False, v
    assert "independent_review_receipt_missing" in v["reasons"], v["reasons"]

    # (b) APPROVED with a receipt digest that is not in the evidence set -> blocked
    v = evaluate_strict_evidence(review_receipt_sha256="0" * 64, **base)
    assert v["experimental_evidence_authoritative"] is False, v
    assert "independent_review_receipt_not_in_evidence_set" in v["reasons"], v["reasons"]

    # (c) APPROVED with the receipt present in the evidence set -> admitted
    v = evaluate_strict_evidence(review_receipt_sha256=digests["review_receipt"], **base)
    assert v["experimental_evidence_authoritative"] is True, v
    assert v["reasons"] == [], v["reasons"]
    print("PASS: review_approval_requires_bound_receipt")


def test_content_digests_must_resolve_to_real_bytes(tmp_path):
    """G02: declared dataset / capture digests must resolve to real bytes."""
    root = tmp_path / "evidence"
    digests = _write_evidence_set(root)
    members = _full_evidence_members(digests)
    base = dict(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        review_receipt_sha256=digests["review_receipt"],
        root=root,
        approved_roots=[root],
    )

    # (a) dataset digest that names nothing -> blocked
    v = evaluate_strict_evidence(
        dataset_content_sha256="0" * 64,
        capture_receipt_sha256=digests["capture_receipt"],
        artifact_members=members,
        **base,
    )
    assert v["experimental_evidence_authoritative"] is False, v
    assert any(r.startswith("dataset_content_sha256_unresolved") for r in v["reasons"]), v["reasons"]

    # (b) capture receipt digest that names nothing -> blocked
    v = evaluate_strict_evidence(
        dataset_content_sha256=digests["dataset"],
        capture_receipt_sha256="0" * 64,
        artifact_members=members,
        **base,
    )
    assert v["experimental_evidence_authoritative"] is False, v
    assert any(r.startswith("capture_receipt_sha256_unresolved") for r in v["reasons"]), v["reasons"]

    # (c) digest bound to a file whose real bytes differ -> blocked
    members_no_dataset = [m for m in members if m["member_id"] != "dataset"]
    v = evaluate_strict_evidence(
        dataset_content_sha256=digests["dataset"],
        capture_receipt_sha256=digests["capture_receipt"],
        artifact_members=members_no_dataset,
        content_index={digests["dataset"]: root / "rgb.bin"},
        **base,
    )
    assert v["experimental_evidence_authoritative"] is False, v
    assert any("digest_bytes_mismatch" in r for r in v["reasons"]), v["reasons"]

    # (d) digest bound to a path outside the approved roots -> blocked
    v = evaluate_strict_evidence(
        dataset_content_sha256=digests["dataset"],
        capture_receipt_sha256=digests["capture_receipt"],
        artifact_members=members_no_dataset,
        content_index={digests["dataset"]: Path(__file__).resolve()},
        **base,
    )
    assert v["experimental_evidence_authoritative"] is False, v
    assert any("digest_path_not_approved_or_missing" in r for r in v["reasons"]), v["reasons"]

    # (e) fully bound -> admitted
    v = evaluate_strict_evidence(
        dataset_content_sha256=digests["dataset"],
        capture_receipt_sha256=digests["capture_receipt"],
        artifact_members=members,
        **base,
    )
    assert v["experimental_evidence_authoritative"] is True, v
    assert v["reasons"] == [], v["reasons"]
    print("PASS: content_digests_must_resolve_to_real_bytes")


def test_c1_bypass_a_review_receipt_sha_from_rgb_capture_frame(tmp_path):
    """(a) review_receipt_sha256 = sha256 of an RGB capture frame (no receipt exists)."""
    root = tmp_path / "evidence"
    root.mkdir(parents=True, exist_ok=True)
    members = []
    (root / "rgb.bin").write_bytes(b"rgbdata")
    rgb_sha = hashlib.sha256(b"rgbdata").hexdigest()
    members.append({"path": "rgb.bin", "sha256": rgb_sha, "modality": "rgb", "committed": True, "session_id": "s1", "member_id": "rgb"})
    (root / "semantic.bin").write_bytes(b"semdata")
    sem_sha = hashlib.sha256(b"semdata").hexdigest()
    members.append({"path": "semantic.bin", "sha256": sem_sha, "modality": "semantic", "committed": True, "session_id": "s1", "member_id": "semantic"})
    (root / "lidar.bin").write_bytes(b"lidata")
    lidar_sha = hashlib.sha256(b"lidata").hexdigest()
    members.append({"path": "lidar.bin", "sha256": lidar_sha, "modality": "lidar", "committed": True, "session_id": "s1", "member_id": "lidar"})
    (root / "review_receipt.json").write_text(json.dumps({"review": "REJECTED"}))
    review_sha = hashlib.sha256((root / "review_receipt.json").read_bytes()).hexdigest()
    members.append({"path": "review_receipt.json", "sha256": review_sha, "modality": "receipt", "committed": True, "session_id": "s1", "member_id": "review_receipt"})
    (root / "dataset.bin").write_bytes(b"dsdata")
    dataset_sha = hashlib.sha256(b"dsdata").hexdigest()
    (root / "capture.bin").write_bytes(b"capdata")
    capture_sha = hashlib.sha256(b"capdata").hexdigest()
    members.append({"path": "dataset.bin", "sha256": dataset_sha, "modality": "receipt", "committed": True, "session_id": "s1", "member_id": "dataset"})
    members.append({"path": "capture.bin", "sha256": capture_sha, "modality": "receipt", "committed": True, "session_id": "s1", "member_id": "capture_receipt"})
    v = evaluate_strict_evidence(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        dataset_content_sha256=dataset_sha,
        capture_receipt_sha256=capture_sha,
        review_receipt_sha256=rgb_sha,
        artifact_members=members,
        root=root,
        approved_roots=[root],
    )
    assert v["experimental_evidence_authoritative"] is False
    assert any("review_receipt" in r for r in v["reasons"])


def test_c1_bypass_b_digest_equality_to_capture_members(tmp_path):
    """(b) review/dataset/capture digests = the rgb/semantic/lidar member frames, content_index=None."""
    root = tmp_path / "evidence"
    root.mkdir(parents=True, exist_ok=True)
    members = []
    (root / "rgb.bin").write_bytes(b"rgbdata")
    rgb_sha = hashlib.sha256(b"rgbdata").hexdigest()
    members.append({"path": "rgb.bin", "sha256": rgb_sha, "modality": "rgb", "committed": True, "session_id": "s1", "member_id": "rgb"})
    (root / "semantic.bin").write_bytes(b"semdata")
    sem_sha = hashlib.sha256(b"semdata").hexdigest()
    members.append({"path": "semantic.bin", "sha256": sem_sha, "modality": "semantic", "committed": True, "session_id": "s1", "member_id": "semantic"})
    (root / "lidar.bin").write_bytes(b"lidata")
    lidar_sha = hashlib.sha256(b"lidata").hexdigest()
    members.append({"path": "lidar.bin", "sha256": lidar_sha, "modality": "lidar", "committed": True, "session_id": "s1", "member_id": "lidar"})
    (root / "review_receipt.json").write_text(json.dumps({"review": "REJECTED"}))
    review_sha = hashlib.sha256((root / "review_receipt.json").read_bytes()).hexdigest()
    members.append({"path": "review_receipt.json", "sha256": review_sha, "modality": "receipt", "committed": True, "session_id": "s1", "member_id": "review_receipt"})
    v = evaluate_strict_evidence(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        dataset_content_sha256=rgb_sha,
        capture_receipt_sha256=sem_sha,
        review_receipt_sha256=lidar_sha,
        artifact_members=members,
        root=root,
        approved_roots=[root],
    )
    assert v["experimental_evidence_authoritative"] is False
    assert any("review_receipt" in r or "dataset_capture_review_digest_collision" in r or "shares_capture_member" in r for r in v["reasons"])


def test_c1_bypass_c_receipt_content_rejected(tmp_path):
    """(c) the "receipt" file's content is {"review":"REJECTED"}."""
    root = tmp_path / "evidence"
    root.mkdir(parents=True, exist_ok=True)
    members = []
    (root / "rgb.bin").write_bytes(b"rgbdata")
    rgb_sha = hashlib.sha256(b"rgbdata").hexdigest()
    members.append({"path": "rgb.bin", "sha256": rgb_sha, "modality": "rgb", "committed": True, "session_id": "s1", "member_id": "rgb"})
    (root / "semantic.bin").write_bytes(b"semdata")
    sem_sha = hashlib.sha256(b"semdata").hexdigest()
    members.append({"path": "semantic.bin", "sha256": sem_sha, "modality": "semantic", "committed": True, "session_id": "s1", "member_id": "semantic"})
    (root / "lidar.bin").write_bytes(b"lidata")
    lidar_sha = hashlib.sha256(b"lidata").hexdigest()
    members.append({"path": "lidar.bin", "sha256": lidar_sha, "modality": "lidar", "committed": True, "session_id": "s1", "member_id": "lidar"})
    (root / "review_receipt.json").write_text(json.dumps({"review": "REJECTED"}))
    review_sha = hashlib.sha256((root / "review_receipt.json").read_bytes()).hexdigest()
    members.append({"path": "review_receipt.json", "sha256": review_sha, "modality": "receipt", "committed": True, "session_id": "s1", "member_id": "review_receipt"})
    (root / "dataset.bin").write_bytes(b"dsdata")
    dataset_sha = hashlib.sha256(b"dsdata").hexdigest()
    (root / "capture.bin").write_bytes(b"capdata")
    capture_sha = hashlib.sha256(b"capdata").hexdigest()
    members.append({"path": "dataset.bin", "sha256": dataset_sha, "modality": "receipt", "committed": True, "session_id": "s1", "member_id": "dataset"})
    members.append({"path": "capture.bin", "sha256": capture_sha, "modality": "receipt", "committed": True, "session_id": "s1", "member_id": "capture_receipt"})
    v = evaluate_strict_evidence(
        synthetic=False,
        independent_review_status="APPROVED",
        terminal_status="COMPLETED",
        dataset_content_sha256=dataset_sha,
        capture_receipt_sha256=capture_sha,
        review_receipt_sha256=review_sha,
        artifact_members=members,
        root=root,
        approved_roots=[root],
    )
    assert v["experimental_evidence_authoritative"] is False
    assert any("verdict_not_approved" in r or "review_receipt_verdict_not_approved" in r for r in v["reasons"])


if __name__ == "__main__":
    test_artifact_integrity_checks()
    test_test_module_paths_are_portable()
    print("\n=== P0-4 ARTIFACT CONTENT VERIFICATION: 10/10 PASS ===")
