#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C11 step 4 — canonical, committed regeneration entrypoint for the map of record.

ONE command reproduces the enriched map of record deterministically from the
pinned inputs, encoding the corrected (post C6-C10) configuration:

    python scripts/regen_map_of_record.py

Behavior:
  1. PROJ environment guard (loud warning; fail-closed via UP_PROJ_ENV_FAIL_CLOSED=1).
  2. Refuses to run on a dirty worktree unless --allow-dirty (governance).
  3. Verifies the campaign INPUTS_MANIFEST digests (fail-closed on mismatch).
  4. Converts the pinned road OSM to a seed XODR via Osm2Odr (deterministic).
  5. Runs the full pipeline with the corrected config (PERCEPTION_RELEASE
     profile, C10 map hygiene enabled, preanchor off, manifest guard active).
  6. Measures acceptance with require_enrichment=True (C7 enrichment gate).
  7. Emits the candidate ONLY if acceptance passes; writes the full
     provenance chain (osm -> seed -> candidate sha + settings snapshot).
  8. --verify-only <xodr> measures an existing candidate without running the
     pipeline (offline mode when SUMO/CARLA are unavailable).

Environment blockers fail fast with a remediation hint:
  - SUMO_HOME unset / netconvert missing  -> stage 05 cannot run.
  - CARLA disabled (UP_DISABLE_CARLA=1)   -> only where allowed by the profile.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

CAMPAIGN = "ingolstadt_cooked_perception_v1"
CAMPAIGN_DIR = REPO_ROOT / "campaigns" / CAMPAIGN
MANIFEST_PATH = CAMPAIGN_DIR / "source" / "INPUTS_MANIFEST.json"
CANDIDATE_DIR = CAMPAIGN_DIR / "candidate"
DEFAULT_PROFILE = "PERCEPTION_RELEASE"


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 16):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _git_dirty() -> List[str]:
    try:
        out = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True)
        return [line for line in out.splitlines() if line.strip()]
    except Exception:
        return ["<git unavailable>"]


def _check_proj_env() -> None:
    from ultimate_pipeline.governance.proj_env_guard import check_proj_environment

    report = check_proj_environment(min_layout_minor=6, fail_closed=False)
    if not report.ok:
        print("WARNING [PROJ-ENV]:")
        for warning in report.warnings:
            print(f"  - {warning}")
        print("  Remediation: pip install --force-reinstall --no-cache-dir pyproj; unset stray PROJ_LIB.")
        if os.getenv("UP_PROJ_ENV_FAIL_CLOSED", "").strip() in ("1", "true"):
            raise RuntimeError("UP_PROJ_ENV_FAIL_CLOSED=1 and proj environment is not clean.")
    else:
        print(f"[proj] environment ok (proj.db layout {report.proj_db_layout_version})")


def _verify_manifest() -> Dict[str, Any]:
    from ultimate_pipeline.governance.inputs_manifest import verify_inputs_manifest

    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"INPUTS_MANIFEST not found: {MANIFEST_PATH}")
    result = verify_inputs_manifest(str(MANIFEST_PATH), base_dir=str(REPO_ROOT))
    print(f"[manifest] verified: ok={result['ok']} checked={sorted(result['checked'])} pending={result['pending']}")
    if not result["ok"]:
        raise RuntimeError("Pinned-input verification FAILED; refusing to regenerate.")
    return result


def _resolve_osm_from_manifest() -> Path:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entry = manifest["inputs"]["roads_osm"]
    osm = (REPO_ROOT / str(entry["path"])).resolve()
    if not osm.is_file():
        raise FileNotFoundError(f"Pinned roads OSM missing: {osm}")
    return osm


def _sumo_status() -> tuple[bool, str]:
    """SUMO availability for stage 05, consistent with the pipeline's own
    resolution (Settings autodetect: hardcoded C:\\Sumo path + C:\\Sumo walk).
    Before 2026-08-17 this guard only accepted SUMO_HOME/PATH and wrongly
    blocked regen even when Settings.SUMO_NETCONVERT resolved to an existing
    binary (SUMO is installed but not on PATH)."""
    if os.getenv("SUMO_HOME"):
        return True, f"SUMO_HOME={os.getenv('SUMO_HOME')}"
    if shutil.which("netconvert") or shutil.which("sumo"):
        return True, "netconvert/sumo on PATH"
    try:
        from ultimate_pipeline.config.settings import SETTINGS

        exe = getattr(SETTINGS, "SUMO_NETCONVERT", "")
        if exe and os.path.isfile(exe):
            return True, f"Settings.SUMO_NETCONVERT={exe}"
    except Exception:
        pass
    return False, "SUMO_HOME unset, netconvert/sumo not on PATH, and Settings.SUMO_NETCONVERT missing"


def _check_sumo() -> None:
    ok, message = _sumo_status()
    if ok:
        print(f"[sumo] available ({message})")
        return
    raise RuntimeError(
        f"SUMO is not available ({message}). "
        "Install SUMO (https://sumo.dlr.de/docs/Installing.html) and set SUMO_HOME, or use "
        "--verify-only against an existing candidate."
    )


def _rebase_to_local(xodr_in: Path, xodr_out: Path) -> Dict[str, Any]:
    """
    Re-base an XODR to a local CARLA-friendly frame.

    The SUMO frame-preservation path (--offset.disable-normalization) keeps
    global tmerc(0,0) coordinates (~832k/5458k for Ingolstadt) through the
    pipeline. Raw geometry that far from the origin breaks float32 precision
    in CARLA and fails the origin_sanity gate. Translation-invariant: planView
    geometry x/y AND building <object><outline><cornerGlobal> x/y are shifted
    by the SAME (dx, dy) (C29: cornerGlobal was previously left un-rebased,
    which -- combined with a separate building-projection-origin bug fixed in
    osm_polygon_loader.py -- produced a verified 7,665m building/road centroid
    drift on the real pinned map). The original frame is preserved in the
    header <offset> element and in the returned report.
    """
    import xml.etree.ElementTree as _ET

    tree = _ET.parse(xodr_in)
    root = tree.getroot()
    xs: List[float] = []
    ys: List[float] = []
    for g in root.findall(".//planView/geometry"):
        xs.append(float(g.get("x", "0")))
        ys.append(float(g.get("y", "0")))
    if not xs:
        raise RuntimeError(f"rebase: no planView geometry in {xodr_in}")
    min_x, min_y = min(xs), min(ys)
    already_local = max(abs(min_x), abs(min_y)) < 10_000.0
    if already_local:
        return {
            "shifted": False,
            "reason": "already_local",
            "bbox_min": [round(min_x, 3), round(min_y, 3)],
        }
    dx = round(min_x, 3)
    dy = round(min_y, 3)
    for g in root.findall(".//planView/geometry"):
        g.set("x", f"{float(g.get('x', '0')) - dx:.6f}")
        g.set("y", f"{float(g.get('y', '0')) - dy:.6f}")
    for c in root.findall(".//object/outline/cornerGlobal"):
        c.set("x", f"{float(c.get('x', '0')) - dx:.6f}")
        c.set("y", f"{float(c.get('y', '0')) - dy:.6f}")
    header = root.find("header")
    if header is None:
        header = _ET.SubElement(root, "header")
    offset = header.find("offset")
    if offset is None:
        offset = _ET.SubElement(header, "offset")
        offset.set("hdg", "0.0")
        offset.set("z", "0.0")
    offset.set("x", f"{dx:.6f}")
    offset.set("y", f"{dy:.6f}")
    xodr_out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(xodr_out), encoding="utf-8", xml_declaration=True)
    return {
        "shifted": True,
        "dx": dx,
        "dy": dy,
        "input_sha256": _sha256_file(xodr_in),
        "output_sha256": _sha256_file(xodr_out),
        "bbox_min_before": [round(min_x, 3), round(min_y, 3)],
        "bbox_min_after": [0.0, 0.0],
    }


def _run_pipeline(seed: Path, out_dir: Path, profile: str, disable_carla: bool) -> None:
    env = os.environ.copy()
    env["UP_INPUT_XODR"] = str(seed)
    env["UP_INPUTS_MANIFEST"] = str(MANIFEST_PATH)
    env["UP_ENABLE_MAP_HYGIENE"] = "1"
    env["UP_PREANCHOR_INPUT_XODR"] = "0"
    env["UP_RELEASE_PROFILE"] = profile
    env["UP_OUTPUT_DIR"] = str(out_dir)
    # F1 CRS contract / enrichment read UP_OSM_FILE to establish the map's
    # geographic frame against the pinned OSM source. Before 2026-08-17 this
    # was never wired here, so the DEM sampler failed closed with
    # osm_source_unavailable and the canonical regen could not complete.
    pinned_osm = _resolve_osm_from_manifest()
    env["UP_OSM_FILE"] = str(pinned_osm)
    # SUMO repair (netconvert) drops lane-level successors; stage 08 enforces
    # the CARLA invariant and crashed without the autofix (C0 evidence:
    # 10565/10565 repaired, 0 downgraded). The canonical config enables it.
    env["UP_AUTOFIX_LANE_SUCCESSORS"] = "1"
    env["UP_STRICT_LANE_SUCCESSORS"] = "0"
    if disable_carla:
        env["UP_DISABLE_CARLA"] = "1"
    env.setdefault("PYTHONUTF8", "1")
    cmd = [sys.executable, "-m", "ultimate_pipeline.run_pipeline"]
    print(f"[pipeline] $ {' '.join(cmd)}")
    print(f"[pipeline] UP_OUTPUT_DIR={out_dir} profile={profile} hygiene=1 preanchor=0")
    print(f"[pipeline] UP_OSM_FILE={pinned_osm}")
    log_path = out_dir / "pipeline.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as logfile:
        logfile.write(f"$ {' '.join(cmd)}\n\n")
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        logfile.write(proc.stdout)
    if proc.returncode != 0:
        raise RuntimeError(f"Pipeline failed (exit {proc.returncode}); log: {log_path}")
    print(f"[pipeline] completed (exit 0); log: {log_path}")


def _find_final_xodr(run_dir: Path) -> Path:
    patterns = list(run_dir.glob("**/08_final*.xodr")) + list(run_dir.glob("**/*DROP_BAD_LINKS*.xodr"))
    if not patterns:
        raise FileNotFoundError(f"No 08_final*.xodr / DROP_BAD_LINKS*.xodr found under {run_dir}")
    patterns.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return patterns[0]


def _measure_acceptance(final_xodr: Path, out_dir: Path) -> Dict[str, Any]:
    from scripts.measure_candidate_acceptance import run_gates
    from ultimate_pipeline.quality.map_acceptance import build_map_acceptance

    dem = REPO_ROOT / "cities" / "ingolstadt" / "dem" / "dem_ing.tif"
    reports = run_gates(final_xodr, out_dir, dem)
    acceptance = build_map_acceptance(
        reports,
        run_id=final_xodr.stem,
        final_xodr_path=str(final_xodr),
        out_dir=str(out_dir),
        require_enrichment=True,
        require_component_reachability=True,
    )
    _write_json(out_dir / "map_acceptance.json", acceptance)
    print(f"[acceptance] valid_for_experiments={acceptance['valid_for_experiments']}")
    for gate in acceptance.get("hard_fail_reasons", []):
        print(f"  FAIL {gate['gate']}: {gate['reason']}")
    for warn in acceptance.get("soft_warnings", []):
        print(f"  WARN {warn['gate']}: {warn['reason']}")
    return acceptance


def _settings_snapshot() -> Dict[str, Any]:
    from ultimate_pipeline.config.settings import Settings

    s = Settings()
    keys = [
        "RELEASE_PROFILE",
        "ENABLE_MAP_HYGIENE",
        "PREANCHOR_INPUT_XODR",
        "INPUTS_MANIFEST",
        "ENABLE_BUILDINGS",
        "ENABLE_TRAFFIC_LIGHTS",
        "PINNED_BUILDINGS_SOURCE",
    ]
    return {key: getattr(s, key, None) for key in keys}


def _emit_candidate(final_xodr: Path, out_dir: Path, name: str, acceptance: Dict[str, Any]) -> Path:
    target = CANDIDATE_DIR / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final_xodr, target)
    provenance = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "command": "python scripts/regen_map_of_record.py",
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip(),
        "git_dirty": bool(_git_dirty()),
        "inputs_manifest": str(MANIFEST_PATH),
        "osm_sha256": _sha256_file(_resolve_osm_from_manifest()),
        "seed_xodr_sha256": _sha256_file(out_dir / "seed_from_osm.xodr") if (out_dir / "seed_from_osm.xodr").is_file() else None,
        "final_xodr_sha256": _sha256_file(final_xodr),
        "emitted_candidate_sha256": _sha256_file(target),
        "structural_signature": compute_structural_signature(target),
        "candidate_path": str(target),
        "acceptance": {k: acceptance.get(k) for k in ("valid_for_experiments", "hard_fail_reasons", "soft_warnings", "metrics")},
        "settings_snapshot": _settings_snapshot(),
    }
    _write_json(out_dir / "regen_provenance.json", provenance)
    print(f"[emit] candidate -> {target} sha256={provenance['emitted_candidate_sha256']}")
    print(f"[emit] provenance -> {out_dir / 'regen_provenance.json'}")
    return target


def compute_structural_signature(xodr_path: Path) -> Dict[str, Any]:
    """Frame-invariant reproducibility anchor: {num_roads, num_junctions, total_road_length}.

    Osm2Odr is byte-non-deterministic (C15/C11_REPRODUCIBILITY_NUANCE.md) -- re-running the
    canonical regen from the same pinned inputs reproduces the map STRUCTURALLY, not
    byte-exactly. Pinning-by-sha256 identifies a specific artifact; this signature is what
    actually verifies "the same map was regenerated" across two candidates or runs.
    """
    from ultimate_pipeline.domain_gap.map_stats_xodr import XODRMapStatsExtractor

    stats = XODRMapStatsExtractor.from_file(str(xodr_path))
    return {
        "num_roads": stats.num_roads,
        "num_junctions": stats.num_junctions,
        "total_road_length": stats.total_road_length,
    }


def structural_signatures_match(a: Dict[str, Any], b: Dict[str, Any], *, length_tol_m: float = 1e-3) -> bool:
    return (
        a.get("num_roads") == b.get("num_roads")
        and a.get("num_junctions") == b.get("num_junctions")
        and abs(float(a.get("total_road_length", 0.0)) - float(b.get("total_road_length", 0.0))) <= length_tol_m
    )


def cmd_verify_structural(args: argparse.Namespace) -> int:
    """--verify-structural <a.xodr> <b.xodr>: structural (not byte-sha) reproduction check."""
    a_path, b_path = (Path(p).expanduser().resolve() for p in args.verify_structural)
    for p in (a_path, b_path):
        if not p.is_file():
            print(f"ERROR: candidate not found: {p}", file=sys.stderr)
            return 2
    sig_a = compute_structural_signature(a_path)
    sig_b = compute_structural_signature(b_path)
    match = structural_signatures_match(sig_a, sig_b)
    print(f"[structural-signature] {a_path.name}: {sig_a}")
    print(f"[structural-signature] {b_path.name}: {sig_b}")
    print(f"[structural-signature] {'MATCH' if match else 'MISMATCH'} "
          f"(byte-sha differs is EXPECTED per Osm2Odr non-determinism; structural equality is the real check)")
    return 0 if match else 1


def cmd_verify_only(args: argparse.Namespace) -> int:
    xodr = Path(args.verify_only).expanduser().resolve()
    if not xodr.is_file():
        print(f"ERROR: candidate not found: {xodr}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir or xodr.parent / f"{xodr.stem}_regen_verify_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    acceptance = _measure_acceptance(xodr, out_dir)
    print(f"sha256: {acceptance.get('final_xodr_sha256')}")
    return 0 if acceptance["valid_for_experiments"] else 1


def cmd_regen(args: argparse.Namespace) -> int:
    _check_proj_env()
    dirty = _git_dirty()
    if dirty and not args.allow_dirty:
        print("ERROR: worktree is dirty. Commit or stash changes first, or pass --allow-dirty.", file=sys.stderr)
        for line in dirty[:10]:
            print(f"  {line}", file=sys.stderr)
        return 2
    if dirty:
        print(f"[git] WARNING: continuing on dirty worktree ({len(dirty)} changes).")
    _verify_manifest()
    osm = _resolve_osm_from_manifest()
    print(f"[input] roads OSM: {osm} sha256={_sha256_file(osm)}")
    _check_sumo()

    out_dir = Path(args.out_dir or CAMPAIGN_DIR / "regen" / datetime.now().strftime("%Y%m%dT%H%M%SZ"))
    out_dir.mkdir(parents=True, exist_ok=True)
    seed = out_dir / "seed_from_osm.xodr"

    from ultimate_pipeline.osm.osm_to_xodr_wrapper import OSMToXODRConfig, convert_osm_to_xodr

    cfg = OSMToXODRConfig(
        carla_root=os.getenv("CARLA_ROOT") or "E:/CARLA/CARLA_0.9.16",
        overwrite=True,
    )
    print("[seed] converting pinned OSM -> seed XODR (Osm2Odr)...")
    convert_osm_to_xodr(osm, seed, cfg=cfg)
    print(f"[seed] {seed} sha256={_sha256_file(seed)}")

    _run_pipeline(seed, out_dir / "pipeline_out", args.profile, disable_carla=not args.with_carla)
    final = _find_final_xodr(out_dir / "pipeline_out")
    print(f"[final] {final} sha256={_sha256_file(final)}")

    # Re-base to a local frame when the SUMO path left global tmerc coords
    # (float32-safe for CARLA, passes origin_sanity). Frame preserved in the
    # header <offset> + provenance.
    rebased = out_dir / "final_rebased.xodr"
    rebase_report = _rebase_to_local(final, rebased)
    measured = rebased if rebase_report.get("shifted") else final
    _write_json(out_dir / "rebase_report.json", rebase_report)
    if rebase_report.get("shifted"):
        print(f"[frame] re-based global -> local: dx={rebase_report['dx']} dy={rebase_report['dy']}")
    else:
        print(f"[frame] already local ({rebase_report.get('reason')}); no re-base needed")

    acceptance = _measure_acceptance(measured, out_dir / "acceptance")
    if not acceptance["valid_for_experiments"]:
        print("ERROR: acceptance FAILED; refusing to emit a candidate.", file=sys.stderr)
        return 1

    name = args.candidate_name or f"ingolstadt_perception_map_of_record_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xodr"
    _emit_candidate(measured, out_dir, name, acceptance)
    return 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Canonical regen of the map of record (C11 step 4).")
    ap.add_argument("--verify-only", type=str, default=None, metavar="XODR", help="Measure an existing candidate only (no pipeline).")
    ap.add_argument("--verify-structural", type=str, default=None, nargs=2, metavar=("A_XODR", "B_XODR"),
                     help="Compare two candidates' structural signature (num_roads/junctions/length) -- "
                          "the honest reproducibility check, since Osm2Odr is byte-non-deterministic.")
    ap.add_argument("--out-dir", type=str, default=None, help="Run/output directory (default: campaign/regen/<ts>).")
    ap.add_argument("--profile", type=str, default=DEFAULT_PROFILE, choices=["DEVELOPMENT", "STRUCTURAL_RELEASE", "CARLA_RELEASE", "VISUAL_RELEASE", "PERCEPTION_RELEASE"], help="Release profile (default: PERCEPTION_RELEASE).")
    ap.add_argument("--candidate-name", type=str, default=None, help="Emitted candidate filename (default: map_of_record timestamped).")
    ap.add_argument("--allow-dirty", action="store_true", help="Proceed even when the worktree is dirty.")
    ap.add_argument("--with-carla", action="store_true", help="Do not set UP_DISABLE_CARLA=1 (requires a running CARLA server).")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if args.verify_structural:
        return cmd_verify_structural(args)
    if args.verify_only:
        return cmd_verify_only(args)
    return cmd_regen(args)


if __name__ == "__main__":
    raise SystemExit(main())