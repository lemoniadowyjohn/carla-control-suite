# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/utils/run_provenance.py (V5 / NEW-203, D17).

Covers strict release provenance: repository-root binding independent of the
process CWD, expected-SHA binding, fail-closed semantics, detached HEAD, dirty
worktree, git unavailability, and environment-variable sanitization.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ultimate_pipeline.utils import run_provenance as rp


def _init_repo(path: Path, *, remote: str | None = "https://example.invalid/o/r.git") -> Path:
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
    if remote:
        g("remote", "add", "origin", remote)
    return path


def _head(path: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(path), check=True,
                          capture_output=True, text=True).stdout.strip()


# ---------------------------------------------------------------------------
# repository-root binding (never CWD-derived)
# ---------------------------------------------------------------------------


def test_strict_provenance_uses_supplied_repo_root_not_cwd(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "the_repo")
    outside = tmp_path / "not_a_repo"
    outside.mkdir()
    # Run with CWD deliberately pointing at a non-repository directory.
    monkeypatch.chdir(outside)

    payload = rp.collect_strict_release_provenance(repo)
    assert payload["git"]["repo_root"] == str(repo.resolve())
    assert payload["git"]["commit"] == _head(repo)
    assert payload["status"] == rp.STATUS_PASS


def test_correct_repository_passes_with_expected_sha(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    payload = rp.collect_strict_release_provenance(repo, expected_sha=_head(repo))
    assert payload["status"] == rp.STATUS_PASS
    assert payload["failures"] == []
    assert payload["git"]["expected_sha"] == _head(repo)


def test_wrong_expected_sha_fails(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    payload = rp.collect_strict_release_provenance(repo, expected_sha="0" * 40)
    assert payload["status"] == rp.STATUS_FAIL
    assert any(f["field"] == "git.commit" for f in payload["failures"])
    # the mismatch reason is preserved, not swallowed
    assert any("expected SHA" in f["reason"] for f in payload["failures"])


def test_wrong_repository_identity_fails(tmp_path):
    repo = _init_repo(tmp_path / "repo", remote="https://example.invalid/o/other.git")
    payload = rp.collect_strict_release_provenance(
        repo, expected_repo_substring="lemoniadowyjohn/carla-control-suite"
    )
    assert payload["status"] == rp.STATUS_FAIL
    assert any(f["field"] == "git.remotes" for f in payload["failures"])


def test_non_git_directory_fails_closed(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "x").write_text("x", encoding="utf-8")
    payload = rp.collect_strict_release_provenance(plain)
    assert payload["status"] == rp.STATUS_FAIL
    assert any(f["field"] == "git" for f in payload["failures"])


def test_missing_repo_root_argument_fails_closed():
    payload = rp.collect_strict_release_provenance(None)
    assert payload["status"] == rp.STATUS_FAIL
    assert any("CWD" in f["reason"] for f in payload["failures"])


def test_nonexistent_repo_root_fails_closed(tmp_path):
    payload = rp.collect_strict_release_provenance(tmp_path / "does_not_exist")
    assert payload["status"] == rp.STATUS_FAIL


def test_git_unavailable_fails_closed(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")

    def no_git(repo_root, *args, **kwargs):
        return False, "", "git executable not found: simulated"

    monkeypatch.setattr(rp, "_git", no_git)
    payload = rp.collect_strict_release_provenance(repo)
    assert payload["status"] == rp.STATUS_FAIL
    assert any("git unavailable" in f["reason"] for f in payload["failures"])


# ---------------------------------------------------------------------------
# dirty / detached / remote states
# ---------------------------------------------------------------------------


def test_dirty_worktree_blocks_release_evidence(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "f.txt").write_text("modified", encoding="utf-8")
    payload = rp.collect_strict_release_provenance(repo, require_clean=True)
    assert payload["status"] == rp.STATUS_FAIL
    assert any(f["field"] == "git.dirty" for f in payload["failures"])


def test_dirty_worktree_allowed_when_not_required(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "f.txt").write_text("modified", encoding="utf-8")
    payload = rp.collect_strict_release_provenance(repo, require_clean=False)
    assert payload["status"] == rp.STATUS_PASS
    assert payload["git"]["dirty"] is True


def test_untracked_file_counts_as_dirty(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "untracked.bin").write_text("x", encoding="utf-8")
    payload = rp.collect_strict_release_provenance(repo, require_clean=True)
    assert payload["status"] == rp.STATUS_FAIL


def test_detached_head_without_expected_sha_fails(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    subprocess.run(["git", "checkout", "--detach", "HEAD"], cwd=str(repo), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    payload = rp.collect_strict_release_provenance(repo)
    assert payload["git"]["detached_head"] is True
    assert payload["status"] == rp.STATUS_FAIL
    assert any("detached HEAD" in f["reason"] for f in payload["failures"])


def test_detached_head_with_expected_sha_is_bound(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    sha = _head(repo)
    subprocess.run(["git", "checkout", "--detach", sha], cwd=str(repo), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    payload = rp.collect_strict_release_provenance(repo, expected_sha=sha)
    assert payload["git"]["detached_head"] is True
    assert payload["status"] == rp.STATUS_PASS


def test_missing_remote_fails_when_required(tmp_path):
    repo = _init_repo(tmp_path / "repo", remote=None)
    payload = rp.collect_strict_release_provenance(repo, require_remote=True)
    assert payload["status"] == rp.STATUS_FAIL
    assert any("no configured git remote" in f["reason"] for f in payload["failures"])


def test_missing_remote_tolerated_when_not_required(tmp_path):
    repo = _init_repo(tmp_path / "repo", remote=None)
    payload = rp.collect_strict_release_provenance(repo, require_remote=False)
    assert payload["status"] == rp.STATUS_PASS


# ---------------------------------------------------------------------------
# path shapes
# ---------------------------------------------------------------------------


def test_repo_path_containing_spaces(tmp_path):
    repo = _init_repo(tmp_path / "repo with spaces")
    payload = rp.collect_strict_release_provenance(repo)
    assert payload["status"] == rp.STATUS_PASS
    assert payload["git"]["commit"] == _head(repo)


@pytest.mark.skipif(os.name == "nt", reason="POSIX path semantics")
def test_relative_repo_root_is_resolved(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.chdir(tmp_path)
    payload = rp.collect_strict_release_provenance("repo")
    assert payload["status"] == rp.STATUS_PASS
    assert payload["git"]["commit"] == _head(repo)


def test_windows_style_absolute_path(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    payload = rp.collect_strict_release_provenance(str(repo))
    assert payload["status"] == rp.STATUS_PASS
    assert Path(payload["git"]["repo_root"]).is_absolute()


# ---------------------------------------------------------------------------
# environment sanitization
# ---------------------------------------------------------------------------


def test_secret_like_up_variable_is_excluded(monkeypatch):
    monkeypatch.setenv("UP_API_KEY", "super-secret-value")
    monkeypatch.setenv("UP_CARLA_VERSION", "0.9.16")
    captured = rp.filter_release_safe_env()
    assert "UP_API_KEY" not in captured
    assert captured["UP_CARLA_VERSION"] == "0.9.16"


@pytest.mark.parametrize(
    "name",
    [
        "UP_API_TOKEN",
        "UP_PASSWORD",
        "UP_CREDENTIALS",
        "UP_AUTHORIZATION",
        "UP_SECRET",
        "UP_PRIVATE_KEY",
        "UP_SESSION_KEY",
    ],
)
def test_secret_like_names_rejected(monkeypatch, name):
    monkeypatch.setenv(name, "value")
    captured = rp.filter_release_safe_env()
    assert name not in captured


def test_unlisted_up_variable_is_excluded(monkeypatch):
    monkeypatch.setenv("UP_SOMETHING_ELSE", "value")
    assert "UP_SOMETHING_ELSE" not in rp.filter_release_safe_env()


def test_allowlisted_secret_name_is_still_rejected():
    # Even if a caller allow-lists a secret-looking name, it must be refused.
    env = {"UP_SECRET_THING": "x"}
    out = rp.filter_release_safe_env(env, allowlist=["UP_SECRET_THING"])
    assert out == {}


def test_secret_shaped_value_in_allowlisted_name_is_rejected():
    env = {"UP_CARLA_VERSION": "Bearer abcdefghijklmnopqrstuvwxyz"}
    assert rp.filter_release_safe_env(env) == {}


def test_provenance_receipt_never_contains_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("UP_API_KEY", "sk-abcdefghijklmnopqrstuvwxyz012345")
    monkeypatch.setenv("UP_CARLA_VERSION", "0.9.16")
    payload = rp.collect_provenance()
    blob = repr(payload)
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in blob
    assert "UP_API_KEY" not in payload.get("up_env_vars", {})


def test_strict_receipt_never_contains_secret(monkeypatch, tmp_path):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setenv("UP_SECRET_TOKEN", "ghp_zzzzzzzzzzzzzzzzzzzz")
    payload = rp.collect_strict_release_provenance(repo)
    assert "ghp_zzzzzzzzzzzzzzzzzzzz" not in repr(payload)
    assert "UP_SECRET_TOKEN" not in payload["environment"]["captured"]


def test_documented_allowlist_is_recorded_in_receipt(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    payload = rp.collect_strict_release_provenance(repo)
    assert payload["environment"]["policy"] == "release_safe_allowlist"
    assert "UP_CARLA_VERSION" in payload["environment"]["allowlist"]


# ---------------------------------------------------------------------------
# required fields always present
# ---------------------------------------------------------------------------


def test_strict_payload_always_contains_required_keys(tmp_path):
    payload = rp.collect_strict_release_provenance(tmp_path / "nope")
    for key in ("repo_root", "commit", "branch", "dirty", "remotes"):
        assert key in payload["git"]
    assert "python" in payload
    assert "platform" in payload
    assert "tools" in payload
    assert "carla" in payload
    assert payload["git"]["commit"] is None
    assert payload["status"] == rp.STATUS_FAIL


def test_tool_versions_include_carla_key(tmp_path):
    payload = rp.collect_strict_release_provenance(tmp_path / "nope")
    assert "carla" in payload["tools"]


# ---------------------------------------------------------------------------
# diagnostic mode preserved
# ---------------------------------------------------------------------------


def test_diagnostic_provenance_still_works_and_is_labelled(tmp_path, monkeypatch):
    monkeypatch.chdir(_init_repo(tmp_path / "repo"))
    payload = rp.collect_provenance()
    assert payload["mode"] == "diagnostic_best_effort"
    assert "git" in payload
    assert payload["git"]["commit"]


def test_diagnostic_provenance_omits_git_outside_repo(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    payload = rp.collect_provenance()
    # best-effort mode preserves the historical "omit when unavailable" behaviour
    assert "git" not in payload


def test_write_strict_provenance_emits_receipt_even_on_fail(tmp_path):
    out = tmp_path / "out"
    payload = rp.collect_and_write_strict_release_provenance(
        str(out), tmp_path / "nope", filename="strict_release_provenance.json"
    )
    assert payload["status"] == rp.STATUS_FAIL
    assert (out / "strict_release_provenance.json").is_file()


def test_cli_strict_release_exit_code(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    # Run with CWD set to this repository so the subprocess imports the code
    # under test rather than whichever copy an editable install points at.
    repo_under_test = Path(rp.__file__).resolve().parents[2]
    base = [sys.executable, "-m", "ultimate_pipeline.utils.run_provenance"]

    proc = subprocess.run(
        base + ["--strict-release", "--repo-root", str(repo),
                "--expected-sha", _head(repo), "--out", str(tmp_path / "o")],
        capture_output=True, text=True, cwd=str(repo_under_test),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    proc2 = subprocess.run(
        base + ["--strict-release", "--repo-root", str(repo),
                "--expected-sha", "0" * 40, "--out", str(tmp_path / "o2")],
        capture_output=True, text=True, cwd=str(repo_under_test),
    )
    assert proc2.returncode == 1, proc.stdout + proc2.stderr
