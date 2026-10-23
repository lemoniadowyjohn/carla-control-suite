"""Phase 8/9: size the git worktrees and classify them for cleanup planning.

Read-only. Nothing is removed. Sizes are computed per worktree so the
capacity model uses measured numbers rather than estimates.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess

OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"
REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"


def git(*args, cwd=REPO):
    r = subprocess.run("git " + " ".join(args), shell=True, cwd=cwd,
                       capture_output=True, text=True)
    return (r.stdout or "").strip()


def dir_size_gb(path):
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total / 1e9


def main():
    raw = git("worktree list --porcelain")
    entries = []
    cur = {}
    for line in raw.splitlines():
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"path": line[9:]}
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].replace("refs/heads/", "")
    if cur:
        entries.append(cur)

    rows = []
    for e in entries:
        path = e["path"]
        exists = os.path.isdir(path)
        dirty = 0
        if exists:
            out = git("status --porcelain", cwd=path)
            dirty = len([l for l in out.splitlines() if l.strip()])
        size = dir_size_gb(path) if exists else 0.0
        if dirty > 0:
            cls = "DIRTY_PRESERVE"
        elif not exists:
            cls = "STALE_MISSING_REGISTRATION"
        else:
            cls = "SAFE_CLEAN_CANDIDATE"
        rows.append({
            "path": path,
            "leaf": os.path.basename(path.rstrip("\\/")) or path,
            "branch": e.get("branch", "DETACHED"),
            "head": (e.get("head") or "")[:12],
            "exists": exists,
            "dirty_entries": dirty,
            "size_gb": round(size, 2),
            "last_write": (datetime_now(path) if exists else ""),
            "classification": cls,
        })

    rows.sort(key=lambda r: -r["size_gb"])
    with open(os.path.join(OUT, "WORKTREE_INVENTORY.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    clean = [r for r in rows if r["classification"] == "SAFE_CLEAN_CANDIDATE"]
    dirty = [r for r in rows if r["classification"] == "DIRTY_PRESERVE"]
    by_drive = {}
    for r in clean:
        d = (r["path"][:2] or "?").upper()
        by_drive[d] = round(by_drive.get(d, 0.0) + r["size_gb"], 2)

    summary = {
        "schema": "WORKTREE_INVENTORY/v1",
        "total_worktrees": len(rows),
        "clean_candidates": len(clean),
        "dirty_preserve": len(dirty),
        "clean_candidate_total_gb": round(sum(r["size_gb"] for r in clean), 2),
        "dirty_preserve_total_gb": round(sum(r["size_gb"] for r in dirty), 2),
        "clean_candidate_gb_by_drive": by_drive,
        "note": "DIRTY_PRESERVE worktrees must not be removed automatically. "
                "Several dirty worktrees belong to other agent sessions and "
                "may still be in use.",
        "rows": rows,
    }
    with open(os.path.join(OUT, "WORKTREE_INVENTORY.json"), "w",
              encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print("worktrees=%d clean=%d (%.2f GB) dirty=%d (%.2f GB)" % (
        len(rows), len(clean), summary["clean_candidate_total_gb"],
        len(dirty), summary["dirty_preserve_total_gb"]))
    print("clean GB by drive:", by_drive)
    for r in rows[:12]:
        print("  %-34s %-46s %7.2f GB  dirty=%-4d %s" % (
            r["leaf"][:34], r["branch"][:46], r["size_gb"], r["dirty_entries"],
            r["classification"]))


def datetime_now(path):
    import datetime
    try:
        return datetime.datetime.utcfromtimestamp(
            os.stat(path).st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return ""


if __name__ == "__main__":
    main()
