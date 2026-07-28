#!/usr/bin/env python3
"""CLI tool to generate gRPC bindings from .proto files.

Generated bindings are written to an ignored build directory
and are never committed to version control.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ultimate_pipeline.roadrunner.grpc_runner import run_grpc_job, GrpcJob


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate gRPC Python bindings from .proto files."
    )
    parser.add_argument(
        "--proto-dir",
        type=str,
        default=None,
        help="Root directory to search for .proto files",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for generated bindings (ignored by git)",
    )
    parser.add_argument(
        "--package",
        type=str,
        default="roadrunner",
        help="Target protobuf package name",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default="localhost:50051",
        help="gRPC endpoint (localhost only by default)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="Per-job timeout in seconds",
    )
    parser.add_argument(
        "--readonly",
        action="store_true",
        help="Dry run: do not generate bindings",
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default=None,
        help="Write job manifest JSON to this file",
    )
    args = parser.parse_args(argv)

    if args.endpoint != "localhost:50051" and not args.endpoint.startswith("127.0.0.1"):
        print("Warning: non-local endpoints are not recommended for offline use.", file=sys.stderr)

    output_dir = args.output_dir or str(Path.cwd() / ".rr_grpc_build")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    job = GrpcJob(
        job_id=args.package,
        proto_sources=(),
        target_package=args.package,
        output_directory=output_dir,
        endpoint=args.endpoint,
        timeout_seconds=args.timeout,
        readonly=args.readonly,
    )

    result = run_grpc_job(job)

    if args.manifest:
        from ultimate_pipeline.roadrunner.process_runner import RunJobManifest
        import json
        manifest_data = {
            "job_id": result.job.job_id,
            "command": list(result.job.command),
            "working_directory": result.job.working_directory,
            "env_allowlist": list(result.job.env_allowlist),
            "timeout_seconds": result.job.timeout_seconds,
            "submitted_at": result.job.submitted_at,
            "completed_at": result.job.completed_at,
            "return_code": result.job.return_code,
            "stdout_sha256": result.job.stdout_sha256,
            "stderr_sha256": result.job.stderr_sha256,
            "terminated_early": result.job.terminated_early,
            "termination_signal": result.job.termination_signal,
        }
        Path(args.manifest).write_text(
            json.dumps(manifest_data, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    if not result.success:
        print(f"Generation failed: {result.error_message}", file=sys.stderr)
        return 1

    print(f"Generated {len(result.generated_files)} binding(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())