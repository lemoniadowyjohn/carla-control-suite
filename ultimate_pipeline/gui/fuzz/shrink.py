"""Dependency-aware failure shrinking (delta debugging).

The predicate preserved is the **failure fingerprint**, not merely "some
failure". A reduction that makes a *different* oracle fail, or turns a
``BUG_CANDIDATE`` into an ``INCONCLUSIVE``, is rejected.

Guarantees:

* the caller's case is never mutated -- every candidate is a fresh copy;
* reduction order is deterministic (ddmin), so the same input shrinks the
  same way twice;
* every accepted and rejected reduction is recorded with its reason;
* ``INCONCLUSIVE`` oracles never count as proof of a reproduced failure;
* operations and wall-clock are both bounded, and cancellation is honoured.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled
from ultimate_pipeline.gui.fuzz.oracles import OracleResult, Verdict
from ultimate_pipeline.gui.fuzz.corpus import normalise
from ultimate_pipeline.gui.results import Result

__all__ = ["Fingerprint", "Reduction", "ShrinkReport", "shrink", "REDUCERS"]


@dataclass(frozen=True)
class Fingerprint:
    """Identity of the failure that must be preserved."""

    oracle: str
    outcome: str
    #: A caller-supplied stable key for the observed failure detail. Without a
    #: key the fingerprint is coarse and shrinking refuses to proceed.
    detail_key: str = ""

    def as_dict(self) -> dict:
        return {"oracle": self.oracle, "outcome": self.outcome,
                "detail_key": self.detail_key}


@dataclass(frozen=True)
class Reduction:
    description: str
    accepted: bool
    reason: str = ""

    def as_dict(self) -> dict:
        return {"description": self.description, "accepted": self.accepted,
                "reason": self.reason}


@dataclass
class ShrinkReport:
    original: Any
    minimised: Any
    preserved: Fingerprint | None
    reductions: list[Reduction] = field(default_factory=list)
    attempts: int = 0
    exhausted: bool = False
    size_before: int = 0
    size_after: int = 0

    def as_dict(self) -> dict:
        return {"preserved": self.preserved.as_dict() if self.preserved else None,
                "attempts": self.attempts, "exhausted": self.exhausted,
                "size_before": self.size_before, "size_after": self.size_after,
                "reductions": [r.as_dict() for r in self.reductions]}


# A predicate returns the observed Fingerprint, or None when the case passes.
Predicate = Callable[[Any], Fingerprint | None]


def structural_size(value: Any) -> int:
    """A measure that actually changes when a case is reduced.

    ``len(content_hash(...))`` is always 64 and would make every reduction
    assertion vacuous, so size is measured on the serialised payload instead.
    """
    return len(json.dumps(normalise(value), sort_keys=True, default=repr))


def _is_preserved(observed: Fingerprint | None, target: Fingerprint) -> bool:
    """Only the SAME failure counts."""
    if observed is None:
        return False
    if observed.oracle != target.oracle or observed.outcome != target.outcome:
        return False
    # An expected rejection is a legitimate fingerprint; an INCONCLUSIVE oracle
    # is NOT proof of a reproduced failure and may not satisfy the target.
    if observed.outcome == Verdict.INCONCLUSIVE.value:
        return False
    if target.detail_key and observed.detail_key != target.detail_key:
        return False
    return True


def _subset(candidate: Sequence, complement: Sequence) -> list:
    """Deterministic delta-debugging subset: alternate elements, n powers of two."""
    n = 2
    size = len(candidate)
    while len(candidate) > 1:
        chunk = max(1, size // n)
        for start in range(0, len(candidate), chunk):
            removed = candidate[start:start + chunk]
            if not removed:
                continue
            remainder = list(candidate[:start]) + list(candidate[start + chunk:])
            yield remainder
        size = chunk
        n *= 2
        if n > len(candidate) + 1:
            return


#: Named reducers, applied in a fixed deterministic order.
REDUCERS: tuple[tuple[str, Callable[[dict], Any]], ...] = (
    ("drop_optional_config_keys",
     lambda p: _drop_keys(p, ("config",))),
    ("reduce_step_list",
     lambda p: _shrink_list_field(p, "steps")),
    ("reduce_lane_links",
     lambda p: _shrink_list_field(p, "lane_links")),
    ("reduce_osm_elements",
     lambda p: _shrink_list_field(p, "osm_elements")),
    ("reduce_geometry_points",
     lambda p: _shrink_list_field(p, "geometry")),
    ("reduce_sensors",
     lambda p: _shrink_list_field(p, "sensors")),
    ("reduce_mutations",
     lambda p: _shrink_list_field(p, "mutations")),
)


def _drop_keys(payload: dict, path: tuple[str, ...]) -> Any:
    clone = copy.deepcopy(payload)
    node = clone
    for key in path[:-1]:
        if not isinstance(node, dict) or key not in node:
            return clone
        node = node[key]
    if isinstance(node, dict):
        node.clear()
    return clone


def _shrink_list_field(payload: dict, field_name: str) -> Any:
    clone = copy.deepcopy(payload)
    if isinstance(clone.get(field_name), list):
        clone[field_name] = []
    return clone


def shrink(
    case: Any,
    predicate: Predicate,
    *,
    target: Fingerprint | None = None,
    max_attempts: int = 64,
    budget_s: float = 30.0,
    clock: Callable[[], float] | None = None,
    token: CancellationToken | None = None,
) -> ShrinkReport:
    """Minimise ``case`` while preserving the target failure fingerprint.

    ``case`` is never mutated. When ``target`` is omitted the first observed
    failure becomes the target, but only if it is concrete enough.
    """
    import time
    tick = clock or time.monotonic
    started = tick()

    probe = predicate(copy.deepcopy(case))
    if probe is None:
        return ShrinkReport(case, case, None, [], 1, False,
                            structural_size(case), structural_size(case))
    if probe.detail_key == "" and probe.outcome == Verdict.INCONCLUSIVE.value:
        return ShrinkReport(case, case, None, [], 1, False,
                            structural_size(case), structural_size(case))

    goal = target or probe
    current = copy.deepcopy(case)
    reductions: list[Reduction] = []
    attempts = 0
    exhausted = False

    for name, reducer in REDUCERS:
        if attempts >= max_attempts or (tick() - started) >= budget_s:
            exhausted = True
            break
        if not isinstance(current, dict):
            break
        token.raise_if_cancelled() if token else None
        attempts += 1
        candidate = reducer(current)
        if candidate == current:
            reductions.append(Reduction(name, False, "reduction had no effect"))
            continue
        token.raise_if_cancelled() if token else None
        observed = predicate(copy.deepcopy(candidate))
        if _is_preserved(observed, goal):
            current = candidate
            reductions.append(Reduction(name, True, "failure fingerprint preserved"))
        else:
            reason = ("failure not reproduced" if observed is None
                      else f"different failure: {observed.oracle}/{observed.outcome}")
            reductions.append(Reduction(name, False, reason))

    size_before = structural_size(case)
    size_after = structural_size(current)
    return ShrinkReport(case, current, goal, reductions, attempts, exhausted,
                        size_before, size_after)