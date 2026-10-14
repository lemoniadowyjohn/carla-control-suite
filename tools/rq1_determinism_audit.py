#!/usr/bin/env python3
"""Attribution audit for RQ1 determinism differences.

The RQ1 matrix deliberately performs **no** normalization, so a differing raw
sha256 is a real observation and stays a FAIL.  This tool exists to answer a
different question that the matrix cannot: *which bytes differ, and can the
difference be attributed to a specific run-local input?*

It reports, per stage artifact, the raw sha256 across runs plus a
**content-normalized** sha256 computed after applying an explicit, enumerated
list of run-local substitutions.  Each rule is declared with the artifact
text it matches, so any attribution can be checked by hand against the source
files.

Normalization rules
-------------------
``sumo_provenance_comment``
    ``<!-- generated on <ts> by Eclipse SUMO netconvert ... -->``.  SUMO
    embeds its wall-clock start time and the absolute input/output paths it was
    invoked with.  Both vary per isolated run by construction.

``opendrive_header_date``
    The ``date`` attribute of the OpenDRIVE ``<header>`` element.  Written once
    by SUMO at stage 02 and carried verbatim through every later stage, so a
    single per-run timestamp propagates to the final artifact.

``geometry_freeze_hash``
    The ``geometryFreezeHash`` attribute written by the stage-06 geometry-freeze
    step.  It is a hash *of the artifact's own bytes*, which include the header
    date, so it is a transitive consequence of the two rules above rather than
    an independent source of nondeterminism.

Convergence after a rule is applied is reported as evidence about attribution
only.  It never upgrades the matrix verdict: see
``tools/rq1_five_run_matrix.py``.

Usage
-----
    python tools/rq1_determinism_audit.py <run_dir> [<run_dir> ...] [--out FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RULES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "sumo_provenance_comment",
        re.compile(rb"<!--\s*generated on .*?by Eclipse SUMO netconvert.*?-->", re.DOTALL),
    ),
    ("opendrive_header_date", re.compile(rb'(<header\b[^>]*?)\s+date="[^"]*"')),
    ("geometry_freeze_hash", re.compile(rb'\s+geometryFreezeHash="[^"]*"')),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(data: bytes, applied: list[str]) -> bytes:
    out = data
    for name, pattern in RULES:
        out, n = pattern.subn(lambda m: m.group(1) if m.lastindex else b"", out)
        if n:
            applied.append(name)
    return out


def artifact_identity(path: Path) -> str | None:
    from tools.rq1_receipt_assembler import stage_identity

    return stage_identity(path.name)


def audit_run(run_dir: Path) -> dict[str, Any]:
    stages: dict[str, dict[str, Any]] = {}
    for path in sorted(run_dir.glob("*.xodr")):
        identity = artifact_identity(path)
        if identity is None:
            continue
        data = path.read_bytes()
        applied: list[str] = []
        normalized = normalize(data, applied)
        stages[identity] = {
            "artifact": path.name,
            "bytes": len(data),
            "raw_sha256": sha256_bytes(data),
            "content_normalized_sha256": sha256_bytes(normalized),
            "normalization_rules_applied": applied,
        }
    return {"run_dir": str(run_dir), "stages": stages}


def audit_runs(run_dirs: list[Path]) -> dict[str, Any]:
    runs = [audit_run(d) for d in run_dirs]
    identities = sorted({s for r in runs for s in r["stages"]}, key=lambda s: (s[:2], s))
    stages: list[dict[str, Any]] = []
    for identity in identities:
        present = [r for r in runs if identity in r["stages"]]
        raws = [r["stages"][identity]["raw_sha256"] for r in present]
        norms = [r["stages"][identity]["content_normalized_sha256"] for r in present]
        raw_converged = len(set(raws)) == 1
        norm_converged = len(set(norms)) == 1
        rules = sorted({rule for r in present for rule in r["stages"][identity]["normalization_rules_applied"]})
        stages.append(
            {
                "stage": identity,
                "runs_present": len(present),
                "runs_missing": len(runs) - len(present),
                "distinct_raw_sha256": len(set(raws)),
                "raw_deterministic": raw_converged,
                "distinct_content_normalized_sha256": len(set(norms)),
                "content_normalized_deterministic": norm_converged,
                "attribution": (
                    "identical bytes"
                    if raw_converged
                    else (
                        f"converges after normalizing {rules}"
                        if norm_converged
                        else "DIFFERENCE NOT FULLY ATTRIBUTED"
                    )
                ),
                "per_run_raw_sha256": {str(r["run_dir"]): r["stages"][identity]["raw_sha256"] for r in present},
                "per_run_content_normalized_sha256": {
                    str(r["run_dir"]): r["stages"][identity]["content_normalized_sha256"] for r in present
                },
            }
        )
    return {
        "schema": "rq1_determinism_attribution/v1",
        "run_count": len(runs),
        "normalization_rules": [
            {"name": name, "description": desc}
            for name, desc in (
                ("sumo_provenance_comment", "SUMO netconvert generation comment: wall-clock time and absolute invocation paths"),
                ("opendrive_header_date", 'OpenDRIVE <header date="..."> written once at stage 02 and propagated forward'),
                ("geometry_freeze_hash", 'geometryFreezeHash="...": hash of the artifact\'s own bytes, hence transitive on header date'),
            )
        ],
        "verdict_note": (
            "This audit attributes byte differences. It does not and cannot change the matrix verdict: "
            "tools/rq1_five_run_matrix.py compares raw sha256 with no normalization, so a differing raw "
            "sha256 remains a FAIL there."
        ),
        "stages": stages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Attribute RQ1 determinism byte differences.")
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    missing = [d for d in args.run_dirs if not d.is_dir()]
    if missing:
        for d in missing:
            print(f"missing run dir: {d}")
        return 2

    report = audit_runs(list(args.run_dirs))
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"audit written to {args.out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
