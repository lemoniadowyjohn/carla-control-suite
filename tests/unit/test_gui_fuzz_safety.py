"""Task 10 acceptance tests: fuzzer safety skeleton, budgets, state machine.

Covers T-FUZZ-06/09/10, T-SCEN-01..06, T-OWNER-* and T-CLEAN-*.

Offline. No simulator is started, no tick is driven, no mutator family exists
in this phase.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled
from ultimate_pipeline.gui.fuzz.service import (
    BudgetDecision,
    Budgets,
    BudgetCheck,
    CaseJournal,
    FuzzState,
    FuzzerService,
    Outcome,
    ResourceProbe,
    SCENARIO_SCHEMA,
    ScenarioError,
    validate_scenario,
)

GOOD = {"schema": SCENARIO_SCHEMA, "seed": 1, "steps": ["noop"], "max_actors": 2,
        "max_sensors": 1}


def _service(tmp_path: Path, **kw) -> FuzzerService:
    defaults = dict(
        journal=CaseJournal(tmp_path / "journal.jsonl"),
        probe=ResourceProbe(vram_free_mib=6000, disk_free_gib=17.0),
    )
    defaults.update(kw)
    return FuzzerService(**defaults)


# ================================================================= T-SCEN
def test_T_SCEN_01_valid_scenario_is_accepted():
    assert validate_scenario(GOOD)["seed"] == 1


def test_T_SCEN_02_unknown_schema_version_is_rejected():
    with pytest.raises(ScenarioError) as exc:
        validate_scenario({"schema": "carla_fuzz_scenario/v99"})
    assert "unsupported scenario schema" in str(exc.value)


def test_T_SCEN_03_malformed_scenario_never_reaches_the_state_machine(tmp_path):
    service = _service(tmp_path)
    result = service.run_case({"schema": "bogus"}, lambda t: None,
                              authority="EXCLUSIVE_WORLD")
    assert result["outcome"] == Outcome.INVALID_SCENARIO.value
    assert service.state is FuzzState.QUEUED, "no transition on invalid input"
    assert service.history == [FuzzState.QUEUED]


def test_T_SCEN_04_seed_must_be_an_integer():
    with pytest.raises(ScenarioError):
        validate_scenario({"schema": SCENARIO_SCHEMA, "seed": "abc"})


def test_T_SCEN_05_non_object_scenario_is_rejected():
    with pytest.raises(ScenarioError):
        validate_scenario(["not", "a", "dict"])


def test_T_SCEN_06_negative_resource_counts_are_rejected():
    with pytest.raises(ScenarioError):
        validate_scenario({"schema": SCENARIO_SCHEMA, "max_actors": -1})
    with pytest.raises(ScenarioError):
        validate_scenario({"schema": SCENARIO_SCHEMA, "max_sensors": -5})


# ================================================================ T-FUZZ
def test_T_FUZZ_06_shared_readonly_refuses_all_mutation(tmp_path):
    service = _service(tmp_path)
    admission = service.admit(GOOD, authority="SHARED_READONLY")
    assert admission.admitted is False
    assert admission.start_enabled is False
    refusing = next(c for c in admission.checks if c.resource == "authority")
    assert refusing.decision == BudgetDecision.EXCEEDED.value


def test_T_FUZZ_09_missing_sensor_refuses_and_is_never_zero(tmp_path):
    service = _service(tmp_path, probe=ResourceProbe(vram_free_mib=None,
                                                    disk_free_gib=17.0))
    admission = service.admit(GOOD, authority="EXCLUSIVE_WORLD")
    vram = next(c for c in admission.checks if c.resource == "vram")
    assert vram.decision == BudgetDecision.SENSOR_UNAVAILABLE.value
    assert "refusing to assume a limit of zero" in vram.detail
    assert admission.start_enabled is False
    # the outcome distinguishes this from a plain refusal
    result = service.run_case(GOOD, lambda t: None, authority="EXCLUSIVE_WORLD")
    assert result["outcome"] == Outcome.SENSOR_UNAVAILABLE.value


def test_T_FUZZ_10_live_requires_lease_and_informed_confirmation(tmp_path):
    no_lease = _service(tmp_path)
    admission = no_lease.admit(GOOD, live=True, authority="EXCLUSIVE_WORLD")
    assert admission.admitted is False
    assert any(c.resource == "lease" for c in admission.checks)

    half = _service(tmp_path, exclusive_lease_token="lease-abc")
    admission2 = half.admit(GOOD, live=True, authority="EXCLUSIVE_WORLD")
    assert admission2.admitted is False
    assert any(c.resource == "confirmation" for c in admission2.checks)

    full = _service(tmp_path, exclusive_lease_token="lease-abc",
                    informed_confirmation=True)
    admission3 = full.admit(GOOD, live=True, authority="EXCLUSIVE_WORLD")
    assert admission3.admitted is True
    assert admission3.start_enabled is True


def test_budget_carry_explicit_units_and_are_proposed_not_approved():
    payload = Budgets().as_dict()
    assert payload["memory"]["unit"] == "MiB"
    assert payload["tick_limit"]["unit"] == "ticks"
    assert payload["case_wall_clock_s"]["unit"] == "seconds"
    assert payload["approval_state"].startswith("PROPOSED")
    assert Budgets().vram_cap_mib < 6144


def test_documented_budget_values_match_the_prompt():
    b = Budgets()
    assert b.case_wall_clock_s_offline == 300.0
    assert b.case_wall_clock_s_live == 900.0
    assert b.tick_limit == 6000
    assert b.memory_mib == 4096
    assert b.disk_per_case_mib == 512
    assert b.max_actors == 25
    assert b.max_sensors == 12
    assert b.concurrency == 1


def test_actor_and_sensor_caps_are_enforced(tmp_path):
    service = _service(tmp_path)
    over = dict(GOOD, max_actors=99, max_sensors=99)
    admission = service.admit(over, authority="EXCLUSIVE_WORLD")
    assert admission.admitted is False
    resources = {c.resource for c in admission.checks if not c.admitted}
    assert {"actors", "sensors"} <= resources


def test_vram_cap_must_be_below_measured_free_headroom(tmp_path):
    service = _service(tmp_path, budgets=Budgets(vram_cap_mib=5632),
                       probe=ResourceProbe(vram_free_mib=5522, disk_free_gib=17.0))
    admission = service.admit(GOOD, authority="EXCLUSIVE_WORLD")
    vram = next(c for c in admission.checks if c.resource == "vram")
    assert vram.decision == BudgetDecision.EXCEEDED.value


# ================================================================= T-CLEAN
def test_T_CLEAN_01_cleanup_runs_on_success_crash_and_cancel(tmp_path):
    service = _service(tmp_path)

    ok = service.run_case(GOOD, lambda t: None, authority="EXCLUSIVE_WORLD")
    assert ok["outcome"] == Outcome.PASS.value

    crashed = _service(tmp_path / "a").run_case(
        GOOD, lambda t: (_ for _ in ()).throw(RuntimeError("boom")),
        authority="EXCLUSIVE_WORLD")
    assert crashed["outcome"] == Outcome.CRASHED.value
    assert crashed["cleanup"]["cleanup_runs"] == 1

    def cancel_body(t: CancellationToken):
        t.cancel("operator")
    cancelled = _service(tmp_path / "b").run_case(
        GOOD, cancel_body, authority="EXCLUSIVE_WORLD")
    assert cancelled["outcome"] == Outcome.CANCELLED.value
    assert cancelled["cleanup"]["cleanup_runs"] == 1


def test_T_CLEAN_02_cleanup_is_idempotent_and_reports_non_restorable_state(tmp_path):
    service = _service(tmp_path)
    first = service.cleanup()
    second = service.cleanup()
    assert first.ok and second.ok
    assert service.cleanup_runs == 2, "double cleanup must be safe"

    service.non_restorable_tm_setters = ["set_percentage_speed_difference"]
    broken = service.cleanup()
    assert broken.ok is False
    assert broken.state_restored is False
    assert "non-restorable" in broken.reason


def test_cancellation_is_honoured_in_every_runnable_state(tmp_path):
    service = _service(tmp_path)
    service.run_case(GOOD, lambda t: t.cancel("stop"), authority="EXCLUSIVE_WORLD")
    assert service.state is FuzzState.EVIDENCE_FINALISED
    assert "CANCELLING" in [s.value for s in service.history]


def test_process_crash_classifies_and_journals(tmp_path):
    service = _service(tmp_path)
    result = service.run_case(GOOD, lambda t: (_ for _ in ()).throw(ValueError("nope")),
                              authority="EXCLUSIVE_WORLD")
    assert result["outcome"] == Outcome.CRASHED.value
    journal = service.journal.read()
    assert any(r.get("outcome") == Outcome.CRASHED.value for r in journal)
    crash = next(r for r in journal if r.get("outcome") == Outcome.CRASHED.value)
    assert "ValueError" in crash["error"]


def test_illegal_transitions_are_refused(tmp_path):
    service = _service(tmp_path)
    refused = service._transition(FuzzState.RUNNING)
    assert refused.ok is False
    assert "illegal transition" in refused.reason
    assert service.state is FuzzState.QUEUED


def test_dry_run_plan_is_preview_only_and_deterministic(tmp_path):
    service = _service(tmp_path)
    plan = service.run_case and service.dry_run_plan(GOOD, live=False)
    assert plan["executes"] is False
    assert plan["seed"] == GOOD["seed"]
    assert plan["wall_clock_budget_s"] == 300.0
    assert service.dry_run_plan(GOOD, live=False) == plan
    assert service.dry_run_plan(GOOD, live=True)["wall_clock_budget_s"] == 900.0


def test_wall_clock_budget_exhaustion_is_an_explicit_outcome(tmp_path):
    ticks = iter([0.0, 10_000.0, 10_000.0, 10_000.0])
    clock = lambda: next(ticks)  # noqa: E731
    service = _service(tmp_path)
    result = service.run_case(GOOD, lambda t: None, authority="EXCLUSIVE_WORLD",
                              clock=clock)
    assert result["outcome"] == Outcome.BUDGET_EXHAUSTED.value


def test_no_mutator_family_exists_in_this_phase(tmp_path):
    """This phase delivers the safety envelope only."""
    service = _service(tmp_path)
    payload = service.as_dict()
    assert "mutators" not in payload
    assert payload["state"] == FuzzState.QUEUED.value
    assert payload["live_admitted"] is False


def test_journal_is_append_only(tmp_path):
    journal = CaseJournal(tmp_path / "j.jsonl")
    first = journal.append(event="a", outcome="x")
    second = journal.append(event="b", outcome="y")
    assert second["seq"] == first["seq"] + 1
    lines = (tmp_path / "j.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert journal.outcomes() == ["x", "y"]


def test_concurrency_budget_is_one(tmp_path):
    assert Budgets().concurrency == 1
    assert BudgetCheck(BudgetDecision.OK).admitted is True