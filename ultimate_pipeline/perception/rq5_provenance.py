#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/rq5_provenance.py

Governed provenance for RQ5 (generalization / transfer) training and
evaluation evidence.

NEW-243 / NEW-244 / NEW-245
---------------------------
RQ5 produces *scientific* evidence. That requires three things the previous
training path did not provide:

1. **Dataset content identity.** A dataset root is a path, and paths lie: they
   can be re-generated, moved, partially overwritten, or point at a different
   capture. Every dataset that participates in a governed RQ5 run is therefore
   identified by a SHA-256 digest computed over the *names and content digests*
   of its ``rgb/<camera>/*.png`` and ``semseg_raw/<camera>/*.png`` members.

2. **Deterministic seed contract.** Model construction, DataLoader shuffling
   and augmentation-free preprocessing all consume randomness. Two nominally
   identical runs that draw different seeds produce different models, so the
   seed must be frozen, applied to *every* relevant RNG, and recorded next to
   the checkpoint. :func:`seed_everything` is the single owner of that contract.

3. **Checkpoint identity binding.** A bare ``state_dict`` file cannot be traced
   back to the code, data, config and seed that produced it. Every governed
   checkpoint gets a companion ``model_manifest.json`` binding the checkpoint
   content SHA-256 to dataset identities, split roles, git SHA, architecture,
   optimizer, learning rate, seed, class mapping, camera, preprocessing and
   augmentation policy.

This module contains no torch import at module scope beyond the lazy helpers so
that provenance collection and manifest verification stay importable (and
testable) in environments without a GPU. No CARLA import at module level.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ultimate_pipeline.utils.file_hashing import sha256_file

__all__ = [
    "MODEL_MANIFEST_SCHEMA",
    "MODEL_MANIFEST_FILENAME",
    "DATASET_IDENTITY_SCHEMA",
    "SPLIT_ROLES",
    "MULTI_ROOT_TRAIN",
    "DatasetIdentityError",
    "canonical_dumps",
    "sha256_text",
    "dataset_content_identity",
    "combine_dataset_identities",
    "assert_disjoint_splits",
    "seed_everything",
    "seed_contract",
    "collect_git_identity",
    "build_model_manifest",
    "write_model_manifest",
    "load_model_manifest",
    "verify_checkpoint_manifest",
    "load_state_dict_governed",
    "StateDictLoadError",
]

MODEL_MANIFEST_SCHEMA = "rq5_model_manifest_v1"
MODEL_MANIFEST_FILENAME = "model_manifest.json"
DATASET_IDENTITY_SCHEMA = "rq5_dataset_identity_v1"

#: Governed split roles. A governed RQ5 run must declare its splits explicitly;
#: no role may be inferred from "the first training directory" (NEW-237).
SPLIT_ROLES: Tuple[str, ...] = (
    "generated_train",
    "generated_validation",
    "generated_test",
    "manual_test",
)

#: Marker recorded in the manifest for a K-sweep condition whose K dataset roots
#: were consumed as one true multi-root training set (NEW-234).
MULTI_ROOT_TRAIN = "multi_root_union"

_GIT_TIMEOUT = 10.0


class DatasetIdentityError(RuntimeError):
    """Raised when a governed dataset cannot be identified as required."""


class StateDictLoadError(RuntimeError):
    """Raised when a checkpoint's parameters do not match the target model."""


# ---------------------------------------------------------------------------
# canonical serialization / digests
# ---------------------------------------------------------------------------


def canonical_dumps(obj: Any) -> str:
    """Deterministic JSON encoding used for every governed digest."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iter_member_files(root: Path, camera: str) -> List[Path]:
    """Return the RGB and label members that define a dataset's content."""
    members: List[Path] = []
    for sub in ("rgb", "semseg_raw"):
        members.extend(sorted((root / sub / str(camera)).glob("*.png")))
    return members


def dataset_content_identity(
    dataset_root: Any,
    camera: str,
    *,
    max_files: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Compute the content identity of one dataset root.

    The identity is a SHA-256 digest over the sorted
    ``(relative member path, member content SHA-256)`` pairs, so it changes if
    any file is added, removed, renamed or re-encoded.

    Args:
        dataset_root: Dataset root containing ``rgb/<camera>`` and
            ``semseg_raw/<camera>``.
        camera: Camera subdirectory name.
        max_files: Optional upper bound on the number of members digested. When
            the bound is exceeded the identity is returned with
            ``complete=False``; governed runs must reject incomplete identities
            rather than silently digest a prefix.

    Returns:
        Identity payload containing ``identity_sha256``, ``file_count``,
        ``complete`` and the resolved root/camera.

    Raises:
        DatasetIdentityError: If the root does not exist or the identity would
            be incomplete while ``max_files`` is ``None``.
    """
    root = Path(dataset_root)
    resolved = str(root.expanduser().resolve()) if root.exists() else str(root)
    if not root.exists():
        raise DatasetIdentityError(f"dataset root does not exist: {root}")

    members = _iter_member_files(root, camera)
    if not members:
        raise DatasetIdentityError(
            f"no rgb/<camera> or semseg_raw/<camera> PNG members under {root} "
            f"for camera {camera!r}"
        )

    total = len(members)
    complete = True
    if max_files is not None and total > int(max_files):
        members = members[: int(max_files)]
        complete = False

    entries: List[List[str]] = []
    for path in members:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:  # pragma: no cover - defensive
            rel = path.name
        entries.append([rel, sha256_file(path)])

    identity_payload = {
        "schema": DATASET_IDENTITY_SCHEMA,
        "camera": str(camera),
        "file_count": total,
        "digested_file_count": len(entries),
        "complete": complete,
        "members": entries,
    }
    return {
        "schema": DATASET_IDENTITY_SCHEMA,
        "root": resolved,
        "camera": str(camera),
        "file_count": total,
        "digested_file_count": len(entries),
        "complete": complete,
        "identity_sha256": sha256_text(canonical_dumps(identity_payload)),
    }


def combine_dataset_identities(
    identities: Sequence[Mapping[str, Any]],
    *,
    strategy: str = MULTI_ROOT_TRAIN,
) -> Dict[str, Any]:
    """
    Combine per-root dataset identities into one ordered multi-root identity.

    The combination digest covers each member identity *and its position*, so
    reordering the K roots yields a different identity. A K-sweep condition can
    therefore never claim to have trained on K datasets when it trained on
    fewer, and K=1 can never collide with K=3.
    """
    items = list(identities or [])
    digest_input = {
        "schema": DATASET_IDENTITY_SCHEMA,
        "strategy": str(strategy),
        "roots": [
            {
                "index": i,
                "root": entry.get("root"),
                "camera": entry.get("camera"),
                "identity_sha256": entry.get("identity_sha256"),
                "file_count": entry.get("file_count"),
            }
            for i, entry in enumerate(items)
        ],
    }
    return {
        "schema": DATASET_IDENTITY_SCHEMA,
        "strategy": str(strategy),
        "root_count": len(items),
        "root_identities": [dict(entry) for entry in items],
        "complete": all(bool(entry.get("complete")) for entry in items),
        "identity_sha256": sha256_text(canonical_dumps(digest_input)),
    }


def assert_disjoint_splits(
    train_identities: Sequence[Mapping[str, Any]],
    eval_identities: Sequence[Mapping[str, Any]],
) -> List[str]:
    """
    Return the list of split overlaps between training and evaluation datasets.

    NEW-237: a governed evaluation split may never share content identity with
    any training split. Overlap is decided by digest, not by path, so copying a
    dataset to a new directory does not launder the overlap.

    Returns an empty list when the splits are disjoint.
    """
    train_digests = {
        str(entry.get("identity_sha256"))
        for entry in (train_identities or [])
        if entry and entry.get("identity_sha256")
    }
    overlaps: List[str] = []
    for entry in (eval_identities or []):
        if not entry:
            continue
        digest = str(entry.get("identity_sha256") or "")
        if digest and digest in train_digests:
            overlaps.append(
                f"evaluation split shares content identity with a training split: "
                f"{entry.get('root')}"
            )
    return overlaps


# ---------------------------------------------------------------------------
# NEW-244: deterministic seed contract
# ---------------------------------------------------------------------------


def seed_everything(seed: int) -> Dict[str, Any]:
    """
    Apply a single governed seed to every RNG that can affect an RQ5 run.

    Covers ``random``, ``numpy``, ``torch`` CPU, CUDA (all devices) and
    ``PYTHONHASHSEED`` for child processes. Returns the contract payload that is
    recorded in the model manifest so the exact applied state is auditable.

    Raises:
        ValueError: If ``seed`` is negative or otherwise out of range.
    """
    value = int(seed)
    if value < 0:
        raise ValueError(f"seed must be non-negative, got {value}")

    os.environ["PYTHONHASHSEED"] = str(value)
    random.seed(value)

    numpy_state: Optional[str] = None
    try:
        import numpy as np

        np.random.seed(value % (2**32))
        numpy_state = "seeded"
    except Exception:  # pragma: no cover - numpy is a hard dep in practice
        numpy_state = "unavailable"

    torch_state: Dict[str, Any] = {"seeded": False, "cuda_devices": 0}
    try:
        import torch

        torch.manual_seed(value)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(value)
            torch_state["cuda_devices"] = int(torch.cuda.device_count())
        torch_state["seeded"] = True
    except Exception:  # pragma: no cover
        torch_state["seeded"] = False

    return {
        "schema": "rq5_seed_contract_v1",
        "seed": value,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "random": "seeded",
        "numpy": numpy_state,
        "torch": torch_state,
    }


def seed_contract(seed: int) -> Dict[str, Any]:
    """Return the recorded seed contract without mutating global RNG state."""
    return {
        "schema": "rq5_seed_contract_v1",
        "seed": int(seed),
        "applied_to": ["random", "numpy", "torch", "torch.cuda", "PYTHONHASHSEED"],
        "dataloader_generator": "seeded_per_run",
    }


# ---------------------------------------------------------------------------
# git identity
# ---------------------------------------------------------------------------


def _git(repo_root: Optional[str], *args: str) -> Tuple[bool, str]:
    cmd = ["git"]
    if repo_root:
        cmd += ["-C", str(repo_root)]
    cmd += list(args)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False, ""
    return (proc.returncode == 0, proc.stdout.strip())


def collect_git_identity(repo_root: Optional[str] = None) -> Dict[str, Any]:
    """
    Best-effort but *explicit* git identity for a checkpoint manifest.

    Availability is never silently dropped: the returned payload always carries
    ``available`` and ``reason`` so a manifest reader can tell "not a git tree"
    apart from "git failed transiently".
    """
    root = repo_root or str(Path(__file__).resolve().parents[2])
    ok_commit, commit = _git(root, "rev-parse", "HEAD")
    if not ok_commit or not commit:
        return {
            "available": False,
            "reason": "git unavailable or repository is not a git work tree",
            "repo_root": root,
            "commit": None,
            "branch": None,
            "dirty": None,
        }
    ok_branch, branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    ok_dirty, dirty = _git(root, "status", "--porcelain")
    return {
        "available": True,
        "reason": None,
        "repo_root": root,
        "commit": commit,
        "branch": branch if ok_branch else None,
        "dirty": bool(dirty.strip()) if ok_dirty else None,
    }


# ---------------------------------------------------------------------------
# NEW-243 / NEW-245: checkpoint manifests and governed loading
# ---------------------------------------------------------------------------


def build_model_manifest(
    *,
    checkpoint: Any,
    train_dataset_identity: Mapping[str, Any],
    train_roots: Sequence[Any],
    validation_dataset_identity: Optional[Mapping[str, Any]] = None,
    test_dataset_identities: Optional[Mapping[str, Mapping[str, Any]]] = None,
    architecture: str = "torchvision.models.segmentation.fcn_resnet50",
    architecture_version: str = "fcn_resnet50_torchvision_default",
    num_classes: int = 23,
    class_mapping: Optional[Mapping[str, Any]] = None,
    camera: str = "",
    optimizer: str = "Adam",
    learning_rate: float = 0.0,
    epochs: int = 0,
    batch_size: int = 0,
    seed: int = 0,
    preprocessing: str = "PIL_RGB_to_float_tensor_div255",
    augmentation_policy: str = "none",
    repo_root: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the immutable model manifest that binds a checkpoint to its origin.

    The manifest embeds the checkpoint's own content SHA-256, so a checkpoint
    cannot be swapped, retrained or replaced without invalidating it.
    """
    ckpt_path = Path(checkpoint)
    if not ckpt_path.is_file():
        raise FileNotFoundError(f"checkpoint not found for manifest: {ckpt_path}")

    payload: Dict[str, Any] = {
        "schema": MODEL_MANIFEST_SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint": {
            "path": str(ckpt_path.resolve()),
            "filename": ckpt_path.name,
            "sha256": sha256_file(ckpt_path),
        },
        "dataset": {
            "train_strategy": train_dataset_identity.get("strategy", "single_root"),
            "train_identity_sha256": train_dataset_identity.get("identity_sha256"),
            "train_root_count": int(train_dataset_identity.get("root_count", 1) or 1),
            "train_roots": [str(p) for p in (train_roots or [])],
            "train_identity": dict(train_dataset_identity),
            "validation_identity": (
                dict(validation_dataset_identity)
                if validation_dataset_identity
                else None
            ),
            "test_identities": {
                str(k): dict(v) for k, v in (test_dataset_identities or {}).items()
            },
        },
        "code": collect_git_identity(repo_root),
        "model": {
            "architecture": architecture,
            "architecture_version": architecture_version,
            "num_classes": int(num_classes),
            "class_mapping": dict(class_mapping) if class_mapping else None,
        },
        "camera": str(camera),
        "optimization": {
            "optimizer": optimizer,
            "learning_rate": float(learning_rate),
            "epochs": int(epochs),
            "batch_size": int(batch_size),
        },
        "seed": seed_contract(seed),
        "preprocessing": preprocessing,
        "augmentation_policy": augmentation_policy,
    }
    if extra:
        payload["extra"] = dict(extra)
    return payload


def write_model_manifest(out_dir: Any, manifest: Mapping[str, Any]) -> Path:
    """Write ``model_manifest.json`` into ``out_dir`` and return its path."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / MODEL_MANIFEST_FILENAME
    target.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return target


def load_model_manifest(manifest_path: Any) -> Dict[str, Any]:
    """Load and schema-check a model manifest."""
    path = Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(f"model manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"model manifest is not a JSON object: {path}")
    schema = payload.get("schema")
    if schema != MODEL_MANIFEST_SCHEMA:
        raise ValueError(
            f"unsupported model manifest schema {schema!r}; expected {MODEL_MANIFEST_SCHEMA!r}"
        )
    return payload


def verify_checkpoint_manifest(
    checkpoint: Any,
    manifest: Any,
    *,
    require_provenance: bool = True,
) -> Dict[str, Any]:
    """
    Verify that a checkpoint file matches the manifest that claims to describe it.

    Returns a verification payload with ``ok`` and an explicit ``failures`` list.
    With ``require_provenance=True`` a manifest lacking a dataset identity or a
    git commit is a *failure*, not a warning: that is exactly the unbound
    checkpoint NEW-243 is about.
    """
    ckpt_path = Path(checkpoint)
    if isinstance(manifest, (str, Path)):
        payload = load_model_manifest(manifest)
    elif isinstance(manifest, Mapping):
        payload = dict(manifest)
    else:
        return {
            "ok": False,
            "failures": ["no model manifest supplied"],
            "checkpoint": str(ckpt_path),
        }

    failures: List[str] = []
    recorded = ((payload.get("checkpoint") or {}).get("sha256")) or ""
    if not recorded:
        failures.append("model manifest does not record a checkpoint sha256")
    elif not ckpt_path.is_file():
        failures.append(f"checkpoint file is missing: {ckpt_path}")
    else:
        actual = sha256_file(ckpt_path)
        if actual.lower() != str(recorded).lower():
            failures.append(
                f"checkpoint sha256 mismatch: manifest={recorded} actual={actual}"
            )

    if require_provenance:
        train_sha = ((payload.get("dataset") or {}).get("train_identity_sha256")) or ""
        if not train_sha:
            failures.append("model manifest does not bind a training dataset identity")
        if not (payload.get("code") or {}).get("commit"):
            failures.append("model manifest does not bind a git commit")
        if (payload.get("seed") or {}).get("seed") is None:
            failures.append("model manifest does not record a seed")

    return {
        "ok": not failures,
        "failures": failures,
        "checkpoint": str(ckpt_path),
        "manifest_schema": payload.get("schema"),
        "checkpoint_sha256": recorded or None,
    }


def load_state_dict_governed(
    model: Any,
    checkpoint: Any,
    *,
    allow_partial: bool = False,
    record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    NEW-245: load a checkpoint and *verify* the parameter set actually matched.

    ``strict=False`` used to be called without inspecting the result, so an
    incompatible or partial checkpoint could load silently and leave the rest of
    the model freshly initialized -- a model that reports metrics but was never
    trained. Here the load is strict by default; a mismatch raises
    :class:`StateDictLoadError` unless ``allow_partial=True`` is passed
    explicitly, and the observed ``missing_keys``/``unexpected_keys`` are always
    returned (and merged into ``record`` when supplied) for the evidence trail.

    Returns:
        ``{"missing_keys": [...], "unexpected_keys": [...], "strict": bool}``
    """
    path = Path(checkpoint)
    if not path.is_file():
        raise FileNotFoundError(f"checkpoint not found: {path}")

    state = _torch_load_state(path)
    if not isinstance(state, Mapping):
        raise StateDictLoadError(
            f"checkpoint {path} does not contain a state_dict mapping "
            f"(got {type(state).__name__}); a full training checkpoint is not a state_dict"
        )

    # Accept either a bare state_dict or a checkpoint wrapper that stores one.
    for wrapper_key in ("state_dict", "model_state_dict", "model"):
        inner = state.get(wrapper_key) if isinstance(state, Mapping) else None
        if isinstance(inner, Mapping):
            state = inner
            break

    # Load permissively *internally* so the exact missing/unexpected key sets can
    # be enumerated and reported. Strictness is then decided here, from the
    # observed result, rather than delegated to torch's opaque RuntimeError.
    load_result = model.load_state_dict(dict(state), strict=False)
    missing = list(getattr(load_result, "missing_keys", []) or [])
    unexpected = list(getattr(load_result, "unexpected_keys", []) or [])
    outcome = {
        "checkpoint": str(path.resolve()),
        "strict": not allow_partial,
        "missing_keys": missing,
        "unexpected_keys": unexpected,
        "parameter_count": len(dict(state)),
    }

    if (missing or unexpected) and not allow_partial:
        raise StateDictLoadError(
            "checkpoint parameter set does not match the target model: "
            f"missing={missing[:8]} unexpected={unexpected[:8]} "
            f"(pass allow_partial=True to accept a recorded partial load)"
        )

    if record is not None:
        record["state_dict_load"] = outcome
    return outcome


def _torch_load_state(path: Path) -> Any:
    """Load a torch checkpoint with ``weights_only`` when the build supports it."""
    import torch

    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:  # pragma: no cover - older torch builds
        return torch.load(path, map_location="cpu")
    except Exception:
        # A checkpoint saved as a bare tensor dict may still trip weights_only on
        # some builds; fall back to the unrestricted load so the governed
        # missing/unexpected-key check above is what decides the outcome.
        return torch.load(path, map_location="cpu")
