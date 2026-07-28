"""MATLAB runner for RoadRunner automation.

All invocations use argument arrays, timeouts, and safe process
termination.  Importing this module must never require MATLAB.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .process_runner import run_process, RunResult, RunJobManifest

logger = logging.getLogger(__name__)

_DEFAULT_MATLAB_TIMEOUT = 300.0


@dataclass(frozen=True)
class MatlabJob:
    """A serialized MATLAB job targeting RoadRunner."""

    job_id: str
    script_path: str
    args: tuple[str, ...] = ()
    output_directory: str = ""
    timeout_seconds: float = _DEFAULT_MATLAB_TIMEOUT
    preserve_source: bool = True
    readonly: bool = False

    def __post_init__(self) -> None:
        if not self.script_path:
            raise ValueError("script_path must be non-empty")
        if self.preserve_source or self.readonly:
            pass  # validated at execution time


@dataclass(frozen=True)
class MatlabResult:
    """Outcome of a MATLAB execution."""

    job: MatlabJob
    success: bool
    output: str
    error_output: str
    return_code: int
    start_time: datetime
    end_time: datetime
    timed_out: bool
    log_path: Optional[str]
    manifest_hash: str


def _build_matlab_args(
    script_path: str,
    args: tuple[str, ...],
    output_directory: str,
) -> tuple[str, ...]:
    """Build the MATLAB argument array."""

    matlab_args: list[str] = ["-batch", f"run('{script_path}')"]

    if output_directory:
        matlab_args.extend(["-logoutput", output_directory])

    for arg in args:
        matlab_args.extend(["-r", arg])

    return tuple(matlab_args)


def _build_matlab_command(
    matlab_executable: str,
    script_path: str,
    args: tuple[str, ...],
    output_directory: str,
) -> tuple[str, ...]:
    """Build the full command array for MATLAB invocation."""

    cmd: list[str] = [matlab_executable]

    # Headless mode, no display, no splash.
    cmd.extend(("-nodisplay", "-nosplash", "-nodesktop"))

    # Pass script and arguments via -r flag for batch execution.
    cmd.extend(("-r", f"addpath(genpath('{os.path.dirname(script_path)}')); run('{script_path}')"))

    # Timeout will be handled by process_runner, not by MATLAB flags here.
    # We rely on process_runner's timeout and safe termination.

    return tuple(cmd)


def _write_matlab_log(
    log_dir: Path,
    job: MatlabJob,
    stdout: str,
    stderr: str,
    submitted_at: datetime,
) -> Path:
    """Save MATLAB output to a log file."""

    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = submitted_at.strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"matlab_job_{job.job_id}_{timestamp}.log"

    content = (
        f"=== MATLAB Job Log ===\n"
        f"job_id={job.job_id}\n"
        f"script={job.script_path}\n"
        f"submitted_at={submitted_at.isoformat()}\n"
        f"args={job.args}\n"
        f"preserve_source={job.preserve_source}\n"
        f"=== STDOUT ===\n"
        f"{stdout}\n"
        f"=== STDERR ===\n"
        f"{stderr}\n"
    )
    log_file.write_text(content, encoding="utf-8")
    return log_file


def run_matlab_job(
    matlab_executable: str,
    job: MatlabJob,
    *,
    env_allowlist: tuple[str, ...] = ("PATH", "HOME", "USER", "TMP", "WINDIR", "SYSTEMROOT"),
) -> MatlabResult:
    """Execute a MATLAB job targeting RoadRunner with safe process handling."""

    from .installation import probe_installation

    probe_installation()  # offline-safe probe; never imports MATLAB

    script_path = Path(job.script_path).resolve()
    if not script_path.exists():
        return MatlabResult(
            job=job,
            success=False,
            output="",
            error_output=f"MATLAB script not found: {script_path}",
            return_code=127,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            timed_out=False,
            log_path=None,
            manifest_hash="",
        )

    command = _build_matlab_command(matlab_executable, str(script_path), job.args, job.output_directory)

    start_time = datetime.now(timezone.utc)
    result = run_process(
        command,
        timeout=job.timeout_seconds,
        cwd=str(script_path.parent),
        env_allowlist=env_allowlist,
        job_id=job.job_id,
        log_directory=job.output_directory if job.output_directory else None,
    )
    end_time = datetime.now(timezone.utc)

    # Write structured log.
    log_dir = Path(job.output_directory) / "logs" if job.output_directory else Path.cwd() / "logs" / "matlab"
    log_path = _write_matlab_log(log_dir, job, result.stdout, result.stderr, start_time)

    # If source preservation is requested and an output directory was given,
    # copy the source XODR into a `source_preserved/` subdirectory.
    if job.preserve_source and job.output_directory:
        _preserve_source(script_path, Path(job.output_directory))

    manifest_hash = _hash_result(job, result)

    return MatlabResult(
        job=job,
        success=result.success,
        output=result.stdout,
        error_output=result.stderr,
        return_code=result.return_code,
        start_time=start_time,
        end_time=end_time,
        timed_out=result.timed_out,
        log_path=str(log_path),
        manifest_hash=manifest_hash,
    )


def _preserve_source(script_path: Path, output_dir: Path) -> None:
    """Copy the source MATLAB script into a preserved output subdirectory."""

    preserve_dir = output_dir / "source_preserved"
    preserve_dir.mkdir(parents=True, exist_ok=True)
    dest = preserve_dir / script_path.name
    try:
        dest.write_bytes(script_path.read_bytes())
    except OSError:
        logger.warning("Could not preserve source %s", script_path)


def _hash_result(job: MatlabJob, result: RunResult) -> str:
    """Produce a deterministic hash of the job outcome."""

    payload = json.dumps(
        {
            "job_id": job.job_id,
            "script": job.script_path,
            "args": list(job.args),
            "return_code": result.return_code,
            "timed_out": result.timed_out,
            "stdout_hash": hashlib.sha256(result.stdout.encode()).hexdigest()[:16] if result.stdout else "",
            "stderr_hash": hashlib.sha256(result.stderr.encode()).hexdigest()[:16] if result.stderr else "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]