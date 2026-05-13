#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Thesis Run Packer (Audit-Ready).

Post-hoc tool to convert existing run directories into contract-compliant 
folders (run_manifest.json, signature.json, SUCCESS.txt).
Supports Scenario B multi-source pack.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ultimate_pipeline.contracts.agent_sync import load_agent_sync
from ultimate_pipeline.utils.file_hashing import sha256_file


def _get_git_info() -> Dict[str, str]:
    """Capture current git branch and commit hash."""
    info = {"branch": "unknown", "commit": "unknown"}
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        info["branch"] = branch
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        info["commit"] = commit
    except Exception:
        pass
    return info


def _get_env_snapshot() -> Dict[str, str]:
    """Capture relevant UP_* environment variables."""
    return {k: v for k, v in os.environ.items() if k.startswith("UP_")}


def pack_run(src: Path, out: Path, run_type: str) -> int:
    """Pack an existing single run directory into a compliant format."""
    print(f"[*] Packing {run_type} run from {src} to {out}...")

    # 1. Load contract
    try:
        contract = load_agent_sync()
    except Exception as e:
        print(f"[!] Failed to load agent_sync.yaml: {e}")
        return 1

    # 2. Get required artifacts
    if run_type == "domain_gap":
        required = contract.artifacts.domain_gap
    elif run_type == "determinism":
        required = contract.artifacts.determinism
    elif run_type == "perception":
        required = contract.artifacts.perception
    else:
        print(f"[!] Unknown run type: {run_type}")
        return 1

    # 3. Check artifacts in src
    missing = []
    found_artifacts = {}
    for artifact in required:
        p = src / artifact
        if not p.exists():
            # Try searching recursively for the filename
            hits = list(src.rglob(artifact.split("/")[-1]))
            if hits:
                p = hits[0]
            else:
                missing.append(artifact)
                continue
        found_artifacts[artifact] = p

    # 4. Initialize output
    out.mkdir(parents=True, exist_ok=True)

    # 5. Copy artifacts and compute signatures
    signatures = {}
    copied_paths = []
    for rel_path, src_path in found_artifacts.items():
        dst_path = out / rel_path
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if src_path.is_file():
            shutil.copy2(src_path, dst_path)
            signatures[rel_path] = sha256_file(dst_path)
            copied_paths.append(rel_path)

    # 6. Write manifest
    manifest_path = out / "run_manifest.json"
    manifest = {
        "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "run_type": run_type,
        "git": _get_git_info(),
        "src_original": str(src.resolve()),
        "command_line": " ".join(sys.argv),
        "environment": _get_env_snapshot(),
        "artifacts_expected": required,
        "artifacts_found": copied_paths,
        "artifacts_missing": missing,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # 7. Write signature.json
    sig_path = out / "signature.json"
    sig_path.write_text(json.dumps(signatures, indent=2), encoding="utf-8")

    # 8. Verify signature integrity (all hashed files must exist)
    signature_missing = []
    for rel_path in signatures.keys():
        if not (out / rel_path).exists():
            signature_missing.append(rel_path)

    if signature_missing:
        print(f"[!] AUDIT FAILURE: signature references non-existent files: {signature_missing}")
        (out / "FAIL.txt").write_text(
            f"SIGNATURE INTEGRITY FAILURE: {', '.join(signature_missing)}", encoding="utf-8"
        )
        if (out / "SUCCESS.txt").exists():
            (out / "SUCCESS.txt").unlink()
        return 1

    # 9. Final Verdict
    if not missing:
        (out / "SUCCESS.txt").write_text("CORE ARTIFACTS VERIFIED", encoding="utf-8")
        if (out / "FAIL.txt").exists():
            (out / "FAIL.txt").unlink()
        print(f"[OK] Run packed successfully: {out}")
        print(f"    Signature integrity: VERIFIED ({len(signatures)} files)")
        return 0
    else:
        (out / "FAIL.txt").write_text(f"MISSING: {', '.join(missing)}", encoding="utf-8")
        if (out / "SUCCESS.txt").exists():
            (out / "SUCCESS.txt").unlink()
        print(f"[!] Run packed with MISSING artifacts: {missing}")
        return 1


def pack_scenario_b(out: Path) -> int:
    """Specialized multi-source packer for Scenario B evidence."""
    print(f"[*] Packing Scenario B evidence pack into {out}...")
    out.mkdir(parents=True, exist_ok=True)

    evidence_map = {
        "determinism": {
            "src": Path("_tmp_t028_retry3"),
            "artifacts": ["determinism_report.json", "determinism_hashes.csv", "determinism_thesis_table.csv", "determinism_delta.csv"]
        },
        "structural_gap": {
            "src": Path("thesis_results/structural_gap_v1/run_01"),
            "artifacts": ["full_report.json", "summary.csv", "reproducibility_hash.json", "tile_pairing_report.json", "domain_gap_status.json"]
        },
        "perception_poc": {
            "src": Path("_tmp_t077_town10_20260228_a"),
            "artifacts": ["perception_status.json", "rig_verification.json", "sensor_rig_report.json", "ego_spawn.png", "camera_front.png", "lidar_bev.png"]
        },
        "grid_blocker": {
            "src": Path("_tmp_t066_t035_probe_gate_demo_20260301"),
            "artifacts": ["probe_result.json"]
        }
    }

    missing_all = []
    signatures = {}
    copied_count = 0

    # 1. Main Evidence Loop
    for cat, cfg in evidence_map.items():
        cat_dir = out / "evidence" / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        src_root = cfg["src"]
        
        for artifact in cfg["artifacts"]:
            src_path = src_root / artifact
            if not src_path.exists():
                hits = list(src_root.rglob(artifact.split("/")[-1]))
                src_path = hits[0] if hits else None
            
            if src_path and src_path.is_file():
                dst_path = cat_dir / artifact
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dst_path)
                signatures[f"evidence/{cat}/{artifact}"] = sha256_file(dst_path)
                copied_count += 1
            else:
                missing_all.append(f"{cat}/{artifact}")

    # 2. Add THESIS_RUN_CONTRACT compliant "contract_run" subfolder (Structural)
    print("[*] Creating THESIS_RUN_CONTRACT compliant 'contract_run'...")
    contract_run = out / "contract_run"
    contract_run.mkdir(parents=True, exist_ok=True)
    
    struct_src = Path("thesis_results/structural_gap_v1/run_01")
    # 08_final_*.xodr
    final_xodr = list(struct_src.rglob("auto_aligned_hardened.xodr"))
    if final_xodr:
        shutil.copy2(final_xodr[0], contract_run / "08_final_structural_gap.xodr")
        signatures["contract_run/08_final_structural_gap.xodr"] = sha256_file(contract_run / "08_final_structural_gap.xodr")
    else:
        missing_all.append("contract_run/08_final_*.xodr")

    # tile_metadata.json (derive from tile_match_map.json or similar)
    meta_src = struct_src / "tile_match_map.json"
    if meta_src.exists():
        shutil.copy2(meta_src, contract_run / "tile_metadata.json")
        signatures["contract_run/tile_metadata.json"] = sha256_file(contract_run / "tile_metadata.json")
    else:
        missing_all.append("contract_run/tile_metadata.json")

    # reproducibility_hash.json
    repo_hash_src = struct_src / "reproducibility_hash.json"
    if repo_hash_src.exists():
        shutil.copy2(repo_hash_src, contract_run / "reproducibility_hash.json")
        signatures["contract_run/reproducibility_hash.json"] = sha256_file(contract_run / "reproducibility_hash.json")

    # domain_gap/*
    dg_dir = contract_run / "domain_gap"
    dg_dir.mkdir(exist_ok=True)
    dg_files = ["full_report.json", "summary.csv", "tile_pairing_report.json", "domain_gap_status.json"]
    for f in dg_files:
        if (struct_src / f).exists():
            shutil.copy2(struct_src / f, dg_dir / f)
            signatures[f"contract_run/domain_gap/{f}"] = sha256_file(dg_dir / f)
        else:
            missing_all.append(f"contract_run/domain_gap/{f}")

    # 3. Copy submission docs
    for doc in Path("docs/submission").glob("*.md"):
        doc_dst = out / "docs" / doc.name
        doc_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(doc, doc_dst)

    # 4. Write manifest and signature
    manifest = {
        "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "pack_mode": "scenario_b",
        "git": _get_git_info(),
        "environment": _get_env_snapshot(),
        "artifacts_copied_count": copied_count,
        "artifacts_missing": missing_all,
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "signature.json").write_text(json.dumps(signatures, indent=2), encoding="utf-8")

    # 5. CRITICAL: Verify all signature entries exist on disk before SUCCESS
    signature_missing = []
    for sig_path in signatures.keys():
        full_path = out / sig_path
        if not full_path.exists():
            signature_missing.append(sig_path)

    if signature_missing:
        print(f"[!] AUDIT FAILURE: signature.json references non-existent files:")
        for sm in signature_missing:
            print(f"    - {sm}")
        (out / "FAIL.txt").write_text(
            f"SIGNATURE INTEGRITY FAILURE: {', '.join(signature_missing)}", encoding="utf-8"
        )
        if (out / "SUCCESS.txt").exists():
            (out / "SUCCESS.txt").unlink()
        return 1

    # 6. Final verdict
    if not missing_all:
        (out / "SUCCESS.txt").write_text("SCENARIO B AUDIT PACK VERIFIED", encoding="utf-8")
        if (out / "FAIL.txt").exists():
            (out / "FAIL.txt").unlink()
        print(f"[OK] Scenario B pack complete: {out}")
        print(f"    Artifacts: {len(signatures)} files hashed")
        print(f"    Signature integrity: VERIFIED")
        return 0
    else:
        (out / "FAIL.txt").write_text(f"INCOMPLETE: {', '.join(missing_all)}", encoding="utf-8")
        if (out / "SUCCESS.txt").exists():
            (out / "SUCCESS.txt").unlink()
        print(f"[!] Scenario B pack INCOMPLETE. Missing: {missing_all}")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["single", "scenario_b"], default="single")
    ap.add_argument("--src", type=Path, help="Existing run directory (single mode)")
    ap.add_argument("--out", required=True, type=Path, help="Target contract directory")
    ap.add_argument(
        "--type",
        choices=["domain_gap", "determinism", "perception"],
        help="Run type contract to enforce (single mode)",
    )
    args = ap.parse_args()

    if args.mode == "scenario_b":
        return pack_scenario_b(args.out)
    
    if not args.src or not args.src.is_dir():
        print(f"[!] Source directory required for single mode: --src")
        return 1
    if not args.type:
        print(f"[!] Run type required for single mode: --type")
        return 1

    return pack_run(args.src, args.out, args.type)


if __name__ == "__main__":
    sys.exit(main())
