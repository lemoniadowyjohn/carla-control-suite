"""Task 11 acceptance tests: mutator families and independent oracles.

Covers the T-FUZZ-NEG-* and T-FUZZ-OR-* families plus determinism and XML
security negatives.

Offline. No simulator is touched; the five simulator-guarded families are only
*built*, never executed.
"""

from __future__ import annotations

import pytest

from ultimate_pipeline.gui.fuzz.mutators import MutatorFamily, registry
from ultimate_pipeline.gui.fuzz.oracles import (
    Verdict,
    actor_cap,
    cleanup_leak_check,
    determinism_signature,
    geometry_continuity,
    lane_link_integrity,
    lane_width_invariant,
    oracle_registry,
    replay_verdict_match,
    road_s_invariant,
    sensor_frame_attribution,
    sync_restored,
    tm_write_only_ack,
    xml_safe_parse,
)
from ultimate_pipeline.gui.sensors.queues import Frame


# ============================================================ mutators
def test_fifteen_families_are_separately_registered_with_contracts():
    assert len(registry.names()) == 15
    for contract in registry.contracts():
        assert contract["name"]
        assert contract["input_preconditions"]
        assert contract["schema_legality"] in ("LEGAL", "ILLEGAL_BY_DESIGN")
        assert contract["expected_outcome"] in ("INPUT_REJECTED_AS_DESIGNED", "BUG_CANDIDATE")
        assert contract["max_work_cost"]
        assert isinstance(contract["reversible"], bool)


def test_config_boundary_families_cover_missing_invalid_and_range():
    payload = registry.get("config_missing_key").run("c1", 7).payload
    assert payload["config"]["missing_key"] == "__ABSENT__"
    invalid = registry.get("config_invalid_type").run("c2", 7).payload
    assert invalid["config"]["tick_limit"] == "not-an-integer"
    out_of_range = registry.get("config_out_of_range").run("c3", 7).payload
    assert out_of_range["config"]["tick_limit"] > 6000


def test_map_families_produce_illegal_payloads_by_design():
    assert "<OpenDRIVE><road></OpenDRIVE>" in registry.get("malformed_xodr").run("m", 1).payload["map"]["xodr_text"]
    assert "<!DOCTYPE" in registry.get("xodr_with_doctype").run("m", 1).payload["map"]["xodr_text"]
    osm = registry.get("osm_constrained").run("m", 1).payload["map"]["osm_elements"][0]
    assert osm["lat"] > 90.0 or osm["lon"] > 180.0
    assert registry.get("dangling_lane_link").run("m", 1).payload["map"]["lane_links"][0]["to"] == 99999


def test_simulator_families_are_guarded_and_never_offline_executable():
    guarded = registry.simulator_families()
    assert len(guarded) == 5
    for name in guarded:
        contract = next(c for c in registry.contracts() if c["name"] == name)
        assert contract["requires_simulator"] is True
        assert contract["reversible"] is False
        payload = registry.get(name).run(name, 1).payload
        assert payload["requires_exclusive_world"] is True
    for name in registry.offline_families():
        assert all(c["requires_simulator"] is False
                   for c in registry.contracts() if c["name"] == name)


def test_cases_are_isolated_with_no_cross_contamination():
    base = {"shared": {"keep": True}}
    first = registry.get("config_missing_key").run("a", 1, base).payload
    second = registry.get("config_missing_key").run("b", 2, base).payload
    assert base == {"shared": {"keep": True}}, "the caller's base must not be mutated"
    assert first is not second


def test_mutators_are_deterministic_for_a_seed():
    a = registry.get("config_missing_key").run("x", 42).payload
    b = registry.get("config_missing_key").run("x", 42).payload
    assert a == b
    c = registry.get("config_missing_key").run("x", 43).payload
    assert c["seed"] == 43


def test_expected_rejection_is_separate_from_discovered_bug():
    rejected = [c for c in registry.contracts()
                if c["expected_outcome"] == "INPUT_REJECTED_AS_DESIGNED"]
    bugs = [c for c in registry.contracts() if c["expected_outcome"] == "BUG_CANDIDATE"]
    assert len(rejected) == 10 and len(bugs) == 5


# ============================================================== oracles
def test_twelve_oracles_are_registered():
    assert len(oracle_registry()) == 12


def test_xml_oracle_observes_independently():
    hostile = ('<!DOCTYPE lolz [<!ENTITY lol "lol">]>'
               '<OpenDRIVE><road name="&lol;"/></OpenDRIVE>')
    result = xml_safe_parse(hostile)
    assert result.verdict == Verdict.PASS.value
    assert result.evidence["refused"] is True
    assert result.expected == result.actual


def test_lane_and_road_invariants():
    assert lane_width_invariant([3.5, 3.5]).verdict == Verdict.PASS.value
    assert lane_width_invariant([3.5, 0.0]).verdict == Verdict.FAIL.value
    assert lane_width_invariant([]).verdict == Verdict.UNVERIFIED.value

    assert road_s_invariant([0.0, 10.0, 20.0]).verdict == Verdict.PASS.value
    assert road_s_invariant([0.0, -1.0]).verdict == Verdict.FAIL.value
    assert road_s_invariant([10.0, 5.0]).verdict == Verdict.FAIL.value


def test_lane_link_integrity_detects_dangling_references():
    result = lane_link_integrity([1, 2, 3], [(1, 2), (2, 99)])
    assert result.verdict == Verdict.FAIL.value
    assert result.evidence["dangling"] == [{"from": 2, "to": 99}]
    assert lane_link_integrity([], []).verdict == Verdict.UNVERIFIED.value


def test_determinism_oracle_needs_two_runs():
    assert determinism_signature(["sig"]).verdict == Verdict.UNVERIFIED.value
    assert determinism_signature(["a", "a"]).verdict == Verdict.PASS.value
    assert determinism_signature(["a", "b"]).verdict == Verdict.FAIL.value


def test_geometry_continuity_never_invents_a_threshold():
    pts = [(0.0, 0.0, 0.0), (1000.0, 0.0, 0.0)]
    undecided = geometry_continuity(pts)
    assert undecided.verdict == Verdict.INCONCLUSIVE.value
    assert undecided.observable is False
    assert undecided.confidence == "NONE"
    assert "max step" in undecided.actual
    # an owner-supplied bound makes it decidable
    assert geometry_continuity(pts, max_step_m=10.0).verdict == Verdict.FAIL.value
    assert geometry_continuity([(0, 0, 0), (1, 0, 0)], max_step_m=10.0).verdict \
        == Verdict.PASS.value


def test_actor_cap_and_leak_oracles():
    assert actor_cap(25, 25).verdict == Verdict.PASS.value
    assert actor_cap(26, 25).verdict == Verdict.FAIL.value
    assert cleanup_leak_check([]).verdict == Verdict.PASS.value
    assert cleanup_leak_check([7]).verdict == Verdict.FAIL.value


def test_sync_restore_oracle():
    assert sync_restored(True).verdict == Verdict.PASS.value
    assert sync_restored(False).verdict == Verdict.FAIL.value


def test_sensor_frame_attribution_never_fabricates():
    assert sensor_frame_attribution(Frame(frame_id=5, timestamp=1.0)).verdict \
        == Verdict.PASS.value
    assert sensor_frame_attribution(None).verdict == Verdict.UNVERIFIED.value
    missing = sensor_frame_attribution(Frame.__new__(Frame))
    assert missing.verdict in (Verdict.FAIL.value, Verdict.UNVERIFIED.value)


def test_replay_verdict_comparison():
    assert replay_verdict_match("PASS", "PASS").verdict == Verdict.PASS.value
    assert replay_verdict_match("PASS", "FAIL").verdict == Verdict.FAIL.value


def test_tm_write_only_ack_is_never_a_confirmation():
    result = tm_write_only_ack("set_percentage_speed_difference", readable=False)
    assert result.verdict == Verdict.INCONCLUSIVE.value
    assert result.observable is False
    assert "not confirmed" in result.expected
    assert tm_write_only_ack("auto_lane_change", readable=True).verdict == Verdict.PASS.value


def test_no_oracle_passes_without_evidence():
    """Every oracle returns evidence, confidence and expected-vs-actual."""
    samples = [
        xml_safe_parse('<r/>'),
        lane_width_invariant([3.0]),
        road_s_invariant([0.0]),
        lane_link_integrity([1], [(1, 1)]),
        determinism_signature(["a", "a"]),
        geometry_continuity([(0, 0, 0), (1, 0, 0)], max_step_m=5.0),
        actor_cap(1, 25),
        cleanup_leak_check([]),
        sync_restored(True),
        sensor_frame_attribution(Frame(frame_id=1, timestamp=0.0)),
        replay_verdict_match("PASS", "PASS"),
        tm_write_only_ack("auto_lane_change", readable=True),
    ]
    assert len(samples) == 12
    for result in samples:
        payload = result.as_dict()
        assert payload["oracle"]
        assert payload["confidence"] in ("HIGH", "MEDIUM", "LOW", "NONE")
        assert "evidence" in payload
        assert payload["expected"] or payload["verdict"] != Verdict.PASS.value


def test_inconclusive_is_never_counted_as_a_pass():
    inconclusive = geometry_continuity([(0, 0, 0), (5, 0, 0)])
    assert inconclusive.verdict == Verdict.INCONCLUSIVE.value
    assert inconclusive.passed is False