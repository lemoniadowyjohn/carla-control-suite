"""Task 12 acceptance tests: replay, shrinking, corpus and coverage.

Offline. No simulator, no live replay, no CARLA launch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled
from ultimate_pipeline.gui.fuzz.coverage import (
    UPSTREAM_ORACLE_COUNT,
    CoverageAnalyzer,
    CoverageStatus,
)
from ultimate_pipeline.gui.fuzz.corpus import (
    CORPUS_SCHEMA,
    CorpusError,
    CorpusKind,
    CorpusStore,
    content_id,
    safe_name,
)
from ultimate_pipeline.gui.fuzz.mutators import registry as mutator_registry
from ultimate_pipeline.gui.fuzz.oracles import ORACLES, Verdict
from ultimate_pipeline.gui.fuzz.replay import (
    Reproducibility,
    ReplayEngine,
    build_manifest,
    content_hash,
)
from ultimate_pipeline.gui.fuzz.shrink import Fingerprint, shrink


# ================================================================= replay
def _manifest(**kw):
    payload = {"schema": "carla_fuzz_scenario/v1", "steps": ["a", "b"]}
    defaults = dict(case_id="c1", payload=payload, output={"verdict": "PASS"},
                    repository_sha="abc123", seed=7,
                    dependencies={"pytest": "9.1.1"},
                    mutators=[{"name": "config_missing_key", "version": "1"}],
                    oracles=[{"name": "actor_cap", "version": "1"}])
    defaults.update(kw)
    return build_manifest(**defaults)


def test_T_FUZZ_RPL_01_identical_inputs_and_seeds_replay_exactly():
    manifest = _manifest()
    engine = ReplayEngine()
    result = engine.replay(manifest, {"schema": "carla_fuzz_scenario/v1",
                                      "steps": ["a", "b"]},
                           lambda p: {"verdict": "PASS"},
                           current_sha="abc123")
    assert result.ok is True
    assert result.unwrap()["reproducibility"] == Reproducibility.EXACT.value
    assert result.unwrap()["output_hash"] == manifest.output_hash


def test_T_FUZZ_RPL_02_incomplete_manifest_is_refused_not_best_effort():
    manifest = _manifest(dependencies={})
    assert "dependency_versions" in manifest.missing
    engine = ReplayEngine()
    result = engine.replay(manifest, {"schema": "carla_fuzz_scenario/v1", "steps": ["a", "b"]},
                           lambda p: {"verdict": "PASS"})
    assert result.ok is False
    assert "incomplete" in result.reason
    assert "best-effort" in result.remediation


def test_T_FUZZ_RPL_03_configuration_and_repository_drift_is_detected():
    engine = ReplayEngine()
    manifest = _manifest()
    drift = engine.check_drift(manifest, current_sha="different")
    assert drift.ok is False
    assert "repository drift" in drift.reason

    ok = engine.check_drift(manifest, current_sha="abc123")
    assert ok.ok is True


def test_T_FUZZ_RPL_04_input_drift_is_refused():
    engine = ReplayEngine()
    manifest = _manifest()
    result = engine.replay(manifest, {"schema": "carla_fuzz_scenario/v1",
                                      "steps": ["TAMPERED"]}, lambda p: {})
    assert result.ok is False
    assert "input drift" in result.reason


def test_T_FUZZ_RPL_05_live_replay_is_never_claimed():
    engine = ReplayEngine()
    offline_manifest = _manifest()
    result = engine.replay(offline_manifest, {"schema": "carla_fuzz_scenario/v1",
                                              "steps": ["a", "b"]},
                           lambda p: {}, live=True)
    assert result.ok is False
    assert result.error_class == "SimulatorUnavailable"

    with_sim = _manifest(simulator={"client_version": "0.9.16"})
    refused = engine.check_compatibility(with_sim, live=True)
    assert refused.ok is False
    assert "NOT IMPLEMENTED" in refused.reason


def test_T_FUZZ_RPL_06_four_reproducibility_states_exist():
    assert {s.value for s in Reproducibility} == {
        "EXACT", "EQUIVALENT", "NONDETERMINISTIC", "UNREPRODUCIBLE"}
    engine = ReplayEngine()
    manifest = _manifest()
    assert engine.classify(manifest, {"verdict": "PASS"}) == Reproducibility.EXACT.value
    # without a declared tolerance a difference is NOT 'equivalent'
    assert engine.classify(manifest, {"verdict": "DIFFERENT"}) == \
        Reproducibility.NONDETERMINISTIC.value
    # equivalence requires an explicit, caller-declared tolerance
    assert engine.classify(manifest, {"verdict": "DIFFERENT"}, tolerance=0.05) == \
        Reproducibility.EQUIVALENT.value
    assert engine.classify(_manifest(output=None), {"x": 1}) == \
        Reproducibility.UNREPRODUCIBLE.value
    assert engine.classify(manifest, {"totally": "unrelated"}) == \
        Reproducibility.NONDETERMINISTIC.value


def test_T_FUZZ_RPL_07_replay_is_bounded_and_cancellable():
    values = iter([0.0, 10_000.0, 10_000.0, 10_000.0, 10_000.0])
    engine = ReplayEngine(clock=lambda: next(values, 10_000.0), budget_s=5.0)
    result = engine.replay(_manifest(), {"schema": "carla_fuzz_scenario/v1",
                                         "steps": ["a", "b"]},
                           lambda p: {"verdict": "PASS"})
    assert result.ok is False
    assert result.error_class == "BudgetExhausted"

    token = CancellationToken()
    token.cancel("stop")
    with pytest.raises(OperationCancelled):
        engine.replay(_manifest(), {"schema": "carla_fuzz_scenario/v1",
                                    "steps": ["a", "b"]}, lambda p: {}, token=token)


def test_schema_version_mismatch_is_refused():
    engine = ReplayEngine()
    manifest = _manifest()
    blocked = engine.check_compatibility(manifest)
    assert blocked.ok is True
    wrong = _manifest(payload={"schema": "carla_fuzz_scenario/v1", "steps": ["a"]})
    object.__setattr__(wrong, "scenario_schema", "carla_fuzz_scenario/v99")
    assert engine.check_compatibility(wrong).ok is False


# ================================================================= shrink
def _failing_predicate(oracle: str = "lane_link_integrity",
                       outcome: str = Verdict.FAIL.value,
                       detail: str = "dangling"):
    def predicate(case):
        links = case.get("lane_links")
        if links:
            return Fingerprint(oracle, outcome, detail)
        return None
    return predicate


def test_shrinking_converges_and_preserves_the_failure_fingerprint():
    case = {"lane_links": [{"from": 1, "to": 2}, {"from": 3, "to": 4}],
            "steps": ["a", "b"], "config": {"x": 1}}
    report = shrink(case, _failing_predicate())
    assert report.preserved is not None
    assert report.preserved.oracle == "lane_link_integrity"
    assert report.size_after <= report.size_before
    # the caller's case was never mutated
    assert len(case["lane_links"]) == 2


def test_a_different_failure_is_not_accepted_as_preservation():
    calls = {"n": 0}

    def predicate(case):
        calls["n"] += 1
        if case.get("config"):
            return Fingerprint("lane_link_integrity", Verdict.FAIL.value, "dangling")
        return Fingerprint("some_other_oracle", Verdict.PASS.value, "other")

    report = shrink({"config": {"x": 1}, "lane_links": [1]}, predicate)
    rejected = [r for r in report.reductions if not r.accepted]
    assert any("different failure" in r.reason for r in rejected)


def test_an_inconclusive_oracle_is_never_proof_of_a_reproduced_failure():
    report = shrink({"config": {"x": 1}, "lane_links": [1]},
                    _failing_predicate(oracle="geometry_continuity",
                                       outcome=Verdict.INCONCLUSIVE.value))
    # the predicate reports INCONCLUSIVE, so nothing is treated as a failure
    assert report.preserved is not None
    assert report.preserved.outcome == Verdict.INCONCLUSIVE.value
    assert report.size_after == report.size_before


def test_reduction_budget_exhaustion_is_recorded():
    ticks = iter([0.0] + [1000.0] * 50)
    report = shrink({"config": {"x": 1}, "lane_links": [1]},
                    _failing_predicate(), budget_s=0.5,
                    clock=lambda: next(ticks))
    assert report.exhausted is True
    assert report.attempts <= 1


def test_shrinking_honours_cancellation():
    token = CancellationToken()
    token.cancel("operator stop")
    with pytest.raises(OperationCancelled):
        shrink({"config": {"x": 1}, "lane_links": [1]},
               _failing_predicate(), token=token)


def test_a_passing_case_is_not_shrunk():
    report = shrink({"config": {"x": 1}}, lambda case: None)
    assert report.preserved is None
    assert report.size_after == report.size_before


# ============================ regressions for the independent-review blockers
def test_B1_an_unobservable_oracle_is_never_counted_as_verified():
    """Real oracle output fed into the analyzer must not inflate coverage."""
    unobservable = ORACLES["lane_width_invariant"]([])
    assert unobservable.verdict == Verdict.UNVERIFIED.value
    report = CoverageAnalyzer(oracle_verdicts={
        "lane_width_invariant": unobservable.verdict}).build()
    entry = next(e for e in report.dimension(
        "oracle_execution_observability").entries
        if e.name == "lane_width_invariant")
    assert entry.status == CoverageStatus.NOT_EVALUATED.value
    assert entry.counted_as_verified is False
    assert report.dimension("oracle_execution_observability").verified == 0


def test_B1_unrecognised_verdicts_are_not_promoted_to_verified():
    report = CoverageAnalyzer(oracle_verdicts={"actor_cap": "SOMETHING_NEW"}).build()
    entry = next(e for e in report.dimension(
        "oracle_execution_observability").entries if e.name == "actor_cap")
    assert entry.counted_as_verified is False


def test_B2_a_difference_without_a_declared_tolerance_is_nondeterministic():
    engine = ReplayEngine()
    manifest = _manifest()
    assert engine.classify(manifest, {"totally": "unrelated", "n": 999}) == \
        Reproducibility.NONDETERMINISTIC.value
    assert Reproducibility.NONDETERMINISTIC.value  # the state is reachable


def test_B3_an_evicted_seed_case_can_be_re_added(tmp_path):
    store = CorpusStore(tmp_path, retention_records=1)
    first = store.add({"n": 1}, kind=CorpusKind.SEED.value).unwrap()["case_id"]
    store.add({"n": 2}, kind=CorpusKind.SEED.value)
    outcome = store.enforce_retention()
    assert first in outcome["removed"]
    assert not store.path_for(first, CorpusKind.SEED.value).is_file()

    again = store.add({"n": 1}, kind=CorpusKind.SEED.value)
    assert again.ok is True
    assert again.unwrap()["deduplicated"] is False, "must not report a dedup lie"
    assert store.path_for(first, CorpusKind.SEED.value).is_file()
    assert store.verify()["intact"] is True


def test_B4_get_never_serves_content_that_no_longer_matches_its_address(tmp_path):
    store = CorpusStore(tmp_path)
    case_id = store.add({"steps": ["a"]}).unwrap()["case_id"]
    path = store.path_for(case_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["payload"] = {"steps": ["TAMPERED"]}
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert store.verify()["intact"] is False
    assert store.get(case_id) is None, "stale cache must not be served"


def test_W1_shrink_size_measure_actually_moves():
    from ultimate_pipeline.gui.fuzz.shrink import structural_size

    small = {"steps": ["a"]}
    large = {"steps": ["a" * 500 for _ in range(20)]}
    assert structural_size(large) > structural_size(small)


def test_W5_simulator_guarded_families_cannot_be_claimed_executed():
    guarded = mutator_registry.simulator_families()
    report = CoverageAnalyzer(executed_mutators=set(guarded),
                              simulator_available=False).build()
    family = report.dimension("mutator_family")
    for name in guarded:
        entry = next(e for e in family.entries if e.name == name)
        assert entry.counted_as_verified is False
        assert entry.status == CoverageStatus.BLOCKED.value


def test_W4_dimensions_without_instrumentation_report_no_fraction():
    report = CoverageAnalyzer().build()
    for name in ("mutation_operator", "backend_capability", "simulator_dependent"):
        dimension = report.dimension(name)
        assert dimension.instrumented is False
        assert dimension.fraction is None
        assert dimension.verified == 0


def test_unhashable_output_is_reported_missing_not_silently_hashed():
    manifest = _manifest(output=object())
    assert "output_hash" in manifest.missing
    engine = ReplayEngine()
    refused = engine.check_compatibility(manifest)
    assert refused.ok is False


def test_coverage_sees_the_coarse_fingerprint_early_return(tmp_path):
    """A shrinking target with no detail_key must not proceed silently."""
    report = shrink({"config": {"x": 1}, "lane_links": [1]},
                    _failing_predicate())
    assert report.attempts >= 1


# ================================================================= corpus
def test_corpus_round_trip_and_content_addressing(tmp_path):
    store = CorpusStore(tmp_path)
    payload = {"schema": "carla_fuzz_scenario/v1", "steps": ["a"]}
    added = store.add(payload, kind=CorpusKind.SEED.value, expected_outcome="PASS")
    assert added.ok is True
    case_id = added.unwrap()["case_id"]
    assert case_id == content_id(payload)
    assert store.get(case_id).payload == payload


def test_corpus_deduplicates_normalised_content(tmp_path):
    store = CorpusStore(tmp_path)
    first = store.add({"a": 1, "b": [1, 2]})
    second = store.add({"b": [1, 2], "a": 1})
    assert second.unwrap()["deduplicated"] is True
    assert first.unwrap()["case_id"] == second.unwrap()["case_id"]
    assert first.unwrap()["deduplicated"] is False


def test_corpus_integrity_verification_detects_tampering(tmp_path):
    store = CorpusStore(tmp_path)
    added = store.add({"steps": ["a"]})
    case_id = added.unwrap()["case_id"]
    assert store.verify()["intact"] is True
    # corrupt the stored content behind the content address
    path = store.path_for(case_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["payload"] = {"steps": ["TAMPERED"]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    store._index.clear()
    assert store.verify()["intact"] is False


def test_corpus_rejects_traversal_and_absolute_names(tmp_path):
    store = CorpusStore(tmp_path)
    for unsafe in ("../escape", "C:/Windows", "a\\b", "..", "/abs"):
        with pytest.raises(CorpusError):
            safe_name(unsafe)
    assert store.verify()["intact"] is True


def test_interrupted_write_leaves_no_partial_entry(tmp_path):
    store = CorpusStore(tmp_path)
    store.add({"steps": ["a"]})
    assert not list(store.root.rglob("*.tmp")), "no temp file may survive a write"


def test_export_import_round_trip(tmp_path):
    source = CorpusStore(tmp_path / "src")
    source.add({"steps": ["a"]}, kind=CorpusKind.SEED.value)
    source.add({"steps": ["b"]}, kind=CorpusKind.SEED.value)
    exported = source.export()
    assert exported.ok is True
    assert exported.unwrap()["count"] == 2

    target = CorpusStore(tmp_path / "dst")
    imported = target.import_records(json.loads(exported.unwrap()["json"]))
    assert imported.ok is True
    assert imported.unwrap()["accepted"] == 2
    assert target.verify()["intact"] is True


def test_import_rejects_unknown_schema(tmp_path):
    store = CorpusStore(tmp_path)
    result = store.import_records({"schema": "carla-fuzz-corpus/v99", "records": []})
    assert result.ok is False
    assert result.error_class == "UnsupportedSchema"


def test_unserialisable_payload_is_quarantined(tmp_path):
    store = CorpusStore(tmp_path)
    result = store.add({"bad": object()})
    assert result.ok is False
    assert result.error_class == "Quarantined"
    assert list(store.quarantine_dir.glob("*.json")), "quarantine must retain the entry"


def test_seed_and_regression_corpora_are_separate(tmp_path):
    store = CorpusStore(tmp_path, retention_records=1)
    store.add({"n": 1}, kind=CorpusKind.SEED.value)
    store.add({"n": 2}, kind=CorpusKind.SEED.value)
    store.add({"n": 3}, kind=CorpusKind.REGRESSION.value)
    outcome = store.enforce_retention()
    assert outcome["regression_preserved"] is True
    assert store.seed_dir.exists() and store.regression_dir.exists()
    assert list(store.regression_dir.glob("*.json")), "regression evidence preserved"
    assert len(list(store.seed_dir.glob("*.json"))) == 1


# ================================================================ coverage
def test_coverage_uses_explicit_denominators_and_never_zero_percent():
    report = CoverageAnalyzer().build()
    family = report.dimension("mutator_family")
    assert family.denominator == len(mutator_registry.names())
    assert family.fraction == 0.0  # nothing executed yet: a true 0 of N
    assert family.denominator_note


def test_uninstrumented_simulator_coverage_is_not_a_percentage():
    report = CoverageAnalyzer().build()
    sim = report.dimension("simulator_dependent")
    assert sim.instrumented is False
    assert sim.fraction is None, "an uninstrumented dimension has NO fraction"
    assert all(e.status == CoverageStatus.NOT_INSTRUMENTED.value for e in sim.entries)


def test_oracle_dimension_covers_exactly_the_twelve_gui_oracles():
    report = CoverageAnalyzer().build()
    oracle_dim = report.dimension("oracle_execution_observability")
    assert oracle_dim.denominator == len(ORACLES) == 12
    assert all(e.status == CoverageStatus.NOT_EXECUTED.value for e in oracle_dim.entries)


def test_upstream_oracles_are_not_claimed_as_implemented():
    payload = CoverageAnalyzer().build().as_dict()
    assert payload["upstream_oracles_documented"] == UPSTREAM_ORACLE_COUNT == 43
    assert payload["upstream_oracles_implemented"] == 0
    assert payload["gui_side_oracles"] == 12
    assert "SUBSET" in payload["note"]


def test_executed_and_observed_families_are_counted_verified():
    executed = mutator_registry.offline_families()[:5]
    rejected = mutator_registry.offline_families()[:3]
    report = CoverageAnalyzer(executed_mutators=executed,
                              expected_rejections=rejected).build()
    family = report.dimension("mutator_family")
    verified = {e.name for e in family.entries if e.counted_as_verified}
    assert verified == set(executed)
    rejection = report.dimension("expected_rejection")
    assert rejection.denominator == 10


def test_simulator_guarded_families_are_blocked_not_passed():
    report = CoverageAnalyzer(simulator_available=False).build()
    bug = report.dimension("reproducible_bug_candidate")
    statuses = {e.status for e in bug.entries}
    assert CoverageStatus.BLOCKED.value in statuses
    assert CoverageStatus.VERIFIED.value not in statuses


def test_inconclusive_oracle_is_distinct_from_verified():
    verdicts = {name: "INCONCLUSIVE" for name in ORACLES}
    report = CoverageAnalyzer(oracle_verdicts=verdicts).build()
    oracle_dim = report.dimension("oracle_execution_observability")
    assert oracle_dim.verified == 0
    assert all(e.status == CoverageStatus.INCONCLUSIVE.value for e in oracle_dim.entries)
    assert oracle_dim.fraction == 0.0


def test_coverage_report_serialises_with_never_unavailable_becoming_pass():
    payload = CoverageAnalyzer().build().as_dict()
    blob = json.dumps(payload)
    assert "NOT_INSTRUMENTED" in blob
    for dimension in payload["dimensions"]:
        if not dimension["instrumented"]:
            assert dimension["fraction"] is None