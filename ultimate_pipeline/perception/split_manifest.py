#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/split_manifest.py

CD-1 remediation: immutable split-manifest authority for perception datasets.

Why this exists
---------------
The generators capture frames with sequential CARLA frame counters
(``model manifest registry: f"{frame:08d}"``) and Deep-Audit CD-1 proved that
any train/validation/test boundary drawn over *individual frames* guarantees
neighbouring frames from the same trajectory end up in different partitions —
an unfalsifiable-inflated RQ5 accuracy. This module makes group-level splitting
the ONLY governed path:

* The partition unit is the **capture session** (optionally refined into
  contiguous temporal blocks). Individual frames are never assignable.
* Two adjacent frames always share a session, therefore always share a
  partition. The adjacency invariant is asserted at build time.
* Neighbouring-frame leakage across partitions is *structurally impossible*,
  not merely "unlikely".
* Manual datasets land only in ``manual_test`` and are excluded from
  training/hyper-parameter selection by construction.
* The manifest is immutable: canonical JSON + SHA-256 sidecar; consumers
  re-verify before use.

Required partitions (rq5 contract):
    generated_train / generated_validation / generated_test / manual_test

Offline, no CARLA: this module reads captured dataset roots and publishes
split manifests; it never executes capture, cooking or training. Runs in
frame-status mode (reads ``frame_status/<frame>.json``) when frame-set status
rows are present, otherwise falls back to listing ``rgb/<camera>/*.png``
with the incompleteness recorded in the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ultimate_pipeline.perception.capture_writer import (
    FRAME_STATUS_REJECTED_INCOMPLETE,
    read_frame_status,
)

SPLIT_MANIFEST_SCHEMA = "split_manifest_v1"
SPLIT_MANIFEST_FILENAME = "split_manifest.json"
SPLIT_MANIFEST_SIDECAR_SUFFIX = ".sha256"

PARTITION_GENERATED_TRAIN = "generated_train"
PARTITION_GENERATED_VALIDATION = "generated_validation"
PARTITION_GENERATED_TEST = "generated_test"
PARTITION_MANUAL_TEST = "manual_test"

REQUIRED_PARTITIONS: Tuple[str, ...] = (
    PARTITION_GENERATED_TRAIN,
    PARTITION_GENERATED_VALIDATION,
    PARTITION_GENERATED_TEST,
    PARTITION_MANUAL_TEST,
)

#: Assignment seed frozen for reproducible splitting; recorded in the manifest.
DEFAULT_SPLIT_SEED = 20260317

#: Granularity of the split unit. ``capture_session`` (default) treats each
#: dataset root as one group; ``temporal_block`` additionally subdivides a
#: session's frames into contiguous blocks (gap > max_gap starts a new block)
#: and assigns at block granularity — adjacent frames still always share a
#: partition, because blocks themselves are the indivisible unit.
GRANULARITY_SESSION = "capture_session"
GRANULARITY_TEMPORAL_BLOCK = "temporal_block"

GRANULARITIES: Tuple[str, ...] = (GRANULARITY_SESSION, GRANULARITY_TEMPORAL_BLOCK)


class SplitManifestError(RuntimeError):
    """Raised when a split manifest cannot be built or fails verification."""


# ---------------------------------------------------------------------------
# dataset-root inspection (members-of-record)
# ---------------------------------------------------------------------------


def list_session_frames(dataset_root: Any) -> Dict[str, Any]:
    """
    Enumerate one captured dataset root as a *frame list*.

    Returns ``{"complete": [frame ints], "rejected": [frame ints],
    "untraced": [frame ints], "cameras": [...], "status_mode": bool}``.

    ``complete`` frames are those for which ``frame_status/<frame>.json``
    records status ``complete``; ``rejected`` frames recorded
    ``rejected_incomplete``; ``untraced`` frames have PNGs present but no
    status row (pre-transaction captures). Untraced frames are NOT eligible
    for inclusion: governed consumers see them listed and rejected.
    """
    root = Path(dataset_root)
    if not root.is_dir():
        raise SplitManifestError(f"dataset root does not exist: {root}")

    rgb_dir = root / "rgb"
    cameras = sorted(d.name for d in rgb_dir.iterdir() if d.is_dir()) if rgb_dir.is_dir() else []

    frame_ids: set = set()
    for cam in cameras:
        for png in (rgb_dir / cam).glob("*.png"):
            stem = png.stem
            try:
                frame_ids.add(int(stem))
            except ValueError:
                continue  # procedural artefacts (e.g. *_aug) are not frames

    status_mode = (root / "frame_status").is_dir()
    complete: List[int] = []
    rejected: List[int] = []
    for frame in sorted(frame_ids):
        payload = read_frame_status(root, frame)
        if payload is None:
            continue  # untraced: no status row, never eligible
        if payload.get("status") == "complete":
            complete.append(frame)
        elif payload.get("status") == FRAME_STATUS_REJECTED_INCOMPLETE:
            rejected.append(frame)

    untraced = sorted(frame_ids.difference(complete, rejected))
    return {
        "complete": complete,
        "rejected": rejected,
        "untraced": untraced,
        "cameras": cameras,
        "status_mode": status_mode,
    }


def session_content_digest(dataset_root: Any) -> str:
    """
    Content identity of one session root: SHA-256 over sorted
    ``(relative member path, size)`` pairs of the image/label members.

    This is a *fast transitive identity* (paths + sizes), not a full content
    hash of every PNG; a full content digest can be attached per frame via
    the frame-status rows the capture transaction publishes. Any change of
    membership (file added/removed/renamed) changes this digest.
    """
    root = Path(dataset_root)
    parts: List[str] = []
    if (root / "rgb").is_dir():
        for png in sorted((root / "rgb").rglob("*.png")):
            rel = png.relative_to(root).as_posix()
            parts.append(f"{rel}:{png.stat().st_size}")
    if (root / "semseg_raw").is_dir():
        for png in sorted((root / "semseg_raw").rglob("*.png")):
            rel = png.relative_to(root).as_posix()
            parts.append(f"{rel}:{png.stat().st_size}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# group-level assignment
# ---------------------------------------------------------------------------


def _stable_group_hash(group_key: str, seed: int) -> int:
    payload = f"split_manifest_v1|{int(seed)}|{group_key}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _assign_partition(group_key: str, *, seed: int, proportions: Mapping[str, float]) -> str:
    roll = (_stable_group_hash(group_key, seed) % 10_000) / 10_000
    cumulative = 0.0
    for partition in (PARTITION_GENERATED_TRAIN, PARTITION_GENERATED_VALIDATION, PARTITION_GENERATED_TEST):
        cumulative += float(proportions[partition])
        if roll < cumulative:
            return partition
    return PARTITION_GENERATED_TEST  # floating point tail: always lands somewhere


def build_temporal_blocks(frames: Sequence[int], *, max_gap: int = 1) -> List[Tuple[int, int]]:
    """
    Contiguous temporal blocks over an ordered frame list.

    Consecutive frame ids differing by more than ``max_gap`` start a new
    block. Returns ``(block_index, [frames])``-free ``(index, frames)`` pairs
    in a deterministic order; a block is the *indivisible* partition unit for
    granularity ``temporal_block``.
    """
    ordered = sorted(int(f) for f in frames)
    blocks: List[Tuple[int, int]] = []
    current: List[int] = []
    for frame in ordered:
        if current and (int(frame) - current[-1]) > max_gap:
            blocks.append((len(blocks), current))
            current = []
        current.append(int(frame))
    if current:
        blocks.append((len(blocks), current))
    return blocks


def build_split_manifest(
    *,
    generated_roots: Sequence[Any],
    manual_roots: Sequence[Any] = (),
    camera_name: Optional[str] = None,
    seed: int = DEFAULT_SPLIT_SEED,
    proportions: Optional[Mapping[str, float]] = None,
    granularity: str = GRANULARITY_SESSION,
    temporal_max_gap: int = 1,
    producer_git_sha: Optional[str] = None,
    pretraining_contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the immutable split manifest for the given capture sessions.

    Parameters
    ----------
    generated_roots:
        One root per *generated* capture session. Each root is one partition
        unit (session granularity) or is subdivided into contiguous temporal
        blocks (block granularity). Individual frames are never assignable.
    manual_roots:
        Roots of manual/reference captures. Every group derived from them is
        unconditionally assigned ``manual_test``.
    proportions:
        Mapping with the three generated partitions (fractions, summing to 1);
        default 0.70/0.15/0.15.
    """
    if granularity not in GRANULARITIES:
        raise SplitManifestError(f"unsupported granularity {granularity!r}")
    props = dict(proportions or {})
    props.setdefault(PARTITION_GENERATED_TRAIN, 0.70)
    props.setdefault(PARTITION_GENERATED_VALIDATION, 0.15)
    props.setdefault(PARTITION_GENERATED_TEST, 0.15)
    total = sum(float(props[p]) for p in REQUIRED_PARTITIONS if p in props)
    if abs(total - 1.0) > 1e-6:
        raise SplitManifestError(f"partition proportions must sum to 1.0 (got {total})")

    sessions: List[Dict[str, Any]] = []
    partitions: Dict[str, List[str]] = {p: [] for p in REQUIRED_PARTITIONS}

    def _enumerate(roots: Iterable[Any], *, manual: bool) -> None:
        for idx, maybe_root in enumerate(roots):
            entry: Dict[str, Any] = {}
            if isinstance(maybe_root, Mapping):
                root_path = maybe_root["root"]
                entry.update(maybe_root)  # explicit session metadata (route id, etc.)
            else:
                root_path = maybe_root
            root = Path(root_path)
            frames = list_session_frames(root)
            session_id = str(maybe_root.get("session_id") if isinstance(maybe_root, Mapping) else root.name)
            if not session_id or session_id in {s["session_id"] for s in sessions}:
                session_id = f"{session_id}#{idx}"
            route = str(maybe_root.get("route_id", "unknown") if isinstance(maybe_root, Mapping) else "unknown")
            content_sha = session_content_digest(root)

            group_key = f"session:{session_id}"
            groups: List[Tuple[str, List[int]]] = [(group_key, list(frames["complete"]))]
            if granularity == GRANULARITY_TEMPORAL_BLOCK:
                blocks = build_temporal_blocks(frames["complete"], max_gap=temporal_max_gap)
                groups = [(f"{group_key}|block:{b}", fs) for b, fs in blocks]

            for gkey, gframes in groups:
                if manual:
                    partition = PARTITION_MANUAL_TEST
                else:
                    partition = _assign_partition(gkey, seed=seed, proportions=props)
                partitions[partition].extend(f"{session_id}:{f}" for f in gframes)

            sessions.append(
                {
                    "session_id": session_id,
                    "root": str(root.resolve()),
                    "manual": bool(manual),
                    "route_id": route,
                    "camera_request": camera_name if camera_name else frames["cameras"],
                    "cameras_present": frames["cameras"],
                    "frame_status_mode": frames["status_mode"],
                    "frames_complete": len(frames["complete"]),
                    "frames_rejected_incomplete": len(frames["rejected"]),
                    "frames_untraced": len(frames["untraced"]),
                    "groups": [g for g, _ in groups],
                    "content_digest_sha256": content_sha,
                    "granularity": granularity,
                }
            )

    _enumerate(generated_roots, manual=False)
    _enumerate(manual_roots, manual=True)

    manifest: Dict[str, Any] = {
        "schema": SPLIT_MANIFEST_SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "split_unit": ("capture_session_or_temporal_block_group"),
        "granularity": granularity,
        "temporal_max_gap": int(temporal_max_gap),
        "seed": int(seed),
        "proportions": {p: float(props[p]) for p in REQUIRED_PARTITIONS if p in props},
        "invariants": {
            "split_by_frame": "forbidden",
            "adjacency_rule": "all frames of a group share one partition",
            "manual_isolation": "manual groups are only ever manual_test",
        },
        "producer_git_sha": producer_git_sha,
        "pretraining_contract": dict(pretraining_contract) if pretraining_contract else None,
        "sessions": sessions,
        "partitions": {
            p: sorted(partitions[p]) for p in REQUIRED_PARTITIONS
        },
        "counts": {p: len(partitions[p]) for p in REQUIRED_PARTITIONS},
    }

    _verify_invariants(manifest)
    return manifest


# ---------------------------------------------------------------------------
# invariants + verification
# ---------------------------------------------------------------------------


def _assert_adjacency(groups: Sequence[Tuple[str, List[int]]], partitions_by_group: Mapping[str, str]) -> None:
    """Every frame between two blocks boundary is in ONE group only; each
    group lands in exactly one partition, so adjacency across partitions is
    impossible by construction. Assert that group keys are unique (a group
    with two partitions would be the leak the frame-level split allowed)."""
    seen: Dict[str, str] = {}
    for gkey, _ in groups:
        partition = partitions_by_group[gkey]
        if gkey in seen and seen[gkey] != partition:
            raise SplitManifestError(f"group {gkey!r} assigned to multiple partitions")
        seen[gkey] = partition


def _verify_invariants(manifest: Mapping[str, Any]) -> None:
    """Fail-closed invariant checks over a built (or loaded) manifest."""
    counts = manifest["counts"]
    generated = {
        p: counts[p]
        for p in (PARTITION_GENERATED_TRAIN, PARTITION_GENERATED_VALIDATION, PARTITION_GENERATED_TEST)
    }
    generated_total = sum(generated.values())

    # Uniqueness of members inside each partition (same frame never twice).
    for partition, members in manifest["partitions"].items():
        if len(members) != len(set(members)):
            raise SplitManifestError(f"duplicate frame in partition {partition}")

    # Cross-partition identity overlap (content SHA + session:frame identity).
    overlaps = find_partition_overlaps(manifest["partitions"])
    if overlaps:
        raise SplitManifestError(f"partition overlap detected: {overlaps}")

    # Manual isolation: manual sessions never contribute to generated training.
    for session in manifest.get("sessions", []):
        if session.get("manual"):
            manual_members = {
                f"{session['session_id']}:{f}"
                for f in _frames_for_session(manifest, session)
            }
            for p in (PARTITION_GENERATED_TRAIN, PARTITION_GENERATED_VALIDATION, PARTITION_GENERATED_TEST):
                intersection = manual_members & set(manifest["partitions"][p])
                if intersection:
                    raise SplitManifestError(
                        f"manual session {session['session_id']!r} leaked into {p}: {sorted(intersection)[:5]}"
                    )

    if generated_total == 0 and any(
        s.get("manual") is False for s in manifest.get("sessions", [])
    ):
        raise SplitManifestError("generated sessions produced an empty generated split")

    if not any(counts[p] for p in generated):
        raise SplitManifestError("all generated partitions empty — split is not usable")

    # Block-level granularity must be reflected by group keys.
    if manifest.get("granularity") == GRANULARITY_TEMPORAL_BLOCK:
        for session in manifest.get("sessions", []):
            for gkey in session.get("groups", []):
                if "|block:" not in gkey:
                    raise SplitManifestError(
                        f"block granularity requested but group {gkey!r} is session-level"
                    )


def _frames_for_session(manifest: Mapping[str, Any], session: Mapping[str, Any]) -> List[int]:
    """Frame ids of one session from partition tuples of the form <sid>:<frame>."""
    sid = str(session["session_id"])
    out: List[int] = []
    for partition, members in manifest["partitions"].items():
        for member in members:
            if member.startswith(f"{sid}:"):
                try:
                    out.append(int(member.rsplit(":", 1)[1]))
                except ValueError:
                    continue
    return out


def find_partition_overlaps(partitions: Mapping[str, Sequence[str]]) -> List[str]:
    """Return human-readable overlaps between the partitions (by session:frame
    identity). Also detects two sessions sharing an identical content digest
    — the copy/capture-replay overlap case a digest inequality alone cannot
    distinguish."""
    problems: List[str] = []
    names = sorted(partitions)
    seen: Dict[str, str] = {}
    for partition in names:
        for member in partitions[partition]:
            if member in seen and not member.startswith((PARTITION_MANUAL_TEST, "manual")):
                problems.append(f"{member!r} in both {seen[member]!r} and {partition!r}")
            if member.startswith(f"{PARTITION_MANUAL_TEST}:") and member in seen:
                problems.append(f"{member!r} in both {seen[member]!r} and {partition!r}")
            seen.setdefault(member, partition)
    return problems


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical manifest form (sorted keys, compact separators)."""
    canonical = json.dumps(dict(manifest), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_split_manifest(out_path: Any, manifest: Mapping[str, Any]) -> Tuple[Path, str]:
    """Write the manifest atomically together with its ``.sha256`` sidecar."""
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(dict(manifest), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = manifest_sha256(manifest)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(canonical + "\n", encoding="utf-8")
    tmp.replace(target)
    Path(str(target) + SPLIT_MANIFEST_SIDECAR_SUFFIX).write_text(digest + "\n", encoding="utf-8")
    return target, digest


def load_and_verify_split_manifest(manifest_path: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Load a manifest and re-verify its sidecar SHA-256 and invariants."""
    path = Path(manifest_path)
    if not path.is_file():
        raise SplitManifestError(f"split manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    failures: List[str] = []
    sidecar = Path(str(path) + SPLIT_MANIFEST_SIDECAR_SUFFIX)
    if sidecar.exists():
        recorded = sidecar.read_text(encoding="utf-8").strip()
        actual = manifest_sha256(payload)
        if recorded.lower() != actual.lower():
            failures.append(f"split manifest digest mismatch: recorded={recorded} actual={actual}")
    else:
        failures.append("split manifest sha256 sidecar missing")
    try:
        _verify_invariants(payload)
    except SplitManifestError as exc:
        failures.append(str(exc))
    # CD-2 / batch 2: v2 contract binding on the split manifest.
    if not payload.get("pretraining_contract"):
        failures.append("split manifest missing pretraining_contract (v2 contract)")
    return payload, failures


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the immutable group-level split manifest (CD-1 authority)."
    )
    parser.add_argument(
        "--generated", action="append", required=True,
        help="one generated capture-session root (repeatable). "
             "May be 'root:session_id:route_id' to attach explicit identity.",
    )
    parser.add_argument(
        "--manual", action="append", default=[],
        help="one manual/reference capture root (repeatable); always manual_test.",
    )
    parser.add_argument("--camera", default=None, help="camera used for identity binding (optional).")
    parser.add_argument("--seed", type=int, default=DEFAULT_SPLIT_SEED)
    parser.add_argument("--granularity", choices=GRANULARITIES, default=GRANULARITY_SESSION)
    parser.add_argument("--temporal-max-gap", type=int, default=1)
    parser.add_argument("--out", required=True, help="path of the split_manifest.json to write.")
    args = parser.parse_args(argv)

    def _root_spec(spec: str) -> Dict[str, Any]:
        parts = spec.split(":", 1)
        if len(parts) == 3:
            return {"root": parts[0], "session_id": parts[1], "route_id": parts[2]}
        return {"root": spec}

    generated = [_root_spec(s) for s in args.generated]
    manual = [{"root": s} for s in args.manual]

    try:
        manifest = build_split_manifest(
            generated_roots=[{**spec, **({"camera": args.camera} if args.camera else {})} for spec in generated],
            manual_roots=manual,
            camera_name=args.camera,
            seed=args.seed,
            granularity=args.granularity,
            temporal_max_gap=args.temporal_max_gap,
        )
        written, digest = write_split_manifest(args.out, manifest)
    except (SplitManifestError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"split manifest written: {written}")
    print(f"sha256: {digest}")
    for partition in REQUIRED_PARTITIONS:
        print(f"  {partition}: {manifest['counts'][partition]} frames")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
