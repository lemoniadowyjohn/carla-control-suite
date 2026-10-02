#!/usr/bin/env python3
"""Batch 13 integration: input lineage, patch duplication and lane scope audit.

Emits, into ``reports/integration_wave/<RUN>/``:

    INPUT_LINEAGE_AUDIT.json
    PATCH_DUPLICATION.json
    PARALLEL_LANE_SCOPE_AUDIT.json

This runs entirely offline against local git object storage. It never fetches,
never pushes, and never mutates the working tree.

Usage:
    python tools/integration_lineage_audit.py --run <RUN> \
        --base <BASE_SHA> \
        --lane RQ2=<SHA> --lane RQ4=<SHA> --lane RQ5=<SHA>
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Expected primary ownership per lane (Batch 13 section 5).
# --------------------------------------------------------------------------
LANE_OWNERSHIP: Dict[str, Tuple[str, ...]] = {
    "RQ2": ("ultimate_pipeline/domain_gap/",),
    "RQ4": ("ultimate_pipeline/domain_gap_gnn/", "reports/parallel_wave/rq4/"),
    "RQ5": ("ultimate_pipeline/perception/",),
}

# Paths a lane may touch outside its primary ownership without that being a
# scope violation, when the prefix/pattern matches.
LANE_ALLOWED_EXTRA: Dict[str, Tuple[str, ...]] = {
    "RQ2": ("tools/rq2_", "tests/", "reports/parallel_wave/rq2/",
            "ultimate_pipeline/analysis/spatial_bootstrap.py"),
    "RQ4": ("tools/rq4_", "tests/", "reports/parallel_wave/rq4/"),
    "RQ5": ("tools/rq5_", "tests/", "reports/parallel_wave/rq5/",
            "configs/rq5_"),
}

UNIQUE = "UNIQUE"
ALREADY_PRESENT = "ALREADY_PRESENT"
DUPLICATE_PATCH = "DUPLICATE_PATCH"
CONFLICTING_PATCH = "CONFLICTING_PATCH"
SUPERSEDED = "SUPERSEDED"


def git(*args: str, cwd: Optional[Path] = None) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True,
                       cwd=str(cwd) if cwd else None)
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def git_lines(*args: str, cwd: Optional[Path] = None) -> List[str]:
    out = git(*args, cwd=cwd)
    return [line for line in out.splitlines() if line.strip()]


def commit_exists(root: Path, sha: str) -> bool:
    return bool(git("cat-file", "-t", sha, cwd=root) == "commit")


def tree_sha(root: Path, sha: str) -> Optional[str]:
    t = git("rev-parse", f"{sha}^{{tree}}", cwd=root)
    return t or None


def patch_id(root: Path, sha: str) -> Optional[str]:
    """Stable patch-id for a commit, independent of commit SHA."""
    text = git("diff-tree", "-p", "--no-color", sha, cwd=root)
    if not text:
        return None
    r = subprocess.run(["git", "patch-id", "--stable"], input=text,
                       capture_output=True, text=True, cwd=str(root))
    parts = r.stdout.strip().split()
    return parts[0] if parts else None


def classify_scope(lane: str, path: str) -> Dict[str, Any]:
    owned = LANE_OWNERSHIP.get(lane, ())
    if any(path.startswith(p) for p in owned):
        return {"path": path, "area": "PRIMARY_OWNERSHIP", "justified": True,
                "basis": f"matches {lane} primary ownership prefix"}
    for pat in LANE_ALLOWED_EXTRA.get(lane, ()):
        if path.startswith(pat) or pat in path:
            return {"path": path, "area": "SUPPORTING", "justified": True,
                    "basis": f"matches {lane} allowed supporting pattern {pat!r}"}
    return {"path": path, "area": "UNEXPECTED", "justified": False,
            "basis": f"outside {lane} declared ownership and allowed patterns"}


def build_input_lineage(root: Path, base: str, lanes: Dict[str, str]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    violations: List[str] = []
    for lane, sha in lanes.items():
        rec: Dict[str, Any] = {"lane": lane, "result_sha": sha}
        if not commit_exists(root, sha):
            rec["status"] = "COMMIT_MISSING"
            rec["commit_exists"] = False
            violations.append(f"{lane}:COMMIT_MISSING")
            entries.append(rec)
            continue
        rec["commit_exists"] = True
        rec["tree_sha"] = tree_sha(root, sha)
        mb = git("merge-base", sha, base, cwd=root)
        rec["merge_base_with_base"] = mb or None
        rec["lane_commit_count_ahead_of_merge_base"] = int(
            git("rev-list", "--count", f"{mb}..{sha}", cwd=root) or 0)
        rec["is_descendant_of_base"] = (
            git("merge-base", "--is-ancestor", sha, base, cwd=root) == "" and
            subprocess.run(["git", "merge-base", "--is-ancestor", sha, base],
                           cwd=str(root)).returncode == 0)
        files = git_lines("diff", "--name-only", f"{mb}..{sha}", cwd=root)
        rec["files_changed_count"] = len(files)
        rec["files_changed"] = files
        scoped = [classify_scope(lane, f) for f in files]
        rec["unexpected_files"] = [s["path"] for s in scoped if not s["justified"]]
        rec["file_scope"] = scoped
        if rec["unexpected_files"]:
            rec["status"] = "LANE_SCOPE_VIOLATION"
            violations.append(f"{lane}:LANE_SCOPE_VIOLATION")
        else:
            rec["status"] = "IN_SCOPE"
        rec["on_remote"] = bool(git_lines("branch", "-r", "--contains", sha,
                                          cwd=root))
        entries.append(rec)

    return {
        "schema": "INTEGRATION_INPUT_LINEAGE_AUDIT/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_candidate_sha": base,
        # Literal fact: base is NOT an ancestor of the lane tips, because the
        # lanes diverged before base gained its own commits. That is the
        # healthy parallel-lane shape, not a defect.
        "base_is_ancestor_of_all_lanes": all(
            e.get("merge_base_with_base") == base for e in entries
            if e.get("status") != "COMMIT_MISSING"),
        # The meaningful check: every lane branched from a commit that IS an
        # ancestor of base, so the lanes are rebasable onto base.
        "lanes_branched_from_ancestor_of_base": all(
            e.get("merge_base_with_base")
            and subprocess.run(
                ["git", "merge-base", "--is-ancestor",
                 e["merge_base_with_base"], base],
                cwd=str(root)).returncode == 0
            for e in entries if e.get("status") != "COMMIT_MISSING"),
        "lane_merge_bases": {
            e["lane"]: e.get("merge_base_with_base") for e in entries},
        "lanes": entries,
        "scope_violations": violations,
        "status": "FAIL" if violations else "PASS",
    }


def build_patch_duplication(root: Path, base: str,
                            lanes: Dict[str, str]) -> Dict[str, Any]:
    """Classify each lane commit against commits already present in base."""
    base_mb = git("merge-base", lanes[list(lanes)[0]], base, cwd=root) or base
    base_only = git_lines("rev-list", "--reverse", f"{base_mb}..{base}", cwd=root)
    base_patch_ids: Dict[str, str] = {}
    for c in base_only:
        pid = patch_id(root, c)
        if pid:
            base_patch_ids[pid] = c

    lane_commit_pids: Dict[str, List[str]] = {}
    results: List[Dict[str, Any]] = []
    for lane, sha in lanes.items():
        mb = git("merge-base", sha, base, cwd=root)
        commits = git_lines("rev-list", "--reverse", f"{mb}..{sha}", cwd=root)
        lane_commit_pids[lane] = commits
        for c in commits:
            pid = patch_id(root, c)
            if pid and pid in base_patch_ids:
                cls = ALREADY_PRESENT
            else:
                cls = UNIQUE
            results.append({
                "lane": lane,
                "commit": c,
                "patch_id": pid or "UNAVAILABLE",
                "classification": cls,
                "already_present_as": base_patch_ids.get(pid) if pid else None,
            })

    # Cross-lane duplicate detection
    by_pid: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        if r["patch_id"] != "UNAVAILABLE":
            by_pid.setdefault(r["patch_id"], []).append(r)
    cross_lane: List[Dict[str, Any]] = []
    for pid, rows in by_pid.items():
        if len({r["lane"] for r in rows}) > 1:
            cross_lane.append({
                "patch_id": pid,
                "commits": [{"lane": r["lane"], "commit": r["commit"]}
                            for r in rows],
                "classification": DUPLICATE_PATCH,
            })

    files_by_lane = {lane: set(git_lines("diff", "--name-only",
                                         f"{git('merge-base', sha, base, cwd=root)}..{sha}",
                                         cwd=root))
                     for lane, sha in lanes.items()}
    overlaps: Dict[str, List[str]] = {}
    names = list(files_by_lane)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = sorted(files_by_lane[a] & files_by_lane[b])
            if shared:
                overlaps[f"{a}+{b}"] = shared

    return {
        "schema": "INTEGRATION_PATCH_DUPLICATION/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_candidate_sha": base,
        "base_only_commits_considered": base_only,
        "base_patch_id_count": len(base_patch_ids),
        "lane_commits": results,
        "cross_lane_duplicate_patches": cross_lane,
        "file_level_overlaps_between_lanes": overlaps,
        "conclusion": (
            "No cross-lane file overlap and no duplicate patch-ids: the three "
            "lanes are disjoint and can be applied in the mandated order."
            if not cross_lane and not overlaps else
            "Review required before applying lanes."
        ),
        "status": "PASS" if not cross_lane and not overlaps else "REVIEW_REQUIRED",
    }


def build_scope_audit(root: Path, base: str,
                      lanes: Dict[str, str]) -> Dict[str, Any]:
    files_by_lane = {lane: git_lines("diff", "--name-only",
                                     f"{git('merge-base', sha, base, cwd=root)}..{sha}",
                                     cwd=root)
                     for lane, sha in lanes.items()}
    cross_lane: List[Dict[str, Any]] = []
    for lane, files in files_by_lane.items():
        for f in files:
            others = [o for o, ofs in files_by_lane.items()
                      if o != lane and f in ofs]
            if others:
                cross_lane.append({"file": f, "lanes": sorted([lane, *others])})

    # Declared ownership regions: did any lane touch a region owned by another?
    ownership_violations: List[Dict[str, Any]] = []
    for lane, files in files_by_lane.items():
        for f in files:
            for other_lane, prefixes in LANE_OWNERSHIP.items():
                if other_lane == lane:
                    continue
                if any(f.startswith(p) for p in prefixes):
                    sc = classify_scope(lane, f)
                    if not sc["justified"]:
                        ownership_violations.append(
                            {"file": f, "touched_by": lane,
                             "owned_by": other_lane, **sc})

    per_lane = {
        lane: {
            "files_changed_count": len(files),
            "primary_ownership": list(LANE_OWNERSHIP.get(lane, ())),
            "files_outside_primary_ownership": [
                f for f in files
                if not any(f.startswith(p) for p in LANE_OWNERSHIP.get(lane, ()))
            ],
            "unexpected_files": [f for f in files
                                 if not classify_scope(lane, f)["justified"]],
        }
        for lane, files in files_by_lane.items()
    }

    return {
        "schema": "PARALLEL_LANE_SCOPE_AUDIT/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_candidate_sha": base,
        "declared_ownership": {k: list(v) for k, v in LANE_OWNERSHIP.items()},
        "per_lane": per_lane,
        "cross_lane_file_collisions": cross_lane,
        "cross_lane_ownership_violations": ownership_violations,
        "status": "PASS" if not ownership_violations and not cross_lane else "REVIEW_REQUIRED",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True, help="integration run id")
    ap.add_argument("--base", required=True, help="BASE_CANDIDATE_SHA")
    ap.add_argument("--lane", action="append", default=[],
                    metavar="NAME=SHA", help="repeatable lane result SHA")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()

    root = Path(args.root).resolve()
    lanes: Dict[str, str] = {}
    for item in args.lane:
        name, _, sha = item.partition("=")
        if not name or not sha:
            ap.error(f"malformed --lane {item!r}; expected NAME=SHA")
        lanes[name] = sha
    if not lanes:
        ap.error("at least one --lane NAME=SHA is required")

    out = root / "reports/integration_wave" / args.run
    out.mkdir(parents=True, exist_ok=True)

    docs = {
        "INPUT_LINEAGE_AUDIT.json": build_input_lineage(root, args.base, lanes),
        "PATCH_DUPLICATION.json": build_patch_duplication(root, args.base, lanes),
        "PARALLEL_LANE_SCOPE_AUDIT.json": build_scope_audit(root, args.base, lanes),
    }
    for name, doc in docs.items():
        (out / name).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
        print(f"{name}: {doc['status']}")
    lineage = docs["INPUT_LINEAGE_AUDIT.json"]
    print(f"scope_violations={lineage['scope_violations']}")
    print(f"base_is_ancestor_of_all_lanes={lineage['base_is_ancestor_of_all_lanes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())