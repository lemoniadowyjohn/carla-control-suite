"""Operational fuzzer safety skeleton -- budgets, admission and the state machine.

Explicitly **not** built here: mutator families (Tasks 11/12) and any live
simulator control. This phase is the safety envelope those later stages run
inside.

The rules that make this safe:

* **Input is validated before anything runs.** The scenario DSL is versioned and
  a malformed scenario never reaches the state machine.
* **Budgets carry explicit units** and are refused, not clamped, when a sensor
  cannot measure a real limit. An absent VRAM probe is ``SENSOR_UNAVAILABLE``,
  never "0 MiB".
* **``Start`` is disabled until every admission check passes.** There is no
  partial start.
* **Cleanup always runs**, on crash and on cancel, and records what could not
  be restored rather than hiding it.
* **SHARED_READONLY refuses all mutation.** Isolated-live additionally requires
  an explicit Q22 server lease plus informed confirmation.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled
from ultimate_pipeline.gui.results import Result

__all__ = [
    "SCENARIO_SCHEMA", "SUPPORTED_SCENARIO_VERSIONS", "ScenarioError",
    "Budgets", "BudgetDecision", "ResourceProbe", "FuzzState", "CaseJournal",
    "Outcome", "FuzzAdmission", "FuzzerService", "DEFAULT_SEED",
]

SCENARIO_SCHEMA = "carla_fuzz_scenario/v1"
SUPPORTED_SCENARIO_VERSIONS = (SCENARIO_SCHEMA,)
DEFAULT_SEED = 20261015


class ScenarioError(ValueError):
    """The scenario is invalid. Validation always runs before execution."""


# ------------------------------------------------------------------ budgets
@dataclass(frozen=True)
class Budgets:
    """Every budget carries an explicit unit.

    Values are the *proposed* documentation defaults and are NOT user-approved
    for live use (Q22 / explicit approval required first).
    """

    case_wall_clock_s_offline: float = 300.0
    case_wall_clock_s_live: float = 900.0
    tick_limit: int = 6000
    memory_mib: int = 4096
    vram_cap_mib: int = 5632          # never the full 6144 MiB device
    disk_per_case_mib: int = 512
    max_actors: int = 25
    max_sensors: int = 12
    concurrency: int = 1

    def as_dict(self) -> dict:
        return {
            "case_wall_clock_s": {"offline": self.case_wall_clock_s_offline,
                                  "live": self.case_wall_clock_s_live, "unit": "seconds"},
            "tick_limit": {"value": self.tick_limit, "unit": "ticks"},
            "memory": {"value": self.memory_mib, "unit": "MiB"},
            "vram_cap": {"value": self.vram_cap_mib, "unit": "MiB"},
            "disk_per_case": {"value": self.disk_per_case_mib, "unit": "MiB"},
            "actors": {"value": self.max_actors, "unit": "actors"},
            "sensors": {"value": self.max_sensors, "unit": "sensors"},
            "concurrency": {"value": self.concurrency, "unit": "cases"},
            "approval_state": "PROPOSED - not user-approved for live use",
        }


class BudgetDecision(str, Enum):
    OK = "OK"
    EXCEEDED = "EXCEEDED"
    SENSOR_UNAVAILABLE = "SENSOR_UNAVAILABLE"


@dataclass(frozen=True)
class BudgetCheck:
    decision: str
    detail: str = ""
    resource: str = ""

    @property
    def admitted(self) -> bool:
        return self.decision == BudgetDecision.OK

    def as_dict(self) -> dict:
        return {"decision": self.decision, "admitted": self.admitted,
                "detail": self.detail, "resource": self.resource}


@dataclass(frozen=True)
class ResourceProbe:
    """Measured limits. Absent sensors stay absent -- they are never zero."""

    vram_free_mib: int | None = None
    disk_free_gib: float | None = None
    memory_free_mib: int | None = None

    def as_dict(self) -> dict:
        return {"vram_free_mib": self.vram_free_mib,
                "disk_free_gib": self.disk_free_gib,
                "memory_free_mib": self.memory_free_mib,
                "vram_sensor_available": self.vram_free_mib is not None}


# ------------------------------------------------------------------- states
class FuzzState(str, Enum):
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    ADMITTED = "ADMITTED"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CLEANUP = "CLEANUP"
    EVIDENCE_FINALISED = "EVIDENCE_FINALISED"


#: Legal transitions. A case that tries to skip a safety stage is refused.
TRANSITIONS: dict[FuzzState, tuple[FuzzState, ...]] = {
    FuzzState.QUEUED: (FuzzState.VALIDATING, FuzzState.CANCELLING),
    FuzzState.VALIDATING: (FuzzState.ADMITTED, FuzzState.CANCELLING),
    FuzzState.ADMITTED: (FuzzState.PREPARING, FuzzState.CANCELLING),
    FuzzState.PREPARING: (FuzzState.RUNNING, FuzzState.CANCELLING),
    FuzzState.RUNNING: (FuzzState.CANCELLING, FuzzState.CLEANUP),
    FuzzState.CANCELLING: (FuzzState.CLEANUP,),
    FuzzState.CLEANUP: (FuzzState.EVIDENCE_FINALISED,),
    FuzzState.EVIDENCE_FINALISED: (),
}


class Outcome(str, Enum):
    """Exact outcome taxonomy. No catch-all 'success'."""

    PASS = "PASS"
    FAIL = "FAIL"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CANCELLED = "CANCELLED"
    CRASHED = "CRASHED"
    NOT_ADMITTED = "NOT_ADMITTED"
    INVALID_SCENARIO = "INVALID_SCENARIO"
    TIMEOUT = "TIMEOUT"
    SENSOR_UNAVAILABLE = "SENSOR_UNAVAILABLE"


# ------------------------------------------------------------------ journal
@dataclass
class CaseJournal:
    """Append-only structured journal. Records are never rewritten."""

    path: Path
    records: list[dict] = field(default_factory=list)

    def append(self, **record: Any) -> dict:
        entry = {"seq": len(self.records), "at": time.time(), **record}
        self.records.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
            handle.flush()
        return entry

    def outcomes(self) -> list[str]:
        return [r.get("outcome", "") for r in self.records if "outcome" in r]

    def read(self) -> list[dict]:
        return list(self.records)


# ------------------------------------------------------------------ scenario
def validate_scenario(scenario: Any) -> dict:
    """Validate before execution. Never partially accepts."""
    if not isinstance(scenario, dict):
        raise ScenarioError("scenario must be a JSON object")
    schema = scenario.get("schema")
    if schema not in SUPPORTED_SCENARIO_VERSIONS:
        raise ScenarioError(
            f"unsupported scenario schema {schema!r}; "
            f"supported: {list(SUPPORTED_SCENARIO_VERSIONS)}")
    seed = scenario.get("seed")
    if seed is not None and not isinstance(seed, int):
        raise ScenarioError("seed must be an integer")
    steps = scenario.get("steps")
    if steps is not None and not isinstance(steps, list):
        raise ScenarioError("steps must be a list")
    actors = scenario.get("max_actors", 0)
    sensors = scenario.get("max_sensors", 0)
    if not isinstance(actors, int) or actors < 0:
        raise ScenarioError("max_actors must be a non-negative integer")
    if not isinstance(sensors, int) or sensors < 0:
        raise ScenarioError("max_sensors must be a non-negative integer")
    return dict(scenario)


# ------------------------------------------------------------------ service
@dataclass
class FuzzAdmission:
    checks: list[BudgetCheck] = field(default_factory=list)
    plan: dict = field(default_factory=dict)

    @property
    def admitted(self) -> bool:
        return bool(self.checks) and all(c.admitted for c in self.checks)

    @property
    def start_enabled(self) -> bool:
        """Start is disabled until EVERY admission check passes."""
        return self.admitted

    def as_dict(self) -> dict:
        return {"admitted": self.admitted, "start_enabled": self.start_enabled,
                "checks": [c.as_dict() for c in self.checks], "plan": self.plan}


class FuzzerService:
    """Safety skeleton. Owns tick; never becomes a second tick authority."""

    def __init__(
        self,
        *,
        budgets: Budgets | None = None,
        journal: CaseJournal | None = None,
        exclusive_lease_token: str = "",
        informed_confirmation: bool = False,
        probe: ResourceProbe | None = None,
    ) -> None:
        self.budgets = budgets or Budgets()
        self.journal = journal or CaseJournal(Path("fuzz_journal.jsonl"))
        self.exclusive_lease_token = exclusive_lease_token
        self.informed_confirmation = informed_confirmation
        self.probe = probe or ResourceProbe()
        self.state = FuzzState.QUEUED
        self.history: list[FuzzState] = [FuzzState.QUEUED]
        self.cleanup_runs = 0
        self.non_restorable_tm_setters: list[str] = []

    # -- transitions -------------------------------------------------------
    def _transition(self, target: FuzzState) -> Result:
        if target not in TRANSITIONS[self.state]:
            return Result.blocked(
                f"illegal transition {self.state.value} -> {target.value}",
                remediation="the safety state machine forbids skipping a stage")
        self.state = target
        self.history.append(target)
        return Result.success(target.value)

    # -- admission ---------------------------------------------------------
    def admit(self, scenario: dict, *, live: bool = False,
              authority: str = "SHARED_READONLY") -> FuzzAdmission:
        """Run every admission check. Nothing is started implicitly."""
        admission = FuzzAdmission()
        checks: list[BudgetCheck] = []

        # 1. scenario validation
        try:
            validated = validate_scenario(scenario)
            checks.append(BudgetCheck(BudgetDecision.OK, "scenario valid"))
        except ScenarioError as exc:
            checks.append(BudgetCheck(BudgetDecision.EXCEEDED, str(exc), "scenario"))
            admission.checks = checks
            self.journal.append(event="admission", outcome=Outcome.INVALID_SCENARIO.value,
                                detail=str(exc))
            return admission

        # 2. authority -- fail-closed allow-list (never a deny-list)
        from ultimate_pipeline.gui.session.session import exclusive_claimed
        if not exclusive_claimed(authority):
            checks.append(BudgetCheck(
                BudgetDecision.EXCEEDED,
                f"authority {authority!r} is not an explicit exclusive grant "
                "(only EXCLUSIVE_* authority may mutate)", "authority"))
        else:
            checks.append(BudgetCheck(BudgetDecision.OK, f"authority {authority}",
                                      "authority"))

        # 3. live requires an explicit lease AND informed confirmation
        if live:
            if not self.exclusive_lease_token:
                checks.append(BudgetCheck(
                    BudgetDecision.EXCEEDED,
                    "live fuzzing requires an exclusive server lease (Q22)", "lease"))
            if not self.informed_confirmation:
                checks.append(BudgetCheck(
                    BudgetDecision.EXCEEDED,
                    "live fuzzing requires informed operator confirmation", "confirmation"))

        # 4. declared resources against the caps
        if validated.get("max_actors", 0) > self.budgets.max_actors:
            checks.append(BudgetCheck(BudgetDecision.EXCEEDED,
                                      f"{validated['max_actors']} actors > "
                                      f"{self.budgets.max_actors}", "actors"))
        else:
            checks.append(BudgetCheck(BudgetDecision.OK, "actors within budget"))
        if validated.get("max_sensors", 0) > self.budgets.max_sensors:
            checks.append(BudgetCheck(BudgetDecision.EXCEEDED,
                                      f"{validated['max_sensors']} sensors > "
                                      f"{self.budgets.max_sensors}", "sensors"))
        else:
            checks.append(BudgetCheck(BudgetDecision.OK, "sensors within budget"))

        # 5. VRAM: refuse when the sensor is absent, never substitute zero
        if self.probe.vram_free_mib is None:
            checks.append(BudgetCheck(
                BudgetDecision.SENSOR_UNAVAILABLE,
                "VRAM probe unavailable; refusing to assume a limit of zero", "vram"))
        elif self.budgets.vram_cap_mib >= self.probe.vram_free_mib:
            checks.append(BudgetCheck(
                BudgetDecision.EXCEEDED,
                f"VRAM cap {self.budgets.vram_cap_mib} MiB must be below the "
                f"{self.probe.vram_free_mib} MiB actually free", "vram"))
        else:
            checks.append(BudgetCheck(BudgetDecision.OK, "VRAM cap below measured free"))

        # 6. disk
        if self.probe.disk_free_gib is None:
            checks.append(BudgetCheck(
                BudgetDecision.SENSOR_UNAVAILABLE,
                "disk probe unavailable", "disk"))
        else:
            needed = self.budgets.disk_per_case_mib / 1024.0
            if self.probe.disk_free_gib < needed:
                checks.append(BudgetCheck(
                    BudgetDecision.EXCEEDED,
                    f"{self.probe.disk_free_gib} GiB free < {needed:.2f} GiB needed", "disk"))
            else:
                checks.append(BudgetCheck(BudgetDecision.OK, "disk sufficient"))

        admission.checks = checks
        admission.plan = self.dry_run_plan(validated, live=live)
        self.journal.append(event="admission",
                            outcome="ADMITTED" if admission.admitted else "NOT_ADMITTED",
                            checks=[c.as_dict() for c in checks])
        return admission

    def effective_vram_cap(probe: ResourceProbe) -> int | None:
        """VRAM cap actually admissible given measured free headroom.

        The documented proposal is 5632 MiB under a 6144 MiB device. When the
        host currently reports LESS free VRAM than that (e.g. another workload
        is resident), the proposal cannot be honoured and the cap must be
        lowered rather than assumed. Returns ``None`` when no measurement
        exists -- the caller must then refuse, not substitute zero.
        """
        if probe.vram_free_mib is None:
            return None
        return min(self.budgets.vram_cap_mib, max(0, probe.vram_free_mib - 1))

    def dry_run_plan(self, scenario: dict, *, live: bool) -> dict:
        """Preview only. Nothing is executed and nothing is mutated."""
        wall = (self.budgets.case_wall_clock_s_live if live
                else self.budgets.case_wall_clock_s_offline)
        return {
            "schema": scenario.get("schema"),
            "seed": scenario.get("seed", DEFAULT_SEED),
            "steps": len(scenario.get("steps") or []),
            "wall_clock_budget_s": wall,
            "tick_budget": self.budgets.tick_limit,
            "memory_budget_mib": self.budgets.memory_mib,
            "vram_cap_mib": self.budgets.vram_cap_mib,
            "actors": scenario.get("max_actors", 0),
            "sensors": scenario.get("max_sensors", 0),
            "live": live,
            "executes": False,
            "note": "dry-run preview only; no mutation and no tick is performed",
        }

    # -- execution ---------------------------------------------------------
    def run_case(self, scenario: dict, body: Callable[[CancellationToken], Any], *,
                 live: bool = False, authority: str = "SHARED_READONLY",
                 clock: Callable[[], float] = time.monotonic) -> dict:
        """Run one case with cleanup that always happens."""
        admission = self.admit(scenario, live=live, authority=authority)
        if not admission.start_enabled:
            # Map the blocking check to an exact outcome rather than collapsing
            # every refusal into one bucket.
            blocked = {c.resource for c in admission.checks if not c.admitted}
            if "scenario" in blocked:
                outcome = Outcome.INVALID_SCENARIO.value
            elif {"vram", "disk"} & blocked and any(
                    c.decision == BudgetDecision.SENSOR_UNAVAILABLE
                    for c in admission.checks):
                outcome = Outcome.SENSOR_UNAVAILABLE.value
            else:
                outcome = Outcome.NOT_ADMITTED.value
            self.journal.append(event="case", outcome=outcome)
            return {"outcome": outcome, "admission": admission.as_dict()}

        self._transition(FuzzState.VALIDATING)
        self._transition(FuzzState.ADMITTED)
        self._transition(FuzzState.PREPARING)

        token = CancellationToken()
        outcome = Outcome.PASS.value
        error: BaseException | None = None
        started = clock()

        self._transition(FuzzState.RUNNING)
        try:
            body(token)
            # A body that returns after being cancelled must still be routed
            # through CANCELLING; otherwise a cooperative stop silently
            # completes the case and reports PASS.
            if token.cancelled:
                raise OperationCancelled(token.reason or "cancelled during run")
        except OperationCancelled:
            outcome = Outcome.CANCELLED.value
            self._transition(FuzzState.CANCELLING)
        except TimeoutError:
            outcome = Outcome.TIMEOUT.value
            self._transition(FuzzState.CANCELLING)
        except Exception as exc:
            outcome = Outcome.CRASHED.value
            error = exc
            self._transition(FuzzState.CANCELLING)

        elapsed = clock() - started
        if outcome == Outcome.PASS.value and elapsed > (
                self.budgets.case_wall_clock_s_live if live
                else self.budgets.case_wall_clock_s_offline):
            outcome = Outcome.BUDGET_EXHAUSTED.value

        # cleanup ALWAYS runs, on success, crash and cancel alike
        self._transition(FuzzState.CLEANUP)
        cleanup = self.cleanup()
        self._transition(FuzzState.EVIDENCE_FINALISED)

        cleanup_payload = {"ok": cleanup.ok, "reason": cleanup.reason,
                           "state_restored": cleanup.state_restored,
                           **(cleanup.value or {})}
        record = self.journal.append(
            event="case", outcome=outcome, elapsed_s=round(elapsed, 3),
            error=None if error is None else f"{type(error).__name__}: {error}",
            cleanup=cleanup_payload)
        return {"outcome": outcome, "elapsed_s": elapsed,
                "cleanup": cleanup_payload, "journal_seq": record["seq"]}

    def cleanup(self) -> Result:
        """Idempotent cleanup that reports what could not be restored.

        Safe to call more than once and safe to call out of band: the state
        machine already guarantees the in-run cleanup happens in ``CLEANUP``.
        Flagging a call merely because it was invoked directly would turn a
        legitimate retry into a false failure.
        """
        self.cleanup_runs += 1
        problems: list[str] = []
        if self.non_restorable_tm_setters:
            problems.append("non-restorable TM setter state: "
                            + ", ".join(self.non_restorable_tm_setters))
        if problems:
            return Result.failure("; ".join(problems),
                                  error_class="CleanupIncomplete", state_restored=False)
        return Result.success({"cleanup_runs": self.cleanup_runs})

    def as_dict(self) -> dict:
        return {"state": self.state.value,
                "history": [s.value for s in self.history],
                "budgets": self.budgets.as_dict(),
                "probe": self.probe.as_dict(),
                "journal_entries": len(self.journal.records),
                "cleanup_runs": self.cleanup_runs,
                "live_admitted": bool(self.exclusive_lease_token
                                      and self.informed_confirmation)}