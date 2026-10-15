"""§6 baseline freeze + §7 baseline metrics.

Produces, into reports/ue4_hardening/:
    IMPORT_BASELINE_MANIFEST.json
    IMPORT_BASELINE_METRICS.json
    IMPORT_BASELINE_METRICS.md

Read-only with respect to the source logs: every file is hashed and stat'ed but
never written, moved or truncated. Historical baseline logs are evidence.

Usage:
    python scripts/ue4_import_baseline.py \
        --log-glob "G:/CARLA/build_logs/ingolstadt_import_*.log" \
        --log-glob "G:/CARLA/carla_source_probe/Unreal/CarlaUE4/Saved/Logs/*.log" \
        --primary G:/CARLA/build_logs/ingolstadt_import_20261004T001601Z.log \
        --out-dir reports/ue4_hardening
"""
from __future__ import annotations

import argparse
import datetime
import glob as globmod
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.ue4_import_log_analysis import analyze_file, percentile  # noqa: E402


def sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def utc(ts: float) -> str:
    return datetime.datetime.fromtimestamp(
        ts, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def git_identity(repo: str) -> dict:
    out = {"repo": repo, "exists": os.path.isdir(repo)}
    if not out["exists"]:
        return out
    for label, args in (
        ("head", ["rev-parse", "HEAD"]),
        ("branch", ["rev-parse", "--abbrev-ref", "HEAD"]),
        ("describe", ["describe", "--tags", "--always", "--dirty"]),
    ):
        try:
            r = subprocess.run(["git", "-C", repo] + args, capture_output=True,
                               text=True, timeout=60)
            out[label] = r.stdout.strip() or None
        except Exception as exc:
            out[label] = f"error: {exc}"
    return out


def engine_identity() -> dict:
    """UE4.26 identity, read from the authoritative engine tree."""
    root = r"G:\UnrealEngine_4.26_CARLA"
    info = {"root": root, "exists": os.path.isdir(root), "git": git_identity(root)}
    version = os.path.join(root, "Engine", "Build", "Build.version")
    if os.path.isfile(version):
        try:
            info["build_version"] = json.loads(open(version, encoding="utf-8").read())
        except Exception as exc:
            info["build_version"] = f"error: {exc}"
    exe = os.path.join(root, "Engine", "Binaries", "Win64", "UE4Editor-Cmd.exe")
    if os.path.isfile(exe):
        st = os.stat(exe)
        info["UE4Editor-Cmd"] = {"path": exe, "size_bytes": st.st_size,
                                 "mtime_utc": utc(st.st_mtime)}
    return info


def carla_identity() -> dict:
    src = r"G:\CARLA\carla_source_probe"
    return {"source_root": src, "git": git_identity(src),
            "ue_project": r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4",
            "ue_project_git": git_identity(
                r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4"),
            "packaged_runtime": r"E:\CARLA\CARLA_0.9.16",
            "packaged_runtime_exists": os.path.isdir(r"E:\CARLA\CARLA_0.9.16")}


def blender_identity() -> dict:
    exe = r"E:\Program Files\Blender Foundation\Blender 4.3\blender.exe"
    info = {"exe": exe, "exists": os.path.isfile(exe)}
    if info["exists"]:
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True,
                               timeout=120)
            info["version"] = (r.stdout or r.stderr).strip().splitlines()[0:2]
            st = os.stat(exe)
            info["size_bytes"] = st.st_size
            info["sha256"] = sha256(exe)
        except Exception as exc:
            info["error"] = str(exc)
    return info


def inventory(patterns: list[str]) -> list[dict]:
    rows = []
    seen = set()
    for pat in patterns:
        for p in sorted(globmod.glob(pat)):
            if p in seen or not os.path.isfile(p):
                continue
            seen.add(p)
            st = os.stat(p)
            rows.append({
                "absolute_path": p,
                "filename": os.path.basename(p),
                "size_bytes": st.st_size,
                "sha256": sha256(p),
                "creation_time_utc": utc(st.st_ctime),
                "modification_time_utc": utc(st.st_mtime),
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log-glob", action="append", default=[])
    ap.add_argument("--primary", default=None,
                    help="the authoritative baseline log to compute metrics from")
    ap.add_argument("--out-dir", default="reports/ue4_hardening")
    ap.add_argument("--skip-hash", action="store_true",
                    help="skip hashing large Saved/Logs trees (manifest only)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    patterns = args.log_glob or [
        r"G:\CARLA\build_logs\ingolstadt_import_*.log*",
        r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Saved\Logs\*.log",
    ]

    print("inventorying %d pattern(s)..." % len(patterns))
    files = inventory(patterns)
    print("  found %d files" % len(files))

    manifest = {
        "schema": "import_baseline_manifest/v1",
        "generated_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "purpose": "§6 baseline freeze. Historical import logs are evidence and are "
                   "never modified, moved or overwritten by this work.",
        "primary_baseline_log": args.primary,
        "engine_identity": engine_identity(),
        "carla_identity": carla_identity(),
        "blender_identity": blender_identity(),
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "logical_processors": os.cpu_count(),
        },
        "file_count": len(files),
        "total_bytes": sum(f["size_bytes"] for f in files),
        "files": files,
    }
    (out_dir / "IMPORT_BASELINE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print("wrote IMPORT_BASELINE_MANIFEST.json (%d files)" % len(files))

    if not args.primary:
        print("no --primary given; stopping after the manifest")
        return 0

    print("analyzing primary log: %s" % args.primary)
    m = analyze_file(args.primary)
    d = m.to_dict()
    df = d.pop("distance_field_stats")

    # shader timing from the queue progression
    shader_events = d.get("shader_compile_events") or []
    shader_seconds = 0.0
    for a, b in zip(shader_events, shader_events[1:]):
        shader_seconds += max(0.0, b["timestamp_seconds"] - a["timestamp_seconds"])

    metrics = {
        "schema": "import_baseline_metrics/v1",
        "generated_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_log": args.primary,
        "source_log_sha256": sha256(args.primary),
        "measurement_tool": "tools/ue4_import_log_analysis.py",
        "line_counts": {
            "total_lines": d["total_lines"],
            "parsed_lines": d["parsed_lines"],
            "unparsed_lines": d["unparsed_lines"],
            "warnings_and_errors": d["warning_total"],
            "category_total_sum": d["category_totals_sum"],
            "unclassified_warning_lines": d["unclassified_warning_lines"],
        },
        "run_window": {
            "first_timestamp": d["first_timestamp"],
            "last_timestamp": d["last_timestamp"],
            "duration_seconds": d["duration_seconds"],
            "duration_hours": round(d["duration_seconds"] / 3600.0, 3),
            "terminal_state": d["terminal_state"],
            "success_marker_line_number": d["success_marker_line_number"],
            "termination_evidence": d["termination_evidence"],
        },
        "verbosity_counts": d["verbosity_counts"],
        "category_counts": d["category_counts"],
        "distance_field": df,
        "distance_field_share_of_wall_clock": (
            round(df["total_seconds"] / d["duration_seconds"], 4)
            if d["duration_seconds"] else None),
        "shaders": {
            "queue_first_observed": d["shader_queue_first"],
            "queue_last_observed": d["shader_queue_last"],
            "queue_min_observed": d["shader_queue_min"],
            "worker_denominators": d["shader_worker_denominators"],
            "worker_progress_samples": len(d["shader_worker_samples"]),
            "compile_events": shader_events,
            "observed_compile_span_seconds": round(shader_seconds, 3),
        },
        "geometry_warnings": {
            "smoothing_group_warnings": d["smoothing_warning_count"],
            "tangent_degenerate_total": len(d["tangent_meshes"]),
            "tangent_degenerate_unique_meshes": len(set(d["tangent_meshes"])),
            "binormal_nearly_zero_total": len(d["binormal_meshes"]),
            "binormal_nearly_zero_unique_meshes": len(set(d["binormal_meshes"])),
            "tangent_mesh_list": sorted(set(d["tangent_meshes"])),
            "binormal_mesh_list": sorted(set(d["binormal_meshes"])),
        },
        "asset_manager": {
            "duplicate_primary_asset_id_all_verbosities":
                d["duplicate_id_total_all_verbosities"],
            "duplicate_primary_asset_id_warning_verbosity":
                d["category_counts"].get("ASSET_MANAGER_DUPLICATE", 0),
            "unique_colliding_ids": sorted(
                {r["primary_asset_id"] for r in d["duplicate_primary_asset_ids"]}),
            "collision_records": d["duplicate_primary_asset_ids"],
        },
        "asset_resolution": {
            "failed_to_find_object_total": len(d["missing_object_paths"]),
            "failed_to_find_object_unique": d["missing_object_unique_paths"],
            "sample_paths": sorted(set(d["missing_object_paths"]))[:40],
        },
        "console_lookup": d["console_lookup_warnings"],
        "per_tile": d["per_tile"],
        "distance_field_by_mesh": sorted(
            d.get("_df", []) or [], key=lambda r: -r["seconds"]),
    }
    # keep the full per-mesh stall list; it is the primary P0 evidence
    metrics["distance_field_by_mesh"] = sorted(
        m.distance_field_blocks, key=lambda r: -r["seconds"])
    metrics["per_mesh"] = d["per_mesh"]
    metrics.pop("distance_field_by_mesh", None)
    metrics["distance_field_by_mesh"] = sorted(
        m.distance_field_blocks, key=lambda r: -r["seconds"])

    (out_dir / "IMPORT_BASELINE_METRICS.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print("wrote IMPORT_BASELINE_METRICS.json")

    md = build_markdown(metrics)
    (out_dir / "IMPORT_BASELINE_METRICS.md").write_text(md, encoding="utf-8")
    print("wrote IMPORT_BASELINE_METRICS.md")
    return 0


def build_markdown(m: dict) -> str:
    dfr = m["distance_field"]
    run = m["run_window"]
    L = []
    A = L.append
    A("# Import Baseline Metrics")
    A("")
    A("Source log: `%s`" % m["source_log"])
    A("")
    A("SHA256: `%s`" % m["source_log_sha256"])
    A("")
    A("Measurement tool: `tools/ue4_import_log_analysis.py` (deterministic).")
    A("")
    A("## Run window")
    A("")
    A("| metric | value |")
    A("| --- | --- |")
    A("| first timestamp | %s |" % run["first_timestamp"])
    A("| last timestamp | %s |" % run["last_timestamp"])
    A("| duration | %s s (%.2f h) |" % (run["duration_seconds"], run["duration_hours"]))
    A("| **terminal state** | **%s** |" % run["terminal_state"])
    A("| success marker at line | %s of %d |" % (
        run["success_marker_line_number"], m["line_counts"]["total_lines"]))
    A("")
    A("## Warning categories")
    A("")
    A("| category | count |")
    A("| --- | --- |")
    for k, v in sorted(m["category_counts"].items(), key=lambda kv: -kv[1]):
        if v:
            A("| %s | %d |" % (k, v))
    A("")
    A("## Distance field (the dominant cost)")
    A("")
    A("| metric | value |")
    A("| --- | --- |")
    for k in ("count", "total_seconds", "total_hours", "max_seconds",
              "p50_seconds", "p95_seconds", "p99_seconds",
              "over_10s", "over_60s", "over_300s", "worst_mesh"):
        A("| %s | %s |" % (k, dfr.get(k)))
    A("| share of wall clock | %s |" % m["distance_field_share_of_wall_clock"])
    A("")
    A("### Worst individual meshes")
    A("")
    A("| seconds | minutes | mesh | emitted at |")
    A("| --- | --- | --- | --- |")
    for r in m["distance_field_by_mesh"][:27]:
        A("| %.3f | %.2f | %s | %s |" % (
            r["seconds"], r["seconds"] / 60.0, r["mesh"], r["timestamp"]))
    A("")
    A("## Shaders")
    A("")
    sh = m["shaders"]
    A("| metric | value |")
    A("| --- | --- |")
    for k in ("queue_first_observed", "queue_last_observed", "queue_min_observed",
              "worker_denominators", "worker_progress_samples",
              "observed_compile_span_seconds"):
        A("| %s | %s |" % (k, sh[k]))
    A("")
    A("## Geometry warnings")
    A("")
    gw = m["geometry_warnings"]
    A("| metric | value |")
    A("| --- | --- |")
    for k in ("smoothing_group_warnings", "tangent_degenerate_total",
              "tangent_degenerate_unique_meshes", "binormal_nearly_zero_total",
              "binormal_nearly_zero_unique_meshes"):
        A("| %s | %s |" % (k, gw[k]))
    A("")
    A("## Asset manager / resolution")
    A("")
    am = m["asset_manager"]
    ar = m["asset_resolution"]
    A("| metric | value |")
    A("| --- | --- |")
    A("| duplicate PrimaryAssetID (all verbosities) | %s |" %
      am["duplicate_primary_asset_id_all_verbosities"])
    A("| duplicate PrimaryAssetID (warning verbosity) | %s |" %
      am["duplicate_primary_asset_id_warning_verbosity"])
    A("| unique colliding IDs | %s |" % len(am["unique_colliding_ids"]))
    A("| failed to find object (total / unique) | %s / %s |" % (
        ar["failed_to_find_object_total"], ar["failed_to_find_object_unique"]))
    A("")
    A("Colliding PrimaryAssetIDs:")
    A("")
    for pid in am["unique_colliding_ids"]:
        A("- `%s`" % pid)
    A("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())