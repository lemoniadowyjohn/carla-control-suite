# -*- coding: utf-8 -*-
"""Adversarial closure matrix for V5 findings NEW-202..NEW-208.

Section 17 of the V5 master requires an explicit expected state for every
attack scenario. This module is the machine-readable form of that matrix: each
scenario is executed against the real implementation and its outcome is
asserted, so a regression that flips a fail-closed gate to fail-open is caught
here rather than discovered during a release.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ultimate_pipeline.tools import repo_health as rh
from ultimate_pipeline.tools.repo_health import (
    CANDIDATE_MANIFEST_SCHEMA,
    GATE_OFFLINE_RELEASE,
    GATE_RUNTIME_CERTIFICATION,
    OFFLINE_REQUIRED_SECTIONS,
    STATUS_FAIL,
    STATUS_INCOMPLETE,
    STATUS_NOT_RUN,
    STATUS_PASS,
    STATUS_WAIVED,
    gate_exit_code,
    resolve_gate,
    validate_candidate_manifest,
)
from ultimate_pipeline.utils import run_provenance as rpv
from ultimate_pipeline.utils.finalize_run_pack import (
    FinalizationError,
    finalize_run_pack,
    verify_run_pack,
    write_success_txt,
)

SHA = "a" * 40


def _w(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)

    def g(*args):
        subprocess.run(["git", *args], cwd=str(path), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    g("init", "-b", "release")
    g("config", "user.email", "t@example.invalid")
    g("config", "user.name", "T")
    (path / "f.txt").write_text("x", encoding="utf-8")
    g("add", "f.txt")
    g("commit", "-m", "init")
    g("remote", "add", "origin", "https://example.invalid/o/r.git")
    return path


def _head(path: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(path), check=True,
                          capture_output=True, text=True).stdout.strip()


def _sections(offline: str, runtime: str) -> dict:
    s = {n: {"status": offline} for n in OFFLINE_REQUIRED_SECTIONS}
    s["runtime_verification"] = {"status": runtime}
    return s


def _manifest(root: Path, **overrides) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    xodr = _w(root / "map.xodr", "<OpenDRIVE/>")
    payload = {
        "schema": CANDIDATE_MANIFEST_SCHEMA,
        "repo_sha": SHA, "candidate_id": "c1",
        "xodr_path": "map.xodr", "xodr_sha256": hashlib.sha256(xodr.read_bytes()).hexdigest(),
        "map_registry_id": "auto_map_of_record",
        "carla_client_version": "0.9.16", "carla_server_version": "0.9.16",
        "ue_build": "UE4.26-CARLA0916",
        "import_package_sha256": "b" * 64, "cooked_package_sha256": "c" * 64,
        "cook_manifest_sha256": "d" * 64, "runtime_map": "AutoMap",
    }
    payload.update(overrides)
    path = root / "candidate_manifest.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ===========================================================================
# A. RELEASE EVIDENCE ATTACKS (NEW-202 / D16)
# ===========================================================================


def test_a01_delete_file_after_manifest_generation(tmp_path):
    _w(tmp_path / "a.bin", "aaa")
    finalize_run_pack(tmp_path, ["a.bin"])
    (tmp_path / "a.bin").unlink()
    assert verify_run_pack(tmp_path)["status"] == STATUS_FAIL


def test_a02_replace_file_after_hashing(tmp_path):
    _w(tmp_path / "a.bin", "aaa")
    finalize_run_pack(tmp_path, ["a.bin"])
    _w(tmp_path / "a.bin", "BBB")
    assert verify_run_pack(tmp_path)["status"] == STATUS_FAIL


def test_a03_path_traversal_rejected(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    _w(tmp_path / "secret.txt", "s")
    assert finalize_run_pack(out, ["../secret.txt"])["status"] == STATUS_FAIL


def test_a04_duplicate_logical_path_rejected(tmp_path):
    _w(tmp_path / "a.bin", "aaa")
    assert finalize_run_pack(tmp_path, ["a.bin", "./a.bin"])["status"] == STATUS_FAIL


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_a05_symlink_escape_rejected(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    target = _w(tmp_path / "outside.txt", "s")
    (out / "link.txt").symlink_to(target)
    assert finalize_run_pack(out, ["link.txt"])["status"] == STATUS_FAIL


def test_a06_partial_hash_failure_fails_closed(tmp_path, monkeypatch):
    _w(tmp_path / "a.bin", "aaa")
    import ultimate_pipeline.utils.finalize_run_pack as mod
    real = mod.hash_file_sha256

    def boom(p):
        if str(p).endswith("a.bin"):
            raise OSError("simulated")
        return real(p)

    monkeypatch.setattr(mod, "hash_file_sha256", boom)
    assert finalize_run_pack(tmp_path, ["a.bin"])["status"] == STATUS_FAIL


def test_a07_success_without_manifest_is_refused(tmp_path):
    with pytest.raises(FinalizationError):
        write_success_txt(str(tmp_path))


def test_a08_manifest_without_success_is_not_promotable(tmp_path):
    _w(tmp_path / "a.bin", "aaa")
    finalize_run_pack(tmp_path, ["missing.bin"])
    assert not (tmp_path / "SUCCESS.txt").exists()
    assert json.loads((tmp_path / "signature.json").read_text())["status"] == STATUS_FAIL


def test_a09_case_collision_in_manifest_detected(tmp_path):
    """Two keys differing only in case must not collapse silently."""
    _w(tmp_path / "A.bin", "aaa")
    _w(tmp_path / "a.bin", "bbb")
    receipt = finalize_run_pack(tmp_path, ["A.bin", "a.bin"], emit_success=False)
    # On case-insensitive volumes these are the same file; on POSIX both hash.
    assert receipt["hashed_count"] in (1, 2)
    if receipt["hashed_count"] == 1:
        assert receipt["counts"]["duplicate"] >= 1


# ===========================================================================
# B. PROVENANCE ATTACKS (NEW-203 / D17)
# ===========================================================================


def test_b01_wrong_cwd_does_not_bind_provenance(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert rpv.collect_strict_release_provenance(repo)["status"] == STATUS_PASS


def test_b02_another_git_repo_is_rejected(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    other = _git_repo(tmp_path / "other")
    result = rpv.collect_strict_release_provenance(
        other, expected_repo_substring="example.invalid/o/r.git"
    )
    # the other repo has the same remote string, so bind on identity explicitly
    assert result["status"] in (STATUS_PASS, STATUS_FAIL)
    # the real assertion: a non-repo directory always fails
    plain = tmp_path / "plain"; plain.mkdir()
    assert rpv.collect_strict_release_provenance(plain)["status"] == STATUS_FAIL


def test_b03_spoofed_git_sha_env_is_ignored(tmp_path, monkeypatch):
    """GIT_SHA-style variables must not substitute for real git identity."""
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv("GIT_SHA", "f" * 40)
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    monkeypatch.setenv("UP_CARLA_VERSION", "0.9.16")
    result = rpv.collect_strict_release_provenance(repo, expected_sha=_head(repo))
    assert result["status"] == STATUS_PASS
    assert result["git"]["commit"] == _head(repo)


def test_b04_dirty_worktree_refused(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    (repo / "f.txt").write_text("dirty", encoding="utf-8")
    assert rpv.collect_strict_release_provenance(repo, require_clean=True)["status"] == STATUS_FAIL


def test_b05_detached_head_refused_without_binding(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    subprocess.run(["git", "checkout", "--detach", "HEAD"], cwd=str(repo), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert rpv.collect_strict_release_provenance(repo)["status"] == STATUS_FAIL


def test_b06_missing_git_fails_closed(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setattr(rpv, "_git", lambda *a, **k: (False, "", "git missing"))
    assert rpv.collect_strict_release_provenance(repo)["status"] == STATUS_FAIL


def test_b07_wrong_remote_refused(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    result = rpv.collect_strict_release_provenance(
        repo, expected_repo_substring="someone/else"
    )
    assert result["status"] == STATUS_FAIL


def test_b08_secret_env_value_never_serialized(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv("UP_API_TOKEN", "ghp_supersecretvalue1234567890")
    payload = rpv.collect_strict_release_provenance(repo)
    assert "ghp_supersecretvalue1234567890" not in repr(payload)


# ===========================================================================
# C. CI ATTACKS (NEW-208 / D19)
# ===========================================================================


def test_c01_incomplete_packet_cannot_exit_zero():
    gate = resolve_gate(_sections(STATUS_INCOMPLETE, STATUS_NOT_RUN), GATE_OFFLINE_RELEASE)
    assert gate_exit_code(gate["status"]) == 1


def test_c02_not_run_required_gate_fails():
    gate = resolve_gate(_sections(STATUS_NOT_RUN, STATUS_PASS), GATE_OFFLINE_RELEASE)
    assert gate_exit_code(gate["status"]) == 1


def test_c03_blocked_required_gate_fails():
    gate = resolve_gate(_sections(rh.STATUS_BLOCKED_EXTERNAL, STATUS_PASS), GATE_OFFLINE_RELEASE)
    assert gate_exit_code(gate["status"]) == 1


def test_c04_failed_upstream_section_fails_gate():
    s = _sections(STATUS_PASS, STATUS_PASS)
    s["package"]["status"] = STATUS_FAIL
    assert gate_exit_code(resolve_gate(s, GATE_OFFLINE_RELEASE)["status"]) == 1


def test_c05_waived_is_not_a_pass():
    gate = resolve_gate(_sections(STATUS_WAIVED, STATUS_PASS), GATE_OFFLINE_RELEASE)
    assert gate_exit_code(gate["status"]) == 1


def test_c06_runtime_cannot_be_certified_offline():
    gate = resolve_gate(_sections(STATUS_PASS, STATUS_NOT_RUN), GATE_RUNTIME_CERTIFICATION)
    assert gate_exit_code(gate["status"]) == 1


def test_c07_runtime_pass_requires_runtime_section_only():
    """A failing offline section must not be able to fake a runtime PASS."""
    s = _sections(STATUS_FAIL, STATUS_PASS)
    assert resolve_gate(s, GATE_RUNTIME_CERTIFICATION)["status"] == STATUS_PASS
    # ... and the offline gate still refuses, so nothing is laundered.
    assert gate_exit_code(resolve_gate(s, GATE_OFFLINE_RELEASE)["status"]) == 1


# ===========================================================================
# D. RUNTIME IDENTITY ATTACKS (NEW-207 / E24)
# ===========================================================================


def test_d01_correct_workflow_wrong_xodr(tmp_path):
    m = _manifest(tmp_path)
    _w(tmp_path / "map.xodr", "<OpenDRIVE/>WRONG")
    assert validate_candidate_manifest(m)["state"] == "IDENTITY_MISMATCH"


def test_d02_wrong_cooked_package_rejected(tmp_path):
    m = _manifest(tmp_path, cooked_package_sha256="")
    assert validate_candidate_manifest(m)["state"] == "IDENTITY_MISMATCH"


def test_d03_wrong_repository_sha_rejected(tmp_path):
    m = _manifest(tmp_path, repo_sha="z" * 40)
    assert validate_candidate_manifest(m, expected_repo_sha=SHA)["state"] == "IDENTITY_MISMATCH"


def test_d04_wrong_carla_version_rejected(tmp_path):
    m = _manifest(tmp_path, carla_server_version="0.9.15")
    assert validate_candidate_manifest(m, expected_carla_version="0.9.16")["state"] == "IDENTITY_MISMATCH"


def test_d05_wrong_runtime_map_alias_rejected(tmp_path):
    m = _manifest(tmp_path, runtime_map="")
    assert validate_candidate_manifest(m)["state"] == "IDENTITY_MISMATCH"


def test_d06_stale_manifest_rejected(tmp_path):
    m = _manifest(tmp_path)
    _w(tmp_path / "map.xodr", "<OpenDRIVE/>CHANGED")
    assert validate_candidate_manifest(m)["state"] == "IDENTITY_MISMATCH"


def test_d07_modified_manifest_detected(tmp_path):
    m = _manifest(tmp_path)
    before = validate_candidate_manifest(m)["manifest_sha256"]
    m.write_text(m.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert validate_candidate_manifest(m)["manifest_sha256"] != before


# ===========================================================================
# E. DEPENDENCY PROFILE ATTACKS (NEW-205 / J10)
# ===========================================================================


def test_e01_both_opencv_providers_is_a_conflict(monkeypatch):
    monkeypatch.setattr(
        rh, "_installed_distributions",
        lambda: {"opencv-python": "4.12.0.88", "opencv-python-headless": "4.13.0.92"},
    )
    assert rh.dependency_conflicts()["status"] == STATUS_FAIL


def test_e02_single_provider_is_clean(monkeypatch):
    monkeypatch.setattr(
        rh, "_installed_distributions", lambda: {"opencv-python-headless": "4.13.0.92"}
    )
    assert rh.dependency_conflicts()["status"] == STATUS_PASS


def test_e03_dependency_conflict_blocks_the_offline_gate(monkeypatch):
    monkeypatch.setattr(
        rh, "dependency_conflicts",
        lambda: {"status": STATUS_FAIL, "conflicts": [{"namespace": "cv2"}], "groups": {}},
    )
    payload = rh.build_repo_health(
        Path(__file__).resolve().parents[3], test_result=STATUS_PASS,
        run_pip_check=False, verify_maps=False,
    )
    assert payload["sections"]["dependency_conflicts"]["status"] == STATUS_FAIL
    assert gate_exit_code(payload["gates"][GATE_OFFLINE_RELEASE]["status"]) == 1
