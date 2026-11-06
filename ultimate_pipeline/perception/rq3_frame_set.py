#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/rq3_frame_set.py

Frame-set intersection and exact synchronization for the governed RQ3
paired-perception capture contract.

Design rules:
* No CARLA import at module level -> fully offline-testable.
* Completion is NEVER inferred from file counts. A frame is "accepted" only
  when every mandatory modality has a *committed* member bound to the same
  CARLA frame id and a simulation timestamp inside the frozen tolerance.
* Staging (uncommitted) frames are never accepted, and are never silently
  promoted into the accepted manifest.
* Every rejected frame carries an explicit machine-readable reason.

Vocabulary
----------
frame_index : stable ordinal within a capture arm (0..N-1).
frame_id    : CARLA simulation frame id observed at capture time.
timestamp   : simulation elapsed time (seconds) observed at capture time.
member      : one sensor observation bound to (frame_index, frame_id, timestamp).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# Frozen contract constants
# --------------------------------------------------------------------------

FRAME_SET_SCHEMA_VERSION = "RQ3_FRAME_SET/v1"

#: Frozen tolerance (seconds) for intra-arm modality timestamp agreement.
DEFAULT_TIMESTAMP_TOLERANCE_S = 1.0 / 60.0

#: Mandatory modalities for an authoritative RQ3 paired capture.
REQUIRED_MODALITIES: Tuple[str, ...] = ("rgb", "semantic", "lidar")

#: Rejection reason codes (stable, machine-readable).
REASON_MISSING_MODALITY = "missing_modality"
REASON_FRAME_ID_MISMATCH = "frame_id_mismatch"
REASON_TIMESTAMP_MISMATCH = "timestamp_mismatch"
REASON_DUPLICATE_MEMBER = "duplicate_member"
REASON_UNCOMMITTED_MEMBER = "uncommitted_member"
REASON_STAGING_FRAME = "staging_frame"
REASON_MISSING_HASH = "missing_hash"
REASON_HASH_MISMATCH = "hash_mismatch"
REASON_EMPTY_FRAME_INDEX = "empty_frame_index"
REASON_NOT_COMMITTED = "not_committed"


class FrameSetError(ValueError):
    """Raised when a frame set cannot be accepted under the frozen contract."""


# --------------------------------------------------------------------------
# Member / arm structures
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameMember:
    """One sensor observation bound to a frame ordinal.

    `sha256` binds the accepted artifact on disk. `committed` distinguishes a
    fully written, digest-verified member from a staging write.
    """

    frame_index: int
    frame_id: int
    timestamp: float
    modality: str
    sensor_name: str
    sha256: str = ""
    committed: bool = False
    staging: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_index": self.frame_index,
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "modality": self.modality,
            "sensor_name": self.sensor_name,
            "sha256": self.sha256,
            "committed": self.committed,
            "staging": self.staging,
        }


@dataclass
class ArmFrameSet:
    """All captured members for one capture arm (manual or automatic)."""

    arm_name: str
    members: List[FrameMember] = field(default_factory=list)

    def add(self, member: FrameMember) -> None:
        self.members.append(member)

    def by_frame_index(self) -> Dict[int, List[FrameMember]]:
        out: Dict[int, List[FrameMember]] = {}
        for m in self.members:
            out.setdefault(m.frame_index, []).append(m)
        return out

    def frame_indices(self) -> List[int]:
        return sorted(self.by_frame_index().keys())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arm_name": self.arm_name,
            "schema_version": FRAME_SET_SCHEMA_VERSION,
            "members": [m.to_dict() for m in self.members],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ArmFrameSet":
        arm = cls(arm_name=str(payload.get("arm_name", "")))
        for raw in payload.get("members", []) or []:
            arm.add(
                FrameMember(
                    frame_index=int(raw["frame_index"]),
                    frame_id=int(raw["frame_id"]),
                    timestamp=float(raw["timestamp"]),
                    modality=str(raw["modality"]),
                    sensor_name=str(raw.get("sensor_name", raw["modality"])),
                    sha256=str(raw.get("sha256", "")),
                    committed=bool(raw.get("committed", False)),
                    staging=bool(raw.get("staging", False)),
                )
            )
        return arm


# --------------------------------------------------------------------------
# Core validation
# --------------------------------------------------------------------------


def _reject(reasons: List[Dict[str, Any]], code: str, frame_index: Any, detail: str = "") -> None:
    reasons.append({"reason": code, "frame_index": frame_index, "detail": detail})


def validate_arm_frame_set(
    arm: ArmFrameSet,
    *,
    required_modalities: Sequence[str] = REQUIRED_MODALITIES,
    timestamp_tolerance_s: float = DEFAULT_TIMESTAMP_TOLERANCE_S,
    require_committed: bool = True,
    require_hash: bool = True,
) -> Dict[str, Any]:
    """Validate one capture arm's frame set and compute its accepted frames.

    A frame index is accepted only when:
      * every required modality contributes exactly one member,
      * all contributing members agree on the CARLA frame id,
      * all contributing member timestamps are within `timestamp_tolerance_s`
        of each other,
      * every contributing member is committed (not staging),
      * every contributing member carries a non-empty sha256 (when required).

    Returns a dict with `accepted_frame_indices`, `rejected` (per-frame
    reasons), and `valid`.
    """
    grouped = arm.by_frame_index()
    accepted: List[int] = []
    rejected: List[Dict[str, Any]] = []

    for frame_index in sorted(grouped.keys()):
        frame_reasons: List[Dict[str, Any]] = []
        members = grouped[frame_index]

        if frame_index < 0:
            _reject(frame_reasons, REASON_EMPTY_FRAME_INDEX, frame_index)

        # duplicate detection: same (modality, frame_id) twice
        seen: Dict[Tuple[str, int], int] = {}
        for m in members:
            key = (m.modality, m.frame_id)
            seen[key] = seen.get(key, 0) + 1
        for (modality, frame_id), count in seen.items():
            if count > 1:
                _reject(
                    frame_reasons,
                    REASON_DUPLICATE_MEMBER,
                    frame_index,
                    f"modality={modality} frame_id={frame_id} count={count}",
                )

        # staging members never satisfy a required modality
        if any(m.staging for m in members):
            _reject(frame_reasons, REASON_STAGING_FRAME, frame_index)

        if require_committed:
            uncommitted = [m for m in members if not m.committed]
            if uncommitted:
                _reject(
                    frame_reasons,
                    REASON_UNCOMMITTED_MEMBER,
                    frame_index,
                    ",".join(sorted({m.modality for m in uncommitted})),
                )

        # per-modality presence
        present: Dict[str, List[FrameMember]] = {}
        for m in members:
            present.setdefault(m.modality, []).append(m)

        for modality in required_modalities:
            if modality not in present:
                _reject(frame_reasons, REASON_MISSING_MODALITY, frame_index, modality)

        # frame-id agreement across the modalities that are present
        frame_ids = {m.frame_id for m in members}
        if len(frame_ids) > 1:
            _reject(
                frame_reasons,
                REASON_FRAME_ID_MISMATCH,
                frame_index,
                "ids=" + ",".join(str(i) for i in sorted(frame_ids)),
            )

        # timestamp agreement across the modalities that are present
        if len(members) > 1:
            stamps = [m.timestamp for m in members]
            spread = max(stamps) - min(stamps)
            if spread > timestamp_tolerance_s:
                _reject(
                    frame_reasons,
                    REASON_TIMESTAMP_MISMATCH,
                    frame_index,
                    f"spread={spread:.9f} tolerance={timestamp_tolerance_s:.9f}",
                )

        if require_hash:
            missing = [m for m in members if not m.sha256]
            if missing:
                _reject(
                    frame_reasons,
                    REASON_MISSING_HASH,
                    frame_index,
                    ",".join(sorted({m.modality for m in missing})),
                )

        if frame_reasons:
            rejected.append({"frame_index": frame_index, "reasons": frame_reasons})
        else:
            accepted.append(frame_index)

    return {
        "arm_name": arm.arm_name,
        "valid": not rejected,
        "accepted_frame_indices": accepted,
        "accepted_count": len(accepted),
        "rejected": rejected,
        "total_frame_indices": len(grouped),
    }


def intersect_frame_sets(
    manual: ArmFrameSet,
    auto: ArmFrameSet,
    *,
    required_modalities: Sequence[str] = REQUIRED_MODALITIES,
    timestamp_tolerance_s: float = DEFAULT_TIMESTAMP_TOLERANCE_S,
    require_committed: bool = True,
    require_hash: bool = True,
    pairing_key: str = "pair_frame_index",
) -> Dict[str, Any]:
    """Intersect two capture arms on the FROZEN pairing key.

    Independently loaded CARLA worlds do NOT share absolute frame ids, so the
    pairing key is the frozen route/temporal ordinal. The arms must produce
    the SAME set of pairing keys and the same frame count; a mismatch of
    counts with unequal key sets is an explicit failure.
    """
    manual_result = validate_arm_frame_set(
        manual,
        required_modalities=required_modalities,
        timestamp_tolerance_s=timestamp_tolerance_s,
        require_committed=require_committed,
        require_hash=require_hash,
    )
    auto_result = validate_arm_frame_set(
        auto,
        required_modalities=required_modalities,
        timestamp_tolerance_s=timestamp_tolerance_s,
        require_committed=require_committed,
        require_hash=require_hash,
    )

    manual_keys = set(manual_result["accepted_frame_indices"])
    auto_keys = set(auto_result["accepted_frame_indices"])
    common = sorted(manual_keys & auto_keys)

    errors: List[str] = []
    if manual_result["accepted_count"] != auto_result["accepted_count"]:
        errors.append(
            f"accepted_count_mismatch:manual={manual_result['accepted_count']}"
            f",auto={auto_result['accepted_count']}"
        )
    only_manual = sorted(manual_keys - auto_keys)
    only_auto = sorted(auto_keys - manual_keys)
    if only_manual:
        errors.append("pairing_keys_missing_in_auto:" + ",".join(str(k) for k in only_manual))
    if only_auto:
        errors.append("pairing_keys_missing_in_manual:" + ",".join(str(k) for k in only_auto))

    return {
        "valid": not errors and manual_result["valid"] and auto_result["valid"],
        "errors": errors,
        "pairing_key": pairing_key,
        "accepted_pairing_keys": common,
        "accepted_count": len(common),
        "manual": manual_result,
        "auto": auto_result,
    }


# --------------------------------------------------------------------------
# Manifest publication
# --------------------------------------------------------------------------


def build_accepted_frame_manifest(
    manual: ArmFrameSet,
    auto: ArmFrameSet,
    intersection: Mapping[str, Any],
    *,
    session_manifest_sha256: str = "",
    protocol_sha256: str = "",
) -> Dict[str, Any]:
    """Publish the accepted-frame manifest.

    Contains ONLY fully committed, synchronized frame sets. Staging frames and
    partially-populated frames are excluded by construction (the intersection
    only contains indices accepted by BOTH arms).
    """
    manual_groups = manual.by_frame_index()
    auto_groups = auto.by_frame_index()
    frames: List[Dict[str, Any]] = []

    for key in intersection.get("accepted_pairing_keys", []):
        manual_members = sorted(manual_groups.get(key, []), key=lambda m: (m.modality, m.sensor_name))
        auto_members = sorted(auto_groups.get(key, []), key=lambda m: (m.modality, m.sensor_name))
        frames.append(
            {
                "pairing_key": key,
                "manual": [m.to_dict() for m in manual_members],
                "auto": [m.to_dict() for m in auto_members],
                "member_sha256": [m.sha256 for m in manual_members + auto_members],
            }
        )

    manifest = {
        "schema_version": FRAME_SET_SCHEMA_VERSION,
        "session_manifest_sha256": session_manifest_sha256,
        "protocol_sha256": protocol_sha256,
        "pairing_key": intersection.get("pairing_key", "pair_frame_index"),
        "accepted_frame_count": len(frames),
        "frames": frames,
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return manifest


def dataset_root_sha256(manifest: Mapping[str, Any]) -> str:
    """Deterministic digest over the accepted-frame manifest."""
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def verify_frame_manifest_hashes(
    manifest: Mapping[str, Any],
    *,
    resolver: Optional[Any] = None,
) -> Dict[str, Any]:
    """Re-verify per-member digests of an accepted-frame manifest.

    `resolver` maps (frame_index, modality, sensor_name) -> artifact path.
    When omitted, only the presence and non-emptiness of digests is checked.
    """
    checked = 0
    mismatches: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []

    for frame in manifest.get("frames", []) or []:
        for side in ("manual", "auto"):
            for member in frame.get(side, []) or []:
                digest = member.get("sha256", "")
                if not digest:
                    missing.append({"frame_index": frame.get("pairing_key"), "member": member})
                    continue
                checked += 1
                if resolver is None:
                    continue
                path = resolver(frame.get("pairing_key"), member.get("modality"), member.get("sensor_name"))
                if path is None:
                    missing.append({"frame_index": frame.get("pairing_key"), "member": member})
                    continue
                actual = _sha256_file(path)
                if actual != digest:
                    mismatches.append(
                        {
                            "frame_index": frame.get("pairing_key"),
                            "modality": member.get("modality"),
                            "expected": digest,
                            "actual": actual,
                            "path": str(path),
                        }
                    )

    return {
        "valid": not mismatches and not missing,
        "checked": checked,
        "mismatches": mismatches,
        "missing": missing,
    }


def _sha256_file(path: Any) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    "FRAME_SET_SCHEMA_VERSION",
    "DEFAULT_TIMESTAMP_TOLERANCE_S",
    "REQUIRED_MODALITIES",
    "REASON_MISSING_MODALITY",
    "REASON_FRAME_ID_MISMATCH",
    "REASON_TIMESTAMP_MISMATCH",
    "REASON_DUPLICATE_MEMBER",
    "REASON_UNCOMMITTED_MEMBER",
    "REASON_STAGING_FRAME",
    "REASON_MISSING_HASH",
    "REASON_HASH_MISMATCH",
    "FrameSetError",
    "FrameMember",
    "ArmFrameSet",
    "validate_arm_frame_set",
    "intersect_frame_sets",
    "build_accepted_frame_manifest",
    "dataset_root_sha256",
    "verify_frame_manifest_hashes",
]
