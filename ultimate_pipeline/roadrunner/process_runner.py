"""Deterministic process runner with argument arrays, timeouts, and safe termination."""

from __future__ import annotations

import hashlib
import logging
import os
import shlex
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SENSITIVE_ENV_KEY_SUBSTRINGS = (
    "SECRET",
    "TOKEN",
    "KEY",
    "PASSWORD",
    "API_KEY",
    "AUTH",
    "CREDENTIAL",
    "PRIVATE",
)

_SAFE_ENV_PREFIXES = (
    "PATH",
    "HOME",
    "USER",
    "TMP",
    "TEMP",
    "SYSTEMROOT",
    "WINDIR",
    "PROGRAMDATA",
    "LANG",
    "LC_",
    "TERM",
    "SHELL",
)


def _is_env_safe(key: str) -> bool:
    upper = key.upper()
    for substring in _SENSITIVE_ENV_KEY_SUBSTRINGS:
        if substring in upper:
            return False
    return any(upper.startswith(prefix) for prefix in _SAFE_ENV_PREFIXES)


def _sanitize_env(env: dict[str, str]) -> dict[str, str]:
    """Return only environment variables that are safe to include in logs."""

    return {k: v for k, v in env.items() if _is_env_safe(k)}


def _redact_secrets(text: str, env: dict[str, str]) -> str:
    """Replace values of sensitive environment variables in text."""

    result = text
    for key, value in env.items():
        upper = key.upper()
        if any(sub in upper for sub in _SENSITIVE_ENV_KEY_SUBSTRINGS):
            if value and value in result:
                result = result.replace(value, "******")
    return result


@dataclass(frozen=True)
class RunJobManifest:
    """Deterministic record of a submitted job."""

    job_id: str
    command: tuple[str, ...]
    working_directory: str
    env_allowlist: tuple[str, ...]
    timeout_seconds: Optional[float]
    submitted_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    return_code: Optional[int] = None
    stdout_sha256: Optional[str] = None
    stderr_sha256: Optional[str] = None
    terminated_early: bool = False
    termination_signal: Optional[str] = None


@dataclass(frozen=True)
class RunResult:
    """Outcome of a single process execution."""

    job: RunJobManifest
    stdout: str
    stderr: str
    return_code: int
    start_time: datetime
    end_time: datetime
    timed_out: bool

    @property
    def success(self) -> bool:
        return self.return_code == 0 and not self.timed_out


def _build_env(allowlist: tuple[str, ...]) -> dict[str, str]:
    """Build a filtered environment from the current environment using the allowlist."""

    current = os.environ.copy()
    filtered: dict[str, str] = {}
    for key in allowlist:
        if key in current:
            filtered[key] = current[key]
    return filtered


def _validate_args(args: tuple[str, ...]) -> None:
    """Ensure arguments are a proper array with no shell metacharacters."""

    if not args:
        raise ValueError("command argument array must not be empty")
    for arg in args:
        if not isinstance(arg, str):
            raise TypeError(f"each argument must be a string, got {type(arg).__name__}")
        if "\x00" in arg:
            raise ValueError("arguments must not contain NUL bytes")


def _ensure_working_directory(path: str) -> Path:
    """Verify and normalize the working directory."""

    wd = Path(path).resolve()
    if not wd.exists():
        raise FileNotFoundError(f"working directory does not exist: {wd}")
    if not wd.is_dir():
        raise NotADirectoryError(f"working directory is not a directory: {wd}")
    return wd


def run_process(
    command: tuple[str, ...],
    *,
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
    env_allowlist: tuple[str, ...] = (),
    extra_env: Optional[dict[str, str]] = None,
    job_id: str = "",
    log_directory: Optional[str] = None,
) -> RunResult:
    """Execute a command with argument arrays, timeout, and safe termination.

    Parameters
    ----------
    command:
        Tuple of program path and arguments.  Never concatenated into a shell string.
    timeout:
        Maximum wall-clock seconds before the process is terminated.
    cwd:
        Working directory for the subprocess.
    env_allowlist:
        Names of environment variables to pass through.
    extra_env:
        Additional environment variables to inject.
    job_id:
        Identifier recorded in the deterministic job manifest.
    log_directory:
        Directory where stdout/stderr snapshots may be written.
    """

    _validate_args(command)
    wd = _ensure_working_directory(cwd or ".")
    env = _build_env(env_allowlist)
    if extra_env:
        env.update(extra_env)

    submitted_at = datetime.now(timezone.utc)
    manifest = RunJobManifest(
        job_id=job_id or shlex.join(command),
        command=command,
        working_directory=str(wd),
        env_allowlist=tuple(sorted(env.keys())),
        timeout_seconds=timeout,
        submitted_at=submitted_at.isoformat(),
    )

    start_time = datetime.now(timezone.utc)
    logger.info("Starting job %s: %s", manifest.job_id, command)
    logger.info("Safe env keys: %s", tuple(sorted(env.keys())))

    timed_out = False
    termination_signal: Optional[str] = None
    proc: subprocess.Popen[str] | None = None

    try:
        proc = subprocess.Popen(  # noqa: S603
            command,
            cwd=str(wd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        manifest_job_started = manifest
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            termination_signal = "SIGTERM"
            logger.warning("Job %s timed out after %s seconds", manifest.job_id, timeout)
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = proc.communicate(timeout=5.0)
            except subprocess.TimeoutExpired:
                termination_signal = "SIGKILL"
                logger.warning("Job %s did not exit after SIGTERM; sending SIGKILL", manifest.job_id)
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                stdout = ""
                stderr = ""
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    pass

        return_code = proc.returncode if proc.poll() is not None else -1
    except OSError as exc:
        return_code = 127
        stdout = ""
        stderr = f"Failed to start process: {exc}"
        timed_out = False
    finally:
        end_time = datetime.now(timezone.utc)

    if log_directory and Path(log_directory).is_dir():
        _write_log_snapshots(
            Path(log_directory),
            manifest.job_id,
            stdout or "",
            stderr or "",
            submitted_at,
            end_time,
        )

    stdout_clean = _redact_secrets(stdout or "", env)
    stderr_clean = _redact_secrets(stderr or "", env)

    stdout_sha = ""
    stderr_sha = ""
    if stdout_clean:
        stdout_sha = hashlib.sha256(stdout_clean.encode("utf-8")).hexdigest()[:16]
    if stderr_clean:
        stderr_sha = hashlib.sha256(stderr_clean.encode("utf-8")).hexdigest()[:16]

    completed_manifest = RunJobManifest(
        job_id=manifest.job_id,
        command=manifest.command,
        working_directory=manifest.working_directory,
        env_allowlist=manifest.env_allowlist,
        timeout_seconds=manifest.timeout_seconds,
        submitted_at=manifest.submitted_at,
        started_at=start_time.isoformat(),
        completed_at=end_time.isoformat(),
        return_code=return_code,
        stdout_sha256=stdout_sha or None,
        stderr_sha256=stderr_sha or None,
        terminated_early=timed_out,
        termination_signal=termination_signal,
    )

    logger.info("Job %s completed: return_code=%s timed_out=%s", completed_manifest.job_id, return_code, timed_out)

    return RunResult(
        job=completed_manifest,
        stdout=stdout_clean,
        stderr=stderr_clean,
        return_code=return_code,
        start_time=start_time,
        end_time=end_time,
        timed_out=timed_out,
    )


def _write_log_snapshots(
    log_dir: Path,
    job_id: str,
    stdout: str,
    stderr: str,
    submitted_at: datetime,
    completed_at: datetime,
) -> None:
    """Write stdout and stderr snapshots to a log directory."""

    safe_id = job_id.replace("/", "_").replace("\\", "_")[:64]
    base = log_dir / f"job_{safe_id}_{submitted_at.strftime('%Y%m%d_%H%M%S')}"
    base.mkdir(parents=True, exist_ok=True)

    (base / "stdout.txt").write_text(stdout, encoding="utf-8")
    (base / "stderr.txt").write_text(stderr, encoding="utf-8")

    manifest_lines = [
        f"job_id={job_id}",
        f"submitted_at={submitted_at.isoformat()}",
        f"completed_at={completed_at.isoformat()}",
    ]
    (base / "manifest.txt").write_text("\n".join(manifest_lines), encoding="utf-8")