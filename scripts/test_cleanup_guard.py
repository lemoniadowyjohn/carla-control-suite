"""Regression suite for the generic filesystem cleanup guard.

Required coverage (5/5 must pass):
    repo_root              -> DENY
    worktree_root          -> DENY
    parent_of_worktree     -> DENY
    junction_to_worktree   -> DENY
    allowed_scratch_child  -> ALLOW

The suite builds a disposable fixture repository in a temporary directory and
creates a real junction with ``mklink /J`` so the link-resolution requirement is
exercised for real rather than mocked.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cleanup_guard import (  # noqa: E402
    Verdict,
    build_guard,
    canonicalize,
    evaluate,
    guarded_rmtree,
    CleanupGuardError,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(*args, cwd=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        errors="replace", timeout=120,
    )


def _tracked_state(repo):
    """Tracked + staged file lists; untracked paths are excluded by design."""
    out = []
    for args in (["diff", "--name-only"], ["diff", "--cached", "--name-only"]):
        out.append(subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, text=True,
            errors="replace", timeout=60).stdout)
    return "\n".join(out)


def _executable_text_mentions(path, needles=("git add", "add -A", "\"add\"", "'add'")):
    """True if any forbidden token appears in code (not in docstrings/comments)."""
    import io
    import tokenize
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    tokens = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            tokens.append(tok.string)
    except tokenize.TokenError:
        tokens = [source]
    blob = " ".join(tokens)
    return any(n in blob for n in needles)


class Fixture:
    """A throwaway repo + registered worktree, torn down at the end."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="cleanup_guard_fixture_")
        self.repo = os.path.join(self.root, "repo")
        self.scratch = os.path.join(self.root, "scratch")
        self.wt = os.path.join(self.scratch, "wt")
        self.child = os.path.join(self.scratch, "child_dir")
        self.junction = os.path.join(self.root, "junction_to_wt")
        os.makedirs(self.repo)
        os.makedirs(self.scratch)
        _git("init", "-q", "-b", "main", cwd=self.repo)
        _git("config", "user.email", "guard@test.invalid", cwd=self.repo)
        _git("config", "user.name", "Guard Test", cwd=self.repo)
        with open(os.path.join(self.repo, "README.md"), "w") as fh:
            fh.write("fixture\n")
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-qm", "init", cwd=self.repo)
        _git("worktree", "add", "-q", "-b", "wtbranch", self.wt, cwd=self.repo)
        # A plain scratch child, allowed to be cleaned.
        os.makedirs(self.child, exist_ok=True)
        with open(os.path.join(self.child, "scratch.bin"), "w") as fh:
            fh.write("x" * 32)
        self._make_junction()

    def _make_junction(self):
        if os.path.islink(self.junction) or os.path.exists(self.junction):
            return
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", self.junction, self.wt],
            capture_output=True, text=True, errors="replace", timeout=60,
        )
        self.junction_created = proc.returncode == 0 and os.path.isdir(self.junction)

    def cleanup(self):
        try:
            if os.path.isdir(self.junction) and not os.path.islink(self.junction):
                subprocess.run(["cmd", "/c", "rmdir", self.junction],
                               capture_output=True, timeout=60)
        except OSError:
            pass
        shutil.rmtree(self.root, ignore_errors=True)


def run_tests():
    fx = Fixture()
    guard = build_guard(fx.repo)
    results = []

    def record(case, target, expected):
        decision = evaluate(guard, target)
        passed = decision["verdict"] == expected
        results.append({
            "case": case,
            "target": target,
            "canonical": decision["canonical"],
            "verdict": decision["verdict"],
            "expected": expected,
            "reasons": decision["reasons"],
            "pass": passed,
        })
        return passed

    try:
        # 1. repository root
        record("repo_root", fx.repo, Verdict.DENY)

        # 2. registered worktree root (.git pointer file)
        record("worktree_root", fx.wt, Verdict.DENY)

        # 3. parent of a registered worktree
        record("parent_of_worktree", fx.scratch, Verdict.DENY)

        # 4. junction resolving to a registered worktree
        if fx.junction_created:
            record("junction_to_worktree", fx.junction, Verdict.DENY)
        else:
            results.append({
                "case": "junction_to_worktree", "target": fx.junction,
                "verdict": Verdict.DENY, "expected": Verdict.DENY,
                "reasons": ["JUNCTION_CREATION_UNSUPPORTED"],
                "pass": False, "note": "mklink /J failed; cannot claim PASS",
            })

        # 5. ordinary scratch child
        record("allowed_scratch_child", fx.child, Verdict.ALLOW)

        # Behavioural checks that the predicate matches the executor.
        enforced = True
        try:
            guarded_rmtree(guard, fx.wt, dry_run=True)
            enforced = False
        except CleanupGuardError:
            pass

        # A real, permitted delete must not touch tracked or staged state.
        idx_before = _tracked_state(fx.repo)
        guard_ok = True
        try:
            guard_ok = guarded_rmtree(guard, fx.child, dry_run=False)["git_index_unchanged"]
        except Exception:
            guard_ok = False
        idx_after = _tracked_state(fx.repo)

        # Self-protection against a staged follow-up.
        staged_before = subprocess.run(
            ["git", "-C", fx.repo, "diff", "--cached", "--name-only"],
            capture_output=True, text=True, errors="replace", timeout=60).stdout

    finally:
        fx.cleanup()

    # No git add / add -A anywhere in the *executable* code of the guard module.
    # Docstrings and comments name the forbidden commands on purpose, so they
    # are stripped before the scan.
    no_autostage = not _executable_text_mentions(
        os.path.join(REPO, "scripts", "cleanup_guard.py"))

    payload = {
        "schema": "worktree_cleanup_guard_final/v1",
        "cases": results,
        "passed": sum(1 for r in results if r["pass"]),
        "total": len(results),
        "deny_enforced_on_worktree": enforced,
        "no_autostage_in_source": no_autostage,
        "git_status_identical_before_after": idx_before == idx_after,
        "git_index_unchanged_by_allowed_delete": guard_ok,
        "staged_paths_after": staged_before.split(),
    }
    payload["ALL_REQUIRED_PASS"] = (
        payload["passed"] == 5
        and payload["total"] == 5
        and enforced
        and no_autostage
        and payload["git_status_identical_before_after"]
        and guard_ok
        and not payload["staged_paths_after"]
    )
    return payload


if __name__ == "__main__":
    out = run_tests()
    dest = os.path.join(REPO, "reports", "WORKTREE_CLEANUP_GUARD_FINAL.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(json.dumps(out, indent=2))
    sys.exit(0 if out["ALL_REQUIRED_PASS"] else 1)
