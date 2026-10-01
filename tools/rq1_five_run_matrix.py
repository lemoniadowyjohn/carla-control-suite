"""Build an RQ1 five-run determinism matrix from explicit run receipt files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

#: Receipt schema each run must declare (NEW-346).  A receipt without it is
#: still compared, but the matrix reports the schema gap instead of claiming a
#: schema-less run set proves determinism.
RUN_RECEIPT_SCHEMA = "rq1_run_receipt/v1"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build_matrix(receipts: list[Path]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(receipts):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"receipt is not a JSON object: {type(data).__name__}")
            rows.append(
                {
                    "receipt_path": str(path),
                    "receipt_sha256": digest(path),
                    "status": "AVAILABLE",
                    "receipt_schema": data.get("schema"),
                    "data": data,
                }
            )
        except Exception as exc:
            rows.append({"receipt_path": str(path), "status": "UNREADABLE", "reason": str(exc)})
    if len(rows) < 5:
        return {"schema": "rq1_full_determinism_matrix/v1", "status": "INCOMPLETE", "verdict": "INCOMPLETE", "run_count": len(rows), "runs": rows, "reason": f"five isolated run receipts required, got {len(rows)}", "comparison_policy": "No normalization of unknown fields; timestamp, ordering, floating-point, and structural differences remain observable."}
    unreadable = [row for row in rows if row.get("status") != "AVAILABLE"]
    if unreadable:
        # A receipt that cannot be parsed proves nothing; comparing the others
        # against a hole would either invent a mismatch or hide a divergence.
        return {"schema": "rq1_full_determinism_matrix/v1", "status": "INCOMPLETE", "verdict": "INCOMPLETE", "run_count": len(rows), "runs": rows, "reason": f"{len(unreadable)} receipt(s) unreadable, determinism cannot be established", "comparison_policy": "No normalization of unknown fields; timestamp, ordering, floating-point, and structural differences remain observable."}
    keys = ["xodr_sha256", "normalized_xodr_sha256", "structural_signature", "feature_counts", "topology_counts", "output_path", "tileset_digest", "map_acceptance_digest", "final_receipt_digest"]
    mismatches = []
    # NEW-346: ``None == None`` is NOT agreement.  A field every receipt leaves
    # null carries no evidence either way, so it is reported INCOMPLETE; a field
    # that is null in only some receipts is a real difference (mismatch).
    incomparable = []
    for key in keys:
        raw = [row.get("data", {}).get(key) for row in rows]
        if all(v is None for v in raw):
            incomparable.append({"field": key, "reason": "all receipts report null"})
            continue
        values = [json.dumps(v, sort_keys=True, separators=(",", ":")) for v in raw]
        if len(set(values)) > 1:
            mismatches.append({"field": key, "values": values})

    schema_gaps = [
        {"receipt_path": row["receipt_path"], "receipt_schema": row.get("receipt_schema")}
        for row in rows
        if row.get("receipt_schema") != RUN_RECEIPT_SCHEMA
    ]

    if mismatches:
        status = "FAIL"
        reason = None
    elif incomparable or schema_gaps:
        status = "INCOMPLETE"
        reason = "some determinism fields are null in every receipt" if incomparable else None
        if schema_gaps:
            reason = (reason + "; " if reason else "") + f"{len(schema_gaps)} receipt(s) do not declare {RUN_RECEIPT_SCHEMA}"
    else:
        status = "PASS"
        reason = None
    return {
        "schema": "rq1_full_determinism_matrix/v1",
        "status": status,
        "verdict": status,
        "run_count": len(rows),
        "runs": rows,
        "mismatches": mismatches,
        "incomparable_fields": incomparable,
        "receipt_schema_gaps": schema_gaps,
        "receipt_schema": RUN_RECEIPT_SCHEMA,
        "reason": reason,
        "comparison_policy": "No normalization of unknown fields; timestamp, ordering, floating-point, and structural differences remain observable.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", nargs="*", type=Path)
    parser.add_argument("--out", type=Path, default=Path("RQ1_FULL_DETERMINISM_MATRIX.json"))
    args = parser.parse_args()
    report = build_matrix(args.receipts)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "verdict", "run_count", "reason") if k in report}, indent=2))
    return 0 if report["verdict"] == "PASS" else 2 if report["verdict"] == "FAIL" else 3


if __name__ == "__main__":
    raise SystemExit(main())
