"""Coverage analysis with explicit denominators.

The prompt is strict: *a coverage explorer may only appear after real
instrumentation exists; otherwise show ``NOT INSTRUMENTED``, never "0%".*

So this module tracks **execution and observability** of the things that do
exist -- the 15 registered mutator families and the 12 GUI-side oracles -- and
refuses to describe anything else. Each dimension carries its own denominator
so a percentage can never be computed against a set that was never measured.

The 43 documented upstream oracles are explicitly **NOT** claimed as
implemented; the 12 here are a verified subset and are labelled as such.

Dimensions: mutator-family, mutation-operator, input-schema-boundary, oracle
execution/observability, expected-rejection, reproducible BUG_CANDIDATE,
backend capability, simulator-dependent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from ultimate_pipeline.gui.fuzz.mutators import registry as mutator_registry
from ultimate_pipeline.gui.fuzz.oracles import ORACLES, Verdict

__all__ = [
    "CoverageStatus", "CoverageEntry", "CoverageDimension", "CoverageReport",
    "CoverageAnalyzer", "UPSTREAM_ORACLE_COUNT",
]


#: The foundation documented this many oracles. None are implemented.
UPSTREAM_ORACLE_COUNT = 43


class CoverageStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_EXECUTED = "NOT_EXECUTED"
    #: An oracle ran but the condition could not be observed. This is the
    #: verdict string produced by Verdict.UNVERIFIED and MUST map here rather
    #: than falling through to VERIFIED.
    NOT_EVALUATED = "NOT_EVALUATED"
    UNSUPPORTED = "UNSUPPORTED"
    BLOCKED = "BLOCKED"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_INSTRUMENTED = "NOT_INSTRUMENTED"


@dataclass(frozen=True)
class CoverageEntry:
    name: str
    status: str
    detail: str = ""

    @property
    def counted_as_verified(self) -> bool:
        return self.status == CoverageStatus.VERIFIED.value

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class CoverageDimension:
    """One dimension with an EXPLICIT denominator."""

    name: str
    entries: list[CoverageEntry] = field(default_factory=list)
    denominator_note: str = ""
    instrumented: bool = True

    @property
    def denominator(self) -> int:
        return len(self.entries)

    @property
    def verified(self) -> int:
        return sum(1 for e in self.entries if e.counted_as_verified)

    @property
    def fraction(self) -> float | None:
        """None when the dimension is not instrumented -- never 0.0."""
        if not self.instrumented or self.denominator == 0:
            return None
        return self.verified / self.denominator

    def as_dict(self) -> dict:
        return {"dimension": self.name,
                "denominator": self.denominator,
                "denominator_note": self.denominator_note,
                "verified": self.verified,
                "fraction": self.fraction,
                "instrumented": self.instrumented,
                "entries": [e.as_dict() for e in self.entries]}


@dataclass
class CoverageReport:
    dimensions: list[CoverageDimension]

    def dimension(self, name: str) -> CoverageDimension | None:
        return next((d for d in self.dimensions if d.name == name), None)

    def as_dict(self) -> dict:
        return {"dimensions": [d.as_dict() for d in self.dimensions],
                "upstream_oracles_documented": UPSTREAM_ORACLE_COUNT,
                "upstream_oracles_implemented": 0,
                "gui_side_oracles": len(ORACLES),
                "note": "the 12 GUI-side oracles are a verified SUBSET; the 43 "
                        "documented upstream oracles remain 0-implemented"}


class CoverageAnalyzer:
    """Builds coverage from what actually ran. Never invents a percentage."""

    def __init__(self, executed_mutators: Iterable[str] = (),
                 oracle_verdicts: dict[str, str] | None = None,
                 expected_rejections: Iterable[str] = (),
                 reproduced_bugs: Iterable[str] = (),
                 simulator_available: bool = False) -> None:
        self.executed_mutators = set(executed_mutators)
        self.oracle_verdicts = dict(oracle_verdicts or {})
        self.expected_rejections = set(expected_rejections)
        self.reproduced_bugs = set(reproduced_bugs)
        self.simulator_available = simulator_available

    def build(self) -> CoverageReport:
        dimensions: list[CoverageDimension] = []

        # A simulator-guarded family can never be legitimately reported as executed
        # without an available simulator, whatever the caller claims.
        guarded = set(mutator_registry.simulator_families())
        if self.simulator_available:
            claimed = set(self.executed_mutators)
        else:
            claimed = set(self.executed_mutators) - guarded
        rejected_claims = sorted(set(self.executed_mutators) - claimed)

        # 1. mutator-family coverage
        family = CoverageDimension("mutator_family",
                                   denominator_note="registered mutator families")
        for contract in mutator_registry.contracts():
            name = contract["name"]
            if name in claimed:
                status = CoverageStatus.VERIFIED.value
            elif contract["requires_simulator"] and not self.simulator_available:
                status = CoverageStatus.BLOCKED.value
            else:
                status = CoverageStatus.NOT_EXECUTED.value
            family.entries.append(CoverageEntry(name, status))
        dimensions.append(family)

        # 2. mutation-operator coverage: the classes EXIST, but nothing is
        # instrumented to observe them, so this is NOT a verified 100%.
        operator = CoverageDimension("mutation_operator",
                                     denominator_note="schema legality classes",
                                     instrumented=False)
        for legality in ("LEGAL", "ILLEGAL_BY_DESIGN"):
            operator.entries.append(CoverageEntry(
                legality, CoverageStatus.NOT_INSTRUMENTED.value,
                "class present in the registry; no execution instrumentation"))
        dimensions.append(operator)

        # 3. input-schema boundary coverage
        boundary = CoverageDimension("input_schema_boundary",
                                     denominator_note="scenario boundary fields")
        for field_name in ("seed", "steps", "max_actors", "max_sensors",
                           "config", "map", "georeference", "calibration"):
            boundary.entries.append(CoverageEntry(
                field_name, CoverageStatus.NOT_EXECUTED.value,
                "boundary covered by T-SCEN-* validation tests"))
        dimensions.append(boundary)

        # 4. oracle execution AND observability
        oracle_dim = CoverageDimension(
            "oracle_execution_observability",
            denominator_note="the 12 registered GUI-side oracles")
        for name in sorted(ORACLES):
            verdict = self.oracle_verdicts.get(name)
            if verdict is None:
                status = CoverageStatus.NOT_EXECUTED.value
                detail = "oracle never executed"
            elif verdict == Verdict.INCONCLUSIVE:
                # ran, but the evidence was contradictory/incomplete
                status = CoverageStatus.INCONCLUSIVE.value
                detail = "executed but the condition was not observable"
            elif verdict == Verdict.UNVERIFIED:
                # the oracle ran and reported it could not observe the condition
                status = CoverageStatus.NOT_EVALUATED.value
                detail = "ran but could not observe the condition; NOT a pass"
            elif verdict == Verdict.FAIL:
                # a FAIL is a real observation, so it is verified coverage of
                # the oracle itself -- the case outcome is reported elsewhere
                status = CoverageStatus.VERIFIED.value
                detail = f"verdict {verdict}"
            elif verdict == Verdict.BLOCKED_EXTERNAL:
                status = CoverageStatus.BLOCKED.value
                detail = "blocked by an external dependency"
            elif verdict == Verdict.PASS:
                status = CoverageStatus.VERIFIED.value
                detail = f"verdict {verdict}"
            else:
                # An unrecognised verdict is NEVER treated as a pass.
                status = CoverageStatus.NOT_EXECUTED.value
                detail = f"unrecognised verdict {verdict!r}; not counted as verified"
            oracle_dim.entries.append(CoverageEntry(name, status, detail))
        dimensions.append(oracle_dim)

        # 5. expected-rejection coverage
        rejection = CoverageDimension("expected_rejection",
                                      denominator_note="families declaring "
                                                      "INPUT_REJECTED_AS_DESIGNED")
        for contract in mutator_registry.contracts():
            if contract["expected_outcome"] != "INPUT_REJECTED_AS_DESIGNED":
                continue
            name = contract["name"]
            status = (CoverageStatus.VERIFIED.value
                      if name in self.expected_rejections and name in claimed
                      else CoverageStatus.NOT_EXECUTED.value)
            rejection.entries.append(CoverageEntry(name, status))
        dimensions.append(rejection)

        # 6. reproducible BUG_CANDIDATE coverage
        bug = CoverageDimension("reproducible_bug_candidate",
                                denominator_note="families declaring BUG_CANDIDATE")
        for contract in mutator_registry.contracts():
            if contract["expected_outcome"] != "BUG_CANDIDATE":
                continue
            name = contract["name"]
            status = (CoverageStatus.VERIFIED.value
                      if name in self.reproduced_bugs and name in claimed
                      else CoverageStatus.BLOCKED.value
                      if contract["requires_simulator"] and not self.simulator_available
                      else CoverageStatus.NOT_EXECUTED.value)
            bug.entries.append(CoverageEntry(name, status))
        dimensions.append(bug)

        # 7. backend capability coverage: presence in the package is evidence of
        # implementation, not of execution, so this dimension is reported as
        # NOT_INSTRUMENTED rather than a hard 100%.
        backend = CoverageDimension("backend_capability",
                                    denominator_note="declared GUI services",
                                    instrumented=False)
        for service in ("status", "freshness", "audit", "evidence", "tick_authority",
                        "actor_registry", "connection", "weather", "traffic_manager",
                        "calibration", "map_registry", "corpus", "replay"):
            backend.entries.append(CoverageEntry(
                service, CoverageStatus.NOT_INSTRUMENTED.value,
                "module present and unit-tested; no runtime instrumentation"))
        dimensions.append(backend)

        # 8. simulator-dependent coverage -- explicitly not instrumented here
        sim = CoverageDimension(
            "simulator_dependent", denominator_note="simulator-guarded mutator families",
            instrumented=False)
        for name in mutator_registry.simulator_families():
            sim.entries.append(CoverageEntry(
                name, CoverageStatus.NOT_INSTRUMENTED.value,
                "no simulator instrumentation exists; NOT 0% coverage"))
        dimensions.append(sim)

        return CoverageReport(dimensions)