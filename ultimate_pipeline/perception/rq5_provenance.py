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
from dataclasses import dataclass, field
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
    "EVALUATION_ROLES",
    "LABELED_EVAL_ROLES",
    "UNLABELED_EVAL_ROLES",
    "REAL_UNLABELED_SHIFT_METRICS",
    "PROTOCOL_V2_RELPATH",
    "PROTOCOL_V2_POLICY",
    "RESEARCH_ROLE_REQUIREMENT",
    "DatasetIdentityError",
    "IncompleteIdentityError",
    "EvaluationRoleError",
    "StateDictLoadError",
    "SEEDED_BUT_NUMERICALLY_NONDETERMINISTIC",
    "DETERMINISM_ENFORCED",
    "canonical_dumps",
    "sha256_text",
    "dataset_content_identity",
    "combine_dataset_identities",
    "assert_disjoint_splits",
    "assert_complete_identity",
    "require_complete_identities",
    "seed_everything",
    "seed_contract",
    "DeterminismContract",
    "apply_determinism_contract",
    "collect_git_identity",
    "protocol_identity",
    "build_model_manifest",
    "write_model_manifest",
    "load_model_manifest",
    "verify_checkpoint_manifest",
    "verify_checkpoint_provenance_strict",
    "evaluation_role_contract",
    "assert_labeled_evaluation_bound",
    "assert_unlabeled_metrics_are_shift_only",
    "load_state_dict_governed",
]

MODEL_MANIFEST_SCHEMA = "rq5_model_manifest_v1"
MODEL_MANIFEST_FILENAME = "model_manifest.json"
DATASET_IDENTITY_SCHEMA = "rq5_dataset_identity_v1"

#: Research-strict roles that must each carry a *complete* dataset identity on
#: any governed checkpoint. A role that does not apply to a given checkpoint
#: (e.g. ``manual_test`` for a training-only diagnostic) is simply absent.
RESEARCH_ROLE_REQUIREMENT = ("generated_train", "generated_validation", "generated_test", "manual_test")

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


class IncompleteIdentityError(DatasetIdentityError):
    """
    Raised when an authoritative role is bound to a *partial* dataset identity.

    A digest over a prefix (``--dataset-identity-max-files``), a sample or a
    prefix-hash identifies that prefix, not the dataset. Binding it to an RQ5
    checkpoint would let a truncated dataset claim to be a complete one.
    """


class EvaluationRoleError(RuntimeError):
    """Raised when evaluation evidence violates its role contract."""


class StateDictLoadError(RuntimeError):
    """Raised when a checkpoint's parameters do not match the target model."""


#: Governed final-evaluation roles. Roles are never merged: a manual-test result
#: can never be presented as a generated-test result.
EVALUATION_ROLES = ("generated_test", "manual_test", "real_unlabeled")

#: Roles where ground-truth labels exist, so accuracy-family metrics are legal.
LABELED_EVAL_ROLES = ("generated_test", "manual_test")

#: Roles with no ground truth. Only shift measures are permitted.
UNLABELED_EVAL_ROLES = ("real_unlabeled",)

#: The only metric families allowed on ``real_unlabeled`` evidence. None of them
#: is an accuracy, and none may be reported as one.
REAL_UNLABELED_SHIFT_METRICS = (
    "entropy",
    "entropy_mean",
    "confidence",
    "confidence_mean",
    "coral",
    "coral_distance",
    "mmd",
    "mmd_distance",
    "fid",
    "fid_like",
    "shift",
    "distribution_shift",
)

#: Location of the frozen RQ5 protocol relative to the repository root.
PROTOCOL_V2_RELPATH = "configs/rq5_protocol_freeze_v2.json"

#: Checkpoint policy recorded in every governed model manifest (protocol v2).
PROTOCOL_V2_POLICY = {
    "protocol": "rq5_protocol_freeze/v2",
    "checkpoint_policy": "final_epoch_only",
    "validation_selects_epoch": False,
    "early_stopping": False,
    "selection_consults_manual": False,
}


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
# NEW-247: dataset identity completeness
# ---------------------------------------------------------------------------


def assert_complete_identity(
    identity: Optional[Mapping[str, Any]],
    *,
    role: str,
    authoritative: bool = True,
) -> Dict[str, Any]:
    """
    Require a *complete* dataset identity for an authoritative role.

    ``complete`` is False whenever the digest covered a prefix of the dataset
    (``max_files``), a sample, or any other subset. A prefix digest is a valid
    diagnostic fingerprint and an invalid scientific identity: it cannot change
    when the omitted tail changes, so it cannot prove which data trained a
    model.

    Args:
        identity: The identity payload to check.
        role: Governed role name, used in the error message.
        authoritative: When False the check is advisory and the payload is
            returned with an ``authoritative=False`` marker (diagnostic use).

    Raises:
        IncompleteIdentityError: If ``authoritative`` and the identity is
            missing, lacks a digest, or is marked incomplete.
    """
    if not isinstance(identity, Mapping):
        if not authoritative:
            return {"role": role, "authoritative": False, "complete": False, "reason": "absent"}
        raise IncompleteIdentityError(
            f"role {role!r} requires a dataset identity, but none was supplied"
        )

    digest = identity.get("identity_sha256")
    complete = bool(identity.get("complete"))
    if not authoritative:
        return {
            "role": role,
            "authoritative": False,
            "complete": complete,
            "identity_sha256": digest,
            "reason": None if (digest and complete) else "diagnostic-only identity",
        }

    if not digest:
        raise IncompleteIdentityError(
            f"role {role!r} dataset identity records no identity_sha256; a governed role "
            "cannot be bound to an unidentified dataset"
        )
    if not complete:
        raise IncompleteIdentityError(
            f"role {role!r} dataset identity is incomplete (complete=false; "
            f"digested={identity.get('digested_file_count')} of {identity.get('file_count')} "
            "members). Partial identities produced by max_files/prefix hashing/sampling are "
            "diagnostic only and must not be bound to an authoritative RQ5 role"
        )
    return {
        "role": role,
        "authoritative": True,
        "complete": True,
        "identity_sha256": str(digest),
        "file_count": identity.get("file_count"),
        "root": identity.get("root"),
        "camera": identity.get("camera"),
    }


def require_complete_identities(
    identities_by_role: Mapping[str, Optional[Mapping[str, Any]]],
    *,
    roles: Sequence[str] = RESEARCH_ROLE_REQUIREMENT,
    authoritative: bool = True,
    allow_absent_roles: Sequence[str] = (),
) -> Dict[str, Any]:
    """
    Check every applicable research role for a complete dataset identity.

    ``allow_absent_roles`` lists roles that legitimately do not apply to the
    checkpoint under inspection. Any *present* role that is incomplete fails.

    Returns a role report; raises :class:`IncompleteIdentityError` listing every
    offending role at once so a run fails once rather than four times.
    """
    report: Dict[str, Any] = {}
    failures: List[str] = []
    allowed = tuple(allow_absent_roles)
    for role in roles:
        if role not in identities_by_role:
            if role in allowed or not authoritative:
                report[role] = {"role": role, "present": False, "skipped": True}
                continue
            failures.append(f"{role}: identity absent")
            report[role] = {"role": role, "present": False, "skipped": False}
            continue
        try:
            report[role] = {
                "present": True,
                **assert_complete_identity(
                    identities_by_role.get(role), role=role, authoritative=authoritative
                ),
            }
        except IncompleteIdentityError as exc:
            report[role] = {"role": role, "present": True, "complete": False, "reason": str(exc)}
            failures.append(str(exc))
    if failures:
        raise IncompleteIdentityError(
            "incomplete or absent dataset identities for governed RQ5 roles: " + "; ".join(failures)
        )
    return report


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


#: Recorded when the seed is fully applied but the hardware/library stack cannot
#: guarantee bit-exact numerics. Never replaced by a false bit-exactness claim.
SEEDED_BUT_NUMERICALLY_NONDETERMINISTIC = "SEEDED_BUT_NUMERICALLY_NONDETERMINISTIC"
DETERMINISM_ENFORCED = "DETERMINISM_ENFORCED"


@dataclass
class DeterminismContract:
    """The determinism settings actually applied, as opposed to intended."""

    seed: int
    seed_record: Dict[str, Any]
    use_deterministic_algorithms: Optional[bool]
    cudnn_deterministic: Optional[bool]
    cudnn_benchmark: Optional[bool]
    strict_supported: bool
    blockers: List[str] = field(default_factory=list)
    environment: Dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return DETERMINISM_ENFORCED if self.strict_supported else SEEDED_BUT_NUMERICALLY_NONDETERMINISTIC

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "rq5_determinism_contract_v1",
            "status": self.status,
            "bit_exactness_claimed": False,
            "seed": int(self.seed),
            "seed_applied": self.seed_record,
            "torch_use_deterministic_algorithms": self.use_deterministic_algorithms,
            "torch_cudnn_deterministic": self.cudnn_deterministic,
            "torch_cudnn_benchmark": self.cudnn_benchmark,
            "strict_determinism_supported": bool(self.strict_supported),
            "strict_determinism_blockers": list(self.blockers),
            "environment": dict(self.environment),
        }


def apply_determinism_contract(
    seed: int,
    *,
    strict: bool = True,
    env: Optional[Mapping[str, str]] = None,
) -> DeterminismContract:
    """
    Seed every RNG *and* request strict deterministic kernels.

    Seeding alone bounds the *stream* of random numbers but not the order of
    floating-point reductions, so two seeded runs can still differ in the last
    bits on some hardware. Where torch supports it this also sets
    ``use_deterministic_algorithms``, ``cudnn.deterministic`` and disables
    ``cudnn.benchmark``.

    If strict determinism cannot be honoured (older build, or a kernel without a
    deterministic implementation) the run is recorded as
    ``SEEDED_BUT_NUMERICALLY_NONDETERMINISTIC`` together with the reason. It is
    never recorded as bit-exact.
    """
    environ: Any = os.environ if env is None else env
    seed_record = seed_everything(seed)
    blockers: List[str] = []
    uda: Optional[bool] = None
    cudnn_det: Optional[bool] = None
    cudnn_bench: Optional[bool] = None
    try:
        import torch

        if strict:
            # The recorded values are the settings READ BACK after the request,
            # not the fact that the request did not raise: "we asked" and "we got"
            # are different claims and only the second one is evidence.
            try:
                torch.use_deterministic_algorithms(True)
                uda = bool(torch.are_deterministic_algorithms_enabled())
            except Exception as exc:  # pragma: no cover - build dependent
                uda = False
                blockers.append(f"use_deterministic_algorithms: {type(exc).__name__}: {exc}")
            try:
                torch.backends.cudnn.deterministic = True
                cudnn_det = bool(torch.backends.cudnn.deterministic)
            except Exception as exc:  # pragma: no cover
                cudnn_det = False
                blockers.append(f"cudnn.deterministic: {type(exc).__name__}: {exc}")
            try:
                torch.backends.cudnn.benchmark = False
                cudnn_bench = bool(torch.backends.cudnn.benchmark)
            except Exception as exc:  # pragma: no cover
                cudnn_bench = False
                blockers.append(f"cudnn.benchmark: {type(exc).__name__}: {exc}")
    except Exception as exc:  # pragma: no cover - torch absent
        blockers.append(f"torch import failed: {type(exc).__name__}: {exc}")

    return DeterminismContract(
        seed=int(seed),
        seed_record=seed_record,
        use_deterministic_algorithms=uda,
        cudnn_deterministic=cudnn_det,
        cudnn_benchmark=cudnn_bench,
        strict_supported=not blockers,
        blockers=blockers,
        environment={
            "pythonhashseed": environ.get("PYTHONHASHSEED"),
            "cuda_device_count": int(seed_record.get("torch", {}).get("cuda_devices", 0) or 0),
        },
    )


# ---------------------------------------------------------------------------
# protocol identity
# ---------------------------------------------------------------------------


def protocol_identity(
    protocol_path: Optional[Any] = None,
    *,
    repo_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve the frozen protocol file and its SHA-256.

    A governed model manifest must be bound to a protocol *file digest*, not to
    a version string: "v2" proves nothing if the file changes afterwards.

    The digest is taken over line-ending-normalised text. A raw byte digest
    would differ between a Windows checkout (CRLF) and a Linux checkout (LF) for
    a file whose *content* is identical, which would make an unchanged protocol
    look amended to every cross-platform reviewer.
    """
    path = Path(protocol_path) if protocol_path else None
    if path is None:
        root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
        path = root / PROTOCOL_V2_RELPATH
    if not path.is_file():
        raise FileNotFoundError(f"frozen RQ5 protocol not found: {path}")
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return {
        "path": str(path),
        "relpath": PROTOCOL_V2_RELPATH,
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "sha256": hashlib.sha256(normalized).hexdigest(),
        "sha256_raw_bytes": hashlib.sha256(raw).hexdigest(),
        "digest_normalizes_line_endings": True,
        "checkpoint_policy": dict(PROTOCOL_V2_POLICY),
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
    protocol_path: Optional[Any] = None,
    class_weighting_policy: Optional[Mapping[str, Any]] = None,
    validation_identity: Optional[Mapping[str, Any]] = None,
    determinism: Optional[Mapping[str, Any]] = None,
    training_history: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the immutable model manifest that binds a checkpoint to its origin.

    The manifest embeds the checkpoint's own content SHA-256, so a checkpoint
    cannot be swapped, retrained or replaced without invalidating it. Under
    protocol v2 it additionally binds the *frozen protocol file digest*, the
    class-weighting policy and the checkpoint policy, because a model trained
    under a different rule is a different experiment even with identical
    hyperparameters.

    Manual-test metrics are deliberately **not** accepted in ``extra``: they are
    outcomes of the experiment, not provenance of the model, and admitting them
    would let a manual-target result participate in model selection.
    """
    ckpt_path = Path(checkpoint)
    if not ckpt_path.is_file():
        raise FileNotFoundError(f"checkpoint not found for manifest: {ckpt_path}")

    forbidden = {"manual_test", "manual_metrics", "manual_test_metrics", "miou_manual_test"}
    if extra:
        leaked = sorted(forbidden & {str(k).lower() for k in extra})
        if leaked:
            raise ValueError(
                "model manifest provenance must not carry manual-test metrics "
                f"(rejected keys: {leaked}); they are experiment outcomes, not model provenance"
            )

    resolved_validation = validation_identity or validation_dataset_identity

    payload: Dict[str, Any] = {
        "schema": MODEL_MANIFEST_SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint": {
            "path": str(ckpt_path.resolve()),
            "filename": ckpt_path.name,
            "sha256": sha256_file(ckpt_path),
            "policy": dict(PROTOCOL_V2_POLICY),
        },
        "protocol": protocol_identity(protocol_path, repo_root=repo_root),
        "dataset": {
            "train_strategy": train_dataset_identity.get("strategy", "single_root"),
            "train_identity_sha256": train_dataset_identity.get("identity_sha256"),
            "train_identity_complete": bool(train_dataset_identity.get("complete")),
            "train_root_count": int(train_dataset_identity.get("root_count", 1) or 1),
            "train_roots": [str(p) for p in (train_roots or [])],
            "train_identity": dict(train_dataset_identity),
            "validation_identity": (
                dict(resolved_validation) if resolved_validation else None
            ),
            "validation_identity_sha256": (resolved_validation or {}).get("identity_sha256"),
            "validation_identity_complete": bool((resolved_validation or {}).get("complete")),
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
        "class_weighting": (
            dict(class_weighting_policy)
            if class_weighting_policy
            else {"policy": "unspecified", "source": "unspecified"}
        ),
        "seed": seed_contract(seed),
        "determinism": dict(determinism) if determinism else None,
        "training_history": dict(training_history) if training_history else None,
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


# ---------------------------------------------------------------------------
# NEW-247: research-mode checkpoint provenance verification
# ---------------------------------------------------------------------------


def verify_checkpoint_provenance_strict(
    checkpoint: Any,
    manifest: Any,
    *,
    expected_roles: Sequence[str] = RESEARCH_ROLE_REQUIREMENT,
    require_protocol: bool = True,
    allow_absent_roles: Sequence[str] = (),
) -> Dict[str, Any]:
    """
    Full research-mode provenance verification of a checkpoint.

    Beyond the byte-level checkpoint binding of
    :func:`verify_checkpoint_manifest`, this requires, for every applicable
    role, a **complete** dataset identity, plus the frozen protocol digest and
    a checkpoint policy that does not claim validation-based epoch selection.
    Returns ``{"ok": bool, "failures": [...]}`` rather than raising, so a gate
    can report every defect at once.
    """
    base = verify_checkpoint_manifest(checkpoint, manifest, require_provenance=True)
    failures: List[str] = list(base.get("failures") or [])

    payload: Dict[str, Any] = {}
    if isinstance(manifest, (str, Path)):
        payload = load_model_manifest(manifest)
    elif isinstance(manifest, Mapping):
        payload = dict(manifest)

    dataset = payload.get("dataset") or {}
    role_identities: Dict[str, Optional[Mapping[str, Any]]] = {
        "generated_train": dataset.get("train_identity"),
        "generated_validation": dataset.get("validation_identity"),
    }
    for role, identity in (dataset.get("test_identities") or {}).items():
        role_identities[str(role)] = identity

    try:
        require_complete_identities(
            role_identities,
            roles=tuple(expected_roles),
            allow_absent_roles=allow_absent_roles,
        )
    except IncompleteIdentityError as exc:
        failures.append(str(exc))

    if require_protocol and not (payload.get("protocol") or {}).get("sha256"):
        failures.append(
            f"model manifest does not bind the frozen protocol digest ({PROTOCOL_V2_RELPATH})"
        )

    if (payload.get("checkpoint") or {}).get("policy", {}).get("validation_selects_epoch"):
        failures.append(
            "checkpoint policy declares validation-based epoch selection, which protocol v2 forbids"
        )

    return {
        "ok": not failures,
        "failures": failures,
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": base.get("checkpoint_sha256"),
        "protocol_sha256": (payload.get("protocol") or {}).get("sha256"),
        "roles_checked": list(expected_roles),
    }


# ---------------------------------------------------------------------------
# NEW-247: evaluation role authority
# ---------------------------------------------------------------------------


def evaluation_role_contract(role: str) -> Dict[str, Any]:
    """Return the metric contract for one governed evaluation role."""
    if role not in EVALUATION_ROLES:
        raise EvaluationRoleError(
            f"unknown evaluation role {role!r}; governed roles are {list(EVALUATION_ROLES)}"
        )
    labeled = role in LABELED_EVAL_ROLES
    return {
        "role": role,
        "labeled": labeled,
        "requires_dataset_identity": labeled,
        "requires_checkpoint_identity": True,
        "allowed_metric_families": (
            ["mIoU", "per_class_iou", "pixel_accuracy", "confusion_matrix"]
            if labeled
            else list(REAL_UNLABELED_SHIFT_METRICS)
        ),
        "accuracy_metrics_allowed": labeled,
        "accuracy_claim_allowed": labeled,
        "claim_boundary": (
            "Ground-truth labels exist for this role; accuracy-family metrics are reportable."
            if labeled
            else (
                "No ground truth exists for this role. Only entropy/confidence/CORAL/MMD/"
                "FID-like distribution-shift measures are reportable, and none of them is "
                "accuracy or a generalization-performance number."
            )
        ),
    }


def assert_labeled_evaluation_bound(
    role: str,
    *,
    checkpoint: Any,
    manifest: Any,
    expected_checkpoint_sha256: Optional[str] = None,
    expected_dataset_identity_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Require that a labeled-sim evaluation names exactly the intended checkpoint
    and dataset.

    An evaluation that ran against a different checkpoint, or against a dataset
    whose identity differs from the requested split, is evidence about a
    different model on different data and must not be filed under this role.
    """
    contract = evaluation_role_contract(role)
    if not contract["requires_dataset_identity"]:
        raise EvaluationRoleError(
            f"role {role!r} is unlabeled; use the real-unlabeled shift contract instead"
        )

    verification = verify_checkpoint_provenance_strict(
        checkpoint, manifest, allow_absent_roles=(role,)
    )
    if not verification["ok"]:
        raise EvaluationRoleError(
            f"checkpoint provenance is incomplete for role {role!r}: "
            + "; ".join(verification["failures"])
        )

    payload = load_model_manifest(manifest)
    actual_ckpt = str((payload.get("checkpoint") or {}).get("sha256") or "")
    if expected_checkpoint_sha256 and actual_ckpt.lower() != str(expected_checkpoint_sha256).lower():
        raise EvaluationRoleError(
            f"role {role!r}: checkpoint identity mismatch "
            f"(manifest={actual_ckpt} expected={expected_checkpoint_sha256})"
        )

    test_identities = (payload.get("dataset") or {}).get("test_identities") or {}
    observed = (test_identities.get(role) or {}).get("identity_sha256")
    if expected_dataset_identity_sha256:
        if observed is None:
            raise EvaluationRoleError(
                f"role {role!r}: the model manifest does not bind a dataset identity for this role"
            )
        if str(observed).lower() != str(expected_dataset_identity_sha256).lower():
            raise EvaluationRoleError(
                f"role {role!r}: dataset identity mismatch "
                f"(manifest={observed} expected={expected_dataset_identity_sha256})"
            )

    return {
        "role": role,
        "checkpoint_sha256": actual_ckpt,
        "dataset_identity_sha256": observed,
        "contract": contract,
    }


def assert_unlabeled_metrics_are_shift_only(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Reject any real-unlabeled report that carries an accuracy metric.

    Unlabeled real-world data has no ground truth. An ``mIoU`` or
    ``pixel_accuracy`` key there can only have come from a labeled set or from a
    hard-coded constant, so its presence is a claim defect regardless of value.
    """
    forbidden = {
        "mIoU",
        "miou",
        "pixel_accuracy",
        "accuracy",
        "per_class_iou",
        "iou",
        "confusion_matrix",
    }
    present = sorted(str(k) for k in payload.keys() if str(k) in forbidden)
    if present:
        raise EvaluationRoleError(
            "real_unlabeled evidence must not carry accuracy metrics "
            f"(rejected keys: {present}); only {list(REAL_UNLABELED_SHIFT_METRICS)} are permitted"
        )
    if payload.get("accuracy_metrics_available") not in (None, False):
        raise EvaluationRoleError(
            "real_unlabeled evidence declares accuracy_metrics_available=True"
        )
    return {
        "role": "real_unlabeled",
        "allowed_metrics": list(REAL_UNLABELED_SHIFT_METRICS),
        "observed_keys": sorted(str(k) for k in payload.keys()),
        "contract": evaluation_role_contract("real_unlabeled"),
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
