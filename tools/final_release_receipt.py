"""Validate the top-level final release receipt without treating missing evidence as PASS."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

STATUSES = {"PASS", "FAIL", "NOT_RUN", "BLOCKED", "NOT_APPLICABLE"}
SECTIONS = ["repository", "source", "map", "visual_package", "unreal_carla", "testing", "runtime", "research", "known_gaps"]


def validate(receipt: dict[str, Any]) -> dict[str, Any]:
    failures = []
    for section in SECTIONS:
        if section not in receipt:
            failures.append(f"missing section {section}")
    invalid = []
    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            status = value.get("status")
            if status is not None and status not in STATUSES:
                invalid.append(f"{path}.status={status}")
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
    walk(receipt, "receipt")
    failures.extend(invalid)
    return {"schema": "final_release_receipt_validation/v1", "status": "PASS" if not failures else "FAIL", "failures": failures, "missing_evidence_is_not_pass": True, "accepted_statuses": sorted(STATUSES)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("FINAL_RELEASE_RECEIPT_VALIDATION.json"))
    args = parser.parse_args()
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    except Exception as exc:
        receipt = {}
        report = {"schema": "final_release_receipt_validation/v1", "status": "FAIL", "failures": [f"cannot parse receipt: {exc}"], "missing_evidence_is_not_pass": True, "accepted_statuses": sorted(STATUSES)}
    else:
        report = validate(receipt)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
