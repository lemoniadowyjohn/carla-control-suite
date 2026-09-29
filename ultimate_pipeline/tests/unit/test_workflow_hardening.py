# -*- coding: utf-8 -*-
"""V5 / NEW-206 (D18): GitHub Actions supply-chain hardening assertions.

The repository-local half of D18 is asserting that the workflows actually
carry the hardening: immutable action SHAs, least-privilege permissions,
timeouts, concurrency, and a semantically-correct release gate. Server-side
branch protection cannot be asserted from a test; that is reported as
BLOCKED_EXTERNAL_GITHUB_PERMISSION in the evidence packet.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _workflow(name: str) -> dict:
    path = _repo_root() / ".github" / "workflows" / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


WORKFLOWS = ["tests.yml", "carla-runtime.yml"]

#: Actions that must never be referenced by mutable tag.
MUTABLE_USE = re.compile(r"uses:\s*[\w.\-/]+@(?![0-9a-f]{40}\b)(?!\$\{)[\w.\-]+")


@pytest.mark.parametrize("wf", WORKFLOWS)
def test_workflow_is_valid_yaml(wf):
    assert isinstance(_workflow(wf), dict)


@pytest.mark.parametrize("wf", WORKFLOWS)
def test_no_mutable_action_tags(wf):
    text = (_repo_root() / ".github" / "workflows" / wf).read_text(encoding="utf-8")
    offenders = [m.group(0).strip() for m in MUTABLE_USE.finditer(text)]
    assert not offenders, f"{wf} uses mutable action tags: {offenders}"


@pytest.mark.parametrize("wf", WORKFLOWS)
def test_actions_are_pinned_to_full_commit_shas(wf):
    text = (_repo_root() / ".github" / "workflows" / wf).read_text(encoding="utf-8")
    for match in re.finditer(r"uses:\s*([\w.\-/]+)@([0-9a-fA-F]+)", text):
        action, sha = match.groups()
        assert len(sha) == 40, f"{wf}: {action} is not pinned to a full 40-char commit SHA"


@pytest.mark.parametrize("wf", WORKFLOWS)
def test_pinned_actions_annotate_the_upstream_version(wf):
    """A bare SHA is unauditable; the human-readable version must be a comment."""
    text = (_repo_root() / ".github" / "workflows" / wf).read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.search(r"uses:\s*[\w.\-/]+@[0-9a-fA-F]{40}\s*(#.*)?$", line)
        if m:
            assert m.group(1), f"{wf}: pinned action lacks a version comment: {line.strip()}"


@pytest.mark.parametrize("wf", WORKFLOWS)
def test_top_level_permissions_are_least_privilege(wf):
    perms = _workflow(wf).get("permissions")
    assert perms is not None, f"{wf} declares no top-level permissions"
    assert perms == {"contents": "read"}, f"{wf} top-level permissions are not read-only"


@pytest.mark.parametrize("wf", WORKFLOWS)
def test_every_job_has_a_timeout(wf):
    for name, job in _workflow(wf)["jobs"].items():
        assert "timeout-minutes" in job, f"{wf}: job {name!r} has no timeout-minutes"
        assert isinstance(job["timeout-minutes"], int)
        assert 1 <= job["timeout-minutes"] <= 360


@pytest.mark.parametrize("wf", WORKFLOWS)
def test_every_job_declares_permissions(wf):
    for name, job in _workflow(wf)["jobs"].items():
        assert "permissions" in job, f"{wf}: job {name!r} inherits permissions implicitly"


@pytest.mark.parametrize("wf", WORKFLOWS)
def test_concurrency_is_declared(wf):
    conc = _workflow(wf).get("concurrency")
    assert isinstance(conc, dict)
    assert "group" in conc
    assert "cancel-in-progress" in conc


def test_offline_workflow_does_not_cancel_runtime_style_long_work():
    """Short offline gates may cancel stale runs; that is asserted explicitly."""
    conc = _workflow("tests.yml")["concurrency"]
    assert conc["cancel-in-progress"] is True


def test_runtime_workflow_does_not_cancel_long_acceptance_runs():
    """Cancelling a half-finished certification would waste the runner."""
    conc = _workflow("carla-runtime.yml")["concurrency"]
    assert conc["cancel-in-progress"] is False


# ---------------------------------------------------------------------------
# D19 semantics must be wired into the workflow
# ---------------------------------------------------------------------------


def test_offline_release_gate_resolves_a_named_gate():
    text = (_repo_root() / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "--gate offline-release-gate" in text
    # the ambiguous diagnostic-only invocation must be gone from the gate job
    assert "--strict-release" not in text


def test_offline_gate_job_exists_as_a_distinct_required_check():
    jobs = _workflow("tests.yml")["jobs"]
    assert "offline-release-gate" in jobs
    assert jobs["offline-release-gate"]["name"] == "offline release gate"


def test_offline_gate_depends_on_every_upstream_job():
    jobs = _workflow("tests.yml")["jobs"]
    gate = jobs["offline-release-gate"]
    upstream = set(gate["needs"])
    expected = set(jobs) - {"offline-release-gate"}
    assert upstream == expected, f"gate needs {upstream}, expected {expected}"


def test_runtime_workflow_does_not_claim_offline_ci_certifies_runtime():
    text = (_repo_root() / ".github" / "workflows" / "carla-runtime.yml").read_text(
        encoding="utf-8"
    )
    # The runtime gate is resolved by its own workflow, not the offline one.
    assert "runtime-certification-gate" in text


def test_runtime_workflow_runs_the_candidate_identity_gate():
    text = (_repo_root() / ".github" / "workflows" / "carla-runtime.yml").read_text(
        encoding="utf-8"
    )
    assert "--validate-candidate" in text
    assert "--expected-repo-sha" in text


def test_runtime_workflow_binds_the_checked_out_sha():
    text = (_repo_root() / ".github" / "workflows" / "carla-runtime.yml").read_text(
        encoding="utf-8"
    )
    assert "git rev-parse HEAD" in text


def test_runtime_receipt_records_candidate_identities():
    text = (_repo_root() / ".github" / "workflows" / "carla-runtime.yml").read_text(
        encoding="utf-8"
    )
    for field in ("candidate_sha", "xodr_sha256", "cooked_package_sha256",
                  "carla_server_version", "ue_build", "workflow_run_id"):
        assert field in text, f"runtime receipt omits {field}"


def test_blocked_external_is_not_treated_as_pass_in_workflow():
    text = (_repo_root() / ".github" / "workflows" / "carla-runtime.yml").read_text(
        encoding="utf-8"
    )
    assert 'if state != "PASS"' in text


# ---------------------------------------------------------------------------
# J09/J10 wiring
# ---------------------------------------------------------------------------


def test_ci_installs_the_headless_dependency_profile():
    text = (_repo_root() / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "requirements-ci.txt" in text
    # the base profile alone must never be installed in CI: it declares no
    # OpenCV provider, so CI would silently lack cv2
    assert "pip install -r requirements.txt" not in text


def test_ci_runs_the_dependency_conflict_gate():
    text = (_repo_root() / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "dependency_conflicts" in text


def test_wheel_smoke_runs_pip_check():
    """J09: an import-only smoke test cannot prove dependency correctness."""
    text = (_repo_root() / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "pip check" in text


def test_wheel_smoke_validates_extras():
    text = (_repo_root() / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "geometry,visualization,test" in text
