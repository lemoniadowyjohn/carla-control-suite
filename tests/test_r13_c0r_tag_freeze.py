#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C0-R tag-anchored freeze verifier tests (read-only; throwaway temp repos).

Positive:
  - valid annotated tag + matching files + matching message  -> VERIFIED

Negative (each must FAIL; never touches the real repository):
  - wrong tag target (tag points at HEAD~1)      -> FAIL
  - tag points HEAD~1                             -> FAIL
  - lightweight tag when annotated required      -> FAIL
  - dirty tree                                   -> FAIL
  - R13 modified                                 -> FAIL
  - R13O modified                                -> FAIL
  - R13P modified                                -> FAIL
  - primary evidence modified                    -> FAIL
  - wrong branch                                 -> FAIL
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from phase_q.c0r_tag_freeze import (  # noqa: E402
    C0RTagFreezeVerifier,
    FREEZE_BRANCH,
    VERDICT_BAD,
    VERDICT_OK,
    sha256_file,
)

BRANCH = FREEZE_BRANCH
SCHEMA = "C0R_TAG_ANCHORED_V2"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(repo),
                       capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resolve(repo: Path, ref: str):
    commit = _git(repo, "rev-parse", f"{ref}^{{commit}}")
    tree = _git(repo, "rev-parse", f"{ref}^{{tree}}")
    rc = subprocess.run(["git", "rev-parse", f"{ref}^"],
                        cwd=str(repo), capture_output=True, text=True)
    parent = rc.stdout.strip() if rc.returncode == 0 else ""
    return commit, tree, parent


def _freeze_repo(tmp: Path, *, tag: str = "c0r_freeze_test",
                 annotated: bool = True, at_head: bool = True,
                 branch: str = BRANCH, with_binding: bool = True) -> Path:
    repo = tmp / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", branch)
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")

    _write(repo / "seed.txt", "seed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    parent = _git(repo, "rev-parse", "HEAD")
    toplevel = _git(repo, "rev-parse", "--show-toplevel")

    r13 = repo / "r13.md"
    r13o = repo / "r13o.json"
    r13r = repo / "r13r.json"
    _write(r13, "# R13 packet\n")
    top_rel = toplevel.replace("\\", "/")
    _write(r13r, json.dumps({
        "schema": "R13_REPOSITORY_BINDING_V1",
        "resolved_toplevel": top_rel,
        "branch": branch,
        "pre_freeze_head": parent,
        "worktree_clean_before": True,
    }))
    _write(r13o, json.dumps({
        "freeze_schema": SCHEMA,
        "branch": branch,
        "freeze_tag": tag,
        "parent_commit": parent,
        "r13_packet_path": "r13.md",
        "primary_evidence_manifest_path": "r13p.json",
        "repository_binding_path": "r13r.json",
        "clean_tree_required": True,
        "head_must_equal_tag_target_at_review": True,
        "no_commit_after_tag_before_review": True,
        "provisional_pre_c0_authority_forbidden": True,
    }))
    r13p = repo / "r13p.json"
    entries = [{
        "path": "r13.md",
        "sha256": sha256_file(r13),
        "size_bytes": r13.stat().st_size,
        "role": "r13_packet",
        "immutable_for_review": True,
    }]
    if with_binding:
        entries.append({
            "path": "r13r.json",
            "sha256": sha256_file(r13r),
            "size_bytes": r13r.stat().st_size,
            "role": "r13_repository_binding",
            "immutable_for_review": True,
        })
    manifest = {
        "manifest_schema": "R13_PRIMARY_EVIDENCE_V1",
        "repository_binding_path": "r13r.json" if with_binding else None,
        "entries": entries,
    }
    _write(r13p, json.dumps(manifest))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "freeze files")

    if not (repo / "r13.md").exists():
        raise AssertionError("fixture broken")
    if annotated:
        target = "HEAD" if at_head else "HEAD^"
        commit, tree, tparent = _resolve(repo, target)
        lines = [
            f"freeze_schema={SCHEMA}",
            f"freeze_commit={commit}", f"freeze_tree={tree}",
            f"freeze_parent={tparent}", f"branch={branch}",
            f"repository={top_rel}",
            f"r13_path=r13.md", f"r13_sha256={sha256_file(r13)}",
            f"r13o_path=r13o.json", f"r13o_sha256={sha256_file(r13o)}",
            f"manifest_path=r13p.json", f"manifest_sha256={sha256_file(r13p)}",
        ]
        if with_binding:
            lines += [
                f"repository_binding_path=r13r.json",
                f"repository_binding_sha256={sha256_file(r13r)}",
            ]
        message = "\n".join(lines)
        _git(repo, "tag", "-a", tag, target, "-m", message)
    else:
        _git(repo, "tag", tag, "HEAD")
    return repo


def _verdict(repo: Path, tag: str = "c0r_freeze_test",
             branch: str = BRANCH) -> str:
    v = C0RTagFreezeVerifier(
        repo, tag, branch=branch,
        r13_path=repo / "r13.md",
        r13o_path=repo / "r13o.json",
        r13p_path=repo / "r13p.json",
        r13r_path=repo / "r13r.json",
    )
    return v.verify().verdict


# ---------------------------------------------------------------------------
def test_positive_verified(tmp_path):
    repo = _freeze_repo(tmp_path)
    assert _verdict(repo) == VERDICT_OK


def test_negative_wrong_tag_target(tmp_path):
    repo = _freeze_repo(tmp_path, at_head=False)
    assert _verdict(repo) == VERDICT_BAD


def test_negative_tag_points_head1(tmp_path):
    repo = _freeze_repo(tmp_path, at_head=False)
    assert _verdict(repo) == VERDICT_BAD


def test_negative_lightweight_tag(tmp_path):
    repo = _freeze_repo(tmp_path, annotated=False)
    assert _verdict(repo) == VERDICT_BAD


def test_negative_dirty_tree(tmp_path):
    repo = _freeze_repo(tmp_path)
    _write(repo / "extra.txt", "dirty")
    assert _verdict(repo) == VERDICT_BAD


def test_negative_r13_modified(tmp_path):
    repo = _freeze_repo(tmp_path)
    _write(repo / "r13.md", "# tampered\n")
    assert _verdict(repo) == VERDICT_BAD


def test_negative_r13o_modified(tmp_path):
    repo = _freeze_repo(tmp_path)
    _write(repo / "r13o.json", "{}\n")
    assert _verdict(repo) == VERDICT_BAD


def test_negative_r13p_modified(tmp_path):
    repo = _freeze_repo(tmp_path)
    _write(repo / "r13p.json", "{}\n")
    assert _verdict(repo) == VERDICT_BAD


def test_negative_primary_evidence_modified(tmp_path):
    repo = _freeze_repo(tmp_path)
    _write(repo / "r13.md", "tampered\n")
    assert _verdict(repo) == VERDICT_BAD


def test_negative_wrong_branch(tmp_path):
    repo = _freeze_repo(tmp_path, branch="other-branch")
    assert _verdict(repo) == VERDICT_BAD


def test_negative_missing_repository_binding(tmp_path):
    repo = _freeze_repo(tmp_path, with_binding=False)
    assert _verdict(repo) == VERDICT_BAD


# ---------------------------------------------------------------------------
# Committed (real-repo) freeze-schema + manifest checks (no git mutation)
# ---------------------------------------------------------------------------
R13_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / "20260808T000000Z_C0_REMEDIATION"


def test_r13o_is_tag_anchored_not_self_referential():
    r13o = json.loads((R13_DIR / "R13O_C0_REVIEW_FREEZE.json").read_text(encoding="utf-8"))
    assert r13o["freeze_schema"] == SCHEMA
    assert r13o["freeze_tag"].startswith("c0r_freeze_")
    assert r13o["clean_tree_required"] is True
    assert r13o["head_must_equal_tag_target_at_review"] is True
    assert r13o["no_commit_after_tag_before_review"] is True
    assert r13o["provisional_pre_c0_authority_forbidden"] is True
    for k in ("head_commit", "freeze_commit", "carrying_commit", "tag_object_sha"):
        assert k not in r13o


def test_r13p_manifest_sorted_hashes_match_no_provisional():
    r13p = R13_DIR / "R13P_C0_PRIMARY_EVIDENCE_MANIFEST.json"
    m = json.loads(r13p.read_text(encoding="utf-8"))
    assert m["manifest_schema"] == "R13_PRIMARY_EVIDENCE_V1"
    assert m["freeze_tag"].startswith("c0r_freeze_")
    entries = m["entries"]
    paths = [e["path"] for e in entries]
    assert paths == sorted(paths)
    n_hashed = 0
    for e in entries:
        assert e["immutable_for_review"] is True
        assert "provisional" not in (e["path"]).lower() and "r00_pre_gate" not in (e["path"]).lower()
        if e.get("role") == "r13p_evidence_manifest_self":
            assert e.get("sha256") is None  # fixed-point: no self hash
            continue
        f = REPO_ROOT / e["path"]
        assert f.is_file(), e["path"]
        assert sha256_file(f) == e["sha256"], f"sha mismatch: {e['path']}"
        assert e["size_bytes"] == f.stat().st_size
        n_hashed += 1
    assert n_hashed == len(entries) - 1


def test_r13r_repository_binding_receipt():
    m = json.loads((R13_DIR / "R13P_C0_PRIMARY_EVIDENCE_MANIFEST.json").read_text(encoding="utf-8"))
    r13r = R13_DIR / "R13R_REPOSITORY_BINDING.json"
    assert r13r.is_file()
    assert m["repository_binding_path"].endswith("R13R_REPOSITORY_BINDING.json")
    assert any(e["path"] for e in m["entries"] if e["role"] == "r13_repository_binding")
    b = json.loads(r13r.read_text(encoding="utf-8"))
    assert b["schema"] == "R13_REPOSITORY_BINDING_V1"
    assert "carla_-main" in b["resolved_toplevel"]
    assert b["branch"] == BRANCH
    assert b["worktree_clean_before"] is True
    assert b["pre_freeze_head"].startswith("38e0522c")


def test_r13o_has_repository_binding_path():
    r13o = json.loads((R13_DIR / "R13O_C0_REVIEW_FREEZE.json").read_text(encoding="utf-8"))
    assert r13o["repository_binding_path"].endswith("R13R_REPOSITORY_BINDING.json")