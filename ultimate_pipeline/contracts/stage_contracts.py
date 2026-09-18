# ultimate_pipeline/contracts/stage_contracts.py
# -*- coding: utf-8 -*-

"""
Cross-stage release contract vocabulary.

Baseline keeps the historical `ReleaseProfile` TypeAlias (plain string
literals consumed by release_profile.py) untouched. Additive extensions for
the quality-gate vocabulary (OC-2 topology component hardening) live below
it:

- `QualityStatus`: the single status vocabulary every quality gate /
  aggregation function returns. NEVER return a raw boolean where a status is
  expected; use `from_legacy_bool`, `from_skipped_mandatory` and
  `from_missing_external` to convert legacy / degenerate inputs.
- `WarningDefinition` + `WARNING_REGISTRY`: warn-once definitions so the same
  warning code always resolves to the same message and origin stage.
- Governed waiver helpers: an aggregate gate may only ever reach
  `QualityStatus.PASS` when EVERY mandatory child passed. A child FAIL may
  become `QualityStatus.WAIVED` (never PASS) only through an explicitly
  registered governed waiver; a skipped-but-mandatory child surfaces as
  `QualityStatus.INCOMPLETE` (still never PASS). This makes the
  evidence-missing gate manager fail-closed instead of fail-open.

All additions are pure and offline (no CARLA dependency).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Dict, List, Literal, Optional, TypeAlias

ReleaseProfile: TypeAlias = Literal[
    "structural_release",
    "visual_build",
    "scenario_augmentation",
    "debug",
    "experimental_unsafe",
]

# ---------------------------------------------------------------------------
# Quality status vocabulary
# ---------------------------------------------------------------------------


class QualityStatus(StrEnum):
    """Single authoritative status vocabulary for quality gates.

    Semantics:
    - PASS: evidence present and satisfies the gate.
    - FAIL: evidence present and violates the gate.
    - INCOMPLETE: a mandatory check could not be evaluated (missing evidence,
      unavailable input, sparse-checkout limitation). NEVER treated as PASS.
    - NOT_RUN: the check was not executed in this invocation.
    - BLOCKED_EXTERNAL: the check could not run because of an external
      dependency (CARLA server, asset download, license server).
    - WAIVED: the check FAILED but a governed, registered waiver explicitly
      authorizes continuing. WAIVED is never PASS; an aggregate gate that is
      WAIVED is not a hard pass and must be surfaced as a warning.
    """

    PASS = "pass"
    FAIL = "fail"
    INCOMPLETE = "incomplete"
    NOT_RUN = "not_run"
    BLOCKED_EXTERNAL = "blocked_external"
    WAIVED = "waived"

    def __str__(self) -> str:
        return self.value


LEGACY_BOOLEAN_MAP: Dict[bool, QualityStatus] = {
    True: QualityStatus.PASS,
    False: QualityStatus.FAIL,
}


def from_legacy_bool(value: bool) -> QualityStatus:
    """Map a legacy True/False gate result onto the status vocabulary."""
    return LEGACY_BOOLEAN_MAP.get(bool(value), QualityStatus.INCOMPLETE)


def from_skipped_mandatory() -> QualityStatus:
    """A mandatory child that was skipped can never pass."""
    return QualityStatus.INCOMPLETE


def from_missing_external() -> QualityStatus:
    """An evidence artifact that could not be produced for external reasons."""
    return QualityStatus.BLOCKED_EXTERNAL


def from_legacy_exception(exc: Exception) -> QualityStatus:
    """Map a raised gate exception onto the vocabulary.

    A raised exception during a mandatory gate is fail-closed: FAIL, not
    INCOMPLETE, unless the exception is a deliberately probed "skipped" /
    "unavailable" sentinel, which callers should map via
    from_skipped_mandatory() / from_missing_external() instead.
    """
    return QualityStatus.FAIL if exc is not None else QualityStatus.PASS


# ---------------------------------------------------------------------------
# Warning registry (warn-once, deterministic)
# ---------------------------------------------------------------------------


class WarningDefinition:
    """Static definition of a warning code."""

    __slots__ = ("code", "message", "origin_stage", "status")

    def __init__(
        self,
        code: str,
        message: str,
        origin_stage: str,
        status: QualityStatus = QualityStatus.WAIVED,
    ) -> None:
        self.code = code
        self.message = message
        self.origin_stage = origin_stage
        self.status = status


WARNING_REGISTRY: Dict[str, WarningDefinition] = {}


def register_warning(definition: WarningDefinition) -> WarningDefinition:
    """Register (or fail loudly on duplicate) a warning definition."""
    if definition.code in WARNING_REGISTRY:
        existing = WARNING_REGISTRY[definition.code]
        if (
            existing.message != definition.message
            or existing.origin_stage != definition.origin_stage
        ):
            raise ValueError(
                f"Warning code {definition.code!r} already registered with a "
                f"different definition from {existing.origin_stage}."
            )
    else:
        WARNING_REGISTRY[definition.code] = definition
    return definition


def lookup_warning(code: str) -> Optional[WarningDefinition]:
    """Look up a registered warning definition, or None when unknown."""
    return WARNING_REGISTRY.get(code)


# ---------------------------------------------------------------------------
# Governed waiver semantics
# ---------------------------------------------------------------------------


def _worst_of(statuses: List[QualityStatus]) -> QualityStatus:
    """Aggregate children by severity so a FAIL anywhere is never hidden.

    Ordering (most to least severe): FAIL > INCOMPLETE > BLOCKED_EXTERNAL >
    WAIVED > NOT_RUN > PASS. Unknown values map to INCOMPLETE (fail-closed).
    """
    severity = {
        QualityStatus.FAIL: 5,
        QualityStatus.INCOMPLETE: 4,
        QualityStatus.BLOCKED_EXTERNAL: 3,
        QualityStatus.WAIVED: 2,
        QualityStatus.NOT_RUN: 1,
        QualityStatus.PASS: 0,
    }
    reduced: List[QualityStatus] = []
    for s in statuses:
        if isinstance(s, QualityStatus):
            reduced.append(s)
        elif s is True:
            reduced.append(QualityStatus.PASS)
        elif s is False:
            reduced.append(QualityStatus.FAIL)
        elif isinstance(s, str):
            try:
                reduced.append(QualityStatus(s))
            except ValueError:
                reduced.append(QualityStatus.INCOMPLETE)
        else:
            reduced.append(QualityStatus.INCOMPLETE)
    return sorted(reduced, key=lambda s: severity.get(s, 4), reverse=True)[0]


def governed_waiver_allowed(waivers: Optional[Dict[str, str]], child: str) -> bool:
    """True only when an explicit governed waiver covers `child`.

    A governed waiver is a mapping of a gate/check key to a free-text
    justification. Generic truthy existence of evidence is NOT a waiver; a
    waiver must name this exact child key. This is what prevents the
    historical fail-open `not rep.get("ok", True)` default from silently
    promoting a never-evaluated gate to PASS.
    """
    if not waivers:
        return False
    justification = waivers.get(child)
    return isinstance(justification, str) and bool(justification.strip())


def promote_aggregate(
    children: List[QualityStatus],
    *,
    mandatory_children: Optional[List[str]] = None,
    waivers: Optional[Dict[str, str]] = None,
    waivable_fail: bool = True,
) -> QualityStatus:
    """Aggregate child gate statuses with fail-closed, waiver-governed rules.

    - Aggregate is PASS only if EVERY child is PASS.
    - A child FAIL without a governed waiver keeps the aggregate FAIL.
    - A child FAIL WITH a governed waiver for that exact child becomes WAIVED
      (never PASS) when `waivable_fail` is True.
    - A skipped/missing mandatory child with no evidence is INCOMPLETE and
      can never be promoted to PASS, even with a waiver (there is evidence of
      nothing, so there is nothing to waive).
    - The aggregate is never PASS while any child is non-PASS; the worst
      non-PASS child governs the result instead.

    `mandatory_children` restricts which named children may be waived;
    children outside that list are unwaivable.
    """
    if not children:
        return QualityStatus.INCOMPLETE

    mandatory_children = mandatory_children or []
    converted: List[QualityStatus] = []
    names: List[str] = []

    for idx, child in enumerate(children):
        if isinstance(child, QualityStatus):
            status = child
        elif child is True:
            status = QualityStatus.PASS
        elif child is False:
            status = QualityStatus.FAIL
        else:
            status = QualityStatus.INCOMPLETE
        converted.append(status)
        label = mandatory_children[idx] if idx < len(mandatory_children) else str(idx)
        names.append(label)

    if all(s == QualityStatus.PASS for s in converted):
        return QualityStatus.PASS
    if not any(s != QualityStatus.PASS for s in converted):
        return QualityStatus.PASS

    waivable = [
        (s, n)
        for s, n in zip(converted, names)
        if s == QualityStatus.FAIL and n in mandatory_children
    ]
    if waivable_fail and waivable:
        if all(governed_waiver_allowed(waivers, n) for s, n in waivable):
            return QualityStatus.WAIVED
        return QualityStatus.FAIL

    if any(s == QualityStatus.FAIL for s in converted):
        return QualityStatus.FAIL
    return _worst_of(converted)


# ---------------------------------------------------------------------------
# Gate-report normalization (single decision authority)
# ---------------------------------------------------------------------------

GATE_STATUS_SYNONYMS: Dict[str, QualityStatus] = {
    "pass": QualityStatus.PASS,
    "passed": QualityStatus.PASS,
    "ok": QualityStatus.PASS,
    "success": QualityStatus.PASS,
    "fail": QualityStatus.FAIL,
    "failed": QualityStatus.FAIL,
    "error": QualityStatus.FAIL,
    "abort": QualityStatus.FAIL,
    "gate_timed_out": QualityStatus.FAIL,
    "incomplete": QualityStatus.INCOMPLETE,
    "pending": QualityStatus.INCOMPLETE,
    "no_evidence": QualityStatus.INCOMPLETE,
    "not_run": QualityStatus.NOT_RUN,
    "skipped": QualityStatus.NOT_RUN,
    "skip": QualityStatus.NOT_RUN,
    "blocked_external": QualityStatus.BLOCKED_EXTERNAL,
    "blocked": QualityStatus.BLOCKED_EXTERNAL,
    "unavailable": QualityStatus.BLOCKED_EXTERNAL,
    "waived": QualityStatus.WAIVED,
}


def _map_gate_status_string(value: object) -> Optional[QualityStatus]:
    """Map a producer's status string onto the QualityStatus vocabulary.

    Foreign producer vocabularies (``PASS`` / ``FAIL`` / ``INCOMPLETE``,
    ``pass`` / ``fail`` / ``skipped`` / ``error``, ``PENDING``,
    ``GATE_TIMED_OUT``) are normalized case-insensitively. Unrecognized
    values return None so callers can fail closed instead of guessing.
    """
    if isinstance(value, QualityStatus):
        return value
    if not isinstance(value, str):
        return None
    return GATE_STATUS_SYNONYMS.get(value.strip().lower())


def normalize_gate_result(report: object) -> Dict[str, object]:
    """Normalize an arbitrary gate report into one fail-closed verdict.

    This is the single normalization authority for gate decisions and MUST
    produce the same verdict wherever it is used (QualityGateManager
    ``_finalize_gate`` and CumulativeGateRunner). Precedence:

    1. Not a dict (None, a list, a bare status) -> FAIL (never crash).
    2. Explicit ``ok`` key -> authoritative. The ``status`` value, when also
       present (e.g. ``structure_elevation_plausibility`` carries BOTH), is
       preserved for provenance but never overrides ``ok``.
    3. ``status`` key only -> mapped onto the vocabulary; only PASS maps to a
       pass verdict. ``PENDING`` -> INCOMPLETE, ``GATE_TIMED_OUT`` -> FAIL,
       unknown status strings -> FAIL (fail-closed, never a silent pass).
    4. No verdict key at all -> FAIL; an empty report is an unverified report
       and can never represent an unambiguous pass.

    Returns a dict with ``decision`` ("pass"|"fail"), ``ok``, normalized
    ``status``, ``reason`` and the inspected verdict keys.
    """
    if not isinstance(report, dict):
        return {
            "ok": False,
            "status": QualityStatus.FAIL,
            "decision": "fail",
            "reason": "not_dict",
            "inspected_keys": [],
        }

    inspected = [k for k in ("ok", "status", "error") if k in report]

    if "ok" in report:
        ok = bool(report["ok"])
        status = _map_gate_status_string(report.get("status")) if "status" in report else None
        if status is None:
            status = QualityStatus.PASS if ok else QualityStatus.FAIL
        return {
            "ok": ok,
            "status": status,
            "decision": "pass" if ok else "fail",
            "reason": "ok_key",
            "inspected_keys": inspected,
        }

    if "status" in report:
        mapped = _map_gate_status_string(report.get("status"))
        if mapped is None:
            return {
                "ok": False,
                "status": QualityStatus.FAIL,
                "decision": "fail",
                "reason": "unrecognized_status",
                "inspected_keys": inspected,
            }
        return {
            "ok": mapped == QualityStatus.PASS,
            "status": mapped,
            "decision": "pass" if mapped == QualityStatus.PASS else "fail",
            "reason": "status_key",
            "inspected_keys": inspected,
        }

    return {
        "ok": False,
        "status": QualityStatus.FAIL,
        "decision": "fail",
        "reason": "no_verdict_key",
        "inspected_keys": inspected,
    }


# ---------------------------------------------------------------------------
# Registered warnings (topology hardening vocabulary)
# ---------------------------------------------------------------------------

register_warning(
    WarningDefinition(
        code="SPEC_TOPOLOGY_NOT_LITERAL",
        message=(
            "Production certification requires the literal spec graph. The "
            "recovered-diagnostic graph passed but the literal graph did not; "
            "the map is not certifiable as topology-spec-conformant."
        ),
        origin_stage="map_acceptance",
        status=QualityStatus.WAIVED,
    )
)
register_warning(
    WarningDefinition(
        code="COMPONENT_QUARANTINE_UNKNOWN_PRESERVED",
        message=(
            "UNKNOWN-classified small components were preserved by quarantine "
            "instead of auto-deleted; review required before promotion."
        ),
        origin_stage="map_hygiene",
        status=QualityStatus.WAIVED,
    )
)