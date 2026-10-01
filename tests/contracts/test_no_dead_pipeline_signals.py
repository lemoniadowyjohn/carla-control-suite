# Static dead-signal gate (NEW-338 / NEW-349).
#
# A signal is "dead" when the registry can declare it but nothing in the
# running pipeline can ever satisfy it: the producer path does not resolve, no
# production source writes the artifact, or the enablement predicate names a
# setting/env var that exists nowhere.  Such a signal would be read forever as
# MISSING (or silently NOT_APPLICABLE), which is exactly the defect class this
# campaign removes.
#
# These tests are static: they never import CARLA and never run the pipeline,
# so they are safe as a pre-flight gate on any change to the registry or to a
# signal's producer.
from __future__ import annotations

import json
import sys
from pathlib import Path


WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.signals.registry import (  # noqa: E402
    SIGNAL_REGISTRY,
    SignalClass,
    artifact_relpath,
    canonical_release_profile,
    mandatory_pack_artifacts,
    required_for_profile,
)
from tools.audit_pipeline_signal_graph import audit, resolve_producer  # noqa: E402


def test_registry_has_no_dead_signals():
    report = audit()
    assert report["status"] == "PASS", json.dumps(
        {"dead_signals": report["dead_signals"],
         "problems": {f["signal_id"]: f["problems"] for f in report["findings"] if f["problems"]}},
        indent=2,
    )
    assert report["dead_count"] == 0
    assert report["signal_count"] >= 20


def test_every_producer_resolves_to_a_callable():
    unresolved = {}
    for sid, entry in SIGNAL_REGISTRY.items():
        status, detail = resolve_producer(entry.get("producer", ""))
        if status not in ("callable", "module"):
            unresolved[sid] = detail
    assert not unresolved, unresolved


def test_every_artifact_has_at_least_one_production_writer():
    report = audit()
    no_writer = {
        f["signal_id"]: f["artifact_relpath"]
        for f in report["findings"]
        if not f["writer_sites"]
    }
    assert not no_writer, no_writer


def test_every_enablement_predicate_is_known():
    report = audit()
    unknown = {
        f["signal_id"]: [p["name"] for p in f["predicates"] if not p["known"]]
        for f in report["findings"]
        if any(not p["known"] for p in f["predicates"])
    }
    assert not unknown, unknown


def test_blocking_signal_classes_are_required_by_some_profile():
    # A REQUIRED_WHEN_ENABLED / HARD_GATE signal that no release profile
    # requires can never block anything -- it is decoration, not a gate.
    orphans = {
        sid
        for sid, entry in SIGNAL_REGISTRY.items()
        if entry.get("class") in (SignalClass.HARD_GATE.value, SignalClass.REQUIRED_WHEN_ENABLED.value)
        and not (entry.get("required_release_profiles") or [])
    }
    assert not orphans, sorted(orphans)


def test_mandatory_pack_paths_resolve_to_registered_or_existing_files():
    final = "/nonexistent/final.xodr"
    for raw in ("structural_release", "visual_build", "perception_research", "debug"):
        profile = canonical_release_profile(raw)
        pack = mandatory_pack_artifacts(profile, final)
        assert final in pack, (profile, pack)
        registered = {artifact_relpath(sid) for sid in SIGNAL_REGISTRY}
        for rel in pack:
            if rel == final:
                continue
            if rel in registered:
                continue
            # Not every mandatory file is a governed signal (tile_metadata,
            # domain_gap outputs, ...), but it must be a plain relative path --
            # an absolute or traversal path would escape the run directory.
            assert not Path(rel).is_absolute(), (profile, rel)
            assert ".." not in Path(rel).parts, (profile, rel)


def test_required_signal_sets_are_stable_and_registered():
    for raw in ("structural_release", "visual_build", "perception_research", "debug"):
        profile = canonical_release_profile(raw)
        req = required_for_profile(profile)
        assert req, profile
        unknown = [sid for sid in req if sid not in SIGNAL_REGISTRY]
        assert not unknown, (profile, unknown)


def test_audit_detects_an_injected_unresolvable_producer(monkeypatch):
    sid = "__AUDIT_DEAD_PRODUCER__"
    SIGNAL_REGISTRY[sid] = {
        "signal_id": sid,
        "producer": "ultimate_pipeline.no_such_module.no_such_function",
        "artifact": "audit_dead_producer.json",
        "class": SignalClass.ADVISORY.value,
        "enabled_by": [],
        "required_release_profiles": [],
        "consumer": "final_run_verdict",
        "consumer_action": "RECORD_ADVISE",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL"],
        "missing_states": ["MISSING"],
        "skip_policy": "RECORD_IF_DISABLED",
        "missing_policy": "RECORD",
        "fields": [],
    }
    try:
        report = audit()
        assert sid in report["dead_signals"], report["dead_signals"]
        finding = next(f for f in report["findings"] if f["signal_id"] == sid)
        assert any(p.startswith("producer_unresolved") for p in finding["problems"])
        assert any(p.startswith("artifact_never_written") for p in finding["problems"])
        assert report["status"] == "FAIL"
    finally:
        SIGNAL_REGISTRY.pop(sid, None)


def test_audit_detects_a_predicate_that_nothing_defines(monkeypatch):
    sid = "__AUDIT_UNKNOWN_PREDICATE__"
    SIGNAL_REGISTRY[sid] = {
        "signal_id": sid,
        "producer": "ultimate_pipeline.quality.pipeline_health_summary.write_pipeline_health_summary",
        "artifact": "pipeline_health_summary.json",
        "class": SignalClass.ADVISORY.value,
        "enabled_by": ["TOTALLY_UNKNOWN_SETTING_XYZ"],
        "required_release_profiles": [],
        "consumer": "final_run_verdict",
        "consumer_action": "RECORD_ADVISE",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL"],
        "missing_states": ["MISSING"],
        "skip_policy": "RECORD_IF_DISABLED",
        "missing_policy": "RECORD",
        "fields": [],
    }
    try:
        report = audit()
        assert sid in report["dead_signals"], report["dead_signals"]
        finding = next(f for f in report["findings"] if f["signal_id"] == sid)
        assert any(p.startswith("unknown_predicates") for p in finding["problems"])
    finally:
        SIGNAL_REGISTRY.pop(sid, None)


def test_auditor_flags_enabled_but_missing_required_evidence(tmp_path):
    # With an explicit out dir, an enabled signal whose artifact is absent and
    # whose missing_policy is FAIL must be reported at runtime, not just
    # statically.
    report = audit(out_dir=str(tmp_path))
    assert report["status"] == "PASS", report["dead_signals"]
    findings = {f["signal_id"]: f for f in report["findings"]}
    # MAP_ACCEPTANCE has no settings/env predicate in this environment, so it
    # is always evaluated; with an empty out dir it must surface as missing.
    assert findings["MAP_ACCEPTANCE"]["runtime"]["status"] in ("MISSING", "FAIL")
    assert findings["MAP_ACCEPTANCE"]["runtime"]["present"] is False


def test_audit_report_is_json_serialisable():
    report = audit()
    json.loads(json.dumps(report))
