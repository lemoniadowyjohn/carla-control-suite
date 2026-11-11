"""Fail-closed validation of required jobs in this GitHub Actions workflow run.

The `needs` context belongs to the *current* Actions run, not historical runs or
artifacts. Do not use this verdict as proof of live CARLA runtime certification.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

REQUIRED = frozenset({
    "offline-tests",
    "package-wheel-smoke",
    "governance-integrity",
    "thesis-rq-contract",
    "research-provenance",
    "offline-evidence-graph",
    "windows-single-writer",
})
SHA40 = re.compile(r"[0-9a-f]{40}\Z")


class CIGateError(ValueError):
    """Required CI evidence is missing, inconsistent, or not successful."""


def verify_needs(payload: Any, *, expected_sha: str, checkout_sha: str) -> dict[str, Any]:
    """Validate exact SHA identity and every declared mandatory predecessor.

    The only allowed dependency outcome is the literal GitHub value `success`.
    Skips, cancellations, failures, absent jobs and unknown values fail closed.
    """
    if not isinstance(expected_sha, str) or not SHA40.fullmatch(expected_sha):
        raise CIGateError("missing or invalid expected GitHub SHA")
    if not isinstance(checkout_sha, str) or not SHA40.fullmatch(checkout_sha):
        raise CIGateError("missing or invalid checked-out repository SHA")
    if checkout_sha != expected_sha:
        raise CIGateError(f"checkout SHA {checkout_sha} != workflow SHA {expected_sha}")
    if not isinstance(payload, Mapping):
        raise CIGateError("needs context must be a JSON object")
    present = set(payload)
    if present != REQUIRED:
        missing = sorted(REQUIRED - present)
        extra = sorted(present - REQUIRED)
        raise CIGateError(f"needs dependency set mismatch: missing={missing}, extra={extra}")
    bad = {}
    for name in sorted(REQUIRED):
        record = payload[name]
        if not isinstance(record, Mapping):
            bad[name] = "MALFORMED"
        else:
            status = record.get("result")
            if status != "success" or not isinstance(status, str):
                bad[name] = status if isinstance(status, str) else "MALFORMED"
    if bad:
        raise CIGateError(f"required upstream checks not successful: {bad}")
    return {
        "verdict": "PASS_OFFLINE_PREDECESSORS_ONLY",
        "workflow_sha": expected_sha,
        "required_jobs": sorted(REQUIRED),
        "runtime_certification": "NOT_RUN",
    }


def main() -> int:
    try:
        raw = os.environ.get("CI_NEEDS_JSON", "")
        needs = json.loads(raw)
        expected = os.environ.get("CI_EXPECTED_SHA", "")
        observed = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.PIPE
        ).strip()
        receipt = verify_needs(needs, expected_sha=expected, checkout_sha=observed)
    except (CIGateError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"CI_NEEDS_GATE_FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
