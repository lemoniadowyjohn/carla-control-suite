# -*- coding: utf-8 -*-
"""Offline unit tests for ultimate_pipeline/perception/route_manifest.py.

Covers the RQ3 paired-capture route authority:

* same spawn index on two different maps does NOT imply the same geographic
  route ($2 defect class);
* route equality is decided by content digest (deterministic, order-safe);
* structure/digest validation is fail-closed;
* pose projection onto a duck-typed map adapter honours the driving-lane and
  distance thresholds; unrepresentable routes yield PAIR_ROUTE_INVALID.
"""
from __future__ import annotations

import pytest

from ultimate_pipeline.perception.route_manifest import (
    PAIR_ROUTE_INVALID,
    build_route_manifest,
    orientation_mismatch_deg,
    pose_distance_m,
    pose_payload,
    project_pose,
    route_digest,
    validate_paired_route,
    validate_route_manifest,
    validate_route_on_map,
)


def _pose(x, y, seq, yaw=0.0):
    return pose_payload(x=x, y=y, z=0.0, yaw=yaw, pitch=0.0, roll=0.0, sequence_index=seq)


def _manifest(poses):
    return build_route_manifest(
        route_id="route-1",
        coordinate_frame="local_carlamap",
        capture_poses=poses,
    )


class _Probe:
    """Attribute-style drivable-waypoint probe (per RouteMapAdapter contract)."""

    def __init__(self, x=0.0, y=0.0, z=0.0, yaw=0.0,
                 projection_distance_m=0.0, is_driving=True, road_id=1, lane_id=-1):
        self.x = x
        self.y = y
        self.z = z
        self.yaw = yaw
        self.projection_distance_m = projection_distance_m
        self.is_driving = is_driving
        self.road_id = road_id
        self.lane_id = lane_id


class _MapAdapter:
    """Adapter that projects every pose onto a fixed probe (or per-pose list)."""

    def __init__(self, probe=None, alt_poses=()):
        self._probe = probe or _Probe()
        self._alt = dict(alt_poses)

    def resolve_drivable_waypoint(self, pose):
        alt = self._alt.get(int(pose["sequence_index"]))
        return alt or self._probe


def _alt_probe(x, y):
    return _Probe(x=x, y=y, projection_distance_m=0.1, is_driving=True)


def test_same_spawn_index_does_not_imply_same_route_digests_differ():
    """$2 defect: identical spawn index on different maps is NOT the same route.

    Two maps with the same spawn index but different coordinates must build
    different route digests, so a paired claim on "spawn 0 both sides" is
    rejected by the digest equality before any capture happens.
    """
    map_a_spawn0 = _pose(10.0, 20.0, 0)
    map_b_spawn0 = _pose(10.0, 20.0, 0)
    assert route_digest(_manifest([map_a_spawn0])) == route_digest(_manifest([map_b_spawn0]))

    map_b_spawn0_shifted = _pose(500.0, 20.0, 0)
    assert route_digest(_manifest([map_a_spawn0])) != route_digest(_manifest([map_b_spawn0_shifted]))

    validation = validate_paired_route(
        route_digest(_manifest([map_a_spawn0])),
        {"valid": True, "manifest_sha256": route_digest(_manifest([map_a_spawn0]))},
        {"valid": True, "manifest_sha256": route_digest(_manifest([map_b_spawn0_shifted]))},
    )
    assert not validation["valid"]
    assert any("route_sha_mismatch" in e or "route_sha" in e for e in validation["errors"])


def test_route_digest_is_deterministic_and_order_safe():
    poses = [_pose(0.0, 0.0, 0), _pose(5.0, 0.0, 1), _pose(10.0, 2.0, 2)]
    m1 = _manifest(poses)
    m2 = _manifest(list(reversed(poses)))
    assert route_digest(m1) == route_digest(m2)
    assert m1["sha256"] == route_digest(m1)


def test_validate_route_manifest_detects_missing_pose_field():
    m = _manifest([_pose(0.0, 0.0, 0)])
    bad = {k: v for k, v in m.items()}
    del bad["capture_poses"][0]["x"]
    reasons = validate_route_manifest(bad)
    assert any("missing_x" in r for r in reasons)


def test_validate_route_manifest_detects_digest_tamper():
    m = _manifest([_pose(0.0, 0.0, 0)])
    m["capture_poses"][0]["x"] = 999.0
    reasons = validate_route_manifest(m)
    assert "route_manifest_digest_mismatch" in reasons


def test_validate_route_manifest_accepts_canonical_route():
    m = _manifest([_pose(0.0, 0.0, 0)])
    assert validate_route_manifest(m) == []


def test_project_pose_accepts_attribute_style_probe():
    pose = _pose(0.0, 0.0, 0, yaw=5.0)
    entry = project_pose(pose, _Probe(yaw=5.0, projection_distance_m=0.3))
    assert entry["usable"] is True
    assert entry["adjusted"] is False
    assert entry["reasons"] == []


def test_project_pose_rejects_far_projection_and_offroad():
    pose = _pose(0.0, 0.0, 0)
    far = project_pose(pose, _Probe(projection_distance_m=25.0))
    assert far["usable"] is False
    assert any("projection_distance_" in r for r in far["reasons"])

    offroad = project_pose(pose, _Probe(is_driving=False))
    assert offroad["usable"] is False
    assert "not_driving_lane" in offroad["reasons"]


def test_validate_route_on_map_marks_unrepresentable_route_invalid():
    manifest = _manifest([_pose(0.0, 0.0, 0), _pose(5.0, 0.0, 1)])
    adapter = _MapAdapter(_Probe(projection_distance_m=0.2))
    result = validate_route_on_map(manifest, adapter, map_name="auto")
    assert result["valid"] is True
    assert result["closure"] == "ROUTE_REPRESENTABLE"

    bad_adapter = _MapAdapter(_Probe(projection_distance_m=999.0))
    bad = validate_route_on_map(manifest, bad_adapter, map_name="auto")
    assert bad["valid"] is False
    assert bad["closure"] == PAIR_ROUTE_INVALID
    assert bad["invalid_poses"] == [0, 1]


def test_validate_paired_route_requires_both_arms_usable():
    manifest = _manifest([_pose(0.0, 0.0, 0)])
    sha = route_digest(manifest)
    ok = validate_route_on_map(manifest, _MapAdapter(_Probe()))
    ok["manifest_sha256"] = sha
    broken = {"valid": False, "closure": PAIR_ROUTE_INVALID, "manifest_sha256": sha}
    result = validate_paired_route(sha, ok, broken)
    assert not result["valid"]
    assert result["closure"] == PAIR_ROUTE_INVALID


def test_orientation_and_distance_helpers():
    a = _pose(0.0, 0.0, 0, yaw=0.0)
    b = _pose(0.0, 0.0, 0, yaw=359.0)
    assert orientation_mismatch_deg(a, b) == pytest.approx(1.0)
    assert pose_distance_m(a, _pose(3.0, 4.0, 0)) == pytest.approx(5.0)