"""V86: strict mandatory-gate schema, artifact identity, XML boundary, entrypoint policy.

Every test runs real production code. Fixtures are minimal synthetic OpenDRIVE.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ultimate_pipeline.quality import final_artifact_gates as fag
from ultimate_pipeline.quality.map_acceptance import build_map_acceptance

REPO = Path(__file__).resolve().parents[2]

VALID_HEADER = '<header revMajor="1" revMinor="4" name="t"/>'


def _road(rid, x0, succ=None, pred=None, lane_succ=None):
    link = ""
    if succ or pred:
        link = "<link>"
        if pred:
            link += f'<predecessor elementType="road" elementId="{pred}" contactPoint="end"/>'
        if succ:
            link += f'<successor elementType="road" elementId="{succ}" contactPoint="start"/>'
        link += "</link>"
    lane_link = f'<link><successor id="{lane_succ}"/></link>' if lane_succ is not None else ""
    return (
        f'<road id="{rid}" length="10.0" junction="-1">{link}'
        f'<planView><geometry s="0" x="{x0}" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><center><lane id="0" type="none"/></center>'
        f'<right><lane id="-1" type="driving">{lane_link}<width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane></right>'
        "</laneSection></lanes></road>"
    )


def _xodr(*roads, header=True):
    return "<?xml version='1.0' encoding='utf-8'?><OpenDRIVE>" + (VALID_HEADER if header else "") + "".join(roads) + "</OpenDRIVE>"


def _write(tmp_path: Path, text: str, name: str = "final.xodr") -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def _status(report):
    reports = {} if report is None else {"g": report}
    acc = build_map_acceptance(reports, run_id="v86", mandatory_gates=("g",))
    return acc["mandatory_gate_status"]["g"], acc["valid_for_experiments"]


# ---- A4/A5: strict status schema, full truth table --------------------------
@pytest.mark.parametrize(
    "report, expected",
    [
        (None, "NOT_RUN"),
        ({}, "NOT_RUN"),
        ({"ok": None}, "NOT_RUN"),
        ({"issues": []}, "NOT_RUN"),                      # no explicit ok -> no inferred PASS
        ({"broken_count": 0}, "NOT_RUN"),                 # legacy inferred success refused
        ({"ok": True, "status": "NOT_RUN"}, "NOT_RUN"),
        ({"ok": True, "status": "ERROR"}, "NOT_RUN"),
        ({"ok": True, "status": "INCOMPLETE"}, "NOT_RUN"),
        ({"ok": True, "status": "BLOCKED_INPUT"}, "BLOCKED_INPUT"),
        ({"ok": True, "status": "FAIL"}, "FAIL"),          # contradictory declared status
        ({"ok": True, "status": "WARN"}, "FAIL"),          # unknown status is not PASS
        ({"ok": "true"}, "FAIL"),
        ({"ok": 1}, "FAIL"),
        ({"ok": False}, "FAIL"),
        ({"ok": True, "issue_count": 3}, "FAIL"),          # contradictory counts
        ({"ok": True, "num_issues": 1}, "FAIL"),
        ({"ok": True, "broken_count": 2}, "FAIL"),
        ({"ok": True, "issues": [{"x": 1}]}, "FAIL"),
        ({"ok": True}, "PASS"),
        ({"ok": True, "status": "PASS", "issue_count": 0, "issues": []}, "PASS"),
    ],
)
def test_strict_status_truth_table(report, expected):
    status, valid = _status(report)
    assert status == expected
    assert valid is (expected == "PASS")


@pytest.mark.parametrize("report", [
    {"ok": True, "issue_count": "zero"},
    {"ok": True, "issues": "none"},
    {"ok": True, "failures": "none"},
])
def test_malformed_mandatory_issue_evidence_cannot_pass(report):
    assert _status(report) == ("FAIL", False)


def test_lane_normalizer_and_acceptance_reject_ok_with_failures():
    report = fag.normalize_lane_section_report({"ok": True, "broken_count": 0, "failures": [{"road": "x"}]})
    assert report["ok"] is True  # normalizer preserves producer field; consumer must reconcile it
    assert _status(report) == ("FAIL", False)


# ---- A7: issue-list results ---------------------------------------------------
@pytest.mark.parametrize("bad", [None, "", 0, {"a": 1}, "issues", [1, 2], [None]])
def test_issues_report_rejects_non_results(bad):
    with pytest.raises(TypeError):
        fag._issues_report(bad)


def test_checker_returning_none_is_not_run_not_zero_issues(tmp_path, monkeypatch):
    real = fag._gate_table

    def table(expected_scope=None):
        t = real(expected_scope)
        t["physics_feasibility"] = lambda p, r: fag._issues_report(None)
        return t

    monkeypatch.setattr(fag, "_gate_table", table)
    reps = fag.compute_final_artifact_reports(_write(tmp_path, _xodr(_road(1, 0))))
    assert reps["physics_feasibility"]["status"] == "NOT_RUN"
    assert _status(reps["physics_feasibility"])[0] == "NOT_RUN"


# ---- A2: empty / incomplete OpenDRIVE ------------------------------------------
def test_empty_but_wellformed_opendrive_fails_structure(tmp_path):
    reps = fag.compute_final_artifact_reports(_write(tmp_path, _xodr()))
    kinds = {i["kind"] for i in reps["artifact_structure"]["issues"]}
    assert "no_roads" in kinds and _status(reps["artifact_structure"])[0] == "FAIL"


@pytest.mark.parametrize(
    "xml, kind",
    [
        (_xodr(_road(1, 0), header=False), "missing_header"),
        (_xodr('<road id="1" length="0" junction="-1"><planView><geometry s="0" x="0" y="0" hdg="0" length="0"><line/></geometry></planView></road>'), "invalid_road_length"),
        (_xodr('<road id="1" length="10" junction="-1"></road>'), "missing_planview_geometry"),
    ],
)
def test_incomplete_structures_fail(tmp_path, xml, kind):
    rep = fag.compute_final_artifact_reports(_write(tmp_path, xml))["artifact_structure"]
    assert kind in {i["kind"] for i in rep["issues"]} and rep["ok"] is False


def _scope(ids=("1",), bounds=(0.0, 0.0, 10.0, 0.0)):
    from ultimate_pipeline.quality.map_scope_authority import (
        EXPECTED_MAP_SHA256, EXPECTED_OSM_SHA256, SCOPE_SCHEMA,
    )
    return {
        "schema": SCOPE_SCHEMA, "authority": "verified_map_registry",
        "map_sha256": EXPECTED_MAP_SHA256, "source_osm_sha256": EXPECTED_OSM_SHA256,
        "frame_id": "ingolstadt_local_rebased", "expected_road_ids": list(ids),
        "road_count": len(ids), "anchor_bounds_xy": list(bounds),
    }


def test_trusted_scope_accepts_exact_membership_and_footprint(tmp_path):
    rep = fag.compute_final_artifact_reports(
        _write(tmp_path, _xodr(_road(1, 0))), expected_scope=_scope()
    )["artifact_structure"]
    assert rep["ok"] is True
    assert rep["trusted_scope"]["road_count"] == 1


def test_trusted_scope_rejects_omitted_roads_and_same_count_substitution(tmp_path):
    xodr = _write(tmp_path, _xodr(_road(2, 0)))
    rep = fag.compute_final_artifact_reports(xodr, expected_scope=_scope(("1",)))["artifact_structure"]
    assert "road_membership_mismatch" in {item["kind"] for item in rep["issues"]}
    assert rep["ok"] is False


def test_trusted_scope_rejects_wrong_geographic_footprint(tmp_path):
    xodr = _write(tmp_path, _xodr(_road(1, 50_000)))
    rep = fag.compute_final_artifact_reports(xodr, expected_scope=_scope())["artifact_structure"]
    assert "geographic_footprint_mismatch" in {item["kind"] for item in rep["issues"]}


@pytest.mark.parametrize("field,value,kind", [
    ("source_osm_sha256", "0" * 64, "source_identity_mismatch"),
    ("map_sha256", "1" * 64, "map_identity_mismatch"),
    ("frame_id", "wrong_frame", "frame_identity_mismatch"),
])
def test_trusted_scope_rejects_altered_identity(tmp_path, field, value, kind):
    scope = _scope()
    scope[field] = value
    rep = fag.compute_final_artifact_reports(
        _write(tmp_path, _xodr(_road(1, 0))), expected_scope=scope
    )["artifact_structure"]
    assert kind in {item["kind"] for item in rep["issues"]}
    assert rep["ok"] is False


def test_release_report_blocks_when_trusted_scope_is_missing(tmp_path):
    reps = fag.compute_final_artifact_reports(
        _write(tmp_path, _xodr(_road(1, 0))), require_trusted_scope=True
    )
    assert reps["artifact_structure"]["status"] == "BLOCKED_INPUT"
    assert reps["artifact_structure"]["ok"] is False


def test_regen_emission_is_bound_to_accepted_digest_and_never_overwrites(tmp_path, monkeypatch):
    import hashlib
    import scripts.regen_map_of_record as regen

    source = Path(_write(tmp_path, _xodr(_road(1, 0))))
    destination = tmp_path / "candidate"
    monkeypatch.setattr(regen, "CANDIDATE_DIR", destination)
    monkeypatch.setattr(regen, "compute_structural_signature", lambda path: {"num_roads": 1})
    monkeypatch.setattr(regen, "_git_dirty", lambda: [])
    monkeypatch.setattr(regen.subprocess, "check_output", lambda *a, **k: "test-commit")
    monkeypatch.setattr(regen, "_settings_snapshot", lambda: {})
    osm = tmp_path / "roads.osm"
    osm.write_text("<osm/>", encoding="utf-8")
    monkeypatch.setattr(regen, "_resolve_osm_from_manifest", lambda: osm)
    monkeypatch.setattr(regen, "_write_json", lambda *a, **k: None)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    acceptance = {"evaluated_xodr_sha256": digest, "final_xodr_sha256": digest}

    published = regen._emit_candidate(source, tmp_path, "accepted.xodr", acceptance)
    assert hashlib.sha256(published.read_bytes()).hexdigest() == digest
    with pytest.raises(RuntimeError, match="refusing overwrite"):
        regen._emit_candidate(source, tmp_path, "accepted.xodr", acceptance)


def test_regen_emission_rejects_bytes_changed_after_acceptance(tmp_path, monkeypatch):
    import scripts.regen_map_of_record as regen

    accepted_source = Path(_write(tmp_path, _xodr(_road(1, 0))))
    accepted_digest = __import__("hashlib").sha256(accepted_source.read_bytes()).hexdigest()
    accepted_source.write_text(_xodr(_road(2, 0)), encoding="utf-8")
    monkeypatch.setattr(regen, "CANDIDATE_DIR", tmp_path / "candidate")
    with pytest.raises(RuntimeError, match="source bytes changed after acceptance"):
        regen._emit_candidate(
            accepted_source, tmp_path, "mutated.xodr",
            {"evaluated_xodr_sha256": accepted_digest, "final_xodr_sha256": accepted_digest},
        )
    assert not (tmp_path / "candidate" / "mutated.xodr").exists()


# ---- A8: XML boundary ---------------------------------------------------------
BILLION_LAUGHS = (
    '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
    '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
    "<OpenDRIVE><header/>&lol2;</OpenDRIVE>"
)


def test_doctype_entity_input_is_rejected_at_boundary(tmp_path):
    with pytest.raises(fag.UnsafeXMLError):
        fag.parse_xodr_bytes(BILLION_LAUGHS.encode())
    reps = fag.compute_final_artifact_reports(_write(tmp_path, BILLION_LAUGHS))
    assert {r["status"] for r in reps.values()} == {"BLOCKED_INPUT"}


def test_oversize_input_is_rejected(monkeypatch):
    monkeypatch.setattr(fag, "MAX_XODR_BYTES", 64)
    with pytest.raises(fag.UnsafeXMLError):
        fag.check_xml_boundary(_xodr(_road(1, 0)).encode())


def test_legitimate_opendrive_passes_boundary():
    root = fag.parse_xodr_bytes(_xodr(_road(1, 0)).encode())
    assert root.tag == "OpenDRIVE"


# ---- A6: immutable content-addressed artifact -----------------------------------
def test_snapshot_is_content_addressed_and_read_only(tmp_path):
    src = _write(tmp_path, _xodr(_road(1, 0)))
    snap = fag.snapshot_final_artifact(src, str(tmp_path / "snap"))
    assert Path(snap["path"]).name == snap["sha256"] + ".xodr"
    assert Path(snap["path"]).read_bytes() == Path(src).read_bytes()
    if os.name == "posix":
        assert Path(snap["path"]).stat().st_mode & 0o222 == 0
    else:
        assert not os.access(snap["path"], os.W_OK)


def test_expected_digest_mismatch_blocks_every_gate(tmp_path):
    src = _write(tmp_path, _xodr(_road(1, 0)))
    reps = fag.compute_final_artifact_reports(src, expected_sha256="0" * 64)
    assert {r["status"] for r in reps.values()} == {"BLOCKED_INPUT"}


def test_xodr_replaced_during_evaluation_cannot_pass(tmp_path, monkeypatch):
    """The original is swapped mid-validation: gates still see the snapshot,
    and acceptance refuses because the published bytes differ."""
    final_out = _write(tmp_path, _xodr(_road(1, 0)))
    snap = fag.snapshot_final_artifact(final_out, str(tmp_path / "snap"))
    real = fag._gate_table
    seen = []

    def table(expected_scope=None):
        t = real(expected_scope)
        inner = t["lane_connectivity"]

        def swap_then_check(p, r):
            Path(final_out).write_text(_xodr(_road(1, 0), _road(2, 10)), encoding="utf-8")
            seen.append(Path(p).read_bytes() == Path(snap["path"]).read_bytes())
            return inner(p, r)

        t["lane_connectivity"] = swap_then_check
        return t

    monkeypatch.setattr(fag, "_gate_table", table)
    reps = fag.compute_final_artifact_reports(snap["path"], expected_sha256=snap["sha256"])
    assert seen == [True]  # validators read the immutable snapshot, not the swapped file
    acc = build_map_acceptance(
        {g: {"ok": True} for g in fag.RELEASE_MANDATORY_GATES} | {k: v for k, v in reps.items() if v.get("ok") is True},
        run_id="v86", final_xodr_path=final_out,
        mandatory_gates=fag.RELEASE_MANDATORY_GATES, purpose="release",
        evaluated_xodr_sha256=snap["sha256"],
    )
    assert "artifact_identity" in acc["failed_gates"]
    assert acc["release_eligible"] is False


def test_tamper_after_acceptance_detected(tmp_path):
    final_out = _write(tmp_path, _xodr(_road(1, 0)))
    snap = fag.snapshot_final_artifact(final_out, str(tmp_path / "snap"))
    assert fag.verify_artifact_unchanged(final_out, snap["sha256"])[0] is True
    Path(final_out).write_text(_xodr(_road(9, 0)), encoding="utf-8")
    ok, actual = fag.verify_artifact_unchanged(final_out, snap["sha256"])
    assert ok is False and actual != snap["sha256"]


def test_production_publish_binds_snapshot_and_checks_tamper():
    import inspect

    from ultimate_pipeline.main_pipeline import MainPipeline

    src = inspect.getsource(MainPipeline._publish_final_artifact_authority)
    snap_i = src.index("snapshot_final_artifact(")
    collect_i = src.index("self._collect_final_acceptance_reports(")
    build_i = src.index("build_map_acceptance(")
    tamper_i = src.index("verify_artifact_unchanged(final_out")
    assert snap_i < collect_i < build_i < tamper_i
    assert 'snapshot["path"]' in src[collect_i:build_i]
    assert 'purpose="release"' in src and 'evaluated_xodr_sha256=snapshot["sha256"]' in src


# ---- A3: cross-road lane target missing ------------------------------------------
def test_cross_road_missing_lane_target_fails(tmp_path):
    xml = _xodr(_road(1, 0, succ=2, lane_succ=-5), _road(2, 10, pred=1))
    rep = fag.compute_final_artifact_reports(_write(tmp_path, xml))["lane_connectivity"]
    assert rep["ok"] is False, rep
    assert _status(rep)[0] == "FAIL"


def test_cross_road_valid_lane_target_passes(tmp_path):
    xml = _xodr(_road(1, 0, succ=2, lane_succ=-1), _road(2, 10, pred=1))
    rep = fag.compute_final_artifact_reports(_write(tmp_path, xml))["lane_connectivity"]
    assert rep["ok"] is True, rep


# ---- A1: pre-hygiene PASS + final origin exception -------------------------------
def test_final_origin_exception_is_not_run_despite_prior_pass(tmp_path):
    from types import SimpleNamespace

    from ultimate_pipeline.main_pipeline import MainPipeline

    class Gate:
        def gate_origin_sanity(self, _p):
            raise RuntimeError("final recompute failed")

    stub = SimpleNamespace(qgate=Gate(), out_dir=str(tmp_path))
    reports = MainPipeline._collect_final_acceptance_reports(
        stub, _write(tmp_path, _xodr(_road(1, 0))), seam_report={"ok": True}
    )
    assert reports["origin_sanity"]["status"] == "NOT_RUN"
    assert _status(reports["origin_sanity"])[0] == "NOT_RUN"


# ---- lane-section normalizer -------------------------------------------------------
@pytest.mark.parametrize(
    "rep, ok",
    [({"broken_count": 0}, True), ({"broken_count": 3}, False), ({"failures": []}, True),
     ({"failures": [{}]}, False), ({"ok": False, "broken_count": 0}, False),
     ({"broken_count": True}, None), ({}, None)],
)
def test_normalize_lane_section_report(rep, ok):
    assert fag.normalize_lane_section_report(rep).get("ok") is ok


# ---- A9: purpose semantics + real CLI entrypoint ------------------------------------
def test_release_purpose_requires_mandatory_gates():
    with pytest.raises(ValueError):
        build_map_acceptance({}, run_id="v86", purpose="release")
    with pytest.raises(ValueError):
        build_map_acceptance({}, run_id="v86", purpose="bogus")


def test_diagnostic_or_legacy_acceptance_is_never_release_eligible(tmp_path):
    good = {g: {"ok": True} for g in fag.RELEASE_MANDATORY_GATES}
    assert build_map_acceptance(good, run_id="v86")["release_eligible"] is False
    diag = build_map_acceptance(good, run_id="v86", purpose="diagnostic",
                                mandatory_gates=fag.RELEASE_MANDATORY_GATES)
    assert diag["valid_for_experiments"] is True and diag["release_eligible"] is False
    artifact = tmp_path / "candidate.xodr"
    artifact.write_bytes(b"candidate bytes")
    digest = fag.sha256_bytes(artifact.read_bytes())
    rel = build_map_acceptance(
        good, run_id="v86", final_xodr_path=str(artifact), purpose="release",
        mandatory_gates=fag.RELEASE_MANDATORY_GATES, evaluated_xodr_sha256=digest,
    )
    assert rel["release_eligible"] is True
    assert rel["acceptance_policy"]["purpose"] == "release"


def test_release_acceptance_rejects_incomplete_gate_set():
    with pytest.raises(ValueError, match="exact authoritative RELEASE_MANDATORY_GATES"):
        build_map_acceptance(
            {"artifact_structure": {"ok": True}}, purpose="release",
            mandatory_gates=("artifact_structure",),
        )


def test_release_acceptance_requires_bound_artifact_identity():
    good = {gate: {"ok": True} for gate in fag.RELEASE_MANDATORY_GATES}
    acceptance = build_map_acceptance(
        good, run_id="no-identity", purpose="release",
        mandatory_gates=fag.RELEASE_MANDATORY_GATES,
    )
    assert acceptance["valid_for_experiments"] is False
    assert acceptance["release_eligible"] is False
    assert "artifact_identity" in acceptance["failed_gates"]


def _run_cli(tmp_path, purpose):
    xodr = _write(tmp_path, _xodr(), "candidate.xodr")  # empty map: missing evidence
    out = tmp_path / f"out_{purpose}"
    env = dict(os.environ, PYTHONPATH=str(REPO), MPLBACKEND="Agg")
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "measure_candidate_acceptance.py"), xodr,
         "--out-dir", str(out), "--dem", str(tmp_path / "no_dem.tif"), "--purpose", purpose],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300,
    )
    return proc, json.loads((out / "map_acceptance.json").read_text(encoding="utf-8"))


def test_standalone_cli_release_rejects_candidate_missing_evidence(tmp_path):
    proc, acc = _run_cli(tmp_path, "release")
    assert proc.returncode == 1, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert acc["release_eligible"] is False
    assert acc["acceptance_policy"]["purpose"] == "release"
    assert "artifact_structure" in acc["failed_gates"]


def test_standalone_cli_diagnostic_is_never_a_release_certificate(tmp_path):
    _proc, acc = _run_cli(tmp_path, "diagnostic")
    assert acc["release_eligible"] is False
    assert acc["acceptance_policy"]["purpose"] == "diagnostic"
    assert acc["mandatory_gates"] == []


_FULL_RELEASE_PAYLOAD = {
    "valid_for_experiments": True,
    "release_eligible": True,
    "artifact_identity_verified": True,
    "acceptance_policy": {"purpose": "release"},
    "mandatory_gates": list(fag.RELEASE_MANDATORY_GATES),
    "mandatory_gate_status": {gate: "PASS" for gate in fag.RELEASE_MANDATORY_GATES},
    "hard_fail_reasons": [],
    "failed_gates": [],
    "final_xodr_sha256": "a" * 64,
    "evaluated_xodr_sha256": "a" * 64,
    "run_id": "v86",
}
# ---- Review round 1: signal consumer, promotion-path snapshot + boundary ----------------
@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"valid_for_experiments": True}, "INCOMPLETE"),  # pre-V86: cannot prove release eligibility
        ({"valid_for_experiments": True, "release_eligible": False,
          "acceptance_policy": {"purpose": "diagnostic"}}, "INCOMPLETE"),
        ({"valid_for_experiments": True, "release_eligible": False,
          "acceptance_policy": {"purpose": "legacy_unspecified"}}, "INCOMPLETE"),
        ({"valid_for_experiments": False, "release_eligible": False,
          "acceptance_policy": {"purpose": "release"}}, "FAIL"),
        ({"valid_for_experiments": True, "release_eligible": True,
          "acceptance_policy": {"purpose": "diagnostic"}}, "INCOMPLETE"),  # forged flag, wrong purpose
        (_FULL_RELEASE_PAYLOAD, "PASS"),
        ({"valid_for_experiments": True, "release_eligible": True,
          "acceptance_policy": {"purpose": "release"}}, "INCOMPLETE"),
    ],
)
def test_map_acceptance_signal_requires_release_eligibility(payload, expected):
    from ultimate_pipeline.signals.index import release_acceptance_status

    assert release_acceptance_status(payload) == expected


@pytest.mark.parametrize(
    "profile",
    ["structural_release", "STRUCTURAL_RELEASE", "carla_release", "visual_build", "VISUAL_RELEASE",
     "perception_research", "PERCEPTION_RELEASE", ""],
)
def test_release_profiles_apply_release_acceptance_policy(profile):
    from ultimate_pipeline.signals.index import apply_release_acceptance_policy, normalize_signal_status

    legacy = {"valid_for_experiments": True}
    base = normalize_signal_status("MAP_ACCEPTANCE", legacy)
    assert base == "PASS"  # experiment semantics unchanged
    assert apply_release_acceptance_policy("MAP_ACCEPTANCE", base, legacy, profile) == "INCOMPLETE"
    good = _FULL_RELEASE_PAYLOAD
    assert apply_release_acceptance_policy("MAP_ACCEPTANCE", "PASS", good, profile) == "PASS"


@pytest.mark.parametrize("profile", ["debug", "DEVELOPMENT", "EXPERIMENTAL_UNSAFE", "scenario_augmentation"])
def test_non_release_profiles_keep_experiment_semantics(profile):
    from ultimate_pipeline.signals.index import apply_release_acceptance_policy

    assert apply_release_acceptance_policy("MAP_ACCEPTANCE", "PASS", {"valid_for_experiments": True}, profile) == "PASS"


def test_release_verdict_blocks_on_legacy_acceptance(tmp_path):
    """Real verdict: a release profile cannot reach PASS from a non-release acceptance."""
    from ultimate_pipeline.signals.verdict import compute_final_run_verdict

    (tmp_path / "map_acceptance.json").write_text(json.dumps({"valid_for_experiments": True}), encoding="utf-8")
    verdict = compute_final_run_verdict(str(tmp_path), profile="structural_release", settings=None, env={})
    blocking = {f.get("signal_id"): f.get("status") for f in verdict["blocking_failures"]}
    assert verdict["status"] != "PASS"
    assert blocking.get("MAP_ACCEPTANCE") in ("INCOMPLETE", "FAIL"), verdict["blocking_failures"]


def test_experiment_readiness_signal_keeps_experiment_semantics():
    from ultimate_pipeline.signals.index import normalize_signal_status

    assert normalize_signal_status("EXPERIMENT_READINESS", {"valid_for_experiments": True}) == "PASS"


def test_promotion_evaluation_runs_every_checker_on_the_snapshot(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO))
    import scripts.measure_candidate_acceptance as mca

    seen = []
    real = mca.run_gates

    def spy(xodr, out_dir, dem):
        seen.append(Path(xodr))
        return real(xodr, out_dir, dem)

    monkeypatch.setattr(mca, "run_gates", spy)
    cand = Path(_write(tmp_path, _xodr(_road(1, 0)), "cand.xodr"))
    acc = mca.evaluate_candidate(cand, tmp_path / "out", tmp_path / "no_dem.tif")
    assert len(seen) == 1 and seen[0].parent.name == ".acceptance_snapshot"
    assert seen[0].name == acc["evaluated_xodr_sha256"] + ".xodr"


def test_promotion_doctype_input_never_reaches_any_checker(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO))
    import scripts.measure_candidate_acceptance as mca

    called = []
    monkeypatch.setattr(mca, "run_gates", lambda *a, **k: called.append(1) or {})
    cand = Path(_write(tmp_path, BILLION_LAUGHS, "evil.xodr"))
    acc = mca.evaluate_candidate(cand, tmp_path / "out", None)
    assert called == []
    assert set(acc["mandatory_gate_status"].values()) == {"BLOCKED_INPUT"}
    assert acc["release_eligible"] is False


def test_promotion_candidate_replaced_after_write_is_not_release_eligible(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO))
    import scripts.measure_candidate_acceptance as mca

    cand = Path(_write(tmp_path, _xodr(_road(1, 0)), "cand.xodr"))
    good = {g: {"ok": True} for g in fag.RELEASE_MANDATORY_GATES}

    def gates_then_tamper(xodr, out_dir, dem):
        return good

    real_write = mca._write_json

    def write_then_tamper(path, data):
        real_write(path, data)
        if path.name == "map_acceptance.json":
            cand.write_text(_xodr(_road(7, 0)), encoding="utf-8")

    monkeypatch.setattr(mca, "run_gates", gates_then_tamper)
    monkeypatch.setattr(mca, "_write_json", write_then_tamper)
    acc = mca.evaluate_candidate(cand, tmp_path / "out", None)
    assert acc["release_eligible"] is False
    assert acc["valid_for_experiments"] is False
    assert "artifact_identity_after_write" in acc
    canonical = json.loads((tmp_path / "out" / "map_acceptance.json").read_text(encoding="utf-8"))
    assert canonical["release_eligible"] is False
    assert canonical["valid_for_experiments"] is False
    assert "artifact_identity" in canonical["failed_gates"]
    artifact = Path(canonical["acceptance_artifact"])
    artifact_receipt = json.loads(artifact.read_text(encoding="utf-8"))
    assert artifact_receipt["release_eligible"] is False
    assert artifact_receipt["valid_for_experiments"] is False


def test_regen_map_of_record_uses_the_shared_guarded_evaluation():
    src = (REPO / "scripts" / "regen_map_of_record.py").read_text(encoding="utf-8")
    assert "evaluate_candidate(" in src
    assert "run_gates(final_xodr" not in src
