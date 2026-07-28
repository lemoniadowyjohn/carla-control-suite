"""gRPC runner for RoadRunner with offline-safe, no-vendor-bindings policy.

Generated protobuf bindings must NEVER be committed.  All bindings are
generated from installed .proto files into an ignored build directory at
runtime.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .process_runner import run_process, RunResult

logger = logging.getLogger(__name__)

_GRPC_BUILD_DIR_NAME = ".rr_grpc_build"
_DEFAULT_ENDPOINT = "localhost:50051"
_DEFAULT_TIMEOUT_SECONDS = 30.0

_PROTO_SUFFIXES = (".proto",)


def _determine_build_dir(root: Optional[str] = None) -> Path:
    """Return the ignored build directory for generated gRPC bindings."""

    base = Path(root) if root else Path.cwd()
    build_dir = base / _GRPC_BUILD_DIR_NAME
    build_dir.mkdir(parents=True, exist_ok=True)
    return build_dir


@dataclass(frozen=True)
class ProtoSource:
    """A single .proto file reference."""

    path: str
    sha256: str


@dataclass(frozen=True)
class GrpcJob:
    """A serialized, deterministic mutating gRPC job."""

    job_id: str
    proto_sources: tuple[ProtoSource, ...]
    target_package: str
    output_directory: str
    endpoint: str
    timeout_seconds: float
    readonly: bool = False

    def __post_init__(self) -> None:
        if self.readonly and self.proto_sources:
            raise ValueError("readonly jobs must have no proto sources")
        if not self.target_package:
            raise ValueError("target_package must be non-empty")


@dataclass(frozen=True)
class GrpcResult:
    """Outcome of a gRPC build job."""

    job: GrpcJob
    success: bool
    generated_files: tuple[str, ...]
    error_message: Optional[str]
    start_time: str
    end_time: str
    manifest_hash: str


def _hash_manifest(job: GrpcJob) -> str:
    """Produce a deterministic hash of the job manifest."""

    payload = (
        f"{job.job_id}|{job.target_package}|{job.endpoint}|"
        f"{job.timeout_seconds}|{job.readonly}|"
        + "|".join(f"{s.path}:{s.sha256}" for s in job.proto_sources)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _locate_proto_files(root: Optional[str] = None) -> tuple[ProtoSource, ...]:
    """Find .proto files under the given root."""

    base = Path(root).resolve() if root else Path.cwd()
    sources: list[ProtoSource] = []
    if not base.exists():
        return tuple(sources)

    for path in sorted(base.rglob("*")):
        if path.suffix not in _PROTO_SUFFIXES:
            continue
        if not path.is_file():
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            sources.append(ProtoSource(path=str(path.resolve()), sha256=digest))
        except OSError:
            continue

    return tuple(sources)


def _generate_bindings(
    proto_sources: tuple[ProtoSource, ...],
    build_dir: Path,
    target_package: str,
) -> tuple[str, ...]:
    """Generate Python gRPC bindings from .proto files.

    This function invokes `grpc_tools_protoc` if available.  It does not
    guess or commit generated vendor bindings.  All output goes to the
    ignored build directory.
    """

    if not proto_sources:
        return ()

    protoc_cmd = _find_protoc_command(proto_sources, build_dir, target_package)
    if protoc_cmd is None:
        return ()

    result = run_process(
        protoc_cmd,
        timeout=600.0,
        env_allowlist=("PATH", "SYSTEMROOT", "WINDIR", "GOPATH"),
        job_id=f"grpc_generate_{target_package}",
        log_directory=str(build_dir.parent),
    )

    if result.return_code != 0:
        logger.error("protoc failed: %s", result.stderr[:500])
        return ()

    generated: list[str] = []
    for candidate in build_dir.rglob("*"):
        if candidate.is_file() and candidate.suffix in (".py",):
            try:
                generated.append(str(candidate.resolve()))
            except OSError:
                continue

    return tuple(sorted(generated))


def _find_protoc_command(
    proto_sources: tuple[ProtoSource, ...],
    build_dir: Path,
    target_package: str,
) -> tuple[str, ...] | None:
    """Build the protoc argument array.

    Returns None if grpc_tools_protoc is not importable.
    """

    try:
        import grpc_tools  # noqa: F401
    except ImportError:
        return None

    protoc = sys.executable
    args = [
        protoc,
        "-m",
        "grpc_tools.protoc",
    ]

    proto_paths = set()
    for src in proto_sources:
        proto_paths.add(str(Path(src.path).parent))
    for p in sorted(proto_paths):
        args.extend(("--proto_path", p))

    args.extend(("--python_out", str(build_dir)))
    args.extend(("--grpc_python_out", str(build_dir)))

    for src in proto_sources:
        args.append(src.path)

    return tuple(args)


def run_grpc_job(job: GrpcJob) -> GrpcResult:
    """Execute a serialized, deterministic gRPC job.

    The endpoint defaults to localhost only.  All generated bindings go
    into the ignored build directory.
    """

    from .installation import probe_installation

    start_time = datetime.datetime.now(datetime.timezone.utc)

    report = probe_installation()
    if not report.grpc_proto_files:
        proto_sources = _locate_proto_files(job.output_directory)
    else:
        proto_sources = tuple(
            ProtoSource(path=p, sha256="") for p in report.grpc_proto_files
        )

    # Resolve actual hashes for any proto sources that exist on disk.
    resolved_sources: list[ProtoSource] = []
    for src in proto_sources:
        p = Path(src.path)
        if p.exists() and p.is_file():
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            resolved_sources.append(ProtoSource(path=str(p.resolve()), sha256=digest))

    proto_sources = tuple(resolved_sources)

    if not proto_sources:
        return GrpcResult(
            job=job,
            success=False,
            generated_files=(),
            error_message="No .proto source files found",
            start_time=start_time.isoformat(),
            end_time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            manifest_hash=_hash_manifest(job),
        )

    build_dir = _determine_build_dir(job.output_directory)
    generated_files = _generate_bindings(proto_sources, build_dir, job.target_package)

    end_time = datetime.datetime.now(datetime.timezone.utc)

    return GrpcResult(
        job=job,
        success=bool(generated_files),
        generated_files=generated_files,
        error_message=None if generated_files else "No .py bindings generated",
        start_time=start_time.isoformat(),
        end_time=end_time.isoformat(),
        manifest_hash=_hash_manifest(job),
    )