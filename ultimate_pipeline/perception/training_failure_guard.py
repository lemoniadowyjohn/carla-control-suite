#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/training_failure_guard.py

CD-4 remediation: explicit, fail-closed handling of the failure modes that
previously let *incomplete* training runs look valid.

Before this module, the training loop had no ``try``/``except`` around the
epoch body at all:

* a CUDA OOM killed the process after some epochs had already been written to
  disk -- the checkpoints stayed on disk and looked like a normal run;
* a NaN/Inf loss produced a checkpoint whose weights were garbage but whose
  filename and manifest looked authoritative;
* a full disk produced a truncated ``.pt`` file that still loaded;
* a DataLoader worker crash surfaced as an opaque exception after the run had
  already been partially recorded.

Every one of those could leave evidence that reads as "training completed".

This module provides the guard primitives:

* :func:`is_finite_loss` / :func:`assert_finite_loss` -- NaN/Inf detection.
* :func:`require_free_disk` -- disk-space precondition before a checkpoint is
  written (fail *before* the write, not after the truncation).
* :func:`atomic_torch_save` -- checkpoint writes go to a temporary file that is
  fsync'ed and then atomically renamed, so a failed write can never leave a
  truncated checkpoint at the authoritative path.
* :func:`is_cuda_oom` -- classification of an exception as an out-of-memory
  condition (including the "out of memory" RuntimeError variants).
* :class:`TrainingFailure` -- the single status carrier; a failure always
  carries an explicit, machine-readable ``status`` and never a success.

The statuses are stable strings so downstream evidence can distinguish
"training aborted because of OOM" from "training completed".
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

#: Stable failure statuses (never numeric, never silently ignored).
STATUS_CUDA_OOM = "TRAINING_ABORTED_CUDA_OOM"
STATUS_NAN_LOSS = "TRAINING_ABORTED_NAN_LOSS"
STATUS_DISK_FULL = "TRAINING_ABORTED_DISK_FULL"
STATUS_CHECKPOINT_WRITE_FAILED = "TRAINING_ABORTED_CHECKPOINT_WRITE_FAILED"
STATUS_WORKER_CRASH = "TRAINING_ABORTED_WORKER_CRASH"
STATUS_DATASET_READ_CORRUPT = "TRAINING_ABORTED_DATASET_READ_CORRUPT"
STATUS_OK = "TRAINING_COMPLETED"

#: Default minimum free space required before a checkpoint is written.
DEFAULT_MIN_FREE_DISK_BYTES = 512 * 1024 * 1024  # 512 MiB


class TrainingFailure(RuntimeError):
    """Raised when training cannot continue. Carries an explicit status."""

    def __init__(self, status: str, message: str, *, detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status = str(status)
        self.message = str(message)
        self.detail = dict(detail or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "detail": dict(self.detail),
        }


def is_cuda_oom(exc: BaseException) -> bool:
    """
    True when ``exc`` denotes a CUDA out-of-memory condition.

    Torch raises ``torch.cuda.OutOfMemoryError`` (a subclass of RuntimeError)
    for allocator failures, but several code paths raise a plain RuntimeError
    with an "out of memory" message instead, and multi-process launches surface
    it as a generic worker exception. Both must be classified as OOM so the
    run is not mistaken for an unrelated crash.
    """
    try:
        import torch

        oom_types = tuple(
            t
            for t in (
                getattr(torch.cuda, "OutOfMemoryError", None),
                getattr(torch, "OutOfMemoryError", None),
            )
            if isinstance(t, type)
        )
        if oom_types and isinstance(exc, oom_types):
            return True
    except Exception:  # pragma: no cover - torch always importable in practice
        pass
    text = str(exc).lower()
    return ("out of memory" in text) or ("cuda oom" in text) or ("cublas_status_alloc_failed" in text)


def is_finite_loss(loss: Any) -> bool:
    """True when the loss tensor carries a finite value."""
    try:
        import torch

        if isinstance(loss, torch.Tensor):
            return bool(torch.isfinite(loss.detach()).all().item())
    except Exception:  # pragma: no cover
        pass
    try:
        value = float(loss)
    except (TypeError, ValueError):
        return False
    return value == value and value not in (float("inf"), float("-inf"))


def assert_finite_loss(loss: Any, *, epoch: int, step: int) -> None:
    """Raise :class:`TrainingFailure` (NaN status) for a non-finite loss."""
    if not is_finite_loss(loss):
        raise TrainingFailure(
            STATUS_NAN_LOSS,
            f"non-finite loss at epoch {epoch} step {step}: {loss!r}",
            detail={"epoch": int(epoch), "step": int(step)},
        )


def require_free_disk(target: Any, *, min_free_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES) -> int:
    """
    Ensure the filesystem hosting ``target`` has at least ``min_free_bytes`` free.

    Returns the observed free bytes. Raises :class:`TrainingFailure` with the
    disk-full status *before* any checkpoint write is attempted, so a truncated
    checkpoint can never be produced.
    """
    path = Path(target)
    probe = path if path.exists() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(str(probe))
    except OSError as exc:  # pragma: no cover - unusual filesystem states
        raise TrainingFailure(
            STATUS_DISK_FULL,
            f"cannot determine free disk space for {probe}: {exc}",
            detail={"path": str(probe)},
        ) from exc
    if usage.free < int(min_free_bytes):
        raise TrainingFailure(
            STATUS_DISK_FULL,
            (
                f"insufficient free disk space for checkpoint: free={usage.free} "
                f"required={int(min_free_bytes)}"
            ),
            detail={
                "free_bytes": int(usage.free),
                "required_bytes": int(min_free_bytes),
                "path": str(probe),
            },
        )
    return int(usage.free)


def atomic_torch_save(state: Any, target: Any) -> Path:
    """
    Write a torch checkpoint atomically.

    The payload is written to a temporary file in the destination directory,
    flushed and fsync'ed, and only then renamed onto the authoritative path.
    A crash or a full disk therefore leaves either the previous checkpoint or
    no checkpoint at all -- never a truncated file that still loads.
    """
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    import torch

    handle, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    os.close(handle)
    tmp_path = Path(tmp_name)
    try:
        with open(tmp_path, "wb") as fh:
            torch.save(state, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp_path), str(path))
    except OSError as exc:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise TrainingFailure(
            STATUS_CHECKPOINT_WRITE_FAILED,
            f"checkpoint write failed for {path}: {exc}",
            detail={"path": str(path), "error": str(exc)},
        ) from exc
    except Exception as exc:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise TrainingFailure(
            STATUS_CHECKPOINT_WRITE_FAILED,
            f"checkpoint write failed for {path}: {exc}",
            detail={"path": str(path), "error": str(exc)},
        ) from exc
    return path


def classify_exception(exc: BaseException, *, epoch: int = -1) -> TrainingFailure:
    """
    Map an arbitrary training exception onto a :class:`TrainingFailure` with a
    stable status. Unclassified exceptions become a dataset/read failure when
    they look like a decoding error, and otherwise a generic worker crash.
    """
    if isinstance(exc, TrainingFailure):
        return exc
    if is_cuda_oom(exc):
        return TrainingFailure(
            STATUS_CUDA_OOM,
            f"CUDA out of memory during training: {exc}",
            detail={"epoch": int(epoch), "error": str(exc)},
        )
    text = str(exc).lower()
    if any(
        marker in text
        for marker in (
            "cannot decode image",
            "truncated image",
            "unidentifiedimageerror",
            "cannot identify image file",
            "image file is truncated",
        )
    ):
        return TrainingFailure(
            STATUS_DATASET_READ_CORRUPT,
            f"dataset read/decode failure during training: {exc}",
            detail={"epoch": int(epoch), "error": str(exc)},
        )
    return TrainingFailure(
        STATUS_WORKER_CRASH,
        f"training aborted by an unhandled exception: {exc}",
        detail={"epoch": int(epoch), "error": str(exc)},
    )
