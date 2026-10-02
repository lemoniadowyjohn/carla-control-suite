"""
RQ5 dataset split authority tests (protocol v2, batch 12).

Every assertion here is a negative-control-shaped claim: a governed split must
be grouped (never frame-random), deterministic, complete, and provably free of
overlap between roles -- including overlap by *content* rather than by path.

All fixtures are synthetic and carry ``claim_scope = TEST_FIXTURE_ONLY``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from ultimate_pipeline.perception.dataset_split_authority import (
    ALL_ROLES,
    DEFAULT_ASSIGNMENT_SALT,
    FALLBACK_GROUP_KIND,
    GENERATED_ROLES,
    GROUP_KIND_PRECEDENCE,
    ROLE_GENERATED_TEST,
    ROLE_MANUAL_TEST,
    ROLE_TRAIN,
    ROLE_VALIDATION,
    SplitAuthorityError,
    assign_groups_to_roles,
    audit_leakage,
    build_split_authority,
    load_split_manifest,
    load_dataset_index,
    resolve_train_label_paths,
    write_leakage_audit,
    write_split_manifests,
)

CAMERA = "front_left_camera"
CLAIM_SCOPE = "TEST_FIXTURE_ONLY"


# ---------------------------------------------------------------------------
# synthetic fixtures
# ---------------------------------------------------------------------------


def _write_capture(
    root: Path,
    *,
    camera: str = CAMERA,
    capture_id: str = "cap_000",
    segment_id: int = 0,
    frames: int = 4,
    seed: int = 0,
    size: int = 16,
    route_id: str = "ingolstadt_route",
) -> list[dict]:
    """Write one synthetic capture block and return its frame metadata records."""
    rgb_dir = root / "rgb" / camera
    lab_dir = root / "semseg_raw" / camera
    rgb_dir.mkdir(parents=True, exist_ok=True)
    lab_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    records = []
    for i in range(frames):
        frame_id = int(capture_id.split("_")[-1]) * 1000 + i
        name = f"{frame_id:08d}.png"
        rgb = rng.integers(0, 255, size=(size, size, 3), dtype=np.uint8)
        Image.fromarray(rgb, mode="RGB").save(rgb_dir / name)
        lab = rng.integers(0, 10, size=(size, size), dtype=np.uint8)
        lab[rng.random((size, size)) < 0.02] = 255
        Image.fromarray(lab, mode="L").save(lab_dir / name)
        records.append(
            {
                "frame_id": frame_id,
                "filename": name,
                "route_id": route_id,
                "segment_id": segment_id,
                "capture_id": capture_id,
            }
        )
    return records


def _write_metadata(root: Path, records: list[dict], write: bool = True) -> Path:
    path = root / "frame_index.json"
    if write:
        path.write_text(json.dumps({"frames": records}), encoding="utf-8")
    return path


def _write_generated(tmp_path: Path, captures: int = 4, frames: int = 4, **kwargs) -> Path:
    root = tmp_path / "generated"
    write_metadata = bool(kwargs.pop("write_metadata", True))
    records: list[dict] = []
    for i in range(captures):
        records += _write_capture(
            root, capture_id=f"cap_{i:03d}", segment_id=i, frames=frames, seed=100 + i, **kwargs
        )
    _write_metadata(root, records, write_metadata)
    return root


def _write_manual(tmp_path: Path, captures: int = 2, frames: int = 3, **kwargs) -> Path:
    root = tmp_path / "manual"
    write_metadata = bool(kwargs.pop("write_metadata", True))
    records: list[dict] = []
    for i in range(captures):
        records += _write_capture(
            root,
            capture_id=f"mcap_{i:03d}",
            segment_id=100 + i,
            frames=frames,
            seed=900 + i,
            route_id="ingolstadt_manual",
            **kwargs,
        )
    _write_metadata(root, records, write_metadata)
    return root


def _manifest_roles(authority) -> dict[str, list[dict]]:
    return {role: list(m["entries"]) for role, m in authority.manifests.items()}


# ---------------------------------------------------------------------------
# grouping
# ---------------------------------------------------------------------------


def test_group_kind_uses_route_segment_metadata(tmp_path):
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path), camera=CAMERA
    )
    assert authority.group_kind == GROUP_KIND_PRECEDENCE[0] == "route_segment"
    assert not authority.degraded


def test_groups_never_cross_roles(tmp_path):
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path, captures=6),
        camera=CAMERA,
        manual_root=_write_manual(tmp_path),
    )
    owner: dict[str, str] = {}
    for role, entries in _manifest_roles(authority).items():
        for group_key in {e["group_key"] for e in entries}:
            assert group_key not in owner, (
                f"group {group_key} appears in both {owner.get(group_key)} and {role}"
            )
            owner[group_key] = role
    assert len(owner) == sum(
        len({e["group_key"] for e in entries}) for entries in _manifest_roles(authority).values()
    )


def test_adjacent_frames_from_one_capture_stay_in_one_role(tmp_path):
    """The core anti-leakage property: neighbouring frames are never split."""
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path, captures=6), camera=CAMERA
    )
    by_capture: dict[str, set[str]] = {}
    for role, entries in _manifest_roles(authority).items():
        for entry in entries:
            by_capture.setdefault(entry["capture_id"], set()).add(role)
    assert by_capture, "fixture must produce captures"
    for capture, roles in by_capture.items():
        assert len(roles) == 1, f"capture {capture} frames were split across roles {roles}"


def test_all_generated_roles_are_populated(tmp_path):
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path, captures=9), camera=CAMERA
    )
    for role in GENERATED_ROLES:
        assert authority.manifests[role]["frame_count"] > 0, f"{role} is empty"


def test_missing_metadata_is_refused_not_guessed(tmp_path):
    root = _write_generated(tmp_path, captures=4, write_metadata=False)
    with pytest.raises(SplitAuthorityError, match="no route_segment"):
        build_split_authority(generated_root=root, camera=CAMERA)


def test_metadata_free_dataset_is_marked_degraded_when_metadata_not_required(tmp_path):
    root = _write_generated(tmp_path, captures=4, write_metadata=False)
    authority = build_split_authority(
        generated_root=root, camera=CAMERA, require_metadata=False
    )
    assert authority.group_kind == FALLBACK_GROUP_KIND
    assert authority.degraded
    assert all(m["degraded_grouping"] for m in authority.manifests.values())


def test_explicit_missing_metadata_path_is_a_hard_failure(tmp_path):
    root = _write_generated(tmp_path, captures=2)
    with pytest.raises(SplitAuthorityError, match="explicit dataset metadata not found"):
        load_dataset_index(
            root, CAMERA, domain="generated", metadata_path=tmp_path / "nope.json"
        )


def test_camera_must_be_explicit(tmp_path):
    with pytest.raises(SplitAuthorityError, match="camera must be explicit"):
        build_split_authority(generated_root=_write_generated(tmp_path), camera="  ")


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_split_assignment_is_deterministic_across_runs(tmp_path):
    a = build_split_authority(generated_root=_write_generated(tmp_path, captures=8), camera=CAMERA)
    b = build_split_authority(generated_root=_write_generated(tmp_path, captures=8), camera=CAMERA)
    assert a.group_assignment == b.group_assignment
    assert a.manifests[ROLE_TRAIN]["group_keys"] == b.manifests[ROLE_TRAIN]["group_keys"]


def test_split_assignment_is_independent_of_mtime(tmp_path):
    """Re-touching files must not reshuffle the split."""
    root_a = _write_generated(tmp_path / "a", captures=8)
    root_b = _write_generated(tmp_path / "b", captures=8)
    for path in root_b.rglob("*.png"):
        os.utime(path, (1_000_000, 1_000_000))
    a = build_split_authority(generated_root=root_a, camera=CAMERA)
    b = build_split_authority(generated_root=root_b, camera=CAMERA)
    assert a.group_assignment == b.group_assignment


def test_assignment_salt_changes_the_split_but_stays_deterministic(tmp_path):
    root = _write_generated(tmp_path, captures=8)
    default = build_split_authority(generated_root=root, camera=CAMERA)
    salted = build_split_authority(
        generated_root=root, camera=CAMERA, salt="a-different-salt"
    )
    assert salted.group_assignment == build_split_authority(
        generated_root=root, camera=CAMERA, salt="a-different-salt"
    ).group_assignment
    # Not required to differ, but the salt must actually reach the ordering.
    assert salted.salt == "a-different-salt"
    assert default.salt == DEFAULT_ASSIGNMENT_SALT


def test_assign_groups_to_roles_places_every_group_exactly_once():
    groups = {f"g{i:02d}": [object()] * (i + 1) for i in range(10)}
    assignment = assign_groups_to_roles(groups, {"a": 0.6, "b": 0.2, "c": 0.2}, roles=("a", "b", "c"))
    flat = [g for role in sorted(assignment) for g in assignment[role]]
    assert sorted(flat) == sorted(groups)
    assert len(flat) == len(set(flat))


def test_assign_groups_to_roles_refuses_empty_group_set():
    with pytest.raises(SplitAuthorityError, match="no groups"):
        assign_groups_to_roles({}, roles=("a",))


# ---------------------------------------------------------------------------
# manifests
# ---------------------------------------------------------------------------


def test_manifest_entries_carry_full_audit_identity(tmp_path):
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path), camera=CAMERA, manual_root=_write_manual(tmp_path)
    )
    for role, manifest in authority.manifests.items():
        assert manifest["role"] == role
        assert manifest["dataset_identity_sha256"]
        for entry in manifest["entries"]:
            for key in (
                "sample_identity",
                "frame_id",
                "capture_id",
                "group_key",
                "group_kind",
                "rgb_sha256",
                "label_sha256",
                "dataset_identity_sha256",
                "role",
            ):
                assert entry[key] not in (None, ""), f"{role} entry missing {key}"


def test_split_manifests_and_leakage_audit_are_written(tmp_path):
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path), camera=CAMERA, manual_root=_write_manual(tmp_path)
    )
    out = tmp_path / "evidence"
    written = write_split_manifests(out, authority)
    assert set(written) == set(ALL_ROLES)
    for role, path in written.items():
        payload = load_split_manifest(path)
        assert payload["role"] == role
        assert payload["claim_scope"] == CLAIM_SCOPE

    audit = audit_leakage(authority.manifests)
    audit_path = write_leakage_audit(out, audit)
    assert audit_path.is_file()
    assert json.loads(audit_path.read_text(encoding="utf-8"))["leak_free"] is True


def test_train_label_paths_come_only_from_the_train_manifest(tmp_path):
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path), camera=CAMERA, manual_root=_write_manual(tmp_path)
    )
    train_paths = set(resolve_train_label_paths(authority.manifests[ROLE_TRAIN]))
    for role in (ROLE_VALIDATION, ROLE_GENERATED_TEST, ROLE_MANUAL_TEST):
        other = {e["label_path"] for e in authority.manifests[role]["entries"]}
        assert not (train_paths & other), f"{role} labels leaked into the training class-weight source"


# ---------------------------------------------------------------------------
# leakage authority / negative controls
# ---------------------------------------------------------------------------


def test_clean_split_passes_the_leakage_audit(tmp_path):
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path, captures=6),
        camera=CAMERA,
        manual_root=_write_manual(tmp_path),
    )
    audit = audit_leakage(authority.manifests)
    assert audit["leak_free"] is True
    assert audit["status"] == "PASS"
    assert audit["violations"] == []
    assert all(c["disjoint"] for c in audit["content_equality_checks"])


def test_leakage_audit_checks_all_three_axes(tmp_path):
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path, captures=6), camera=CAMERA
    )
    audit = audit_leakage(authority.manifests)
    assert audit["content_equality_checks"]
    assert audit["group_identity_checks"]
    assert audit["adjacency_window"] == 1
    assert len(audit["required_guarantees"]) == 3


def test_copied_frame_in_another_split_is_detected_despite_a_different_path(tmp_path):
    """Content equality, not path equality, decides overlap."""
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path, captures=6), camera=CAMERA
    )
    manifests = {role: json.loads(json.dumps(m)) for role, m in authority.manifests.items()}
    donor = dict(manifests[ROLE_TRAIN]["entries"][0])
    manifests[ROLE_GENERATED_TEST]["entries"].append(donor)

    audit = audit_leakage(manifests)
    assert audit["leak_free"] is False
    kinds = {v["kind"] for v in audit["violations"]}
    assert "content_equality" in kinds
    with pytest.raises(Exception):
        audit_leakage(manifests, raise_on_leak=True)


def test_manual_frame_in_train_is_detected(tmp_path):
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path, captures=6),
        camera=CAMERA,
        manual_root=_write_manual(tmp_path),
    )
    manifests = {role: json.loads(json.dumps(m)) for role, m in authority.manifests.items()}
    manual_entry = dict(manifests[ROLE_MANUAL_TEST]["entries"][0])
    manifests[ROLE_TRAIN]["entries"].append(manual_entry)

    audit = audit_leakage(manifests)
    assert audit["leak_free"] is False
    pairs = {tuple(c["pair"]) for c in audit["content_equality_checks"]}
    assert (ROLE_TRAIN, ROLE_MANUAL_TEST) in pairs
    offending = [
        c for c in audit["content_equality_checks"] if c["pair"] == [ROLE_TRAIN, ROLE_MANUAL_TEST]
    ][0]
    assert offending["shared_sample_identities"] >= 1
    assert offending["disjoint"] is False


def test_adjacent_group_leakage_is_detected(tmp_path):
    """Same capture, adjacent frame ids, different roles => temporal leakage."""
    authority = build_split_authority(
        generated_root=_write_generated(tmp_path, captures=6), camera=CAMERA
    )
    manifests = {role: json.loads(json.dumps(m)) for role, m in authority.manifests.items()}
    entry = dict(manifests[ROLE_TRAIN]["entries"][0])
    entry["role"] = ROLE_GENERATED_TEST
    manifests[ROLE_GENERATED_TEST]["entries"].append(entry)

    audit = audit_leakage(manifests)
    assert audit["leak_free"] is False
    assert any(v["kind"] == "temporal_adjacency" for v in audit["violations"])
    assert any(
        c["adjacent_role_breaches"] > 0 for c in audit["temporal_adjacency_checks"]
    )