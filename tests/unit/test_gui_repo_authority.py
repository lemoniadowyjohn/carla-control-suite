"""GUI repository mutation authority: same lease as the CLI, fail-closed."""

from __future__ import annotations

import pytest

from ultimate_pipeline.governance.single_writer import lock_paths
from ultimate_pipeline.governance.single_writer.worktree_lock import (
    acquire_worktree_lease,
    release_worktree_lease,
)
from ultimate_pipeline.gui.control_center.plans import ExperimentPlan, save_plan
from ultimate_pipeline.gui.repo_authority import (
    RepositoryAuthority,
    RepositoryMutationRefused,
)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "worktree"
    (root / ".git").mkdir(parents=True)
    return root


def test_gui_write_inside_repo_holds_and_releases_worktree_lease(repo):
    authority = RepositoryAuthority()
    target = repo / "plans" / "run.json"
    with authority.write(target, "test write"):
        assert authority.held is True
        assert lock_paths.worktree_lease_path(repo, repo).exists()
    assert authority.held is False
    assert not lock_paths.worktree_lease_path(repo, repo).exists()


def test_gui_write_outside_repo_is_not_governed(tmp_path):
    authority = RepositoryAuthority()
    target = tmp_path / "exports" / "run.json"
    with authority.write(target):
        assert authority.held is False
    assert not (tmp_path / ".git").exists()


def test_reentrant_writes_share_one_lease_until_outermost_exits(repo):
    authority = RepositoryAuthority()
    seen = []
    with authority.write(repo / "a.json"):
        seen.append(authority.lease_id)
        with authority.write(repo / "b.json"):
            seen.append(authority.lease_id)
            assert authority.held is True
        assert authority.held is True, "inner exit must not release the lease"
    assert len(set(seen)) == 1
    assert authority.held is False


def test_read_only_session_refuses_repo_write(repo, monkeypatch):
    monkeypatch.setenv("READ_ONLY_SESSION", "1")
    authority = RepositoryAuthority()
    with pytest.raises(RepositoryMutationRefused, match="BLOCKED_READ_ONLY_SESSION"):
        with authority.write(repo / "blocked.json"):
            pass


def test_held_lease_by_live_process_refuses_write(repo):
    holder = acquire_worktree_lease(repo, purpose="other writer")
    try:
        authority = RepositoryAuthority()
        with pytest.raises(RepositoryMutationRefused,
                           match="BLOCKED_MUTATION_AUTHORITY"):
            with authority.write(repo / "blocked.json"):
                pass
        assert authority.held is False
    finally:
        release_worktree_lease(
            repo, owner_token=holder.owner_token, lease_id=holder.lease_id
        )


def test_save_plan_in_repo_is_gated_and_read_only_blocks_it(repo, monkeypatch):
    plan = ExperimentPlan(name="authority", experiment="Weather robustness", seed=1)
    target = repo / "plans" / "authority.json"
    save_plan(plan, target)
    assert target.exists()
    assert not lock_paths.worktree_lease_path(repo, repo).exists()

    monkeypatch.setenv("READ_ONLY_SESSION", "1")
    with pytest.raises(RepositoryMutationRefused):
        save_plan(plan, repo / "plans" / "blocked.json")
