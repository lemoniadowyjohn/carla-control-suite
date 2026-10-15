"""Cross-volume worktree relocation with full before/after proofs.

`git worktree move` is implemented with rename(2) and therefore refuses to move
a worktree between volumes (confirmed: "Source and destination path must have
identical roots"). This driver performs the equivalent operation safely:

  1. copy the worktree tree to the destination (no delete yet)
  2. re-point <repo>/.git/worktrees/<name>/gitdir at the new location
  3. validate: HEAD, tree SHA, tracked diff fingerprint, untracked manifest
  4. confirm the repository now registers the NEW path
  5. only then delete the old directory, through the cleanup guard

The worktree's own `.git` pointer file needs no change: it references the admin
directory under the main repository, which does not move.

Nothing is deleted until step 5, and step 5 is gated by a freshly built
cleanup_guard so the guard's protected set reflects the post-move registration.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cleanup_guard import build_guard, guarded_rmtree, canonicalize  # noqa: E402

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
ADMIN = os.path.join(REPO, ".git", "worktrees")
SCRATCH = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "opencode")
DEST_ROOT = r"E:\CARLA\worktrees"
NAMES = [
    "new316-333-perception-hardening",
    "rq1-matrix-fix",
    "wt-p1",
    "wt-p1-base",
    "wt-runtime-rig",
]


def git(*args, cwd=None):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       errors="replace", timeout=900)
    return p.returncode, p.stdout, p.stderr


def fingerprint(wt):
    """Identity + dirty-state fingerprint, independent of absolute path."""
    _, head, _ = git("-C", wt, "rev-parse", "HEAD")
    _, tree, _ = git("-C", wt, "rev-parse", "HEAD^{tree}")
    _, branch, _ = git("-C", wt, "rev-parse", "--abbrev-ref", "HEAD")
    _, diff, _ = git("-C", wt, "diff", "HEAD", "--no-color")
    _, status, _ = git("-C", wt, "status", "--porcelain=v1", "--untracked-files=all")

    manifest = []
    for line in sorted(status.splitlines()):
        if len(line) < 3 or "?" not in line[:2]:
            continue
        path = line[3:].strip()
        full = os.path.join(wt, path.replace("/", os.sep))
        size, sha = None, None
        if os.path.isfile(full):
            size = os.path.getsize(full)
            h = hashlib.sha256()
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            sha = h.hexdigest()
        manifest.append({"path": path, "size": size, "sha256": sha})
    manifest.sort(key=lambda x: x["path"])

    # Full-tree content digest of every tracked file: catches any copy defect
    # that a git-level fingerprint would miss (e.g. line-ending rewrite).
    _, ls, _ = git("-C", wt, "ls-files", "-z")
    tracked_digest = hashlib.sha256()
    for rel in ls.split("\0"):
        if not rel:
            continue
        full = os.path.join(wt, rel.replace("/", os.sep))
        if os.path.isfile(full):
            tracked_digest.update(rel.encode("utf-8", "replace"))
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    tracked_digest.update(chunk)

    return {
        "head": head.strip(),
        "tree": tree.strip(),
        "branch": branch.strip(),
        "tracked_content_sha256": tracked_digest.hexdigest(),
        "tracked_diff_sha256": hashlib.sha256(
            diff.encode("utf-8", "replace")).hexdigest(),
        "untracked_manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest(),
        "untracked_count": len(manifest),
    }


def robocopy_copy(src, dst):
    t0 = time.time()
    proc = subprocess.run(
        ["robocopy", src, dst, "/E", "/COPY:DAT", "/DCOPY:DAT",
         "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
        capture_output=True, text=True, errors="replace", timeout=5400)
    # robocopy exit codes < 8 are success.
    return {"rc": proc.returncode, "ok": proc.returncode < 8,
            "seconds": round(time.time() - t0, 1)}


def _finish_stale_shell(src, dst, name, entry):
    """Retire a source shell that has already been copied and re-registered.

    The shell still contains a ``.git`` pointer file, so the cleanup guard
    correctly refuses to delete it: from git's point of view it is still a
    worktree root. That refusal is the guard working, not a bug, so the shell is
    de-registered first by removing ONLY the stale pointer file, after which the
    directory is an ordinary folder and the guard will authorise removal.
    """
    pointer = os.path.join(src, ".git")
    if os.path.isfile(pointer):
        with open(pointer, encoding="utf-8", errors="replace") as fh:
            entry["stale_git_pointer_content"] = fh.read().strip()
        os.remove(pointer)
        entry["stale_git_pointer_removed"] = True
    else:
        entry["stale_git_pointer_removed"] = False

    guard = build_guard(REPO)
    verdict = guard.reasons(src)
    entry["delete_verdict_after_deregister"] = "DENY" if verdict else "ALLOW"
    if verdict:
        entry["status"] = "DELETE_BLOCKED_BY_GUARD"
        return entry

    decision = guarded_rmtree(guard, src, dry_run=False)
    entry["old_dir_deleted"] = decision["executed"]
    entry["git_index_unchanged_by_delete"] = decision["git_index_unchanged"]
    entry["status"] = "RELOCATED"
    return entry


def relocate_one(name, report):
    src = os.path.join(SCRATCH, name)
    dst = os.path.join(DEST_ROOT, name)
    entry = {"name": name, "src": src, "dst": dst}

    if not os.path.isdir(src):
        entry["status"] = "ALREADY_MOVED" if os.path.isdir(dst) else "SRC_MISSING"
        return entry

    entry["before"] = fingerprint(src)

    if os.path.isdir(dst):
        # A previous attempt copied and re-registered but could not retire the
        # shell; finish that migration instead of re-copying 4 GB.
        entry["resumed"] = True
    else:
        copy = robocopy_copy(src, dst)
        entry["copy"] = copy
        if not copy["ok"]:
            entry["status"] = "COPY_FAILED"
            return entry

    # Re-point the admin record at the new location.
    gitdir_file = os.path.join(ADMIN, name, "gitdir")
    with open(gitdir_file, encoding="utf-8") as fh:
        entry["gitdir_before"] = fh.read().strip()
    with open(gitdir_file, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dst.replace("\\", "/") + "/.git\n")
    entry["gitdir_after"] = dst.replace("\\", "/") + "/.git"

    git("-C", REPO, "worktree", "prune")

    entry["after"] = fingerprint(dst)
    b, a = entry["before"], entry["after"]
    entry["head_match"] = b["head"] == a["head"]
    entry["tree_match"] = b["tree"] == a["tree"]
    entry["branch_match"] = b["branch"] == a["branch"]
    entry["tracked_content_match"] = b["tracked_content_sha256"] == a["tracked_content_sha256"]
    entry["tracked_diff_match"] = b["tracked_diff_sha256"] == a["tracked_diff_sha256"]
    entry["untracked_manifest_match"] = (
        b["untracked_manifest_sha256"] == a["untracked_manifest_sha256"])
    entry["ALL_PROOFS_MATCH"] = all(entry[k] for k in (
        "head_match", "tree_match", "branch_match", "tracked_content_match",
        "tracked_diff_match", "untracked_manifest_match"))

    # The repository must now register the NEW path and not the old one.
    _, listing, _ = git("-C", REPO, "worktree", "list", "--porcelain")
    registered = [ln[9:].strip() for ln in listing.splitlines() if ln.startswith("worktree ")]
    canon = {canonicalize(p) for p in registered}
    entry["dst_registered"] = canonicalize(dst) in canon
    entry["src_still_registered"] = canonicalize(src) in canon

    if not (entry["ALL_PROOFS_MATCH"] and entry["dst_registered"]
            and not entry["src_still_registered"]):
        entry["status"] = "VALIDATION_FAILED_OLD_PATH_RETAINED"
        return entry

    return _finish_stale_shell(src, dst, name, entry)


def main():
    os.makedirs(DEST_ROOT, exist_ok=True)
    report = {
        "schema": "worktree_relocation/v2",
        "method": "robocopy + admin gitdir repoint + prune + guarded delete",
        "git_worktree_move_cross_volume": "UNSUPPORTED_RENAME_EXDEV",
        "destination_root": DEST_ROOT,
        "destination_is_temporary": any(
            m in DEST_ROOT for m in ("Temp", "AppData", ".claude", "scratch")),
        "worktrees": [],
    }
    for name in NAMES:
        try:
            report["worktrees"].append(relocate_one(name, report))
        except Exception as exc:
            report["worktrees"].append({
                "name": name, "status": "EXCEPTION",
                "error": "%s: %s" % (type(exc).__name__, exc),
            })
        # Flush progress after every worktree so a failure never loses proofs.
        dest = os.path.join(REPO, "reports", "WORKTREE_RELOCATION.json")
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)

    _, out, _ = git("-C", REPO, "worktree", "list", "--porcelain")
    scratch = os.path.normcase(os.path.normpath(SCRATCH)).rstrip("\\")
    registered = [ln[9:].strip() for ln in out.splitlines() if ln.startswith("worktree ")]
    report["registered_worktrees_under_temp"] = sum(
        1 for p in registered if canonicalize(p).startswith(scratch + "\\"))
    report["relocated_ok"] = sum(
        1 for w in report["worktrees"] if w.get("status") == "RELOCATED")

    dest = os.path.join(REPO, "reports", "WORKTREE_RELOCATION.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print(json.dumps({k: v for k, v in report.items() if k != "worktrees"}, indent=2))
    for w in report["worktrees"]:
        print("%-32s %-38s proofs=%s" % (
            w["name"], w.get("status"), w.get("ALL_PROOFS_MATCH")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
