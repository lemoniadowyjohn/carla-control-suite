"""Build an RQ1 five-run determinism matrix from explicit run receipt files.

Comparability gate
------------------
The matrix compares *replication* determinism, so every receipt must describe
the same experiment.  A receipt is admissible only when all of the following
hold, and each violated condition is reported as its own reason:

* it parses as JSON;
* its ``schema`` is the expected ``rq1_run_receipt/v2`` (v1 receipts use a
  different stage keying and a different junction metric, so mixing them
  silently compares different quantities);
* the pipeline recorded a terminal state (a receipt for a run that stopped
  mid-pipeline cannot witness end-to-end determinism);
* it reached the same ``terminal_stage`` as its peers.

When fewer than five admissible receipts remain, the verdict is INCOMPLETE.
This is deliberate: a matrix that silently averages over a crashed run and four
complete runs reports a mismatch between an artifact and a crash, not a
determinism defect.

Comparison policy
-----------------
No normalization.  Raw sha256, structural signature and topology counts are
compared as measured.  ``output_path`` and ``out_dir`` are deliberately NOT
compared: each isolated run writes to its own timestamped directory, so they
are guaranteed to differ and carry no determinism signal.  Profiling tools that
want to inspect timestamp-driven byte differences should run
``tools/rq1_determinism_audit.py``, which reports raw and attribution data side
by side without altering the verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "rq1_run_receipt/v2"

# Identity/observability fields. Compared for determinism only where the
# quantity is a property of the map rather than of the run's location.
COMPARED_KEYS = (
    "xodr_sha256",
    "normalized_xodr_sha256",
    "structural_signature",
    "feature_counts",
    "topology_counts",
    "tileset_digest",
    "map_acceptance_digest",
    "final_receipt_digest",
)

COMPARISON_POLICY = (
    "No normalization of any field. Raw sha256, structural signature and topology counts are "
    "compared as measured. output_path/out_dir/run are excluded: isolated runs write to distinct "
    "timestamped directories, so those fields cannot match and carry no determinism signal. "
    "Receipts are comparable only when schema, pipeline terminal state and terminal_stage agree; "
    "any deviation yields INCOMPLETE rather than a PASS or FAIL."
)

# A run may only witness replication determinism if it recorded a successful
# terminal state. "running" means the process never terminated; "failed" means it
# terminated early. Neither describes a completed replication.
TERMINAL_SUCCESS_STATES = frozenset({"ok", "success", "completed", "complete", "finished", "passed"})


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _admissibility(data: dict[str, Any]) -> list[str]:
    """Return the list of reasons this receipt cannot witness determinism."""
    reasons: list[str] = []

    schema = data.get("schema")
    if schema != SCHEMA:
        reasons.append(f"schema is {schema!r}, expected {SCHEMA!r}")

    pipeline = data.get("pipeline_status") or {}
    if not pipeline.get("recorded"):
        reasons.append("run recorded no terminal pipeline status (run_status.json absent or unreadable)")
    else:
        status = str(pipeline.get("status") or "").strip().lower()
        if status in {"failed", "error", "crashed"}:
            reasons.append(f"pipeline terminated as {status!r} at stage {pipeline.get('stage')!r}")
        elif status not in TERMINAL_SUCCESS_STATES:
            reasons.append(
                f"pipeline status {status!r} is not a completed terminal state; "
                "the run never reported success and cannot witness end-to-end determinism"
            )

    if not data.get("completed_stages"):
        reasons.append("receipt records no completed stages")

    return reasons


def build_matrix(receipts: list[Path]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(receipts):
        row: dict[str, Any] = {"receipt_path": str(path)}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            row.update(status="UNREADABLE", reason=str(exc))
            rows.append(row)
            continue
        row["receipt_sha256"] = digest(path)
        row["run"] = data.get("run")
        row["schema"] = data.get("schema")
        row["terminal_stage"] = data.get("terminal_stage")
        inadmissible = _admissibility(data)
        row["admissible"] = not inadmissible
        row["inadmissible_reasons"] = inadmissible
        row["status"] = "AVAILABLE" if not inadmissible else "INADMISSIBLE"
        row["data"] = data
        rows.append(row)

    readable = [r for r in rows if "data" in r]
    admissible = [r for r in readable if r["admissible"]]

    base = {
        "schema": "rq1_full_determinism_matrix/v2",
        "comparison_policy": COMPARISON_POLICY,
        "run_count": len(rows),
        "admissible_run_count": len(admissible),
        "runs": rows,
    }

    if len(admissible) < 5:
        return {
            **base,
            "status": "INCOMPLETE",
            "verdict": "INCOMPLETE",
            "reason": f"five admissible run receipts required, got {len(admissible)} of {len(rows)}",
            "blocking": sorted({r for row in readable for r in row["inadmissible_reasons"]}),
            "mismatches": [],
        }

    # Five admissible receipts must agree on the terminal stage, else they do
    # not witness the same computation.
    terminals = {json.dumps(r["terminal_stage"], sort_keys=True) for r in admissible}
    if len(terminals) > 1:
        return {
            **base,
            "status": "INCOMPLETE",
            "verdict": "INCOMPLETE",
            "reason": "admissible receipts reached different terminal stages; they do not witness the same computation",
            "terminal_stage_values": sorted(terminals),
            "mismatches": [],
        }

    compared = [r for r in admissible]
    mismatches: list[dict[str, Any]] = []
    for key in COMPARED_KEYS:
        values = [json.dumps(r["data"].get(key), sort_keys=True, separators=(",", ":")) for r in compared]
        if len(set(values)) > 1:
            mismatches.append({"field": key, "values": values})

    verdict = "FAIL" if mismatches else "PASS"
    return {
        **base,
        "status": verdict,
        "verdict": verdict,
        "reason": (
            f"{len(compared)} admissible receipts compared across {len(COMPARED_KEYS)} raw fields; "
            f"{len(mismatches)} field(s) differ"
        ),
        "compared_keys": list(COMPARED_KEYS),
        "mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", nargs="*", type=Path)
    parser.add_argument("--out", type=Path, default=Path("RQ1_FULL_DETERMINISM_MATRIX.json"))
    args = parser.parse_args()
    report = build_matrix(args.receipts)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "verdict", "run_count", "admissible_run_count", "reason") if k in report}, indent=2))
    return {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}[report["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
