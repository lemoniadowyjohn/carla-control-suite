"""Quality gates: measured, invalid, skipped and waived are four different things.

The single most important rule here is that an **INVALID metric is not a PASS**.
The repository has ``tile_frame_consistency`` recorded as FAIL whose metric is
itself invalid; correcting it into a green gate would be fabrication, so it is
surfaced as ``INVALID_METRIC``.

Similarly:

* **GAP-026 stays unresolved.** Its historical 2992 / 23529 lane-link pose
  failures are carried as-is. Thresholds are not raised to clear it.
* **Supplied vs silently skipped** is recorded per gate. A backend that quietly
  omits a gate must not read as a pass.
* **Non-waivable gates** are only applied once **Q12** is decided. Until then
  the taxonomy is reported as *proposed*, never enforced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from ultimate_pipeline.gui.results import Result

__all__ = [
    "GateStatus", "GateClass", "GateOutcome", "GateSuite", "GAP026_RECORD",
    "TILE_FRAME_CONSISTENCY", "run_gates", "gate_taxonomy_status",
]


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    #: The gate produced a number, but the number is not trustworthy.
    INVALID_METRIC = "INVALID_METRIC"
    #: The gate was not evaluated at all.
    NOT_EVALUATED = "NOT_EVALUATED"
    #: Deliberately not run.
    SKIPPED = "SKIPPED"
    #: The backend silently omitted it.
    NOT_SUPPLIED = "NOT_SUPPLIED"
    #: Could not run (missing input, external block).
    BLOCKED = "BLOCKED"


class GateClass(str, Enum):
    HARD = "hard"
    SOFT = "soft"
    INFORMATIONAL = "informational"


#: The unresolved GAP-026 record. Carried verbatim; thresholds are NOT raised.
GAP026_RECORD = {
    "id": "GAP-026",
    "state": "UNRESOLVED",
    "failed_lane_links": 2992,
    "total_lane_links": 23529,
    "note": "Historical lane-link pose failures. This must not be cleared by "
            "raising a tolerance.",
    "waivable": False,
}

#: A FAIL whose underlying metric is itself invalid.
TILE_FRAME_CONSISTENCY = {
    "name": "tile_frame_consistency",
    "status": GateStatus.INVALID_METRIC.value,
    "detail": "recorded FAIL, but the metric that produced it is itself "
              "invalid; corrected to INVALID_METRIC rather than PASS",
}


@dataclass(frozen=True)
class GateOutcome:
    name: str
    status: str
    gate_class: str = GateClass.SOFT.value
    value: Any = None
    detail: str = ""
    remediation: str = ""

    @property
    def green(self) -> bool:
        return self.status == GateStatus.PASS.value

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "gate_class": self.gate_class,
                "value": self.value, "detail": self.detail,
                "remediation": self.remediation}


@dataclass
class GateSuite:
    outcomes: list[GateOutcome] = field(default_factory=list)
    gap026: dict = field(default_factory=lambda: dict(GAP026_RECORD))

    @property
    def all_green(self) -> bool:
        return bool(self.outcomes) and all(o.green for o in self.outcomes)

    @property
    def blocking(self) -> list[GateOutcome]:
        return [o for o in self.outcomes
                if o.status in (GateStatus.FAIL.value, GateStatus.INVALID_METRIC.value,
                                GateStatus.NOT_EVALUATED.value, GateStatus.BLOCKED.value)]

    @property
    def not_supplied(self) -> list[GateOutcome]:
        return [o for o in self.outcomes if o.status == GateStatus.NOT_SUPPLIED.value]

    def as_dict(self) -> dict:
        return {"all_green": self.all_green,
                "blocking": [o.name for o in self.blocking],
                "not_supplied": [o.name for o in self.not_supplied],
                "outcomes": [o.as_dict() for o in self.outcomes],
                "gap026": self.gap026}


def _status_for(name: str, raw: Any, supplied: bool) -> GateOutcome:
    if not supplied:
        return GateOutcome(name, GateStatus.NOT_SUPPLIED.value,
                           detail="the backend did not supply this gate",
                           remediation="treat as unverified, not as a pass")
    if raw is None:
        return GateOutcome(name, GateStatus.NOT_EVALUATED.value,
                           detail="gate produced no result",
                           remediation="run the gate, or record why it was skipped")
    if raw is False:
        return GateOutcome(name, GateStatus.FAIL.value, detail="gate reported failure")
    if raw == "INVALID":
        return GateOutcome(name, GateStatus.INVALID_METRIC.value,
                           detail="the metric itself is invalid",
                           remediation="fix the metric; do not correct this to a pass")
    if raw == "SKIPPED":
        return GateOutcome(name, GateStatus.SKIPPED.value, detail="deliberately not run")
    if raw == "BLOCKED":
        return GateOutcome(name, GateStatus.BLOCKED.value, detail="external dependency missing")
    if raw is True:
        return GateOutcome(name, GateStatus.PASS.value)
    return GateOutcome(name, GateStatus.NOT_EVALUATED.value,
                       detail=f"unrecognised gate result {raw!r}",
                       remediation="never invent a verdict")


def run_gates(results: dict[str, Any], *, requested: Iterable[str] = (),
              gate_classes: dict[str, str] | None = None) -> GateSuite:
    """Run the requested gate set, distinguishing supplied from skipped."""
    wanted = list(requested) if requested else sorted(results)
    classes = gate_classes or {}
    suite = GateSuite(outcomes=[])
    for name in wanted:
        outcome = _status_for(name, results.get(name), name in results)
        suite.outcomes.append(GateOutcome(
            outcome.name, outcome.status,
            gate_class=classes.get(name, GateClass.SOFT.value),
            value=outcome.value, detail=outcome.detail,
            remediation=outcome.remediation))
    return suite


def gate_taxonomy_status(operator_decided_q12: bool = False) -> Result:
    """Non-waivable gate taxonomy is only applied after a maintainer decision."""
    if operator_decided_q12:
        return Result.success(
            {"non_waivable": ["GAP-026", "tile_frame_consistency"],
             "status": "ENFORCED"})
    return Result.blocked(
        "non-waivable gate taxonomy (Q12) is undecided; it is PROPOSED only",
        remediation="a maintainer must decide Q12 before the taxonomy is enforced")


def accept_suite(suite: GateSuite) -> Result:
    """Acceptance refuses while anything blocks, including GAP-026."""
    problems = [f"{o.name}: {o.status}" for o in suite.blocking]
    if not suite.gap026.get("waivable", False):
        problems.append(f"GAP-026 remains {suite.gap026['state']} "
                        f"({suite.gap026['failed_lane_links']}/"
                        f"{suite.gap026['total_lane_links']})")
    if problems:
        return Result.failure("map acceptance refused: " + "; ".join(problems),
                              error_class="GateFailure", state_restored=None)
    return Result.success({"accepted": True})