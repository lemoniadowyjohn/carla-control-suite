"""Tests for the O17 / NEW-265 RQ3 dataset manifest verifier."""
import hashlib
import json

from tools.rq3_dataset_manifest_verifier import (
    REQUIRED,
    PAIRED_EQUALITY_FIELDS,
    verify,
    verify_dataset_files,
    verify_manifest_self_hash,
)

IDENTITY = {
    "calibration_identity": "calib1",
    "capture_config_sha256": "c" * 64,
    "software_sha256": "d" * 64,
}


def _manifest(root=None, frames=("f1", "f2"), **extra):
    payload = {field: "value" for field in REQUIRED}
    payload.update(IDENTITY)
    payload["frame_ids"] = list(frames)
    if root is not None:
        payload["dataset_root"] = str(root)
    payload.update(extra)
    return payload


def _write_dataset(tmp_path, n=2):
    root = tmp_path / "dataset"
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for i in range(n):
        path = root / "rgb" / f"{i:08d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = f"frame-{i}".encode()
        path.write_bytes(data)
        entries.append(
            {
                "sensor": "rgb_front",
                "kind": "rgb",
                "path": f"rgb/{i:08d}.png",
                "frame_id": f"f{i + 1}",
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return root, entries


def test_valid_manifest_without_paired_is_incomplete():
    """GAP-033: verify() without paired manifest must not return PASS."""
    report = verify(_manifest())
    assert report["status"] in ("INCOMPLETE", "SKIPPED_NO_PAIR")
    assert report["paired_contract_mismatches"] == []
    assert report.get("pairing_performed") is False


def test_valid_manifest_with_paired_passes(tmp_path):
    """NEW-265: PASS now requires real dataset inspection, not field presence."""
    root, entries = _write_dataset(tmp_path)
    a = _manifest(root=root, files=entries)
    b = _manifest(root=root, files=entries)
    report = verify(a, b)
    assert report["status"] == "PASS"
    assert report["quality_comparison"] == "NOT_RUN"
    assert report.get("pairing_performed") is True
    assert report["file_verification"]["status"] == "PASS"
    assert report["file_verification"]["files_inspected"] == 2
    assert report["independent_verification"] is True


def test_manifest_without_dataset_root_is_not_scientific_authority(tmp_path):
    """Presence-only verification must never be reported as PASS."""
    report = verify(_manifest(), _manifest())
    assert report["status"] != "PASS"
    assert report["status"] == "INCOMPLETE"
    assert report["file_verification"]["status"] == "NOT_RUN"


def test_duplicate_frames_fail():
    manifest = _manifest(frames=("f1", "f1"))
    assert verify(manifest)["status"] == "FAIL"


def test_missing_frames_fail():
    manifest = _manifest()
    manifest["missing_frames"] = ["f2"]
    assert verify(manifest)["status"] == "FAIL"


def test_paired_contract_mismatch_fails(tmp_path):
    root, entries = _write_dataset(tmp_path)
    a = _manifest(root=root, files=entries)
    b = _manifest(root=root, files=entries, route_id="other")
    report = verify(a, b)
    assert report["status"] == "FAIL"
    assert "route_id" in report["paired_contract_mismatches"]
    assert report.get("pairing_performed") is True


def test_paired_controlled_variable_mismatch_is_caught(tmp_path):
    """NEW-266: ALL controlled variables must match, not a hand-picked subset."""
    root, entries = _write_dataset(tmp_path)
    a = _manifest(root=root, files=entries)
    b = _manifest(root=root, files=entries, capture_config_sha256="e" * 64)
    report = verify(a, b)
    assert report["status"] == "FAIL"
    assert "capture_config_sha256" in report["paired_contract_mismatches"]
    assert "capture_config_sha256" in PAIRED_EQUALITY_FIELDS


def test_file_content_hash_mismatch_fails(tmp_path):
    root, entries = _write_dataset(tmp_path)
    entries = [dict(e) for e in entries]
    entries[0]["sha256"] = "0" * 64
    manifest = _manifest(root=root, files=entries)
    report = verify(manifest, manifest)
    assert report["status"] == "FAIL"
    assert any("file_content_hash_mismatch" in f for f in report["failures"])


def test_missing_file_fails(tmp_path):
    root, entries = _write_dataset(tmp_path)
    entries = [dict(e) for e in entries]
    entries.append(
        {
            "sensor": "rgb_front",
            "kind": "rgb",
            "path": "rgb/does_not_exist.png",
            "frame_id": "f99",
            "sha256": "1" * 64,
        }
    )
    manifest = _manifest(root=root, files=entries)
    report = verify(manifest, manifest)
    assert report["status"] == "FAIL"
    assert any("expected_files_missing" in f for f in report["failures"])


def test_missing_identity_fields_fail():
    payload = {field: "value" for field in REQUIRED}
    payload["frame_ids"] = ["f1"]
    report = verify(payload, payload)
    assert report["status"] == "FAIL"
    assert any("missing calibration_identity" in f for f in report["failures"])
    assert any("missing software_sha256" in f for f in report["failures"])


def test_manifest_self_hash_tamper_detected(tmp_path):
    root, entries = _write_dataset(tmp_path)
    payload = {k: v for k, v in _manifest(root=root, files=entries).items()}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    payload["manifest_self_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    assert verify_manifest_self_hash(payload) == []
    payload["route_id"] = "tampered"
    assert verify_manifest_self_hash(payload)


def test_verify_dataset_files_requires_root():
    report = verify_dataset_files(_manifest())
    assert report["status"] == "NOT_RUN"
    assert report["failures"] == ["dataset_root_required_for_independent_verification"]
