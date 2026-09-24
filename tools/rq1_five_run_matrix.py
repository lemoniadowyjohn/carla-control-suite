"""Build an RQ1 five-run determinism matrix from explicit run receipt files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


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
            rows.append({"receipt_path": str(path), "receipt_sha256": digest(path), "status": "AVAILABLE", "data": data})
        except Exception as exc:
            rows.append({"receipt_path": str(path), "status": "UNREADABLE", "reason": str(exc)})
    if len(rows) < 5:
        return {"schema": "rq1_full_determinism_matrix/v1", "status": "INCOMPLETE", "verdict": "INCOMPLETE", "run_count": len(rows), "runs": rows, "reason": f"five isolated run receipts required, got {len(rows)}", "comparison_policy": "No normalization of unknown fields; timestamp, ordering, floating-point, and structural differences remain observable."}
    keys = ["xodr_sha256", "normalized_xodr_sha256", "structural_signature", "feature_counts", "topology_counts", "output_path", "tileset_digest", "map_acceptance_digest", "final_receipt_digest"]
    mismatches = []
    for key in keys:
        values = [json.dumps(row.get("data", {}).get(key), sort_keys=True, separators=(",", ":")) for row in rows]
        if len(set(values)) > 1:
            mismatches.append({"field": key, "values": values})
    return {"schema": "rq1_full_determinism_matrix/v1", "status": "FAIL" if mismatches else "PASS", "verdict": "FAIL" if mismatches else "PASS", "run_count": len(rows), "runs": rows, "mismatches": mismatches, "comparison_policy": "No normalization of unknown fields; timestamp, ordering, floating-point, and structural differences remain observable."}


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
