#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Thesis experiment orchestrator:
map build -> QA -> paired capture -> domain gap -> exports.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Dict, Any

from ultimate_pipeline.experiments.thesis.manual_refs import resolve_manual_town, assert_manual_auto_distinct, sha256_file
from ultimate_pipeline.experiments.thesis.perception_preflight import validate_cooked_manual_maps


def _resolve_auto_xodr(auto_run_dir: Path, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    if not auto_run_dir.exists():
        return None
    candidates = sorted(auto_run_dir.glob("08_final*.xodr"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    fallback = sorted(auto_run_dir.glob("*.xodr"), key=lambda p: p.stat().st_mtime, reverse=True)
    return fallback[0] if fallback else None


def _discover_enrichments(auto_run_dir: Path, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    candidate = auto_run_dir / "enrichments.json"
    return candidate if candidate.is_file() else None


def _write_index(out_dir: Path, payload: Dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "thesis_run_index.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _build_index(
    auto_run_dir: Path,
    auto_xodr: Optional[Path],
    manual_xodr: Path,
    perception_dir: Path,
    structural_dir: Path,
    hashes: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "auto_run_dir": str(auto_run_dir),
        "auto_xodr": str(auto_xodr) if auto_xodr else None,
        "manual_xodr": str(manual_xodr) if manual_xodr.exists() else None,
        "manual_xodr_sha256": hashes.get("manual_xodr_sha256"),
        "auto_xodr_sha256": hashes.get("auto_xodr_sha256"),
        "structural_report": str(structural_dir / "full_report.json") if (structural_dir / "full_report.json").is_file() else None,
        "perception_metrics": str(perception_dir / "perception_metrics.json") if (perception_dir / "perception_metrics.json").is_file() else None,
        "pair_manifest": str(perception_dir / "pair_manifest.json") if (perception_dir / "pair_manifest.json").is_file() else None,
        "protocol_snapshot": str(perception_dir / "protocol_snapshot.json") if (perception_dir / "protocol_snapshot.json").is_file() else None,
        "determinism_fingerprint_auto": str(auto_run_dir / "determinism_fingerprint.json") if (auto_run_dir / "determinism_fingerprint.json").is_file() else None,
        "determinism_links": str(perception_dir / "determinism_links.json") if (perception_dir / "determinism_links.json").is_file() else None,
    }


def _write_batch_summary(
    out_dir: Path,
    manual_xodr: Path,
    auto_xodr: Optional[Path],
    hashes: Dict[str, Any],
    status: str,
) -> None:
    batch_summary = {
        "manual_xodr": str(manual_xodr.resolve()),
        "auto_xodr": str(auto_xodr.resolve()) if auto_xodr else "",
        "manual_xodr_sha256": hashes.get("manual_xodr_sha256"),
        "auto_xodr_sha256": hashes.get("auto_xodr_sha256"),
        "status": status,
    }
    (out_dir / "batch_summary.json").write_text(json.dumps(batch_summary, indent=2), encoding="utf-8")
    (out_dir / "batch_summary.csv").write_text(
        "manual_xodr,auto_xodr,manual_xodr_sha256,auto_xodr_sha256,status\n"
        f"{batch_summary['manual_xodr']},{batch_summary['auto_xodr']},{batch_summary['manual_xodr_sha256']},{batch_summary['auto_xodr_sha256']},{batch_summary['status']}\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Thesis experiment runner (paired perception + domain gap).")
    ap.add_argument("--auto_run_dir", required=True, help="Auto pipeline output directory containing final XODR")
    ap.add_argument("--auto_xodr", default="", help="Explicit auto XODR path (optional)")
    ap.add_argument("--manual_xodr", default="", help="Manual Ingolstadt XODR path")
    ap.add_argument("--manual-town", choices=["Grid0821", "Grid0828"], default="", help="Manual reference town (resolves manual XODR + cooked town)")
    ap.add_argument("--out", required=True, help="Output directory for thesis run")
    ap.add_argument("--capture-perception", action="store_true", help="Run paired perception capture")
    ap.add_argument("--validate-manual-cooked", dest="validate_manual_cooked", action="store_true", help="Validate cooked manual maps in CARLA")
    ap.add_argument("--no-validate-manual-cooked", dest="validate_manual_cooked", action="store_false", help="Skip cooked map validation")
    ap.add_argument("--host", default=None, help="CARLA host override (defaults to CARLA_HOST env or 127.0.0.1)")
    ap.add_argument("--port", type=int, default=None, help="CARLA port override (defaults to CARLA_PORT env or 2000)")
    ap.add_argument("--carla-timeout-s", type=float, default=10.0, help="CARLA map load timeout for cooked validation")
    ap.add_argument("--frames", type=int, default=50, help="Perception capture frames per arm")
    ap.add_argument("--protocol", default="", help="Optional protocol YAML path for perception capture")
    ap.add_argument("--spawn-enrichments", default="", help="Optional enrichments.json path for proxy spawning")
    ap.add_argument("--run-domain-gap", dest="run_domain_gap", action="store_true", default=True)
    ap.add_argument("--no-run-domain-gap", dest="run_domain_gap", action="store_false")
    ap.add_argument("--no-carla", action="store_true", help="Skip CARLA capture")
    ap.set_defaults(validate_manual_cooked=None)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    auto_run_dir = Path(args.auto_run_dir).expanduser()
    if args.manual_town and args.manual_xodr:
        raise SystemExit("Use only one of --manual-town or --manual_xodr")
    if args.manual_town:
        manual_ref = resolve_manual_town(args.manual_town)
        manual_xodr = Path(manual_ref["manual_xodr_path"])
        cooked_town = manual_ref["cooked_town"]
    else:
        manual_xodr = Path(args.manual_xodr).expanduser()
        cooked_town = args.manual_town or "Grid0828"
    out_dir = Path(args.out).expanduser()
    structural_dir = out_dir / "structural"
    perception_dir = out_dir / "perception_pair"

    out_dir.mkdir(parents=True, exist_ok=True)
    structural_dir.mkdir(parents=True, exist_ok=True)

    auto_xodr = _resolve_auto_xodr(auto_run_dir, args.auto_xodr or None)
    enrichments = _discover_enrichments(auto_run_dir, args.spawn_enrichments or None)
    if not manual_xodr.is_file():
        raise SystemExit(f"Manual XODR not found: {manual_xodr}")
    if not auto_xodr:
        raise SystemExit("Auto XODR not found; provide --auto_xodr or valid --auto_run_dir")
    hashes = assert_manual_auto_distinct(manual_xodr, auto_xodr)

    should_validate_cooked = args.validate_manual_cooked if args.validate_manual_cooked is not None else args.capture_perception
    if should_validate_cooked and args.capture_perception and not args.no_carla:
        host = args.host or os.environ.get("CARLA_HOST", "127.0.0.1")
        port = int(args.port if args.port is not None else os.environ.get("CARLA_PORT", "2000"))
        requested_cooked_map = str(cooked_town).strip() or "Grid0828"
        report = validate_cooked_manual_maps(
            host,
            port,
            maps=[requested_cooked_map],
            out_dir=str(out_dir),
            timeout_s=float(args.carla_timeout_s),
        )
        if not report.get("ok", False):
            by_name = {entry.get("requested"): entry for entry in report.get("results", [])}
            entry = by_name.get(requested_cooked_map, {})
            if not entry.get("available", False):
                print(f"[ERROR] Cooked map '{requested_cooked_map}' not in available_maps")
            elif not entry.get("ok", False):
                err = entry.get("error", "load_failed")
                print(f"[ERROR] Cooked map '{requested_cooked_map}' load failed: {err}")
            raise SystemExit(f"Cooked manual maps validation failed. See {out_dir / 'cooked_maps_report.json'}")

    protocol_path = args.protocol
    if not protocol_path:
        default_protocol = Path(__file__).with_name("protocol.yaml")
        if default_protocol.is_file():
            protocol_path = str(default_protocol)

    if args.capture_perception and not args.no_carla and auto_xodr:
        perception_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            "-m",
            "ultimate_pipeline.experiments.thesis.run_perception_capture_pair",
            "--auto_xodr",
            str(auto_xodr) if auto_xodr else "",
            "--output_dir",
            str(perception_dir),
        ]
        if args.manual_xodr and not args.manual_town:
            cmd.extend(["--manual_xodr", str(manual_xodr)])
        else:
            cmd.extend(["--manual_map", cooked_town])
        cmd.extend(["--calib-json", str(Path(__file__).parents[2] / "sensors" / "calib_data.json")])
        cmd.extend(["--frames", str(int(args.frames))])
        if protocol_path:
            cmd.extend(["--protocol", str(protocol_path)])

        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            index = _build_index(auto_run_dir, auto_xodr, manual_xodr, perception_dir, structural_dir, hashes)
            _write_index(out_dir, index)
            _write_batch_summary(out_dir, manual_xodr, auto_xodr, hashes, status="FAIL_PERCEPTION")
            return int(result.returncode)
    elif args.capture_perception and not auto_xodr:
        print("[WARNING] Auto XODR not found; skipping perception capture.")

    if args.run_domain_gap and manual_xodr.is_file() and auto_xodr:
        env = os.environ.copy()
        if auto_xodr:
            env["UP_AUTO_FINAL_XODR"] = str(auto_xodr)
        env["UP_AUTO_RUN_DIR"] = str(auto_run_dir)
        pair_metrics_path = perception_dir / "perception_metrics.json"
        if pair_metrics_path.is_file():
            env["UP_PERCEPTION_PAIR_METRICS_JSON"] = str(pair_metrics_path)
        cmd = [
            sys.executable,
            "-m",
            "ultimate_pipeline.run_full_domain_gap",
            "--manual_xodr",
            str(manual_xodr),
            "--output_dir",
            str(structural_dir),
        ]
        result = subprocess.run(cmd, check=False, env=env)
        if result.returncode != 0:
            index = _build_index(auto_run_dir, auto_xodr, manual_xodr, perception_dir, structural_dir, hashes)
            _write_index(out_dir, index)
            _write_batch_summary(out_dir, manual_xodr, auto_xodr, hashes, status="FAIL_DOMAIN_GAP")
            return int(result.returncode)
    elif args.run_domain_gap:
        print("[WARNING] Domain gap skipped (manual or auto XODR missing).")

    run_meta = structural_dir / "run_metadata.json"
    if run_meta.exists():
        try:
            data = json.loads(run_meta.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            data = {}
        data["manual_xodr_resolved"] = str(manual_xodr.resolve())
        data["auto_xodr_resolved"] = str(auto_xodr.resolve()) if auto_xodr else None
        data.setdefault("input_fingerprints", {})
        data["input_fingerprints"].update({
            "manual_xodr": {"sha256": hashes.get("manual_xodr_sha256")},
            "auto_xodr": {"sha256": hashes.get("auto_xodr_sha256")},
        })
        run_meta.write_text(json.dumps(data, indent=2), encoding="utf-8")

    index = _build_index(auto_run_dir, auto_xodr, manual_xodr, perception_dir, structural_dir, hashes)
    _write_index(out_dir, index)

    final_status = "FAIL_IDENTICAL" if hashes.get("manual_xodr_sha256") == hashes.get("auto_xodr_sha256") else "OK"
    _write_batch_summary(out_dir, manual_xodr, auto_xodr, hashes, status=final_status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
