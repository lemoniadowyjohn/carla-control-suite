# -*- coding: utf-8 -*-
"""Central result-status normalizer for quality gate reports.

Converts fall-open ``report.get("ok", True)`` patterns into a
deterministic status: PASS, FAIL, or INCOMPLETE.

Design invariants
----------------
- A missing or empty report is INCOMPLETE, never PASS.
- An explicit ok=True is PASS.
- An explicit ok=False is FAIL.
- A dict with no "ok" key, None, or a malformed dict is INCOMPLETE.
- The function never raises; it always returns one of the three statuses.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Literal

Status = Literal["PASS", "FAIL", "INCOMPLETE"]


def normalize_quality_result(report: Any) -> Dict[str, Any]:
    """Normalize a quality gate report dict.

    Returns a dict with keys:
    - "status": one of "PASS", "FAIL", "INCOMPLETE"
    - "ok": bool (the resolved ok value)
    - "raw": the original input for debugging

    The normalization is fail-closed: missing evidence never becomes PASS.
    """
    raw = report

    # None -> INCOMPLETE
    if raw is None:
        return {"status": "INCOMPLETE", "ok": False, "raw": None}

    # Not a dict -> INCOMPLETE
    if not isinstance(raw, dict):
        return {"status": "INCOMPLETE", "ok": False, "raw": raw}

    # Empty dict {} -> INCOMPLETE
    if len(raw) == 0:
        return {"status": "INCOMPLETE", "ok": False, "raw": raw}

    # Extract ok value safely
    ok = raw.get("ok")

    # ok is explicitly True -> PASS
    if ok is True:
        return {"status": "PASS", "ok": True, "raw": raw}

    # ok is explicitly False -> FAIL
    if ok is False:
        return {"status": "FAIL", "ok": False, "raw": raw}

    # ok is missing (key not present) -> INCOMPLETE
    # ok is present but not bool (e.g. ok: "yes", ok: 1) -> INCOMPLETE
    if "ok" not in raw:
        return {"status": "INCOMPLETE", "ok": False, "raw": raw}

    # ok key present but value is not a bool -> INCOMPLETE
    return {"status": "INCOMPLETE", "ok": False, "raw": raw}


def status_is_pass(report: Any) -> bool:
    """Convenience: return True only when normalized status is PASS."""
    return normalize_quality_result(report)["status"] == "PASS"


def status_is_fail(report: Any) -> bool:
    """Convenience: return True when normalized status is FAIL."""
    return normalize_quality_result(report)["status"] == "FAIL"


def status_is_incomplete(report: Any) -> bool:
    """Convenience: return True when normalized status is INCOMPLETE."""
    return normalize_quality_result(report)["status"] == "INCOMPLETE"