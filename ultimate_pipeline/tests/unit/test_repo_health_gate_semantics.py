# -*- coding: utf-8 -*-
"""V5 / NEW-208 (D19): release-gate status semantics truth table.

The defect (NEW-208) was that ``repo_health`` could report
``overall_status = INCOMPLETE`` while the process exited 0, so a green GitHub
check was not equivalent to release PASS. These tests pin the corrected
contract: only an explicitly resolved ``PASS`` gate exits 0, and offline CI
never claims runtime certification it cannot perform.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from ultimate_pipeline.tools.repo_health import (
    GATE_DIAGNOSTIC,
    GATE_OFFLINE_RELEASE,
    GATE_RUNTIME_CERTIFICATION,
    GATES,
    OFFLINE_REQUIRED_SECTIONS,
    RUNTIME_REQUIRED_SECTIONS,
    STATUS_BLOCKED_EXTERNAL,
    STATUS_FAIL,
    STATUS_INCOMPLETE,
    STATUS_NOT_RUN,
    STATUS_PASS,
    STATUS_WAIVED,
    build_repo_health,
    gate_exit_code,
    main,
    resolve_gate,
)

ALL_STATUSES = [
    STATUS_PASS,
    STATUS_FAIL,
    STATUS_INCOMPLETE,
    STATUS_NOT_RUN,
    STATUS_BLOCKED_EXTERNAL,
    STATUS_WAIVED,
]


def _sections(offline_status: str, runtime_status: str = STATUS_PASS) -> dict:
    sections = {name: {"status": offline_status} for name in OFFLINE_REQUIRED_SECTIONS}
    sections["runtime_verification"] = {"status": runtime_status}
    return sections


# ---------------------------------------------------------------------------
# offline release gate truth table
# ---------------------------------------------------------------------------


def test_offline_gate_passes_only_when_every_section_passes():
    assert resolve_gate(_sections(STATUS_PASS), GATE_OFFLINE_RELEASE)["status"] == STATUS_PASS


@pytest.mark.parametrize("bad", [STATUS_FAIL, STATUS_INCOMPLETE, STATUS_NOT_RUN, STATUS_BLOCKED_EXTERNAL, STATUS_WAIVED])
def test_offline_gate_never_passes_on_non_pass(bad):
    gate = resolve_gate(_sections(bad), GATE_OFFLINE_RELEASE)
    assert gate["status"] != STATUS_PASS
    assert gate["blocking_sections"], "blocking sections must be named"


def test_offline_gate_fail_is_distinct_from_incomplete():
    assert resolve_gate(_sections(STATUS_FAIL), GATE_OFFLINE_RELEASE)["status"] == STATUS_FAIL
    assert resolve_gate(_sections(STATUS_INCOMPLETE), GATE_OFFLINE_RELEASE)["status"] == STATUS_INCOMPLETE
    assert resolve_gate(_sections(STATUS_NOT_RUN), GATE_OFFLINE_RELEASE)["status"] == STATUS_INCOMPLETE


def test_offline_gate_reports_the_specific_offending_section():
    sections = _sections(STATUS_PASS)
    sections["tests"]["status"] = STATUS_FAIL
    gate = resolve_gate(sections, GATE_OFFLINE_RELEASE)
    assert gate["status"] == STATUS_FAIL
    assert gate["blocking_sections"] == [{"section": "tests", "status": STATUS_FAIL}]


def test_runtime_status_does_not_affect_offline_gate():
    """Offline CI cannot certify runtime, but that must not fail the offline gate."""
    gate = resolve_gate(_sections(STATUS_PASS, STATUS_NOT_RUN), GATE_OFFLINE_RELEASE)
    assert gate["status"] == STATUS_PASS
    assert gate["blocking_sections"] == []


# ---------------------------------------------------------------------------
# runtime certification gate truth table
# ---------------------------------------------------------------------------


def test_runtime_gate_passes_only_when_runtime_is_pass():
    assert resolve_gate(_sections(STATUS_PASS, STATUS_PASS), GATE_RUNTIME_CERTIFICATION)["status"] == STATUS_PASS


@pytest.mark.parametrize("bad", [STATUS_FAIL, STATUS_INCOMPLETE, STATUS_NOT_RUN, STATUS_BLOCKED_EXTERNAL, STATUS_WAIVED])
def test_runtime_gate_never_passes_on_non_pass(bad):
    gate = resolve_gate(_sections(STATUS_PASS, bad), GATE_RUNTIME_CERTIFICATION)
    assert gate["status"] != STATUS_PASS


def test_blocked_external_runtime_cannot_become_pass():
    """Explicit adversarial requirement: BLOCKED_EXTERNAL must never read as PASS."""
    sections = _sections(STATUS_PASS, STATUS_BLOCKED_EXTERNAL)
    assert resolve_gate(sections, GATE_RUNTIME_CERTIFICATION)["status"] != STATUS_PASS
    assert gate_exit_code(resolve_gate(sections, GATE_RUNTIME_CERTIFICATION)["status"]) == 1


def test_offline_pass_plus_runtime_not_run_splits_the_two_gates():
    """The headline NEW-208 case: split verdicts, never one ambiguous green."""
    sections = _sections(STATUS_PASS, STATUS_NOT_RUN)
    offline = resolve_gate(sections, GATE_OFFLINE_RELEASE)
    runtime = resolve_gate(sections, GATE_RUNTIME_CERTIFICATION)
    assert offline["status"] == STATUS_PASS
    assert runtime["status"] == STATUS_INCOMPLETE
    assert gate_exit_code(offline["status"]) == 0
    assert gate_exit_code(runtime["status"]) == 1


# ---------------------------------------------------------------------------
# exit-code contract
# ---------------------------------------------------------------------------


def test_exit_code_is_zero_only_for_pass():
    for status in ALL_STATUSES:
        assert gate_exit_code(status) == (0 if status == STATUS_PASS else 1)


def test_gate_rejects_unknown_name():
    with pytest.raises(ValueError):
        resolve_gate(_sections(STATUS_PASS), "not-a-gate")


def test_all_gates_are_resolvable():
    for gate in GATES:
        assert resolve_gate(_sections(STATUS_PASS), gate)["gate"] == gate


# ---------------------------------------------------------------------------
# exhaustive single-defect sweep
# ---------------------------------------------------------------------------


def test_any_single_failing_offline_section_fails_the_offline_gate():
    for section in OFFLINE_REQUIRED_SECTIONS:
        for bad in (STATUS_FAIL, STATUS_INCOMPLETE, STATUS_NOT_RUN):
            sections = _sections(STATUS_PASS)
            sections[section]["status"] = bad
            assert resolve_gate(sections, GATE_OFFLINE_RELEASE)["status"] != STATUS_PASS, (
                f"{section}={bad} must not pass the offline gate"
            )


def test_any_single_failing_runtime_status_fails_the_runtime_gate():
    for bad in ALL_STATUSES:
        if bad == STATUS_PASS:
            continue
        sections = _sections(STATUS_PASS, bad)
        assert resolve_gate(sections, GATE_RUNTIME_CERTIFICATION)["status"] != STATUS_PASS


# ---------------------------------------------------------------------------
# payload / CLI / workflow consistency
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_payload_exposes_all_gates():
    payload = build_repo_health(
        _repo_root(), test_result=STATUS_PASS, run_pip_check=False,
        verify_maps=False, runtime_status=STATUS_NOT_RUN,
    )
    assert set(payload["gates"]) == set(GATES)
    for name, gate in payload["gates"].items():
        assert gate["status"] in RELEASE_STATUSES_ALL
        # payload status and exit-code mapping must agree
        assert gate_exit_code(gate["status"]) == (0 if gate["status"] == STATUS_PASS else 1)


RELEASE_STATUSES_ALL = set(ALL_STATUSES)


def test_cli_offline_gate_exit_code_reflects_payload(tmp_path, monkeypatch):
    """CLI exit status must equal the resolved gate's exit code."""
    import ultimate_pipeline.tools.repo_health as rh

    def fake_build(repo_root, **kwargs):
        kwargs["run_pip_check"] = False
        kwargs["verify_maps"] = False
        return build_repo_health(repo_root, **kwargs)

    monkeypatch.setattr(rh, "build_repo_health", fake_build)

    rc = rh.main(["--out-dir", str(tmp_path), "--test-result", STATUS_PASS,
                  "--runtime-status", STATUS_NOT_RUN, "--gate", GATE_RUNTIME_CERTIFICATION])
    assert rc == 1, "runtime gate must not pass when runtime was not run"

    rc2 = rh.main(["--out-dir", str(tmp_path / "b"), "--test-result", STATUS_INCOMPLETE,
                   "--runtime-status", STATUS_NOT_RUN, "--gate", GATE_OFFLINE_RELEASE])
    assert rc2 == 1, "offline gate must not pass when the test result is INCOMPLETE"


def test_cli_runtime_gate_does_not_require_runtime_for_offline(tmp_path, monkeypatch):
    import ultimate_pipeline.tools.repo_health as rh

    # Force every offline section to PASS so only runtime status can vary.
    def all_pass(repo_root, **kwargs):
        sections = {name: {"status": STATUS_PASS} for name in OFFLINE_REQUIRED_SECTIONS}
        sections["runtime_verification"] = {"status": kwargs.get("runtime_status", STATUS_NOT_RUN)}
        return {
            "schema_version": 2,
            "generated_at_utc": "",
            "repo": "x",
            "authoritative_lineage": "x",
            "release_branch": "x",
            "git": {"branch": "b", "head": "h", "dirty": False},
            "python": {"executable": "", "version": ""},
            "sections": sections,
            "overall_status": rh._overall_status(sections),
            "gates": {g: rh.resolve_gate(sections, g) for g in GATES},
            "deferred_checks": [],
        }

    monkeypatch.setattr(rh, "build_repo_health", all_pass)

    assert rh.main(["--out-dir", str(tmp_path), "--runtime-status", STATUS_NOT_RUN,
                    "--gate", GATE_OFFLINE_RELEASE]) == 0
    assert rh.main(["--out-dir", str(tmp_path), "--runtime-status", STATUS_NOT_RUN,
                    "--gate", GATE_RUNTIME_CERTIFICATION]) == 1
    assert rh.main(["--out-dir", str(tmp_path), "--runtime-status", STATUS_PASS,
                    "--gate", GATE_RUNTIME_CERTIFICATION]) == 0


def test_legacy_behaviour_preserved_without_gate_flag(tmp_path, monkeypatch):
    """No --gate: keep the historical exit contract so unrelated callers are safe."""
    import ultimate_pipeline.tools.repo_health as rh

    def controlled(overall_required_status, runtime_status):
        sections = {
            name: {"status": overall_required_status} for name in OFFLINE_REQUIRED_SECTIONS
        }
        sections["runtime_verification"] = {"status": runtime_status}
        return {
            "schema_version": 2,
            "generated_at_utc": "",
            "repo": "x",
            "authoritative_lineage": "x",
            "release_branch": "x",
            "git": {"branch": "b", "head": "h", "dirty": False},
            "python": {"executable": "", "version": ""},
            "sections": sections,
            "overall_status": rh._overall_status(sections),
            "gates": {g: rh.resolve_gate(sections, g) for g in GATES},
            "deferred_checks": [],
        }

    # INCOMPLETE overall with no --gate and no --strict-release -> historical exit 0
    monkeypatch.setattr(
        rh, "build_repo_health",
        lambda *a, **k: controlled(STATUS_INCOMPLETE, STATUS_NOT_RUN),
    )
    assert rh.main(["--out-dir", str(tmp_path)]) == 0
    assert rh.main(["--out-dir", str(tmp_path), "--strict-release"]) == 1

    # FAIL overall -> exit 1 even without --gate
    monkeypatch.setattr(
        rh, "build_repo_health",
        lambda *a, **k: controlled(STATUS_FAIL, STATUS_PASS),
    )
    assert rh.main(["--out-dir", str(tmp_path)]) == 1

    # ... and the same INCOMPLETE payload FAILS the explicit offline gate
    monkeypatch.setattr(
        rh, "build_repo_health",
        lambda *a, **k: controlled(STATUS_INCOMPLETE, STATUS_NOT_RUN),
    )
    assert rh.main(["--out-dir", str(tmp_path), "--gate", GATE_OFFLINE_RELEASE]) == 1


def test_diagnostic_gate_is_explicitly_not_a_release_decision():
    gate = resolve_gate(_sections(STATUS_PASS, STATUS_NOT_RUN), GATE_DIAGNOSTIC)
    assert gate["status"] == STATUS_INCOMPLETE
    assert "not a release decision" in gate["reason"]


def test_required_section_tuples_are_the_documented_ones():
    assert "runtime_verification" not in OFFLINE_REQUIRED_SECTIONS
    assert "tests" in OFFLINE_REQUIRED_SECTIONS
    assert RUNTIME_REQUIRED_SECTIONS == ("runtime_verification",)


def test_main_is_callable_with_gate(tmp_path):
    rc = main(["--out-dir", str(tmp_path), "--skip-pip-check", "--skip-map-hash",
               "--test-result", STATUS_PASS, "--gate", GATE_OFFLINE_RELEASE])
    assert rc in (0, 1)
