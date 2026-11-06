"""Validate the top-level final release receipt without treating missing evidence as PASS.

ARCHITECTURAL DISTINCTION: SCHEMA_VALID != RELEASE_ADMISSIBLE.

This function performs SCHEMA-ONLY validation: it checks that required
sections exist and that status values belong to the allowed vocabulary.
It does NOT determine whether a receipt is admissible for release promotion.

A receipt where all sections have status NOT_RUN is schema-valid (PASS from
this function) but NOT release-admissible. Release admission requires
additional checks beyond schema validity:
    * All mandatory sections must have status PASS (not NOT_RUN, FAIL, or BLOCKED)
    * Identity digests must match actual artifact bytes
    * Runtime certification must be available (CARLA runtime certified)

No production caller promotes based on validate() output alone. Callers must
implement their own admission logic that checks actual section statuses,
identity digests, and runtime certification before promoting a release.

This function intentionally does NOT implement release admission logic, to
avoid creating a competing release authority.
"""
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
