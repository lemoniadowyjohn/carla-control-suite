# ultimate_pipeline/tiling/carla_0916_import_process_contract.py
# -*- coding: utf-8 -*-
"""CARLA 0.9.16 import/cook mandatory child-process contract (NEW-196).

Fail-closed execution wrapper for every mandatory Unreal commandlet / import /
cook child process. Closes the V4 finding where the Windows path used checked
execution while the POSIX path used ``subprocess.call()`` with the return
value unenforced, allowing downstream stages (asset movement, map
preparation, material loading, Traffic Manager generation, cook
certification, runtime acceptance) to proceed after a commandlet failure.

Both platform branches (``windows`` / ``posix`` / ``auto``) enforce the same
receipt + fail-closed semantics; the platform switch only selects *how* the
child is spawned, never *whether* its result is checked.

Required receipt per process::

    {"command": [], "cwd": "...", "started_at_utc": "...",
     "finished_at_utc": "...", "returncode": 0,
     "stdout_path": "...", "stderr_path": "...", "status": "PASS"}

Statuses: PASS | FAIL | TIMEOUT | SPAWN_ERROR | CANCELLED | OUTPUT_MISSING.
No unknown state may become PASS. Any mandatory failure raises :class:`ImportProcessError`
so callers cannot proceed downstream.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

ALLOWED_STATUSES = ("PASS", "FAIL", "TIMEOUT", "SPAWN_ERROR", "CANCELLED", "OUTPUT_MISSING")


class ImportProcessError(RuntimeError):
    """Raised when a mandatory import/cook child process fails closed."""

    def __init__(self, message: str, *, receipt: Optional[Dict] = None) -> None:
        super().__init__(message)
        self.receipt = receipt or {}


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


@dataclass
class ImportProcessResult:
    status: str
    command: List[str]
    cwd: str
    started_at_utc: str
    finished_at_utc: str
    returncode: Optional[int]
    stdout_path: str = ""
    stderr_path: str = ""
    reason: str = ""
    expected_outputs: List[str] = field(default_factory=list)
    missing_outputs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "argv": list(self.command),
            "command": list(self.command),
            "cwd": self.cwd,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "returncode": self.returncode,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "status": self.status,
            "reason": self.reason,
            "expected_outputs": list(self.expected_outputs),
            "missing_outputs": list(self.missing_outputs),
        }


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_mandatory_process(
    command: Sequence[str],
    *,
    cwd: Optional[str] = None,
    timeout_s: Optional[float] = None,
    expected_outputs: Optional[Sequence[str]] = None,
    expected_output_hashes: Optional[Dict[str, str]] = None,
    log_dir: Optional[str] = None,
    platform: str = "auto",
    runner: Optional[Callable] = None,
    cancelled: bool = False,
) -> ImportProcessResult:
    """Run one mandatory import/cook child process, fail-closed.

    Args:
        command: argv to execute (must be non-empty).
        cwd: working directory (defaults to os.getcwd()).
        timeout_s: optional timeout in seconds.
        expected_outputs: files that must exist after a returncode-0 run.
        expected_output_hashes: optional ``{path: sha256}`` map; a present
            but content-mismatched output (fake/stale artifact) also fails.
        log_dir: directory for captured stdout/stderr files.
        platform: "auto" | "windows" | "posix". Both branches enforce the
            result; the branch only changes spawn mechanics.
        runner: injectable ``subprocess.run``-compatible callable for tests.
        cancelled: when True, immediately return CANCELLED without spawning.

    Returns:
        ImportProcessResult with status PASS on full success.

    Raises:
        ImportProcessError: on any mandatory failure (FAIL/TIMEOUT/
            SPAWN_ERROR/CANCELLED/missing output). The receipt is attached
        as ``err.receipt`` and also returned via ``err.receipt`` dict.
    """
    cmd = [str(c) for c in command]
    workdir = str(cwd) if cwd else os.getcwd()
    expected = [str(p) for p in (expected_outputs or [])]
    for hashed_path in (expected_output_hashes or {}):
        if str(hashed_path) not in expected:
            expected.append(str(hashed_path))
    started = _utc_now_iso()
    logs = Path(log_dir) if log_dir else Path(tempfile.mkdtemp(prefix="import_proc_"))
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path = str(logs / "stdout.log")
    stderr_path = str(logs / "stderr.log")

    def _fail(status: str, returncode: Optional[int], reason: str,
              missing: Optional[List[str]] = None) -> ImportProcessResult:
        result = ImportProcessResult(
            status=status, command=cmd, cwd=workdir,
            started_at_utc=started, finished_at_utc=_utc_now_iso(),
            returncode=returncode, stdout_path=stdout_path,
            stderr_path=stderr_path, reason=reason,
            expected_outputs=expected, missing_outputs=missing or [],
        )
        _write_text(Path(stdout_path), "")
        _write_text(Path(stderr_path), reason)
        return result

    if platform not in ("auto", "windows", "posix"):
        result = _fail("FAIL", None, f"unknown platform branch: {platform!r}")
        raise ImportProcessError(result.reason, receipt=result.to_dict())

    if cancelled:
        result = _fail("CANCELLED", None, "cancelled before spawn")
        raise ImportProcessError(result.reason, receipt=result.to_dict())

    if not cmd:
        result = _fail("FAIL", None, "empty command")
        raise ImportProcessError(result.reason, receipt=result.to_dict())

    exe = cmd[0]
    # Absolute-path executables must exist; bare names are resolved via PATH.
    if os.path.isabs(exe) or os.sep in exe or (os.altsep and os.altsep in exe):
        if not Path(exe).is_file():
            result = _fail("SPAWN_ERROR", None, f"missing executable: {exe}")
            raise ImportProcessError(result.reason, receipt=result.to_dict())
    elif runner is None and shutil.which(exe) is None:
        result = _fail("SPAWN_ERROR", None, f"missing executable on PATH: {exe}")
        raise ImportProcessError(result.reason, receipt=result.to_dict())

    run_fn = runner or subprocess.run
    try:
        if platform == "windows":
            # Checked execution branch (historical Windows path), now explicit.
            completed = run_fn(cmd, cwd=workdir, capture_output=True, text=True,
                               timeout=timeout_s, check=False)
        elif platform == "posix":
            # Historical POSIX path used subprocess.call() unchecked; this
            # contract enforces the return value on this branch too.
            completed = run_fn(cmd, cwd=workdir, capture_output=True, text=True,
                               timeout=timeout_s, check=False)
        else:
            completed = run_fn(cmd, cwd=workdir, capture_output=True, text=True,
                               timeout=timeout_s, check=False)
        _write_text.last_stdout = getattr(completed, "stdout", "") or ""
        _write_text.last_stderr = getattr(completed, "stderr", "") or ""
        returncode = getattr(completed, "returncode", None)
    except FileNotFoundError as exc:
        _write_text.last_stdout = ""
        _write_text.last_stderr = str(exc)
        result = _fail("SPAWN_ERROR", None, f"spawn error: {exc}")
        raise ImportProcessError(result.reason, receipt=result.to_dict()) from exc
    except subprocess.TimeoutExpired as exc:
        _write_text.last_stdout = ""
        _write_text.last_stderr = f"timeout after {timeout_s}s: {exc}"
        result = _fail("TIMEOUT", None, f"timeout after {timeout_s}s")
        raise ImportProcessError(result.reason, receipt=result.to_dict()) from exc
    except Exception as exc:
        _write_text.last_stdout = ""
        _write_text.last_stderr = f"{type(exc).__name__}: {exc}"
        result = _fail("SPAWN_ERROR", None, f"spawn error: {type(exc).__name__}: {exc}")
        raise ImportProcessError(result.reason, receipt=result.to_dict()) from exc

    _write_text(Path(stdout_path), _write_text.last_stdout)
    _write_text(Path(stderr_path), _write_text.last_stderr)

    if returncode != 0:
        result = ImportProcessResult(
            status="FAIL", command=cmd, cwd=workdir,
            started_at_utc=started, finished_at_utc=_utc_now_iso(),
            returncode=returncode, stdout_path=stdout_path,
            stderr_path=stderr_path,
            reason=f"non-zero exit: {returncode}",
            expected_outputs=expected,
        )
        raise ImportProcessError(result.reason, receipt=result.to_dict())

    missing = [p for p in expected if not Path(p).exists()]
    if missing:
        result = ImportProcessResult(
            status="OUTPUT_MISSING", command=cmd, cwd=workdir,
            started_at_utc=started, finished_at_utc=_utc_now_iso(),
            returncode=returncode, stdout_path=stdout_path,
            stderr_path=stderr_path,
            reason=f"required output absent: {missing}",
            expected_outputs=expected, missing_outputs=missing,
        )
        raise ImportProcessError(result.reason, receipt=result.to_dict())

    # Fake/stale output: a present file with wrong content must also stop
    # the sequence (hash-bound freshness, defense against stale artifacts
    # from a previous run being mistaken for this run's output).
    hash_mismatch: List[str] = []
    for hashed_path, want_sha in (expected_output_hashes or {}).items():
        try:
            got_sha = _sha256_file(Path(hashed_path))
        except OSError as exc:
            raise ImportProcessError(
                f"required output unreadable: {hashed_path}: {exc}",
                receipt=ImportProcessResult(
                    status="OUTPUT_MISSING", command=cmd, cwd=workdir,
                    started_at_utc=started, finished_at_utc=_utc_now_iso(),
                    returncode=returncode, stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    reason=f"required output unreadable: {hashed_path}",
                    expected_outputs=expected,
                    missing_outputs=[str(hashed_path)]).to_dict()) from exc
        if got_sha.lower() != str(want_sha).lower():
            hash_mismatch.append(f"{hashed_path}: got {got_sha}, want {want_sha}")
    if hash_mismatch:
        result = ImportProcessResult(
            status="FAIL", command=cmd, cwd=workdir,
            started_at_utc=started, finished_at_utc=_utc_now_iso(),
            returncode=returncode, stdout_path=stdout_path,
            stderr_path=stderr_path,
            reason=f"required output content mismatch (fake/stale): {hash_mismatch}",
            expected_outputs=expected, missing_outputs=hash_mismatch,
        )
        raise ImportProcessError(result.reason, receipt=result.to_dict())

    return ImportProcessResult(
        status="PASS", command=cmd, cwd=workdir,
        started_at_utc=started, finished_at_utc=_utc_now_iso(),
        returncode=returncode, stdout_path=stdout_path,
        stderr_path=stderr_path, reason="",
        expected_outputs=expected,
    )


def run_import_sequence(
    steps: Sequence[Dict],
    *,
    log_dir: Optional[str] = None,
    platform: str = "auto",
    runner: Optional[Callable] = None,
) -> Dict:
    """Run an ordered mandatory sequence; stop at the first failure.

    Each step is ``{"command": [...], "cwd": ..., "timeout_s": ...,
    "expected_outputs": [...], "expected_output_hashes": {...},
    "name": ...}``. Returns
    ``{"status": "PASS"|"FAIL", "receipts": [...], "failed_step": ...}``.
    Downstream steps never execute after a mandatory failure.
    """
    receipts: List[Dict] = []
    base = Path(log_dir) if log_dir else Path(tempfile.mkdtemp(prefix="import_seq_"))
    for idx, step in enumerate(steps):
        name = str(step.get("name", f"step_{idx}"))
        step_log = str(base / f"{idx:02d}_{name}")
        try:
            result = run_mandatory_process(
                step.get("command", []),
                cwd=step.get("cwd"),
                timeout_s=step.get("timeout_s"),
                expected_outputs=step.get("expected_outputs"),
                expected_output_hashes=step.get("expected_output_hashes"),
                log_dir=step_log,
                platform=step.get("platform", platform),
                runner=step.get("runner", runner),
                cancelled=bool(step.get("cancelled", False)),
            )
            receipts.append({"name": name, **result.to_dict()})
        except ImportProcessError as exc:
            receipts.append({"name": name, **dict(exc.receipt)})
            return {"status": "FAIL", "receipts": receipts, "failed_step": name}
    return {"status": "PASS", "receipts": receipts, "failed_step": None}
