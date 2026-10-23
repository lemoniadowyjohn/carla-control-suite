"""Read-only audit of the 5 registered worktrees under the scratch root.

Emits per-worktree: branch, HEAD, tree SHA, tracked diff, staged diff,
untracked manifest, and a per-entry classification. No writes to any worktree.
"""
import hashlib
import json
import os
import subprocess
import sys

SCRATCH = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "opencode")
WTS = [
    "new316-333-perception-hardening",
    "rq1-matrix-fix",
    "wt-p1",
    "wt-p1-base",
    "wt-runtime-rig",
]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE_EXT = {
    ".py", ".cpp", ".h", ".c", ".hpp", ".cs", ".ini", ".json", ".yaml",
    ".yml", ".toml", ".sh", ".bat", ".ps1", ".cfg", ".txt", ".md",
}
SOURCE_DIRS = ("src", "lib", "scripts", "tools", "tests", "config", "Content", "Unreal")
EVIDENCE_DIRS = ("reports", "submission", "artifacts", "evidence")
EVIDENCE_EXT = {
    ".xodr", ".fbx", ".glb", ".gltf", ".obj", ".png", ".jpg", ".jpeg", ".npy",
    ".npz", ".bin", ".zip", ".tar", ".gz", ".7z", ".pcap", ".bin", ".umap",
    ".uasset", ".uexp", ".ubulk", ".tiff", ".tif", ".svg", ".pdf", ".ply",
}
SOURCE_EXT = SOURCE_EXT - EVIDENCE_EXT


def git(wt, *args):
    p = subprocess.run(
        ["git", "-C", wt, *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


def classify(rel):
    parts = rel.replace("\\", "/").split("/")
    name = parts[-1]
    low = name.lower()
    ext = os.path.splitext(name)[1].lower()

    if parts[0] in (".git",) or "/.git/" in "/" + "/".join(parts) or parts[0].endswith(".git"):
        return "LFS_FILTER_ARTIFACT"
    if low.endswith((".lfs", ".lfs-pointer")) or ext in (".lfs",):
        return "LFS_FILTER_ARTIFACT"
    if low.endswith((".idx", ".pack", ".bitmap", ".rev", ".keep", ".promisor", ".lock")):
        return "LFS_FILTER_ARTIFACT" if ".git" in parts else "STAT_CACHE_ARTIFACT"
    if low in ("index", "index.lock", "shallow", "config", "gitdir", "commondir", "head"):
        return "LFS_FILTER_ARTIFACT"
    if ext in EVIDENCE_EXT and parts[0] in EVIDENCE_DIRS:
        return "UNTRACKED_EVIDENCE"
    if low.endswith((".json", ".md", ".txt", ".csv", ".log", ".xml", ".htm", ".html")) and \
            parts[0] not in SOURCE_DIRS:
        return "EXPECTED_REPORT"
    if low.endswith((".pyc", ".pyo")) or "__pycache__" in parts:
        return "STAT_CACHE_ARTIFACT"
    if any(p in (".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".idea") for p in parts):
        return "STAT_CACHE_ARTIFACT"
    if ext in SOURCE_EXT:
        return "REAL_SOURCE_CHANGE"
    return "UNKNOWN"


def audit(name):
    wt = os.path.join(SCRATCH, name)
    rec = {"name": name, "path": wt, "exists": os.path.isdir(wt)}

    rc, branch, _ = git(wt, "rev-parse", "--abbrev-ref", "HEAD")
    rec["branch"] = branch.strip() if rc == 0 else None
    rc, head, _ = git(wt, "rev-parse", "HEAD")
    rec["HEAD"] = head.strip() if rc == 0 else None
    rc, tree, _ = git(wt, "rev-parse", "HEAD^{tree}")
    rec["tree_sha"] = tree.strip() if rc == 0 else None

    rc, out, _ = git(wt, "status", "--porcelain=v1", "--untracked-files=all")
    rec["status_rc"] = rc
    lines = out.splitlines() if rc == 0 else []
    tracked, staged, untracked = [], [], []
    for ln in lines:
        if len(ln) < 3:
            continue
        xy, path = ln[:2], ln[3:].strip()
        entry = {"path": path, "xy": xy, "class": classify(path)}
        if "?" in xy:
            untracked.append(entry)
        else:
            (staged if xy[0] not in " " else tracked).append(entry)

    rec["tracked_changes"] = tracked
    rec["staged_changes"] = staged
    rec["untracked_files"] = untracked

    classes = {}
    for bucket in (tracked, staged, untracked):
        for e in bucket:
            classes.setdefault(e["class"], []).append(e["path"])
    rec["class_counts"] = {k: len(v) for k, v in sorted(classes.items())}
    rec["class_paths"] = {k: sorted(v) for k, v in sorted(classes.items())}
    rec["UNKNOWN_COUNT"] = rec["class_counts"].get("UNKNOWN", 0)
    rec["REAL_SOURCE_CHANGE_COUNT"] = rec["class_counts"].get("REAL_SOURCE_CHANGE", 0)

    # tracked diff fingerprint
    rc, diff, _ = git(wt, "diff", "HEAD", "--no-color")
    rec["tracked_diff_sha256"] = hashlib.sha256(diff.encode("utf-8", "replace")).hexdigest()
    rec["tracked_diff_lines"] = len(diff.splitlines())
    rec["tracked_diff_bytes"] = len(diff.encode("utf-8", "replace"))

    # untracked manifest (path + size + sha)
    man = []
    for e in untracked:
        full = os.path.join(wt, e["path"].replace("/", os.sep))
        size = None
        sha = None
        try:
            if os.path.isfile(full):
                size = os.path.getsize(full)
                h = hashlib.sha256()
                with open(full, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                sha = h.hexdigest()
        except OSError:
            pass
        man.append({"path": e["path"], "size": size, "sha256": sha})
    man.sort(key=lambda x: x["path"])
    rec["untracked_manifest"] = man
    rec["untracked_manifest_sha256"] = hashlib.sha256(
        json.dumps(man, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return rec


def main():
    out = [audit(n) for n in WTS]
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "reports",
        "WORKTREE_TEMP_CLASSIFICATION.json")
    dest = os.path.abspath(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    payload = {
        "scratch_root": SCRATCH,
        "worktree_count": len(out),
        "total_unknown": sum(r["UNKNOWN_COUNT"] for r in out),
        "worktrees": out,
    }
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(json.dumps({
        "report": dest,
        "total_unknown": payload["total_unknown"],
        "summary": [
            {
                "name": r["name"],
                "branch": r["branch"],
                "HEAD": r["HEAD"],
                "tree": r["tree_sha"],
                "classes": r["class_counts"],
                "unknown": r["UNKNOWN_COUNT"],
            }
            for r in out
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
