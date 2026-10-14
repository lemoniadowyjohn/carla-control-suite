#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Governed signal persistence (NEW-349).

Every artifact registered in :mod:`ultimate_pipeline.signals.registry` must be
written through :func:`write_governed_signal`.  A bare ``open() + json.dump()``
that can half-succeed, be silently swallowed by a ``try/except: pass``, or be
skipped entirely is exactly how a signal becomes dead: the consumer reads a
file that was never durably produced and reports PASS from its absence.

Guarantees:

* **atomic** -- written to a same-directory temp file, flushed, ``fsync``-ed and
  ``os.replace``-d, so a reader never observes a partial artifact;
* **verified** -- the bytes on disk are re-read and re-parsed before the write
  is reported as successful;
* **fail-closed** -- a persistence failure for a governed signal is recorded in
  a process-local :class:`PersistenceFailure` ledger *and* raised, so it can be
  neither ignored nor logged-and-continued into a PASS verdict.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "SignalPersistenceError",
    "PersistenceFailure",
    "record_persistence_failure",
    "persistence_failures",
    "clear_persistence_failures",
    "has_persistence_failures",
    "write_governed_signal",
]


class SignalPersistenceError(RuntimeError):
    """A governed signal artifact could not be durably persisted."""


@dataclass(frozen=True)
class PersistenceFailure:
    signal_id: str
    path: str
    error: str
    timestamp_utc: str

    def to_dict(self) -> dict[str, str]:
        return {
            "signal_id": self.signal_id,
            "path": self.path,
            "error": self.error,
            "timestamp_utc": self.timestamp_utc,
        }


_FAILURES: list[PersistenceFailure] = []


def record_persistence_failure(signal_id: str, path: str, error: str) -> None:
    _FAILURES.append(
        PersistenceFailure(
            signal_id=str(signal_id),
            path=str(path),
            error=str(error),
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )
    )


def persistence_failures() -> list[dict[str, str]]:
    return [f.to_dict() for f in _FAILURES]


def clear_persistence_failures() -> None:
    _FAILURES.clear()


def has_persistence_failures() -> bool:
    return bool(_FAILURES)


def write_governed_signal(
    path: str | os.PathLike[str],
    payload: Any,
    *,
    signal_id: str,
    expect_json: bool = True,
    encoding: str = "utf-8",
) -> str:
    """Atomically persist ``payload`` as ``signal_id``'s artifact.

    Returns the absolute path written.  Raises
    :class:`SignalPersistenceError` (after recording the failure) when the
    artifact cannot be durably written *and* read back.
    """
    target = Path(path)
    error: str | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if expect_json:
            text = json.dumps(payload, indent=2, ensure_ascii=True, default=str)
            if not text.endswith("\n"):
                text += "\n"
        else:
            text = str(payload)

        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(tmp), str(target))
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

        # Verify: the artifact must be readable and re-parseable, otherwise a
        # consumer would later read garbage and report whatever it guesses.
        if expect_json:
            json.loads(target.read_text(encoding=encoding))
        else:
            if not target.is_file() or target.stat().st_size == 0:
                raise OSError("non-JSON signal artifact is empty after write")
    except BaseException as exc:  # noqa: BLE001 - re-raised below, never swallowed
        error = f"{type(exc).__name__}: {exc}"

    if error is not None:
        record_persistence_failure(signal_id, str(target), error)
        raise SignalPersistenceError(
            f"signal {signal_id} could not be persisted to {target}: {error}"
        )
    return str(target)


def write_governed_signal_quiet(
    path: str | os.PathLike[str],
    payload: Any,
    *,
    signal_id: str,
) -> str | None:
    """Best-effort variant used only where a producer must not raise.

    The failure is still recorded in the persistence ledger, so it surfaces in
    ``final_run_verdict.json`` as a blocking evidence-persistence failure
    instead of disappearing.
    """
    try:
        return write_governed_signal(path, payload, signal_id=signal_id)
    except SignalPersistenceError:
        return None
