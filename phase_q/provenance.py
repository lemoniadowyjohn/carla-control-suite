"""Q0 - Evidence-generation provenance and clean-worktree closure.

Captures, for any final certification run:

* git rev-parse HEAD / branch
* git status --porcelain=v1
* git diff --binary              (working tree)
* git diff --cached --binary     (staged)
* git submodule status
* git lfs status

Then classifies the run as either:

* CLEAN_COMMITTED_EVIDENCE_RUN
* DIRTY_WORKTREE_EVIDENCE_RUN_WITH_PATCH_HASH

For a dirty run the base commit, working-tree patch SHA-256, staged patch
SHA-256, untracked-file inventory, exact script SHA-256 values and Python
module import paths are recorded.  The evidence commit chain distinguishes
implementation / evidence-generation / publication / package-build commits.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase_q.common import (
    PROJECT_ROOT,
    make_run_id,
    save_json,
    save_text,
    sha256_bytes,
    sha256_file,
    utcnow_iso,
)

CLEAN_RUN = "CLEAN_COMMITTED_EVIDENCE_RUN"
DIRTY_RUN = "DIRTY_WORKTREE_EVIDENCE_RUN_WITH_PATCH_HASH"


def git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_git_bytes(repo_root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        cwd=str(repo_root),
        capture_output=True,
    ).stdout


def git_or_error(repo_root: Path, *args: str) -> str:
    proc = git(repo_root, *args)
    return proc.stdout


def capture_worktree_provenance(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    root = Path(repo_root) if repo_root else PROJECT_ROOT
    root = root.resolve()
    record: Dict[str, Any] = {
        "captured_at": utcnow_iso(),
        "repo_root": str(root),
        "git": {},
        "patch_hashes": {},
        "untracked": [],
        "classification": None,
        "run_id": make_run_id(),
    }

    head = git_or_error(root, "rev-parse", "HEAD").strip()
    branch = git_or_error(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    record["git"]["head_commit"] = head
    record["git"]["branch"] = branch
    record["git"]["head_short"] = head[:12] if head else ""

    status_proc = git(root, "status", "--porcelain=v1")
    record["git"]["status_porcelain"] = status_proc.stdout
    record["git"]["status_exit"] = status_proc.returncode
    dirty = bool(status_proc.stdout.strip())

    sub_proc = git(root, "submodule", "status")
    record["git"]["submodule_status"] = sub_proc.stdout
    record["git"]["submodule_exit"] = sub_proc.returncode

    lfs_proc = git(root, "lfs", "status")
    record["git"]["lfs_status"] = lfs_proc.stdout if lfs_proc.returncode == 0 else ""
    record["git"]["lfs_exit"] = lfs_proc.returncode

    diff_working = run_git_bytes(root, "diff", "--binary")
    diff_staged = run_git_bytes(root, "diff", "--cached", "--binary")
    record["patch_hashes"]["working_tree_patch_sha256"] = sha256_bytes(diff_working)
    record["patch_hashes"]["staged_patch_sha256"] = sha256_bytes(diff_staged)
    record["patch_hashes"]["working_tree_patch_bytes"] = len(diff_working)
    record["patch_hashes"]["staged_patch_bytes"] = len(diff_staged)

    untracked = _untracked_inventory(root)
    record["untracked"] = untracked
    record["untracked_count"] = len(untracked)

    record["classification"] = DIRTY_RUN if dirty else CLEAN_RUN
    record["clean_worktree"] = not dirty
    return record


def _untracked_inventory(root: Path) -> List[Dict[str, Any]]:
    proc = git(root, "ls-files", "--others", "--exclude-standard")
    entries = []
    for line in proc.stdout.splitlines():
        rel = line.strip()
        if not rel:
            continue
        p = root / rel
        try:
            entries.append({
                "path": rel,
                "size_bytes": p.stat().st_size if p.is_file() else None,
                "is_dir": p.is_dir(),
            })
        except OSError:
            entries.append({"path": rel, "size_bytes": None, "is_dir": False})
    entries.sort(key=lambda e: e["path"])
    return entries


def script_hash_registry(scripts: Optional[List[str]] = None) -> Dict[str, Any]:
    """Q01 - hash of every governing script plus its import provenance."""
    default_scripts = [
        "phase_l_validation.py",
        "run_n_certify.py",
        "run_q_phase.py",
        "ultimate_pipeline/tools/load_final_into_carla.py",
        "ultimate_pipeline/core/carla_opendrive_loader.py",
        "ultimate_pipeline/quality/check_carla_opendrive_compat.py",
    ]
    scripts = scripts or default_scripts
    entries = []
    for rel in scripts:
        p = PROJECT_ROOT / rel
        if p.is_file():
            entries.append({
                "path": rel,
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
                "exists": True,
            })
        else:
            entries.append({"path": rel, "sha256": None, "size_bytes": None, "exists": False})
    entries.sort(key=lambda e: e["path"])

    module_paths: Dict[str, str] = {}
    try:
        import phase_q
        module_paths["phase_q"] = phase_q.__file__
    except Exception as exc:
        module_paths["phase_q"] = f"unimportable: {exc}"

    return {
        "generated_at": utcnow_iso(),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "module_import_paths": {
            "sys_path": list(sys.path),
            "phase_q_resolved": module_paths,
        },
        "scripts": entries,
    }


def classify_commits(max_count: int = 60) -> List[Dict[str, str]]:
    """Parse git log and classify each commit's role.

    Roles:
      implementation      - functional/pipeline changes (phase-*, fix:, feat:)
      evidence-generation - run reports / evidence manifests
      package-build       - cooked package / packaging commits
      publication         - release / publish / final-verdict commits
      unknown             - unclassifiable
    """
    proc = git(PROJECT_ROOT, "log", f"--max-count={max_count}", "--format=%H|%s")
    commits = []
    for line in proc.stdout.splitlines():
        if "|" not in line:
            continue
        sha, subject = line.split("|", 1)
        role = classify_commit_role(subject)
        commits.append({"commit": sha, "short": sha[:12], "subject": subject, "role": role})
    return commits


def classify_commit_role(subject: str) -> str:
    s = subject.lower()
    if any(k in s for k in ("release", "publish", "final", "verdict", "certif")):
        return "publication"
    if any(k in s for k in ("package", "cook", "cooking", "build:")):
        return "package-build"
    if any(k in s for k in ("evidence", "report", "run ", "n0", "n1", "phase-l", "audit", "manifest")):
        return "evidence-generation"
    if any(k in s for k in ("phase-", "fix:", "feat:", "test:", "chore:", "refactor:")):
        return "implementation"
    return "unknown"


def evidence_commit_chain_md(commits: Optional[List[Dict[str, str]]] = None) -> str:
    """Q02 - evidence commit chain markdown."""
    commits = commits or classify_commits()
    lines = [
        "# Q02 - Evidence Commit Chain",
        "",
        f"Generated: {utcnow_iso()}",
        f"Branch: {git(PROJECT_ROOT, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()}",
        "",
        "Commit roles are distinguished as:",
        "",
        "- **implementation** - pipeline/functional changes",
        "- **evidence-generation** - run reports / evidence manifests",
        "- **publication** - release verdicts / certification commits",
        "- **package-build** - cooked package / packaging commits",
        "",
        "| Commit | Role | Subject |",
        "|--------|------|---------|",
    ]
    for c in commits:
        subject = c["subject"].replace("|", "\\|")
        lines.append("| {} | {} | {} |".format(c["short"], c["role"], subject))
    return "\n".join(lines)


def write_q0_outputs(out_dir: Path) -> Dict[str, str]:
    """Write Q00/Q01/Q02 artifacts.  Returns map of artifact -> absolute path."""
    prov = capture_worktree_provenance()
    q00 = save_json(out_dir / "Q00_WORKTREE_PROVENANCE.json", prov)
    q01 = save_json(out_dir / "Q01_SCRIPT_HASH_REGISTRY.json", script_hash_registry())
    q02 = save_text(out_dir / "Q02_EVIDENCE_COMMIT_CHAIN.md", evidence_commit_chain_md())

    # Persist the exact patches for forensic comparison.
    root = PROJECT_ROOT
    diff_working = run_git_bytes(root, "diff", "--binary")
    diff_staged = run_git_bytes(root, "diff", "--cached", "--binary")
    wf = out_dir / "worktree.patch"
    wf.write_bytes(diff_working)
    sf = out_dir / "staged.patch"
    sf.write_bytes(diff_staged)

    return {
        "Q00_WORKTREE_PROVENANCE.json": q00,
        "Q01_SCRIPT_HASH_REGISTRY.json": q01,
        "Q02_EVIDENCE_COMMIT_CHAIN.md": q02,
        "worktree.patch": str(wf),
        "staged.patch": str(sf),
    }


def require_clean_for_final_release(prov: Optional[Dict[str, Any]] = None) -> None:
    """Fail-closed: final release requires a clean committed rerun."""
    prov = prov or capture_worktree_provenance()
    if prov["classification"] != CLEAN_RUN:
        raise ProvenanceGateError(
            "Final release requires CLEAN_COMMITTED_EVIDENCE_RUN; "
            f"got {prov['classification']} (base commit {prov['git']['head_short']}). "
            "Commit all changes and rerun."
        )


class ProvenanceGateError(RuntimeError):
    pass
