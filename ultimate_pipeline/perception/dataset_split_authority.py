#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/dataset_split_authority.py

Single authority for RQ5 dataset splitting and split-leakage proof.

Why this module exists
----------------------
Consecutive frames from one CARLA capture are near-duplicates: the vehicle
moves a few centimetres between them and the semantic layout barely changes. A
per-frame random split therefore places frame N in train and frame N+1 in the
test set, the model memorises the scene, and the reported generalization number
measures nothing but leakage. This module makes the split unit a *group*, never
an individual frame.

Design rules
------------
* **No CARLA import.** Fully offline.
* **No randomness.** Group-to-role assignment is a pure function of
  ``(group_key, salt)`` via SHA-256 ordering, so a re-run reproduces the same
  split on any machine, in any order of filesystem traversal, and without
  depending on mtimes or glob ordering luck.
* **No guessing when metadata exists.** Group identity is read from available
  dataset metadata with a fixed precedence chain
  (``route_segment > capture_block > scenario_seed_block > spatial_region``).
  Only when *no* metadata is available at all does the module fall back to
  filename-stem blocks, and it then records the split as ``DEGRADED`` so a
  reader knows the grouping was inferred rather than governed.
* **Leakage is decided by content, not by path.** A copied frame under a
  different filename or a different directory still overlaps, because overlap
  is computed from per-frame content digests.

Governed roles
--------------
``generated_train``, ``generated_validation`` and ``generated_test`` are carved
out of the *generated* (simulator) pool as whole groups. ``manual_test`` is
carved out of the *manual* (target-world) pool and is never mixed with the
generated pool. Manual frames can never reach train, validation, generated-test
or class weighting.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ultimate_pipeline.perception.rq5_provenance import (
    canonical_dumps,
    dataset_content_identity,
    sha256_text,
)

__all__ = [
    "SPLIT_MANIFEST_SCHEMA",
    "LEAKAGE_AUDIT_SCHEMA",
    "SPLIT_FILENAMES",
    "LEAKAGE_AUDIT_FILENAME",
    "GENERATED_ROLES",
    "ROLE_MANUAL_TEST",
    "ROLE_TRAIN",
    "ROLE_VALIDATION",
    "ROLE_GENERATED_TEST",
    "GROUP_KIND_PRECEDENCE",
    "FALLBACK_GROUP_KIND",
    "DEFAULT_GROUPED_RATIOS",
    "DEFAULT_ASSIGNMENT_SALT",
    "DEFAULT_ADJACENCY_WINDOW",
    "SplitAuthorityError",
    "LeakageDetected",
    "FrameRecord",
    "DatasetIndex",
    "SplitAuthority",
    "load_dataset_index",
    "assign_groups_to_roles",
    "build_split_authority",
    "audit_leakage",
    "write_split_manifests",
    "write_leakage_audit",
    "load_split_manifest",
    "resolve_train_label_paths",
]

SPLIT_MANIFEST_SCHEMA = "rq5_split_manifest_v1"
LEAKAGE_AUDIT_SCHEMA = "rq5_split_leakage_audit_v1"

ROLE_TRAIN = "generated_train"
ROLE_VALIDATION = "generated_validation"
ROLE_GENERATED_TEST = "generated_test"
ROLE_MANUAL_TEST = "manual_test"

#: Roles carved out of the generated pool by :func:`build_split_authority`.
GENERATED_ROLES: Tuple[str, str, str] = (ROLE_TRAIN, ROLE_VALIDATION, ROLE_GENERATED_TEST)

#: All governed roles, in report order.
ALL_ROLES: Tuple[str, str, str, str] = (
    ROLE_TRAIN,
    ROLE_VALIDATION,
    ROLE_GENERATED_TEST,
    ROLE_MANUAL_TEST,
)

#: Roles with a manifest file on disk.
SPLIT_FILENAMES: Dict[str, str] = {
    ROLE_TRAIN: "train_manifest.json",
    ROLE_VALIDATION: "validation_manifest.json",
    ROLE_GENERATED_TEST: "generated_test_manifest.json",
    ROLE_MANUAL_TEST: "manual_test_manifest.json",
}

LEAKAGE_AUDIT_FILENAME = "RQ5_SPLIT_LEAKAGE_AUDIT.json"

#: Strict precedence for deriving a group identity from dataset metadata.
#: The first kind available for *every* frame wins; it is never mixed per frame.
GROUP_KIND_PRECEDENCE: Tuple[str, ...] = (
    "route_segment",
    "capture_block",
    "scenario_seed_block",
    "spatial_region",
)

#: Last-resort grouping when the dataset carries no usable metadata at all.
FALLBACK_GROUP_KIND = "filename_stem_block"

#: Frames per inferred filename-stem block when metadata is absent.
FALLBACK_BLOCK_FRAMES = 50

DEFAULT_GROUPED_RATIOS: Dict[str, float] = {
    ROLE_TRAIN: 0.70,
    ROLE_VALIDATION: 0.15,
    ROLE_GENERATED_TEST: 0.15,
}

DEFAULT_ASSIGNMENT_SALT = "rq5_split_authority/v2"

#: Two frames of the same capture whose numeric frame ids differ by at most
#: this many are treated as temporally adjacent.
DEFAULT_ADJACENCY_WINDOW = 1

#: Metadata files searched, in order, when no explicit path is supplied.
_METADATA_CANDIDATES = (
    "frame_index.json",
    "capture_manifest.json",
    "frames_manifest.json",
    "metadata.json",
)

#: Alias sets per group kind. The first alias whose value is present and
#: non-empty wins; multi-part kinds are joined in a fixed order so the key is
#: stable.
_GROUP_ALIASES: Dict[str, Tuple[Tuple[str, ...], ...]] = {
    "route_segment": (
        ("route_id", "route", "route_name"),
        ("segment_id", "segment", "segment_index", "segment_idx"),
    ),
    "capture_block": (
        ("capture_id", "capture", "block_id", "block", "session_id", "record_id"),
    ),
    "scenario_seed_block": (
        ("scenario_id", "scenario", "scenario_name"),
        ("scenario_seed", "seed", "traffic_seed", "tm_seed"),
    ),
    "spatial_region": (
        ("spatial_region", "region", "region_id", "tile", "tile_id", "spatial_cell"),
    ),
}

_FRAME_ID_KEYS = (
    "frame_id",
    "frame",
    "frame_index",
    "frame_idx",
    "index",
    "id",
)


class SplitAuthorityError(RuntimeError):
    """Raised when a governed split cannot be produced as requested."""


class LeakageDetected(SplitAuthorityError):
    """Raised when :func:`audit_leakage` proves an overlap between roles."""


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameRecord:
    """One paired (RGB, semantic-label) frame with its full audit identity."""

    frame_id: str
    filename: str
    rgb_path: str
    label_path: str
    capture_id: Optional[str]
    group_kind: str
    group_key: str
    rgb_sha256: str
    label_sha256: str
    content_sha256: str
    frame_index: Optional[int]
    degraded_grouping: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def sample_identity(self) -> str:
        return self.content_sha256

    def to_entry(self, role: str, dataset_identity_sha256: Optional[str]) -> Dict[str, Any]:
        return {
            "role": role,
            "sample_identity": self.content_sha256,
            "frame_id": self.frame_id,
            "frame_index": self.frame_index,
            "filename": self.filename,
            "rgb_path": self.rgb_path,
            "label_path": self.label_path,
            "capture_id": self.capture_id,
            "group_kind": self.group_kind,
            "group_key": self.group_key,
            "rgb_sha256": self.rgb_sha256,
            "label_sha256": self.label_sha256,
            "dataset_identity_sha256": dataset_identity_sha256,
            "degraded_grouping": bool(self.degraded_grouping),
        }


@dataclass
class DatasetIndex:
    """A dataset root indexed into frame records plus its identity."""

    root: str
    camera: str
    domain: str
    frames: List[FrameRecord]
    group_kind: str
    metadata_source: Optional[str]
    identity: Dict[str, Any]
    unpaired_rgb: List[str] = field(default_factory=list)
    unpaired_labels: List[str] = field(default_factory=list)

    @property
    def groups(self) -> Dict[str, List[FrameRecord]]:
        buckets: Dict[str, List[FrameRecord]] = {}
        for frame in self.frames:
            buckets.setdefault(frame.group_key, []).append(frame)
        for members in buckets.values():
            members.sort(key=lambda f: (_frame_sort_key(f), f.filename))
        return dict(sorted(buckets.items()))


def _frame_sort_key(frame: FrameRecord) -> Tuple[int, int, str]:
    if frame.frame_index is not None:
        return (0, int(frame.frame_index), frame.filename)
    return (1, 0, frame.filename)


# ---------------------------------------------------------------------------
# hashing helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _frame_content_sha256(rgb_sha: str, label_sha: str) -> str:
    """Content identity of a *paired* frame: both members must match."""
    return sha256_text(canonical_dumps(["rq5_frame_pair/v1", rgb_sha, label_sha]))


# ---------------------------------------------------------------------------
# metadata discovery
# ---------------------------------------------------------------------------


def _coerce_str(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        return repr(value)
    text = str(value).strip()
    return text or None


def _lookup(record: Mapping[str, Any], keys: Sequence[str]) -> Optional[str]:
    for key in keys:
        if key in record:
            value = _coerce_str(record.get(key))
            if value is not None:
                return value
    return None


def _lookup_frame_index(record: Mapping[str, Any]) -> Optional[str]:
    for key in _FRAME_ID_KEYS:
        if key in record:
            value = _coerce_str(record.get(key))
            if value is not None:
                return value
    return None


def _load_metadata(path: Path) -> Dict[str, Mapping[str, Any]]:
    """Return ``{frame_filename_or_id: metadata_record}`` from a metadata file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - unreadable metadata is a failure
        raise SplitAuthorityError(f"dataset metadata is unreadable: {path}: {exc}") from exc

    raw: Any = None
    if isinstance(payload, Mapping):
        for key in ("frames", "frame_records", "records", "entries", "samples"):
            if isinstance(payload.get(key), list):
                raw = payload[key]
                break
    elif isinstance(payload, list):
        raw = payload
    if raw is None:
        raise SplitAuthorityError(
            f"dataset metadata {path} contains no frame record list "
            "(expected a 'frames' array or a top-level array)"
        )

    table: Dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        keys = [v for v in (_lookup_frame_index(item), _coerce_str(item.get("filename"))) if v]
        for key in keys:
            table[key] = item
            # Also index the bare stem so "00000042" and "00000042.png" both resolve.
            table.setdefault(key[:-4] if key.endswith(".png") else key, item)
    if not table:
        raise SplitAuthorityError(f"dataset metadata {path} yielded no usable frame records")
    return table


def _resolve_group_kind(
    table: Mapping[str, Mapping[str, Any]],
    frame_keys: Sequence[Tuple[str, str]],
) -> Tuple[str, bool]:
    """
    Choose one group kind for the whole dataset.

    A kind qualifies only when it resolves for *every* frame; mixing kinds
    across frames would make two groups incomparable and the split meaningless.
    """
    for kind in GROUP_KIND_PRECEDENCE:
        parts = _GROUP_ALIASES[kind]
        ok = True
        for keys in frame_keys:
            record = None
            for key in keys:
                record = table.get(key)
                if record is not None:
                    break
            if record is None:
                ok = False
                break
            if any(_lookup(record, alias) is None for alias in parts):
                ok = False
                break
        if ok:
            return kind, False
    return FALLBACK_GROUP_KIND, True


def _group_key_for(
    kind: str,
    record: Optional[Mapping[str, Any]],
    ordinal: int,
    filename: str,
) -> str:
    if record is not None and kind in _GROUP_ALIASES:
        parts = [_lookup(record, alias) for alias in _GROUP_ALIASES[kind]]
        if all(p is not None for p in parts):
            return "|".join(str(p) for p in parts)
    stem = filename[:-4] if filename.endswith(".png") else filename
    digits = re.findall(r"\d+", stem)
    if digits:
        ordinal_value = int(digits[-1])
        prefix = re.sub(r"\d+$", "", stem) or stem
        return f"{prefix}#{ordinal_value // FALLBACK_BLOCK_FRAMES:04d}"
    return f"{stem}#{ordinal // FALLBACK_BLOCK_FRAMES:04d}"


# ---------------------------------------------------------------------------
# dataset indexing
# ---------------------------------------------------------------------------


def load_dataset_index(
    dataset_root: Any,
    camera: str,
    *,
    domain: str,
    metadata_path: Optional[Any] = None,
    compute_identity: bool = True,
    max_files: Optional[int] = None,
) -> DatasetIndex:
    """
    Index one dataset root into auditable frame records.

    Args:
        dataset_root: Root containing ``rgb/<camera>`` and ``semseg_raw/<camera>``.
        camera: Camera subdirectory name. Never inferred in research-strict use.
        domain: ``"generated"`` or ``"manual"``. Recorded in every manifest.
        metadata_path: Explicit frame metadata JSON. When omitted the module
            searches the standard candidate names inside ``dataset_root``.
        compute_identity: Compute the dataset content identity (SHA-256).
        max_files: Diagnostic-only digest cap. A capped identity is marked
            ``complete=False`` and must be rejected for authoritative use.

    Raises:
        SplitAuthorityError: If the root, camera or paired frames are missing, or
            an explicit metadata path was given but cannot be used.
    """
    root = Path(dataset_root)
    if not root.is_dir():
        raise SplitAuthorityError(f"dataset root does not exist: {root}")
    camera = str(camera)
    rgb_dir = root / "rgb" / camera
    label_dir = root / "semseg_raw" / camera
    if not rgb_dir.is_dir():
        raise SplitAuthorityError(f"dataset root {root} has no rgb/{camera}")
    if not label_dir.is_dir():
        raise SplitAuthorityError(f"dataset root {root} has no semseg_raw/{camera}")

    rgb_names = {p.name: p for p in rgb_dir.glob("*.png")}
    label_names = {p.name: p for p in label_dir.glob("*.png")}
    paired = sorted(set(rgb_names) & set(label_names))
    if not paired:
        raise SplitAuthorityError(
            f"dataset root {root} has no paired rgb/semseg_raw/{camera} frames "
            f"(rgb={len(rgb_names)} labels={len(label_names)})"
        )

    table: Dict[str, Mapping[str, Any]] = {}
    metadata_source: Optional[str] = None
    candidates: List[Path] = (
        [Path(metadata_path)]
        if metadata_path is not None
        else [root / name for name in _METADATA_CANDIDATES]
    )
    for candidate in candidates:
        if candidate.is_file():
            table = _load_metadata(candidate)
            metadata_source = str(candidate)
            break
        if metadata_path is not None:
            raise SplitAuthorityError(
                f"explicit dataset metadata not found: {candidate}; research-strict mode "
                "never falls back to inferred frame identity"
            )

    group_kind, degraded = _resolve_group_kind(table, [(n, n[:-4]) for n in paired])

    frames: List[FrameRecord] = []
    for ordinal, name in enumerate(paired):
        stem = name[:-4]
        record = table.get(name) or table.get(stem)
        rgb_path = rgb_names[name]
        label_path = label_names[name]
        rgb_sha = _sha256_file(rgb_path)
        label_sha = _sha256_file(label_path)
        frame_index = _lookup_frame_index(record) if record is not None else None
        capture_id = _lookup(record, _GROUP_ALIASES["capture_block"][0]) if record else None
        numeric_index: Optional[int] = None
        if frame_index is not None and re.fullmatch(r"-?\d+", str(frame_index)):
            numeric_index = int(frame_index)
        frames.append(
            FrameRecord(
                frame_id=str(frame_index) if frame_index is not None else stem,
                filename=name,
                rgb_path=rgb_path.as_posix(),
                label_path=label_path.as_posix(),
                capture_id=capture_id,
                group_kind=group_kind,
                group_key=_group_key_for(group_kind, record, ordinal, name),
                rgb_sha256=rgb_sha,
                label_sha256=label_sha,
                content_sha256=_frame_content_sha256(rgb_sha, label_sha),
                frame_index=numeric_index,
                degraded_grouping=degraded,
                extra={"metadata_present": bool(record is not None)},
            )
        )

    frames.sort(key=lambda f: (_frame_sort_key(f), f.filename))

    identity: Dict[str, Any] = {}
    if compute_identity:
        identity = dataset_content_identity(root, camera, max_files=max_files)

    return DatasetIndex(
        root=str(root.resolve()),
        camera=camera,
        domain=str(domain),
        frames=frames,
        group_kind=group_kind,
        metadata_source=metadata_source,
        identity=identity,
        unpaired_rgb=sorted(
            (root / "rgb" / camera / n).as_posix() for n in set(rgb_names) - set(label_names)
        ),
        unpaired_labels=sorted(
            (root / "semseg_raw" / camera / n).as_posix() for n in set(label_names) - set(rgb_names)
        ),
    )


# ---------------------------------------------------------------------------
# deterministic grouped assignment
# ---------------------------------------------------------------------------


def _group_order_key(group_key: str, salt: str) -> str:
    return sha256_text(f"{salt}|{group_key}")


def _group_size(members: Sequence[Any]) -> int:
    return len(members)


def _duplicate_content_count(index: Optional["DatasetIndex"]) -> Optional[int]:
    """Number of frames in ``index`` whose paired content repeats (surplus)."""
    if index is None:
        return None
    seen: set = set()
    duplicates = 0
    for frame in index.frames:
        if frame.content_sha256 in seen:
            duplicates += 1
        else:
            seen.add(frame.content_sha256)
    return duplicates


def assign_groups_to_roles(
    groups: Mapping[str, Sequence[Any]],
    ratios: Optional[Mapping[str, float]] = None,
    *,
    salt: str = DEFAULT_ASSIGNMENT_SALT,
    roles: Sequence[str] = GENERATED_ROLES,
    min_groups_per_role: int = 1,
) -> Dict[str, List[str]]:
    """
    Assign whole groups to roles deterministically.

    Groups are ordered by ``sha256("<salt>|<group_key>")``. That ordering is a
    pure function of the group key, so it is stable across machines, Python
    versions and filesystem traversal orders, and it is independent of mtime --
    re-capturing a dataset cannot silently reshuffle the split.

    Returns:
        ``{role: [group_key, ...]}``. Every group appears in exactly one role.
    """
    keys = sorted(groups)
    role_list = [str(r) for r in roles]
    if not role_list:
        raise SplitAuthorityError("no split roles requested")
    if not keys:
        raise SplitAuthorityError("no groups available to assign")

    weights = dict(ratios or DEFAULT_GROUPED_RATIOS)
    for role in role_list:
        weights.setdefault(role, 0.0)
    total_weight = sum(float(weights[r]) for r in role_list)
    if total_weight <= 0:
        raise SplitAuthorityError(f"split ratios must sum to a positive value, got {total_weight}")

    ordered = sorted(keys, key=lambda k: (_group_order_key(k, salt), k))

    # Reserve one group per role first (when the dataset is large enough), so a
    # skewed dataset can never silently produce an empty validation or test set.
    assignment: Dict[str, List[str]] = {role: [] for role in role_list}
    remaining = list(ordered)
    if len(remaining) >= len(role_list) * max(1, int(min_groups_per_role)):
        for role in role_list:
            assignment[role].append(remaining.pop(0))

    counts = {role: sum(_group_size(groups[g]) for g in assignment[role]) for role in role_list}
    total_frames = sum(_group_size(groups[g]) for g in remaining) + sum(counts.values())
    targets = {
        role: (float(weights[role]) / total_weight) * float(total_frames) for role in role_list
    }

    for group_key in remaining:
        size = _group_size(groups[group_key])
        deficits = {role: max(0.0, targets[role] - counts[role]) for role in role_list}
        if sum(deficits.values()) <= 0:
            # Every role already met its target: give the remainder to the role
            # that is furthest below its relative fill.
            role = min(
                role_list,
                key=lambda r: (counts[r] / max(1e-9, targets[r]), role_list.index(r)),
            )
        else:
            role = max(role_list, key=lambda r: (deficits[r], -role_list.index(r)))
        assignment[role].append(group_key)
        counts[role] += size

    return {role: sorted(assignment[role]) for role in role_list}


# ---------------------------------------------------------------------------
# split construction
# ---------------------------------------------------------------------------


@dataclass
class SplitAuthority:
    """The governed result of one split-authority run."""

    roles: Dict[str, List[FrameRecord]]
    group_kind: str
    group_assignment: Dict[str, List[str]]
    generated_index: DatasetIndex
    manual_index: Optional[DatasetIndex]
    ratios: Dict[str, float]
    salt: str
    degraded: bool
    manifests: Dict[str, Dict[str, Any]]

    def label_paths(self, role: str) -> List[str]:
        return [f.label_path for f in self.roles.get(role, [])]

    def summary(self) -> Dict[str, Any]:
        return {
            "schema": "rq5_split_authority_summary/v1",
            "claim_scope": "TEST_FIXTURE_ONLY",
            "generated": {
                "root": self.generated_index.root,
                "camera": self.generated_index.camera,
                "group_kind": self.group_kind,
                "group_count": sum(
                    len(self.group_assignment.get(r, [])) for r in GENERATED_ROLES
                ),
                "frame_count": len(self.generated_index.frames),
                "identity_sha256": self.generated_index.identity.get("identity_sha256"),
                "identity_complete": bool(self.generated_index.identity.get("complete", False)),
                "metadata_source": self.generated_index.metadata_source,
            },
            "manual": (
                {
                    "root": self.manual_index.root,
                    "camera": self.manual_index.camera,
                    "group_kind": self.manual_index.group_kind,
                    "frame_count": len(self.manual_index.frames),
                    "identity_sha256": self.manual_index.identity.get("identity_sha256"),
                    "identity_complete": bool(self.manual_index.identity.get("complete", False)),
                    "metadata_source": self.manual_index.metadata_source,
                }
                if self.manual_index is not None
                else None
            ),
            "ratios": dict(self.ratios),
            "assignment_salt": self.salt,
            "degraded_grouping": bool(self.degraded),
            "generated_duplicate_content_frames": _duplicate_content_count(self.generated_index),
            "manual_duplicate_content_frames": _duplicate_content_count(self.manual_index),
            "role_frame_counts": {role: len(frames) for role, frames in sorted(self.roles.items())},
            "role_group_counts": {role: len(v) for role, v in sorted(self.group_assignment.items())},
        }


def build_split_authority(
    *,
    generated_root: Any,
    camera: str,
    manual_root: Optional[Any] = None,
    ratios: Optional[Mapping[str, float]] = None,
    salt: str = DEFAULT_ASSIGNMENT_SALT,
    generated_metadata_path: Optional[Any] = None,
    manual_metadata_path: Optional[Any] = None,
    require_metadata: bool = True,
    compute_identity: bool = True,
    generated_max_files: Optional[int] = None,
    manual_max_files: Optional[int] = None,
) -> SplitAuthority:
    """
    Build the four governed RQ5 split manifests from grouped dataset content.

    Args:
        generated_root: Simulator capture root (``rgb/<cam>`` + ``semseg_raw/<cam>``).
        camera: Camera name. Explicit; never inferred.
        manual_root: Optional target-world capture root. Every one of its frames
            becomes ``manual_test`` and nothing else.
        ratios: Group-level target ratios for the three generated roles.
        salt: Deterministic assignment salt.
        require_metadata: When True, a dataset with no usable frame metadata is a
            hard failure rather than a degraded filename grouping.
        generated_max_files / manual_max_files: Diagnostic digest caps. Capped
            identities are ``complete=False`` and are rejected by the research
            strict gates, so they may only be used for diagnostics.

    Raises:
        SplitAuthorityError: On a missing root, missing metadata under
            ``require_metadata``, a degraded grouping under
            ``require_metadata``, or an empty resulting role.
    """
    if not str(camera or "").strip():
        raise SplitAuthorityError("camera must be explicit; research-strict mode forbids inference")

    index = load_dataset_index(
        generated_root,
        camera,
        domain="generated",
        metadata_path=generated_metadata_path,
        compute_identity=compute_identity,
        max_files=generated_max_files,
    )
    if require_metadata and index.group_kind == FALLBACK_GROUP_KIND:
        raise SplitAuthorityError(
            f"generated dataset {index.root} carries no route_segment / capture_block / "
            f"scenario_seed_block / spatial_region metadata; splitting {len(index.frames)} "
            "frames on inferred filename blocks would silently create an ungoverned split"
        )

    manual_index: Optional[DatasetIndex] = None
    if manual_root is not None:
        manual_index = load_dataset_index(
            manual_root,
            camera,
            domain="manual",
            metadata_path=manual_metadata_path,
            compute_identity=compute_identity,
            max_files=manual_max_files,
        )
        if require_metadata and manual_index.group_kind == FALLBACK_GROUP_KIND:
            raise SplitAuthorityError(
                f"manual dataset {manual_index.root} carries no group metadata; manual frames "
                "cannot be attributed to a capture group and therefore cannot be audited for leakage"
            )

    used_ratios = {r: float((ratios or DEFAULT_GROUPED_RATIOS).get(r, 0.0)) for r in GENERATED_ROLES}
    groups = index.groups
    assignment = assign_groups_to_roles(groups, used_ratios, salt=salt, roles=GENERATED_ROLES)

    roles: Dict[str, List[FrameRecord]] = {}
    for role, group_keys in assignment.items():
        members: List[FrameRecord] = []
        for key in group_keys:
            members.extend(groups[key])
        if not members:
            raise SplitAuthorityError(
                f"role {role} is empty after grouped assignment; refusing to emit an empty "
                "governed split (supply more capture groups or adjust the ratios)"
            )
        roles[role] = members

    group_assignment: Dict[str, List[str]] = {r: list(assignment[r]) for r in GENERATED_ROLES}

    if manual_index is not None:
        manual_groups = manual_index.groups
        roles[ROLE_MANUAL_TEST] = [
            frame for key in sorted(manual_groups) for frame in manual_groups[key]
        ]
        group_assignment[ROLE_MANUAL_TEST] = sorted(manual_groups)

    identity_sha = index.identity.get("identity_sha256")
    manual_identity_sha = manual_index.identity.get("identity_sha256") if manual_index else None
    manifests: Dict[str, Dict[str, Any]] = {}
    for role, frames in roles.items():
        is_manual = role == ROLE_MANUAL_TEST and manual_index is not None
        source = manual_index if is_manual else index
        linked = manual_identity_sha if is_manual else identity_sha
        manifests[role] = {
            "schema": "rq5_split_entry/v1",
            "role": role,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "claim_scope": "TEST_FIXTURE_ONLY",
            "dataset_root": source.root,
            "camera": camera,
            "domain": source.domain,
            "group_kind": source.group_kind,
            "degraded_grouping": bool(source.group_kind == FALLBACK_GROUP_KIND),
            "dataset_identity_sha256": linked,
            "dataset_identity_complete": bool(source.identity.get("complete", False)),
            "assignment_salt": salt,
            "group_keys": list(group_assignment.get(role, [])),
            "frame_count": len(frames),
            "entries": [f.to_entry(role, linked) for f in frames],
        }

    return SplitAuthority(
        roles=roles,
        group_kind=index.group_kind,
        group_assignment=group_assignment,
        generated_index=index,
        manual_index=manual_index,
        ratios=used_ratios,
        salt=salt,
        degraded=index.group_kind == FALLBACK_GROUP_KIND,
        manifests=manifests,
    )


# ---------------------------------------------------------------------------
# leakage audit
# ---------------------------------------------------------------------------


def _role_frame_maps(
    manifests: Mapping[str, Mapping[str, Any]]
) -> Dict[str, Dict[str, Mapping[str, Any]]]:
    out: Dict[str, Dict[str, Mapping[str, Any]]] = {}
    for role, manifest in manifests.items():
        out[role] = {str(e["sample_identity"]): e for e in manifest.get("entries", [])}
    return out


def audit_leakage(
    manifests: Mapping[str, Mapping[str, Any]],
    *,
    adjacency_window: int = DEFAULT_ADJACENCY_WINDOW,
    raise_on_leak: bool = False,
    claim_scope: str = "TEST_FIXTURE_ONLY",
) -> Dict[str, Any]:
    """
    Prove the governed RQ5 splits do not overlap.

    Three independent axes are checked, because any one of them alone is
    insufficient:

    1. **Content equality.** Per-frame paired-content digests. A file copied to
       a different directory or renamed keeps its digest, so a copy still
       counts as overlap.
    2. **Group identity.** A group key may appear in exactly one role. Two
       frames from the same capture block in different roles is leakage even if
       their pixels differ.
    3. **Temporal adjacency.** Within a shared capture identity, two frames
       whose numeric frame ids differ by at most ``adjacency_window`` must not
       land in different roles.

    Returns a payload with ``leak_free`` and an explicit ``violations`` list.
    """
    frame_maps = _role_frame_maps(manifests)
    present_roles = [r for r in ALL_ROLES if r in frame_maps]

    violations: List[Dict[str, Any]] = []

    pairs = [
        (ROLE_TRAIN, ROLE_VALIDATION),
        (ROLE_TRAIN, ROLE_GENERATED_TEST),
        (ROLE_VALIDATION, ROLE_GENERATED_TEST),
        (ROLE_TRAIN, ROLE_MANUAL_TEST),
        (ROLE_VALIDATION, ROLE_MANUAL_TEST),
        (ROLE_GENERATED_TEST, ROLE_MANUAL_TEST),
    ]
    content_checks: List[Dict[str, Any]] = []
    for left, right in pairs:
        if left not in frame_maps or right not in frame_maps:
            continue
        shared = sorted(set(frame_maps[left]) & set(frame_maps[right]))
        content_checks.append(
            {
                "pair": [left, right],
                "shared_sample_identities": len(shared),
                "examples": shared[:5],
                "disjoint": not shared,
            }
        )
        for identity in shared[:50]:
            violations.append(
                {
                    "kind": "content_equality",
                    "roles": [left, right],
                    "sample_identity": identity,
                    "left_entry": dict(frame_maps[left][identity]),
                    "right_entry": dict(frame_maps[right][identity]),
                }
            )

    group_checks: List[Dict[str, Any]] = []
    group_to_roles: Dict[str, set] = {}
    for role in present_roles:
        for entry in manifests[role].get("entries", []):
            group_to_roles.setdefault(str(entry.get("group_key")), set()).add(role)
    for key, roles in sorted(group_to_roles.items()):
        shared_roles = sorted(roles)
        group_checks.append(
            {"group_key": key, "roles": shared_roles, "exclusive": len(shared_roles) == 1}
        )
        if len(shared_roles) > 1:
            violations.append({"kind": "group_identity", "group_key": key, "roles": shared_roles})

    adjacency_checks: List[Dict[str, Any]] = []
    by_capture: Dict[str, List[Tuple[int, str, str]]] = {}
    for role in present_roles:
        manifest = manifests[role]
        for entry in manifest.get("entries", []):
            # Adjacency is only meaningful *within one capture*. The dataset root
            # is part of the key so two unrelated captures that happen to share a
            # capture_id (a generated block and a manual block, say) are not
            # mistaken for temporally adjacent frames.
            capture = "|".join(
                [str(manifest.get("dataset_root") or ""), str(entry.get("capture_id") or entry.get("group_key"))]
            )
            index = entry.get("frame_index")
            if index is None:
                continue
            by_capture.setdefault(capture, []).append(
                (int(index), role, str(entry.get("sample_identity")))
            )
    for capture, items in sorted(by_capture.items()):
        items.sort()
        breaches: List[Dict[str, Any]] = []
        for (i_a, role_a, id_a), (i_b, role_b, id_b) in zip(items, items[1:]):
            if role_a != role_b and abs(i_b - i_a) <= int(adjacency_window):
                breaches.append(
                    {
                        "capture_id": capture,
                        "frame_index_a": i_a,
                        "frame_index_b": i_b,
                        "roles": [role_a, role_b],
                        "sample_identities": [id_a, id_b],
                    }
                )
        adjacency_checks.append(
            {
                "capture_id": capture,
                "frame_count": len(items),
                "adjacent_role_breaches": len(breaches),
                "examples": breaches[:5],
            }
        )
        for breach in breaches:
            violations.append({"kind": "temporal_adjacency", **breach})

    required = [
        f"{ROLE_TRAIN} ∩ {ROLE_VALIDATION} = empty",
        f"{ROLE_TRAIN} ∩ {ROLE_GENERATED_TEST} = empty",
        f"generated({ROLE_TRAIN} ∪ {ROLE_VALIDATION}) ∩ {ROLE_MANUAL_TEST} = empty",
    ]
    group_leak = any(v["kind"] == "group_identity" for v in violations)
    content_clean = all(check["disjoint"] for check in content_checks)
    leak_free = bool(content_clean and not group_leak and not violations)

    payload = {
        "schema": LEAKAGE_AUDIT_SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "claim_scope": claim_scope,
        "roles_present": present_roles,
        "required_guarantees": required,
        "content_equality_checks": content_checks,
        "group_identity_checks": group_checks,
        "temporal_adjacency_checks": adjacency_checks,
        "adjacency_window": int(adjacency_window),
        "violations": violations,
        "leak_free": leak_free,
        "status": "PASS" if leak_free else "FAIL",
        "audit_sha256": sha256_text(
            canonical_dumps(
                {
                    "content": [c["pair"] + [c["shared_sample_identities"]] for c in content_checks],
                    "groups": [[g["group_key"]] + g["roles"] for g in group_checks],
                    "violations": len(violations),
                }
            )
        ),
    }
    if raise_on_leak and violations:
        raise LeakageDetected(
            f"RQ5 split leakage detected ({len(violations)} violation(s)): "
            + "; ".join(str(v.get("kind")) for v in violations[:5])
        )
    return payload


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


def write_split_manifests(out_dir: Any, authority: SplitAuthority) -> Dict[str, Path]:
    """Write ``*_manifest.json`` for every role; returns ``{role: path}``."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}
    for role, manifest in authority.manifests.items():
        filename = SPLIT_FILENAMES.get(role, f"{role}_manifest.json")
        target = directory / filename
        target.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        written[role] = target
    return written


def write_leakage_audit(out_dir: Any, payload: Mapping[str, Any]) -> Path:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / LEAKAGE_AUDIT_FILENAME
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def load_split_manifest(path: Any) -> Dict[str, Any]:
    """Load a split manifest and check its schema."""
    p = Path(path)
    if not p.is_file():
        raise SplitAuthorityError(f"split manifest not found: {p}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "rq5_split_entry/v1":
        raise SplitAuthorityError(f"unsupported split manifest schema in {p}")
    return payload


def resolve_train_label_paths(manifest: Mapping[str, Any]) -> List[str]:
    """
    Return the label paths of a governed *training* split manifest.

    This is the only sanctioned source of class-weight statistics under
    protocol v2: class counts are derived from exactly these files, so a
    validation, generated-test or manual-test label cannot enter the weights.
    """
    entries = list(manifest.get("entries") or [])
    if not entries:
        raise SplitAuthorityError("training split manifest contains no entries")
    paths: List[str] = []
    seen: set = set()
    for entry in entries:
        label = str(entry.get("label_path") or "")
        if not label:
            raise SplitAuthorityError(f"training split entry has no label_path: {entry}")
        if label in seen:
            continue
        seen.add(label)
        paths.append(label)
    return paths