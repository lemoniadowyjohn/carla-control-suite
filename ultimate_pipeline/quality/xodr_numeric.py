"""ultimate_pipeline.quality.xodr_numeric

OC-59 §3: one strict numeric-parsing API for all OpenDRIVE validators.

A required numeric attribute parse distinguishes exactly four outcomes:

    MISSING    -- attribute absent (None)
    MALFORMED  -- present but not parseable as a number ("banana", "")
    NONFINITE  -- parses but is nan/inf ("nan", "inf", "-inf")
    VALID      -- finite number

A physical zero is NEVER substituted before validity is decided. After
validation, diagnostic code may use an explicitly labeled fallback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


MISSING = "MISSING"
MALFORMED = "MALFORMED"
NONFINITE = "NONFINITE"
VALID = "VALID"


@dataclass(frozen=True)
class ParseResult:
    status: str  # one of MISSING / MALFORMED / NONFINITE / VALID
    value: Optional[float]  # finite float iff status == VALID, else None
    raw: Optional[str]  # original attribute text (None when absent)

    @property
    def ok(self) -> bool:
        return self.status == VALID


def parse_required_float(raw: Optional[str]) -> ParseResult:
    """Parse a required float attribute with full outcome discrimination."""
    if raw is None:
        return ParseResult(MISSING, None, None)
    text = str(raw).strip()
    if not text:
        return ParseResult(MALFORMED, None, str(raw))
    try:
        value = float(text)
    except Exception:
        return ParseResult(MALFORMED, None, str(raw))
    if not math.isfinite(value):
        return ParseResult(NONFINITE, None, str(raw))
    return ParseResult(VALID, value, str(raw))


def parse_optional_float(
    raw: Optional[str], *, default: float,
) -> tuple[ParseResult, float]:
    """Parse an optional float; MISSING yields the labeled default.

    Returns (result, effective_value). MALFORMED/NONFINITE are still reported
    (effective value falls back to ``default`` but the outcome is explicit,
    so callers can warn instead of silently accepting).
    """
    result = parse_required_float(raw)
    if result.status == MISSING:
        return result, float(default)
    if result.ok:
        return result, float(result.value)
    return result, float(default)


def parse_required_int(raw: Optional[str]) -> ParseResult:
    """Parse a required int attribute (lane ids, revisions, counts)."""
    if raw is None:
        return ParseResult(MISSING, None, None)
    text = str(raw).strip()
    if not text:
        return ParseResult(MALFORMED, None, str(raw))
    lowered = text.lower()
    if lowered in ("nan", "inf", "+inf", "-inf", "infinity",
                   "+infinity", "-infinity"):
        return ParseResult(NONFINITE, None, str(raw))
    try:
        # OpenDRIVE ints are decimal; reject float spellings ("1.5",
        # "1e3") explicitly rather than truncating.
        if any(c in text for c in ".eE"):
            float(text)  # raises for garbage like "1.2.3"
            return ParseResult(MALFORMED, None, str(raw))
        value = int(text, 10)
    except Exception:
        return ParseResult(MALFORMED, None, str(raw))
    return ParseResult(VALID, float(value), str(raw))


def describe_parse_issue(
    what: str, result: ParseResult, context: Optional[dict] = None
) -> dict:
    """Human/machine-readable issue payload for a non-VALID parse."""
    return {
        "field": what,
        "outcome": result.status,
        "raw": result.raw,
        "context": dict(context or {}),
    }
