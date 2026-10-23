"""Machine audits for the hardening batch.

Produces the authority artifacts that do not require starting CARLA:
environment fingerprint, storage topology, configuration drift, reparse-point
graph, LFS integrity, worktree lifecycle registry, branch authority, artifact
authority registry, backup durability, and the atomic evidence index.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orch_core import SCHEMA_VERSION, atomic_write_json, sha256_file, utc_now  # noqa: E402
from orch_env import (  # noqa: E402
    CONFIG_DRIFT_FILES, configuration_drift, environment_fingerprint,
    storage_topology,
)

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT = os.path.join(REPO, "reports")
CARLA = r"G:\CARLA\carla_source_probe"
CONTENT = os.path.join(CARLA, "Unreal", "CarlaUE4", "Content")

CRITICAL_PATHS = {
    "carla_source": CARLA,
    "ue_source": r"G:\UnrealEngine_4.26_CARLA",
    "worktrees": r"E:\CARLA\worktrees",
    "ddc_current": r"G:\UnrealEngine_4.26_CARLA\Engine\DerivedDataCache",
    "ddc_proposed": r"F:\UnrealEngine_DDC",
    "temp": os.environ.get("TEMP", ""),
    "cook_output": r"G:\CARLA\cook_out",
    "pagefile": r"C:\pagefile.sys",
    "evidence": OUT,
    "unreal_content": CONTENT,
}


def write(name, payload):
    path = os.path.join(OUT, name)
    atomic_write_json(path, payload)
    return path


def git(*args, cwd=REPO):
    p = subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                       text=True, errors="replace", timeout=900)
    return p.stdout.strip() if p.returncode == 0 else None


# ---------------------------------------------------------------------------
# phase 14: reparse point / junction authority
# ---------------------------------------------------------------------------
def reparse_audit(roots):
    """Enumerate junctions and symlinks and detect namespace aliasing.

    The known CARLA defect is that multiple logical /Game roots can resolve to
    one physical Content directory, so the same asset is reachable under two
    package namespaces. That is detected here by resolving every reparse point
    and grouping by physical target.
    """
    script_template = r"""
$roots = @(%s)
$rows = @()
foreach ($r in $roots) {
  if (-not (Test-Path -LiteralPath $r)) { continue }
  $item = Get-Item -LiteralPath $r -Force -ErrorAction SilentlyContinue
  if ($item -and $item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    $rows += [pscustomobject]@{
      logical = $item.FullName
      target = $item.Target
      kind = [string]$item.LinkType
      attributes = [string]$item.Attributes
    }
  }
  Get-ChildItem -LiteralPath $r -Recurse -Force -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
    ForEach-Object {
      $rows += [pscustomobject]@{
        logical = $_.FullName
        target = $_.Target
        kind = [string]$_.LinkType
        attributes = [string]$_.Attributes
      }
    }
}
$rows | ConvertTo-Json -Compress
"""
    quoted = ",".join("'" + r.replace("'", "''") + "'" for r in roots)
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        script_template % quoted],
                       capture_output=True, text=True, errors="replace",
                       timeout=1800)
    points = []
    if p.stdout.strip():
        try:
            data = json.loads(p.stdout)
            points = data if isinstance(data, list) else [data]
        except ValueError:
            points = []

    # The recursive walk revisits nested reparse points: scanning Content and
    # then Content/Carla enumerates the same junction twice. Without this dedup
    # every stock junction looks like "one physical directory exposed under two
    # logical paths", which is a false positive of the audit rather than a
    # finding about the project.
    deduped = {}
    for pt in points:
        logical = os.path.normcase(os.path.abspath(pt["logical"]))
        deduped.setdefault(logical, pt)
    duplicate_detections = len(points) - len(deduped)
    points = list(deduped.values())

    by_target = {}
    for pt in points:
        tgt = pt.get("target")
        if isinstance(tgt, list):
            tgt = ";".join(tgt)
        if tgt:
            by_target.setdefault(os.path.normcase(os.path.abspath(tgt)), []).append(pt["logical"])

    aliases = {t: v for t, v in by_target.items() if len(set(v)) > 1}

    # Stock CARLA exposes the shared top-level folders under Content/Carla so
    # that assets live at /Game/Carla/... This is upstream, intentional
    # structure. It is recorded as an explicit allowlist rather than being
    # silently ignored, so a NEW alias cannot hide behind a known-good pattern.
    content_root = os.path.normcase(os.path.abspath(CONTENT))
    allowlisted, unallowlisted = {}, {}
    for tgt, logicals in aliases.items():
        if any(_is_stock_carla_alias(tgt, content_root) for _ in (0,)):
            allowlisted[tgt] = logicals
        else:
            unallowlisted[tgt] = logicals

    temp_markers = ("\\Temp\\", "\\Temp\\opencode", "AppData")
    into_temp = [pt for pt in points
                 if any(m.lower() in (str(pt.get("target")) or "").lower()
                        for m in temp_markers)]

    outside = []
    for pt in points:
        tgt = str(pt.get("target") or "")
        norm = tgt.lower()
        if not any(norm.startswith(r.lower()) for r in
                   (CARLA.lower(), r"g:\unrealengine_4.26_carla", CONTENT.lower(),
                    r"e:\carla\worktrees")):
            outside.append(pt)

    return {
        "schema": "REPARSE_POINT_AUTHORITY/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "roots_scanned": [r for r in roots if os.path.exists(r)],
        "roots_missing": [r for r in roots if not os.path.exists(r)],
        "reparse_point_count": len(points),
        "duplicate_detections_collapsed": duplicate_detections,
        "reparse_points": points,
        "physical_targets_with_multiple_logical_paths": unallowlisted,
        "namespace_aliasing_detected": bool(unallowlisted),
        "stock_carla_aliases_allowlisted": allowlisted,
        "stock_alias_policy": ("Content/Carla/{Blueprints,Config,HDMaps,Maps,"
                               "Static} -> Content/<Dir> is upstream CARLA "
                               "structure making shared assets reachable as "
                               "/Game/Carla/<Dir>. Recorded explicitly so a new "
                               "alias is still a failure."),
        "junctions_into_temporary_storage": into_temp,
        "junctions_outside_governed_project": outside,
        "cycles_detected": _detect_cycles(points),
        "PASS": not unallowlisted and not into_temp,
    }


def _is_stock_carla_alias(target, content_root):
    """True when the alias is CARLA's documented Content/Carla re-export.

    Content/Carla/<Dir> is a junction to Content/<Dir> for Blueprints, Config,
    HDMaps, Maps and Static. This is upstream CARLA structure that makes shared
    assets reachable as /Game/Carla/<Dir>. It is allowlisted explicitly so that
    an unrelated alias cannot be excused by proximity.
    """
    stock_dirs = {"blueprints", "config", "hdmaps", "maps", "static"}
    if not target.startswith(content_root + os.sep):
        return False
    remainder = target[len(content_root) + 1:]
    parts = remainder.split(os.sep)
    return len(parts) == 1 and parts[0].lower() in stock_dirs


def _detect_cycles(points):
    edges = {}
    for pt in points:
        tgt = pt.get("target")
        if isinstance(tgt, list):
            tgt = tgt[0] if tgt else None
        if tgt:
            edges[os.path.normcase(os.path.abspath(pt["logical"]))] = \
                os.path.normcase(os.path.abspath(tgt))
    cycles = []
    for start in list(edges):
        seen = set()
        cur = start
        while cur in edges:
            if cur in seen:
                cycles.append({"entry": start, "cycle_at": cur})
                break
            seen.add(cur)
            cur = edges[cur]
    return cycles


# ---------------------------------------------------------------------------
# phase 16: LFS integrity
# ---------------------------------------------------------------------------
def lfs_audit():
    available = subprocess.run(["git", "lfs", "version"], cwd=REPO,
                               capture_output=True, text=True,
                               timeout=300).returncode == 0
    attributes = os.path.join(REPO, ".gitattributes")
    fsck = {"executed": False, "raw": None, "parsed_missing_objects": []}
    if available:
        p = subprocess.run(["git", "lfs", "fsck", "--pointers"], cwd=REPO,
                           capture_output=True, text=True, errors="replace",
                           timeout=1800)
        fsck["executed"] = True
        fsck["raw"] = (p.stdout + p.stderr)[:8000]
        fsck["exit_code"] = p.returncode
        for line in fsck["raw"].splitlines():
            if "missing" in line.lower():
                fsck["parsed_missing_objects"].append(line.strip()[:200])

    tracked = git("ls-files")
    lfs_tracked = []
    if tracked:
        for line in tracked.splitlines():
            low = line.lower()
            if low.endswith((".fbx", ".xodr", ".png", ".uasset", ".umap",
                              ".obj", ".glb", ".zip")):
                lfs_tracked.append(line)

    return {
        "schema": "GIT_LFS_INTEGRITY/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "git_lfs_available": available,
        "gitattributes_present": os.path.isfile(attributes),
        "gitattributes_sha256": sha256_file(attributes),
        "fsck": fsck,
        "pointer_files_in_worktree": _count_pointer_files(tracked.splitlines() if tracked else []),
        "large_tracked_file_count": len(lfs_tracked),
        "policy": ("LFS clean-filter diffs must never be interpreted as mass source "
                   "deletion without independent byte/hash verification. The 2026-10 "
                   "worktree loss was exactly such a misreading."),
        "PASS": available and not fsck["parsed_missing_objects"],
    }


def _count_pointer_files(paths):
    """A valid LFS pointer is a small text file starting with the LFS signature."""
    count = 0
    for rel in paths[:4000]:
        full = os.path.join(REPO, rel.replace("/", os.sep))
        try:
            if not os.path.isfile(full):
                continue
            if os.path.getsize(full) > 1024:
                continue
            with open(full, "rb") as fh:
                head = fh.read(64)
            if head.startswith(b"version https://git-lfs.github.com/spec"):
                count += 1
        except OSError:
            continue
    return count


# ---------------------------------------------------------------------------
# phase 17: worktree lifecycle registry
# ---------------------------------------------------------------------------
FORBIDDEN_ROOTS = ("\\temp\\", "\\appdata\\", "\\.claude\\worktrees\\",
                   "\\scratch\\", "\\opencode\\")


def worktree_registry():
    raw = subprocess.run(["git", "-C", REPO, "worktree", "list", "--porcelain"],
                         capture_output=True, text=True, timeout=900).stdout
    entries = []
    current = {}
    for line in raw.splitlines():
        if line.startswith("worktree "):
            if current:
                entries.append(current)
            current = {"path": line[9:].strip()}
        elif line.startswith("HEAD "):
            current["head"] = line[5:].strip()
        elif line.startswith("branch "):
            current["branch"] = line[7:].strip()
        elif line.strip() == "detached":
            current["branch"] = "(detached)"
    if current:
        entries.append(current)

    rows = []
    for e in entries:
        path = e["path"]
        low = path.lower()
        forbidden = next((m for m in FORBIDDEN_ROOTS if m in low), None)
        dirty = None
        mtime = None
        if os.path.isdir(path):
            try:
                mtime = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(os.path.getmtime(os.path.join(path, ".git"))))
            except OSError:
                mtime = None
            st = subprocess.run(["git", "-C", path, "status", "--porcelain=v1"],
                                capture_output=True, text=True, timeout=600)
            dirty = bool(st.stdout.strip()) if st.returncode == 0 else None
        rows.append({
            "path": path,
            "branch": e.get("branch"),
            "head": e.get("head"),
            "created_or_link_mtime_utc": mtime,
            "dirty": dirty,
            "forbidden_root": forbidden,
            "retention_class": "REMOVAL_CANDIDATE" if forbidden else "ACTIVE",
        })

    violations = [r for r in rows if r["forbidden_root"]]
    return {
        "schema": "WORKTREE_LIFECYCLE/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "worktree_count": len(rows),
        "under_forbidden_root": len(violations),
        "REGISTERED_WORKTREES_UNDER_TEMP": len(
            [r for r in violations if "\\temp\\" in r["path"].lower()]),
        "forbidden_root_patterns": list(FORBIDDEN_ROOTS),
        "worktrees": rows,
        "PASS": not violations,
        "policy": ("No automatic deletion. Creation must go through a wrapper "
                   "that rejects forbidden roots."),
    }


# ---------------------------------------------------------------------------
# phases 18/19/30/36: authority registries and evidence index
# ---------------------------------------------------------------------------
def branch_authority():
    branches = (git("for-each-ref", "--format=%(refname:short) %(objectname) %(committerdate:iso8601-strict)",
                    "refs/heads/") or "").splitlines()
    rows = []
    for line in branches:
        parts = line.split()
        if len(parts) >= 2:
            rows.append({"branch": parts[0], "sha": parts[1],
                         "committed_utc": parts[2] if len(parts) > 2 else None})
    return {
        "schema": "BRANCH_AUTHORITY/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "policy": ("The canonical branch is an explicit recorded decision. It is "
                   "never inferred from the current checkout or from the most "
                   "recently modified branch name."),
        "branches": rows,
        "branch_count": len(rows),
        "canonical_selected": False,
        "canonical_selected_reason": (
            "Not selected in this batch: branch convergence is gated on build, "
            "publication and regression gates that are not all green."),
    }


def artifact_authority():
    entries = [
        {"role": "AUTHORITATIVE_XODR",
         "path": os.path.join(CARLA, "Import", "Ingolstadt",
                              "ingolstadt_perception_map_of_record_20260916_232831.xodr")},
        {"role": "INGOLSTADT_RUNTIME_UMAP",
         "path": os.path.join(CONTENT, "Ingolstadt", "Maps", "Ingolstadt", "Ingolstadt.umap")},
        {"role": "IMPORT_MANIFEST_PRIMARY",
         "path": os.path.join(CARLA, "Import", "Ingolstadt", "Ingolstadt.json")},
        {"role": "IMPORT_MANIFEST_DUPLICATE",
         "path": os.path.join(CARLA, "Import", "Ingolstadt", "package.json")},
        {"role": "UE_TARGET_CONFIG",
         "path": CONFIG_DRIFT_FILES["DefaultEngine.ini"]},
        {"role": "IMPORTER",
         "path": CONFIG_DRIFT_FILES["Import.py"]},
    ]
    rows = []
    for e in entries:
        path = e["path"]
        rows.append({
            "logical_role": e["role"],
            "path": path,
            "exists": os.path.isfile(path),
            "sha256": sha256_file(path),
            "size_bytes": os.path.getsize(path) if os.path.isfile(path) else None,
            "producer": "map_registry.py / promotion gate"
            if "XODR" in e["role"] or "UMAP" in e["role"] else "working tree",
            "producer_sha": git("rev-parse", "HEAD", cwd=CARLA),
            "supersedes": None,
            "superseded_by": None,
        })
    return {
        "schema": "ARTIFACT_AUTHORITY/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "artifacts": rows,
        "policy": ("An artifact may exist on disk without being selectable. "
                   "Selection requires a promotion receipt binding role, hash and "
                   "producer SHA."),
        "selection_requires_promotion_receipt": True,
    }


def backup_durability():
    """At least two copies of irreplaceable artifacts."""
    primary = os.path.join(CARLA, "Import", "Ingolstadt",
                           "ingolstadt_perception_map_of_record_20260916_232831.xodr")
    candidates = []
    for root in (r"F:\carla-worktrees", r"F:\carla-control-suite-worktrees",
                 r"C:\Users\admin\PycharmProjects\gpt4"):
        for hit in glob.glob(os.path.join(root, "**", "*map_of_record*.xodr"),
                             recursive=True)[:20]:
            candidates.append(hit)
    copies = [{"role": "PRIMARY", "path": primary, "sha256": sha256_file(primary)}]
    for c in candidates:
        copies.append({"role": "COPY", "path": c, "sha256": sha256_file(c),
                       "matches_primary": sha256_file(c) == sha256_file(primary)})
    distinct = len({c["sha256"] for c in copies if c["sha256"]})
    return {
        "schema": "BACKUP_DURABILITY/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "artifact": "authoritative XODR",
        "copies": copies,
        "distinct_hashes": distinct,
        "two_verified_copies": distinct >= 2,
        "note": ("A git repository is not sufficient for large generated "
                 "artifacts that are not fully tracked."),
    }


def evidence_index():
    """One machine-generated index of all evidence, with freshness."""
    candidate_sha = git("rev-parse", "HEAD")
    items = []
    for path in sorted(glob.glob(os.path.join(OUT, "**", "*.json"), recursive=True)):
        try:
            st = os.stat(path)
        except OSError:
            continue
        item = {
            "path": os.path.relpath(path, REPO).replace("\\", "/"),
            "sha256": sha256_file(path),
            "schema": None,
            "schema_version": None,
            "candidate_sha": None,
            "status": "PRESENT",
            "freshness": "UNKNOWN",
            "producer": None,
            "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
            "size_bytes": st.st_size,
        }
        try:
            with open(path, encoding="utf-8") as fh:
                head = json.load(fh)
            if isinstance(head, dict):
                item["schema"] = head.get("schema")
                item["schema_version"] = head.get("schema_version")
                item["candidate_sha"] = head.get("candidate_sha") or head.get("git", {}).get("head") if isinstance(head.get("git"), dict) else head.get("candidate_sha")
                item["producer"] = head.get("producer")
                item["status"] = head.get("status", "PRESENT")
        except (ValueError, OSError):
            item["status"] = "UNREADABLE"
        # Freshness: an artifact bound to a different candidate SHA is stale.
        if item["candidate_sha"] and candidate_sha and item["candidate_sha"] != candidate_sha:
            item["freshness"] = "STALE"
        elif item["candidate_sha"] == candidate_sha:
            item["freshness"] = "FRESH"
        items.append(item)

    return {
        "schema": "EVIDENCE_INDEX/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "candidate_sha": candidate_sha,
        "item_count": len(items),
        "stale_count": len([i for i in items if i["freshness"] == "STALE"]),
        "unreadable_count": len([i for i in items if i["status"] == "UNREADABLE"]),
        "items": items,
        "policy": ("Final closure must read this index rather than searching "
                   "report directories, so that STALE evidence cannot be "
                   "selected by directory accident."),
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    written = {}

    written["ENVIRONMENT_FINGERPRINT"] = write(
        "ENVIRONMENT_FINGERPRINT.json",
        environment_fingerprint(
            target_rhis=["PCD3D_SM5", "SF_VULKAN_SM5"],
            ddc_path=CRITICAL_PATHS["ddc_current"]))

    written["STORAGE_TOPOLOGY_AUTHORITY"] = write(
        "STORAGE_TOPOLOGY_AUTHORITY.json", storage_topology(CRITICAL_PATHS))

    written["CONFIGURATION_DRIFT_GATE"] = write(
        "CONFIGURATION_DRIFT_GATE.json",
        configuration_drift({"DefaultEngine.ini": sha256_file(
            CONFIG_DRIFT_FILES["DefaultEngine.ini"])}))

    written["REPARSE_POINT_AUTHORITY"] = write(
        "REPARSE_POINT_AUTHORITY.json",
        reparse_audit([CONTENT, os.path.join(CARLA, "Unreal", "CarlaUE4"),
                       r"E:\CARLA\worktrees"]))

    written["GIT_LFS_INTEGRITY"] = write("GIT_LFS_INTEGRITY.json", lfs_audit())
    written["WORKTREE_LIFECYCLE"] = write("WORKTREE_LIFECYCLE.json",
                                           worktree_registry())
    written["BRANCH_AUTHORITY"] = write("BRANCH_AUTHORITY.json", branch_authority())
    written["ARTIFACT_AUTHORITY"] = write("ARTIFACT_AUTHORITY.json",
                                          artifact_authority())
    written["BACKUP_DURABILITY"] = write("BACKUP_DURABILITY.json",
                                         backup_durability())
    written["EVIDENCE_INDEX"] = write("EVIDENCE_INDEX.json", evidence_index())

    for name, path in written.items():
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        verdict = d.get("PASS", d.get("RUN_ALLOWED", d.get("all_resolved", "n/a")))
        print("%-32s -> %s  (%s)" % (name, os.path.basename(path), verdict))


if __name__ == "__main__":
    main()
