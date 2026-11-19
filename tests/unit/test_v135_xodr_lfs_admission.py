"""F08 Git LFS pointer / malformed XODR / identity-mismatch admission tests (V135, test-only)."""
from __future__ import annotations

import hashlib
import json

import pytest

from ultimate_pipeline.quality.map_acceptance import validate_release_acceptance_contract
from ultimate_pipeline.quality.xml_admission import (
    UnsafeXMLError,
    admitted_xodr_snapshot,
    check_xml_boundary,
    parse_xodr_bytes,
    parse_xodr_file,
    read_xodr_bytes,
)

LFS_POINTER = (
    b"version https://git-lfs.github.com/spec/v1\n"
    b"oid sha256:4b825dc642cb6eb9a060e54bf8d69288fbee4904\n"
    b"size 123456789\n"
)


def test_lfs_pointer_rejected_by_xml_admission():
    # Must fail closed before any expensive map parsing/metrics can treat it as a map.
    with pytest.raises(UnsafeXMLError):
        check_xml_boundary(LFS_POINTER)
    with pytest.raises(UnsafeXMLError):
        parse_xodr_bytes(LFS_POINTER)


def test_lfs_pointer_file_rejected(tmp_path):
    p = tmp_path / "pointer.xodr"
    p.write_bytes(LFS_POINTER)
    # read_xodr_bytes performs bounded read/snapshot checks, not content parsing;
    # callers must not treat a readable file as admitted before parse.
    assert read_xodr_bytes(p) == LFS_POINTER
    with pytest.raises(UnsafeXMLError):
        parse_xodr_file(p)


def test_corrupted_or_incomplete_xml_rejected():
    with pytest.raises(UnsafeXMLError):
        parse_xodr_bytes(b"<OpenDRIVE><road")
    with pytest.raises(UnsafeXMLError):
        parse_xodr_bytes(b"<?xml version='1.0'?><OpenDRIVE>")


def test_wrong_root_rejected():
    with pytest.raises(UnsafeXMLError):
        parse_xodr_bytes(b'<?xml version="1.0"?><notOpenDRIVE></notOpenDRIVE>')


def test_valid_minimal_xodr_bytes_admitted():
    data = b'<?xml version="1.0" encoding="UTF-8"?><OpenDRIVE><header revMajor="1" revMinor="4"/></OpenDRIVE>'
    root = parse_xodr_bytes(data)
    assert root.tag == "OpenDRIVE"


def test_admitted_snapshot_preserves_exact_bytes(tmp_path):
    data = b'<?xml version="1.0" encoding="UTF-8"?><OpenDRIVE></OpenDRIVE>'
    with admitted_xodr_snapshot(data, parent=tmp_path) as snap:
        assert snap.read_bytes() == data
        assert snap.name == "admitted.xodr"
    assert not snap.exists()


def test_release_acceptance_contract_rejects_incorrect_expected_sha():
    good_sha = hashlib.sha256(b"map").hexdigest()
    payload = {
        "acceptance_purpose": "release",
        "mandatory_gate_set": "RELEASE_EXPERIMENT_READY",
        "valid_for_experiments": True,
        "valid_for_release": True,
        "artifact_identity_verified": True,
        "release_eligible": True,
        "final_xodr_sha256": good_sha,
        "evaluated_xodr_sha256": good_sha,
        "run_id": "run-1",
        "hard_fail_reasons": [],
    }
    # Correct expected digest: no identity problem for that check.
    problems = validate_release_acceptance_contract(payload, expected_xodr_sha256=good_sha)
    assert not any("expected published artifact sha256" in p for p in problems)

    bad_sha = "0" * 64
    problems = validate_release_acceptance_contract(payload, expected_xodr_sha256=bad_sha)
    assert any("expected published artifact sha256" in p for p in problems)


def test_release_acceptance_contract_rejects_mismatched_or_nonhex_identity():
    payload = {
        "acceptance_purpose": "release",
        "mandatory_gate_set": "RELEASE_EXPERIMENT_READY",
        "valid_for_experiments": True,
        "valid_for_release": True,
        "artifact_identity_verified": True,
        "release_eligible": True,
        "final_xodr_sha256": "not-a-sha",
        "evaluated_xodr_sha256": "not-a-sha",
        "run_id": "run-1",
        "hard_fail_reasons": [],
    }
    problems = validate_release_acceptance_contract(payload)
    assert any("final_xodr_sha256" in p for p in problems)
    assert any("evaluated_xodr_sha256" in p for p in problems)

    payload["final_xodr_sha256"] = hashlib.sha256(b"a").hexdigest()
    payload["evaluated_xodr_sha256"] = hashlib.sha256(b"b").hexdigest()
    problems = validate_release_acceptance_contract(payload)
    assert any("does not match evaluated_xodr_sha256" in p for p in problems)


def test_release_acceptance_contract_rejects_missing_or_wrong_run_identity():
    good_sha = hashlib.sha256(b"map").hexdigest()
    payload = {
        "acceptance_purpose": "release",
        "mandatory_gate_set": "RELEASE_EXPERIMENT_READY",
        "valid_for_experiments": True,
        "valid_for_release": True,
        "artifact_identity_verified": True,
        "release_eligible": True,
        "final_xodr_sha256": good_sha,
        "evaluated_xodr_sha256": good_sha,
        "run_id": "",
        "hard_fail_reasons": [],
    }
    problems = validate_release_acceptance_contract(payload)
    assert any("run_id is required" in p for p in problems)
    payload["run_id"] = "run-1"
    problems = validate_release_acceptance_contract(payload, expected_run_id="run-other")
    assert any("does not match expected" in p for p in problems)
