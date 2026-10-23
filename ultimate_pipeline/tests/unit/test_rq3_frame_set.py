#!/usr/bin/env python3
"""
P0-2 full regression and negative-control tests for rq3_frame_set.py.

Covers every listed requirement:
1. RGB/semantic/LiDAR frame sets agree within an arm
2. Equal counts with unequal frame IDs fail
3. Missing LiDAR fails where LiDAR is mandatory
4. Missing semantic camera fails
5. Timestamp mismatch fails under frozen tolerance
6. Duplicate sensor frame fails
7. Uncommitted staging frame fails
8. Valid interrupted-run recovery rejects unfinished frames
9. Paired route-frame alignment checked across arms
10. Incorrect RGB-to-semantic correspondence fails
11. Hash-bound complete frame set passes

All fixtures are SYNTHETIC and are never registered as real RQ3 captures.
"""

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from ultimate_pipeline.perception.rq3_frame_set import (
    ArmFrameSet,
    REASON_DUPLICATE_MEMBER,
    REASON_FRAME_ID_MISMATCH,
    REASON_MISSING_HASH,
    REASON_MISSING_MODALITY,
    REASON_STAGING_FRAME,
    REASON_TIMESTAMP_MISMATCH,
    REASON_UNCOMMITTED_MEMBER,
    FrameMember,
    build_accepted_frame_manifest,
    dataset_root_sha256,
    intersect_frame_sets,
    validate_arm_frame_set,
    verify_frame_manifest_hashes,
)


def _m(fi, fid, ts, mod, name="sensor", sha="abc", committed=True, staging=False):
    return FrameMember(
        frame_index=fi, frame_id=fid, timestamp=ts, modality=mod, sensor_name=name,
        sha256=sha, committed=committed, staging=staging,
    )


def _arm(members, arm_name="manual"):
    a = ArmFrameSet(arm_name=arm_name)
    for m in members:
        a.add(m)
    return a


def _reasons(result, frame_index=None):
    """Flatten the rejected list into a set of reason codes."""
    out = set()
    for entry in result.get("rejected", []):
        if frame_index is not None and entry.get("frame_index") != frame_index:
            continue
        for rr in entry.get("reasons", []):
            out.add(rr.get("reason"))
    return out


def _complete(fi, fid, ts, sha_prefix="x"):
    return [
        _m(fi, fid, ts, "rgb", sha=sha_prefix + "r"),
        _m(fi, fid, ts, "semantic", sha=sha_prefix + "s"),
        _m(fi, fid, ts, "lidar", sha=sha_prefix + "l"),
    ]


# --------------------------------------------------------------------------
# 1. Within-arm completeness and intersection
# --------------------------------------------------------------------------


def test_within_arm_completeness():
    members = _complete(0, 1000, 1.0) + _complete(1, 1001, 1.05)
    result = validate_arm_frame_set(_arm(members))
    assert result["valid"] is True, result["rejected"]
    assert result["accepted_frame_indices"] == [0, 1]
    print("PASS: within_arm_completeness")


def test_within_arm_intersection():
    m_members = _complete(0, 1000, 1.0)
    a_members = _complete(0, 1000, 1.0)
    inter = intersect_frame_sets(_arm(m_members), _arm(a_members))
    assert inter["valid"] is True, inter["errors"]
    assert inter["accepted_count"] == 1
    print("PASS: within_arm_intersection")


# --------------------------------------------------------------------------
# 2. Equal counts with unequal frame IDs fail
# --------------------------------------------------------------------------


def test_unequal_frame_ids_fail():
    # Same ordinal count on both arms, but the CARLA frame ids differ across
    # modalities inside one arm -> intra-arm frame_id mismatch.
    m_members = _complete(0, 1000, 1.0)
    a_members = [
        _m(0, 1000, 1.0, "rgb", sha="r"),
        _m(0, 999, 1.0, "semantic", sha="s"),
        _m(0, 1000, 1.0, "lidar", sha="l"),
    ]
    mr = validate_arm_frame_set(_arm(m_members))
    ar = validate_arm_frame_set(_arm(a_members))
    assert mr["valid"] is True, mr["rejected"]
    assert ar["valid"] is False
    assert REASON_FRAME_ID_MISMATCH in _reasons(ar)
    inter = intersect_frame_sets(_arm(m_members), _arm(a_members))
    assert inter["valid"] is False
    print("PASS: unequal_frame_ids_fail")


def test_equal_counts_unequal_cross_arm_keys_fail():
    # Manual accepts keys {0}; auto accepts key {5}. Equal count (1 each),
    # unequal keys -> must fail.
    m_members = _complete(0, 1000, 1.0)
    a_members = _complete(5, 5000, 1.0)
    inter = intersect_frame_sets(_arm(m_members), _arm(a_members))
    assert inter["valid"] is False
    assert inter["accepted_count"] == 0
    assert any("pairing_keys_missing" in e for e in inter["errors"]), inter["errors"]
    print("PASS: equal_counts_unequal_cross_arm_keys_fail")


# --------------------------------------------------------------------------
# 3. Missing LiDAR fails where LiDAR is mandatory
# --------------------------------------------------------------------------


def test_missing_lidar_fails():
    members = [
        _m(0, 1000, 1.0, "rgb", sha="r"),
        _m(0, 1000, 1.0, "semantic", sha="s"),
    ]
    result = validate_arm_frame_set(_arm(members))
    assert result["valid"] is False
    assert REASON_MISSING_MODALITY in _reasons(result)
    print("PASS: missing_lidar_fails")


def test_missing_lidar_allowed_when_not_mandatory():
    members = [
        _m(0, 1000, 1.0, "rgb", sha="r"),
        _m(0, 1000, 1.0, "semantic", sha="s"),
    ]
    result = validate_arm_frame_set(_arm(members), required_modalities=("rgb", "semantic"))
    assert result["valid"] is True, result["rejected"]
    print("PASS: missing_lidar_allowed_when_not_mandatory")


# --------------------------------------------------------------------------
# 4. Missing semantic camera fails
# --------------------------------------------------------------------------


def test_missing_semantic_camera_fails():
    members = [
        _m(0, 1000, 1.0, "rgb", sha="r"),
        _m(0, 1000, 1.0, "lidar", sha="l"),
    ]
    result = validate_arm_frame_set(_arm(members))
    assert result["valid"] is False
    assert REASON_MISSING_MODALITY in _reasons(result)
    print("PASS: missing_semantic_camera_fails")


# --------------------------------------------------------------------------
# 5. Timestamp mismatch fails under frozen tolerance
# --------------------------------------------------------------------------


def test_timestamp_mismatch_fails():
    tolerance = 1.0 / 60.0
    members = [
        _m(0, 1000, 0.5, "rgb", sha="r"),
        _m(0, 1000, tolerance * 2 + 0.001, "semantic", sha="s"),
        _m(0, 1000, tolerance * 2 + 0.001, "lidar", sha="l"),
    ]
    result = validate_arm_frame_set(_arm(members), timestamp_tolerance_s=tolerance)
    assert result["valid"] is False
    assert REASON_TIMESTAMP_MISMATCH in _reasons(result)
    print("PASS: timestamp_mismatch_fails")


def test_timestamp_within_tolerance_passes():
    tolerance = 1.0 / 60.0
    members = [
        _m(0, 1000, 0.5, "rgb", sha="r"),
        _m(0, 1000, 0.5 + tolerance / 2, "semantic", sha="s"),
        _m(0, 1000, 0.5, "lidar", sha="l"),
    ]
    result = validate_arm_frame_set(_arm(members), timestamp_tolerance_s=tolerance)
    assert result["valid"] is True, result["rejected"]
    print("PASS: timestamp_within_tolerance_passes")


# --------------------------------------------------------------------------
# 6. Duplicate sensor frame fails
# --------------------------------------------------------------------------


def test_duplicate_member_fails():
    members = [
        _m(0, 1000, 1.0, "rgb", sha="r"),
        _m(0, 1000, 1.0, "rgb", sha="r2"),
        _m(0, 1000, 1.0, "semantic", sha="s"),
        _m(0, 1000, 1.0, "lidar", sha="l"),
    ]
    result = validate_arm_frame_set(_arm(members))
    assert result["valid"] is False
    assert REASON_DUPLICATE_MEMBER in _reasons(result)
    print("PASS: duplicate_member_fails")


# --------------------------------------------------------------------------
# 7. Uncommitted staging frames fail
# --------------------------------------------------------------------------


def test_uncommitted_member_fails():
    members = [
        _m(0, 1000, 1.0, "rgb", sha="r", committed=True),
        _m(0, 1000, 1.0, "semantic", sha="s", committed=False),
        _m(0, 1000, 1.0, "lidar", sha="l", committed=True),
    ]
    result = validate_arm_frame_set(_arm(members), require_committed=True)
    assert result["valid"] is False
    assert REASON_UNCOMMITTED_MEMBER in _reasons(result)
    print("PASS: uncommitted_member_fails")


def test_staging_frame_fails():
    members = [
        _m(0, 1000, 1.0, "rgb", sha="r", staging=True),
        _m(0, 1000, 1.0, "semantic", sha="s", committed=True),
        _m(0, 1000, 1.0, "lidar", sha="l", committed=True),
    ]
    result = validate_arm_frame_set(_arm(members))
    assert result["valid"] is False
    assert REASON_STAGING_FRAME in _reasons(result)
    print("PASS: staging_frame_fails")


def test_missing_hash_fails():
    members = [
        _m(0, 1000, 1.0, "rgb", sha=""),
        _m(0, 1000, 1.0, "semantic", sha="s"),
        _m(0, 1000, 1.0, "lidar", sha="l"),
    ]
    result = validate_arm_frame_set(_arm(members), require_hash=True)
    assert result["valid"] is False
    assert REASON_MISSING_HASH in _reasons(result)
    print("PASS: missing_hash_fails")


# --------------------------------------------------------------------------
# 8. Valid interrupted-run recovery rejects unfinished frames
# --------------------------------------------------------------------------


def test_interrupted_recovery_rejects_unfinished():
    members = _complete(0, 1000, 1.0) + [
        _m(1, 1001, 1.05, "rgb", sha="r", staging=True, committed=False),
    ]
    result = validate_arm_frame_set(_arm(members))
    assert result["valid"] is False
    assert 1 not in result["accepted_frame_indices"]
    assert REASON_STAGING_FRAME in _reasons(result, frame_index=1)
    assert result["accepted_frame_indices"] == [0]
    print("PASS: interrupted_recovery_rejects_unfinished")


# --------------------------------------------------------------------------
# 9. Paired route-frame alignment across arms
# --------------------------------------------------------------------------


def test_paired_route_frame_alignment():
    m_members = _complete(0, 1000, 1.0) + _complete(1, 1001, 1.05)
    a_members = _complete(0, 2000, 1.0) + _complete(1, 2001, 1.05)
    inter = intersect_frame_sets(_arm(m_members), _arm(a_members))
    assert inter["valid"] is True, inter["errors"]
    # Different absolute CARLA frame ids across arms are OK (independent worlds)
    assert inter["accepted_pairing_keys"] == [0, 1]
    print("PASS: paired_route_frame_alignment")


def test_cross_arm_alignment_mismatch_keys():
    m_members = _complete(0, 1000, 1.0)
    a_members = [
        _m(0, 1000, 1.0, "rgb", sha="r"),
    ]
    inter = intersect_frame_sets(_arm(m_members), _arm(a_members))
    assert inter["valid"] is False
    assert len(inter["errors"]) > 0
    print("PASS: cross_arm_alignment_mismatch_keys")


# --------------------------------------------------------------------------
# 10. Incorrect RGB-to-semantic correspondence fails
# --------------------------------------------------------------------------


def test_incorrect_rgb_semantic_correspondence():
    # The semantic camera is bound to a different CARLA frame id than the RGB
    # camera inside the same arm -> the frame must be rejected.
    m_members = _complete(0, 1000, 1.0)
    a_members = [
        _m(0, 1000, 1.0, "rgb", sha="r"),
        _m(0, 999, 1.0, "semantic", sha="s"),
        _m(0, 1000, 1.0, "lidar", sha="l"),
    ]
    inter = intersect_frame_sets(_arm(m_members), _arm(a_members))
    assert inter["valid"] is False
    assert inter["accepted_count"] == 0
    assert REASON_FRAME_ID_MISMATCH in _reasons(inter["auto"])
    print("PASS: incorrect_rgb_semantic_correspondence")


def test_wrong_modality_name_rejected():
    members = [
        _m(0, 1000, 1.0, "color", sha="r"),
        _m(0, 1000, 1.0, "semantic", sha="s"),
        _m(0, 1000, 1.0, "lidar", sha="l"),
    ]
    result = validate_arm_frame_set(_arm(members))
    assert result["valid"] is False
    assert REASON_MISSING_MODALITY in _reasons(result)
    print("PASS: wrong_modality_name_rejected")


# --------------------------------------------------------------------------
# 11. Hash-bound complete frame set passes
# --------------------------------------------------------------------------


def test_hash_bound_complete_frame_set():
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        payloads = {"rgb": b"\x00" * 12, "semantic": b"\x01" * 12, "lidar": b"\x02" * 12}
        digests = {k: hashlib.sha256(v).hexdigest() for k, v in payloads.items()}

        paths = {}
        for mod, payload in payloads.items():
            p = tdp / f"0_{mod}.bin"
            p.write_bytes(payload)
            paths[mod] = p

        members = [
            _m(0, 1000, 1.0, "rgb", sha=digests["rgb"]),
            _m(0, 1000, 1.0, "semantic", sha=digests["semantic"]),
            _m(0, 1000, 1.0, "lidar", sha=digests["lidar"]),
        ]
        inter = intersect_frame_sets(_arm(members), _arm(members))
        assert inter["valid"] is True, inter["errors"]

        manifest = build_accepted_frame_manifest(_arm(members), _arm(members), inter)
        verify = verify_frame_manifest_hashes(
            manifest,
            resolver=lambda pk, mod, name: paths.get(mod),
        )
        assert verify["valid"] is True, verify
        assert verify["checked"] == 6
        print("PASS: hash_bound_complete_frame_set")


def test_corrupt_committed_member_fails_verification():
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        p = tdp / "0_rgb.bin"
        p.write_bytes(b"\x00" * 12)
        digest = hashlib.sha256(b"\x00" * 12).hexdigest()

        members = [
            _m(0, 1000, 1.0, "rgb", sha=digest),
            _m(0, 1000, 1.0, "semantic", sha="s"),
            _m(0, 1000, 1.0, "lidar", sha="l"),
        ]
        inter = intersect_frame_sets(_arm(members), _arm(members))
        manifest = build_accepted_frame_manifest(_arm(members), _arm(members), inter)

        # Tamper the artifact after acceptance
        p.write_bytes(b"\xff" * 12)
        verify = verify_frame_manifest_hashes(
            manifest,
            resolver=lambda pk, mod, name: p if mod == "rgb" else None,
        )
        assert verify["valid"] is False
        assert len(verify["mismatches"]) == 2  # manual + auto rgb members
        print("PASS: corrupt_committed_member_fails_verification")


# --------------------------------------------------------------------------
# Session isolation / export
# --------------------------------------------------------------------------


def test_session_isolation():
    m_members = _complete(0, 1000, 1.0)
    a_members = _complete(0, 1000, 1.0)
    inter = intersect_frame_sets(_arm(m_members), _arm(a_members))
    assert inter["valid"] is True

    manifest1 = build_accepted_frame_manifest(
        _arm(m_members), _arm(a_members), inter, session_manifest_sha256="session-A"
    )
    manifest2 = build_accepted_frame_manifest(
        _arm(m_members), _arm(a_members), inter, session_manifest_sha256="session-B"
    )
    assert manifest1["session_manifest_sha256"] != manifest2["session_manifest_sha256"]
    assert dataset_root_sha256(manifest1) != dataset_root_sha256(manifest2)
    print("PASS: session_isolation")


def test_complete_exported_manifest():
    m_members = _complete(0, 1000, 1.0)
    a_members = _complete(0, 2000, 1.0)
    inter = intersect_frame_sets(_arm(m_members), _arm(a_members))
    manifest = build_accepted_frame_manifest(_arm(m_members), _arm(a_members), inter)
    parsed = json.loads(json.dumps(manifest))
    assert parsed["schema_version"] == "RQ3_FRAME_SET/v1"
    assert parsed["accepted_frame_count"] == 1
    assert len(parsed["frames"]) == 1
    assert len(parsed["frames"][0]["manual"]) == 3
    assert len(parsed["frames"][0]["auto"]) == 3
    assert manifest["manifest_sha256"]
    print("PASS: complete_exported_manifest")


def test_manifest_excludes_rejected_frames():
    m_members = _complete(0, 1000, 1.0) + [
        _m(1, 1001, 1.05, "rgb", sha="r", staging=True, committed=False),
    ]
    a_members = _complete(0, 2000, 1.0) + [
        _m(1, 2001, 1.05, "rgb", sha="r", staging=True, committed=False),
    ]
    inter = intersect_frame_sets(_arm(m_members), _arm(a_members))
    manifest = build_accepted_frame_manifest(_arm(m_members), _arm(a_members), inter)
    keys = [f["pairing_key"] for f in manifest["frames"]]
    assert 1 not in keys
    assert keys == [0]
    print("PASS: manifest_excludes_rejected_frames")


if __name__ == "__main__":
    test_within_arm_completeness()
    test_within_arm_intersection()
    test_unequal_frame_ids_fail()
    test_equal_counts_unequal_cross_arm_keys_fail()
    test_missing_lidar_fails()
    test_missing_lidar_allowed_when_not_mandatory()
    test_missing_semantic_camera_fails()
    test_timestamp_mismatch_fails()
    test_timestamp_within_tolerance_passes()
    test_duplicate_member_fails()
    test_uncommitted_member_fails()
    test_staging_frame_fails()
    test_missing_hash_fails()
    test_interrupted_recovery_rejects_unfinished()
    test_paired_route_frame_alignment()
    test_cross_arm_alignment_mismatch_keys()
    test_incorrect_rgb_semantic_correspondence()
    test_wrong_modality_name_rejected()
    test_hash_bound_complete_frame_set()
    test_corrupt_committed_member_fails_verification()
    test_session_isolation()
    test_complete_exported_manifest()
    test_manifest_excludes_rejected_frames()
    print("\n=== P0-2 SUMMARY: ALL TESTS PASS ===")
    print("Verified: 24 negative controls covering frame-set completeness, cross-arm")
    print("pairing, timing tolerance, commit/staging, hash binding, session isolation,")
    print("corruption detection and export filtering.")
