"""ultimate_pipeline.quality.xodr_validation_result

OC-59 §17: one normalized validation-result envelope shared by all
OpenDRIVE validators.

    {
      "validator": "...",
      "schema_version": "...",
      "input_xodr_sha256": "...",
      "status": "PASS|FAIL|INCOMPLETE|NOT_RUN",
      "errors": [],
      "warnings": [],
      "statistics": {},
    }

Status semantics (never conflate):
  PASS       -- all applicable checks ran and passed.
  FAIL       -- at least one check failed.
  INCOMPLETE -- could not run to completion (missing dependency, unreadable
                input, crashed check). MUST NOT be read as PASS.
  NOT_RUN    -- deliberately not executed (not configured, profile excludes
                it). MUST NOT be read as PASS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


PASS = "PASS"
FAIL = "FAIL"
INCOMPLETE = "INCOMPLETE"
NOT_RUN = "NOT_RUN"

STATUSES = (PASS, FAIL, INCOMPLETE, NOT_RUN)


@dataclass
class ValidationResult:
    validator: str
    schema_version: str = "xodr_validation_envelope_v1"
    input_xodr_sha256: Optional[str] = None
    status: str = NOT_RUN
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)

    def fail(self, code: str, message: str, **context: Any) -> None:
        self.errors.append({"code": code, "message": message, **context})
        self.status = FAIL

    def warn(self, code: str, message: str, **context: Any) -> None:
        self.warnings.append({"code": code, "message": message, **context})
        if self.status == NOT_RUN:
            self.status = PASS

    def finalize(self) -> "ValidationResult":
        # Explicitly assigned statuses are preserved: in particular NOT_RUN
        # with no errors stays NOT_RUN (callers decide whether a skipped
        # check blocks their envelope -- it must remain visible, never
        # silently become PASS). Only the untouched default resolves.
        if self.status == NOT_RUN and self.errors:
            self.status = FAIL
        elif self.status == PASS and self.errors:
            self.status = FAIL
        return self

    def to_dict(self) -> Dict[str, Any]:
        if self.status not in STATUSES:
            raise ValueError(f"invalid validation status {self.status!r}")
        return {
            "validator": self.validator,
            "schema_version": self.schema_version,
            "input_xodr_sha256": self.input_xodr_sha256,
            "status": self.status,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "statistics": dict(self.statistics),
        }


def merge_results(
    name: str,
    results: List[ValidationResult],
    *,
    input_xodr_sha256: Optional[str] = None,
) -> ValidationResult:
    """Combine sub-validator envelopes; FAIL > INCOMPLETE > NOT_RUN precedence.

    INCOMPLETE anywhere (without FAIL) yields INCOMPLETE overall -- partial
    evidence must never present as PASS.
    """
    merged = ValidationResult(validator=name,
                              input_xodr_sha256=input_xodr_sha256)
    merged.status = PASS
    for sub in results:
        merged.errors.extend(
            dict(e, validator=sub.validator) for e in sub.errors
        )
        merged.warnings.extend(
            dict(w, validator=sub.validator) for w in sub.warnings
        )
        merged.statistics[sub.validator] = {
            "status": sub.status,
            "n_errors": len(sub.errors),
            "n_warnings": len(sub.warnings),
        }
        if sub.status == FAIL:
            merged.status = FAIL
        elif sub.status == INCOMPLETE and merged.status != FAIL:
            merged.status = INCOMPLETE
        elif sub.status == NOT_RUN and merged.status == PASS:
            merged.status = NOT_RUN
    return merged.finalize()
