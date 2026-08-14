#!/usr/bin/env python3
"""Pre-run candidate-identity gate (offline GO/NO-GO).

Verifies that a candidate XODR present on disk matches an EXPECTED signed sha256
*before* a costly live CARLA certification pass is launched. Prevents wasting a
runtime window on a superseded/wrong candidate (the 80ebb00 vs 6bac3570 trap).

This tool performs digest comparison only. It does NOT import or modify the
certifier, and it does NOT decide which candidate is authoritative -- the expected
digest is always supplied by the caller.

Usage:
    python tools/verify_candidate_digest.py --xodr <path> --expected <sha256>
Exit code: 0 on match (GO), 1 otherwise (NO-GO / missing).
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Optional, Sequence, Union

PathLike = Union[str, Path]


def sha256_file(path: PathLike, _chunk: int = 1 << 20) -> str:
    """Streaming sha256 (candidate XODRs are ~80 MB)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(_chunk), b""):
            h.update(block)
    return h.hexdigest()


def verify(path: PathLike, expected: str) -> bool:
    """True iff the file exists and its sha256 equals ``expected`` (case-insensitive)."""
    p = Path(path)
    if not p.is_file():
        return False
    return sha256_file(p).lower() == expected.strip().lower()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify a candidate XODR against an expected sha256 (pre-run gate)."
    )
    ap.add_argument("--xodr", required=True, help="path to the candidate .xodr")
    ap.add_argument("--expected", required=True, help="expected full sha256 (64 hex chars)")
    args = ap.parse_args(argv)

    p = Path(args.xodr)
    if not p.is_file():
        print(f"NO-GO MISSING  {args.xodr}")
        return 1
    actual = sha256_file(p)
    if actual.lower() == args.expected.strip().lower():
        print(f"GO  {actual}  {args.xodr}")
        return 0
    print(f"NO-GO  expected={args.expected.strip().lower()}  actual={actual}  {args.xodr}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
