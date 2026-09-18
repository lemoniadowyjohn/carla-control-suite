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


def _coerce_status(value: object) -> QualityStatus:
    """Coerce a single child input onto the status vocabulary, fail-closed.

    - `QualityStatus` instances pass through unchanged.
    - True -> PASS; False -> FAIL.
    - Recognized status strings map to their literal status.
    - Anything else (unknown object / unknown string) -> INCOMPLETE so that an
      ungoverned value can never be mistaken for PASS.
    """
    if isinstance(value, QualityStatus):
        return value
    if value is True:
        return QualityStatus.PASS
    if value is False:
        return QualityStatus.FAIL
    if isinstance(value, str):
        try:
            return QualityStatus(value)
        except ValueError:
            return QualityStatus.INCOMPLETE
    return QualityStatus.INCOMPLETE


def promote_aggregate_detailed(
    children: List[object],
    *,
    mandatory_children: Optional[List[str]] = None,
    waivers: Optional[Dict[str, str]] = None,
    waivable_fail: bool = True,
    child_names: Optional[List[str]] = None,
) -> Dict[str, object]:
    """Aggregate child gate statuses per-child, with waiver-governed rules.

    Conversion happens **per child** before any reduction:

    - PASS stays PASS.
    - FAIL stays FAIL unless BOTH the child is on the `mandatory_children`
      allow-list AND an explicit governed waiver names that exact child, in
      which case it becomes WAIVED (never PASS). This applies when
      `waivable_fail` is True.
    - INCOMPLETE / NOT_RUN / BLOCKED_EXTERNAL are never convertible to WAIVED
      or PASS by a waiver: there is no evidence to waive.
    - Unknown values coerce to INCOMPLETE (fail-closed).

    After conversion the aggregate is the worst remaining status under
    FAIL > INCOMPLETE > BLOCKED_EXTERNAL > WAIVED > NOT_RUN > PASS. A waiver
    is single-use: it covers only the exact failing child it names, so
    multiple failing children each need their own governed waiver.

    `child_names` explicitly binds per-child labels to positions (strict,
    raises on length mismatch or duplicate). When omitted, names fall back to
    the positional `mandatory_children` alignment (legacy) with ``str(index)``
    fill for overflow. A waiver can never waive a child it does not name, so a
    positional/label mismatch isolates rather than silently waives.

    Returns a structured report: `aggregate`, per-child conversion rows, the
    positional/label audit and unused waiver keys.
    """
    mandatory_children = list(mandatory_children) if mandatory_children else []
    waivers = dict(waivers) if waivers else {}

    if not children:
        return {
            "aggregate": QualityStatus.INCOMPLETE,
            "children": [],
            "mandatory_children": mandatory_children,
            "waivable_count": 0,
            "waived_count": 0,
            "positional_audit": {
                "children_count": 0,
                "mandatory_children_count": len(mandatory_children),
                "explicit_child_names": child_names is not None,
                "overflow_names": list(mandatory_children),
                "collisions": [],
                "ambiguous": bool(mandatory_children) or child_names is not None,
            },
            "unused_waiver_keys": sorted(waivers),
        }

    if child_names is not None:
        if len(child_names) != len(children):
            raise ValueError(
                f"child_names length {len(child_names)} does not match "
                f"children length {len(children)}."
            )
        seen: Dict[str, int] = {}
        for idx, name in enumerate(child_names):
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"child_names[{idx}] is not a non-empty string.")
            if name in seen:
                raise ValueError(
                    f"Duplicate child name {name!r} at positions "
                    f"{seen[name]} and {idx}; waiver resolution would be "
                    f"ambiguous."
                )
            seen[name] = idx

    overflow_names = list(mandatory_children[len(children):]) if len(mandatory_children) > len(children) else []

    converted: List[QualityStatus] = []
    rows: List[Dict[str, object]] = []
    names_by_index: List[str] = []
    waived_count = 0

    for idx, child in enumerate(children):
        raw_status = _coerce_status(child)
        if child_names is not None:
            name = child_names[idx]
        else:
            name = mandatory_children[idx] if idx < len(mandatory_children) else str(idx)
        names_by_index.append(name)

        waiver: Optional[str] = None
        if (
            waivable_fail
            and raw_status == QualityStatus.FAIL
            and name in mandatory_children
            and governed_waiver_allowed(waivers, name)
        ):
            status = QualityStatus.WAIVED
            waiver = waivers.get(name)
            waived_count += 1
        else:
            status = raw_status

        converted.append(status)
        rows.append(
            {
                "index": idx,
                "name": name,
                "input": child,
                "status": status,
                "waived": status == QualityStatus.WAIVED,
                "waiver": waiver,
                "coerced_from": raw_status if not (status == QualityStatus.WAIVED) else QualityStatus.FAIL,
            }
        )

    aggregate = _worst_of(converted)

    used_waiver_names = {
        row["name"] for row in rows if row["waived"] and row["waiver"] is not None
    }
    unused_waiver_keys = sorted(
        key for key in waivers if key not in {row["name"] for row in rows} or key not in used_waiver_names
    )

    collisions: List[str] = []
    if child_names is None:
        seen_positional: Dict[str, int] = {}
        for idx, name in enumerate(names_by_index):
            if name in seen_positional:
                collisions.append(name)
            seen_positional[name] = idx

    return {
        "aggregate": aggregate,
        "children": rows,
        "mandatory_children": mandatory_children,
        "waivable_count": sum(
            1 for row in rows if row["status"] == QualityStatus.FAIL and row["name"] in mandatory_children
        ),
        "waived_count": waived_count,
        "positional_audit": {
            "children_count": len(children),
            "mandatory_children_count": len(mandatory_children),
            "explicit_child_names": child_names is not None,
            "overflow_names": overflow_names,
            "collisions": sorted(set(collisions)),
            "ambiguous": bool(overflow_names) or bool(collisions),
        },
        "unused_waiver_keys": unused_waiver_keys,
    }


def promote_aggregate(
    children: List[object],
    *,
    mandatory_children: Optional[List[str]] = None,
    waivers: Optional[Dict[str, str]] = None,
    waivable_fail: bool = True,
    child_names: Optional[List[str]] = None,
) -> QualityStatus:
    """Aggregate child gate statuses with fail-closed, waiver-governed rules.

    Convenience wrapper around `promote_aggregate_detailed` that returns only
    the aggregate status. Per-child conversion happens first, then severity
    reduction:

    - Aggregate is PASS only if EVERY child is PASS.
    - A child FAIL without a governed waiver for that exact child keeps the
      aggregate FAIL (unwaivable FAIL, including FAILs off the allow-list).
    - A child FAIL WITH a governed waiver for that exact child becomes WAIVED
      (never PASS) when `waivable_fail` is True.
    - INCOMPLETE / NOT_RUN / BLOCKED_EXTERNAL children are never convertible
      by a waiver and always keep the aggregate from being WAIVED when they
      are more severe (INCOMPLETE and BLOCKED_EXTERNAL are worse than WAIVED).
    - The aggregate is the worst remaining status under
      FAIL > INCOMPLETE > BLOCKED_EXTERNAL > WAIVED > NOT_RUN > PASS.

    `mandatory_children` restricts which named children may be waived;
    children outside that list are unwaivable. `child_names` explicitly binds
    per-child labels to positions and is validated for length/duplicates.
    """
    return promote_aggregate_detailed(
        children,
        mandatory_children=mandatory_children,
        waivers=waivers,
        waivable_fail=waivable_fail,
        child_names=child_names,
    )["aggregate"]


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