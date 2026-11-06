from __future__ import annotations

import subprocess
from pathlib import Path

from research.evidence.canonical import is_dirty_worktree


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "tracked.py")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_untracked_importable_python_file_makes_source_dirty(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "shadow_module.py").write_text("VALUE = 2\n", encoding="utf-8")

    assert is_dirty_worktree(repo) is True


def test_untracked_non_python_artifact_does_not_make_source_dirty(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "run.log").write_text("diagnostic output\n", encoding="utf-8")

    assert is_dirty_worktree(repo) is False
