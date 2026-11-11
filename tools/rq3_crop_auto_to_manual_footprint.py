#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ3 CLI: crop the auto map-of-record to the manual Grid0828 footprint.

Governed, deterministic wrapper around
``ultimate_pipeline.domain_gap.footprint_crop.crop_auto_to_manual_footprint``.
Inputs are resolved ONLY via ``ultimate_pipeline.carla_tools.map_registry``
(never by glob/mtime); a hash mismatch against the registry pin fails closed
before any crop logic runs. Output is written atomically
(``ultimate_pipeline.core.file_utils.write_xodr``) together with a provenance
manifest.

This is a pure SUBSET derivation tool: it writes a NEW file and never
touches the frozen map-of-record or any registry-pinned path (enforced by
``_assert_safe_out_dir`` below, independent of the registry's own
read-side fail-closed checks).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional

_TOOLS_DIR = Path(__file__).resolve().parent
_REPO_ROOT_OF_THIS_WORKTREE = _TOOLS_DIR.parent
if str(_REPO_ROOT_OF_THIS_WORKTREE) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_OF_THIS_WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import (
    MapRegistryDriftError,
    PINNED_MAP_REGISTRY,
    verify_pinned_map,
)
from ultimate_pipeline.core.file_utils import write_xodr
from ultimate_pipeline.domain_gap.footprint_crop import (
    SELECTION_MODES,
    DEFAULT_SAMPLE_SPACING_M,
    crop_auto_to_manual_footprint,
)
from ultimate_pipeline.governance.reproducibility.inputs_manifest import sha256_file
from ultimate_pipeline.quality.check_lane_link_targets_exist import check_lane_link_targets_exist
from ultimate_pipeline.quality.check_road_link_reciprocity import check_road_link_reciprocity
from ultimate_pipeline.quality.xodr_strict_validator import StrictXodrValidator

OUTPUT_FILENAME = "auto_crop_grid0828_footprint.xodr"
MANIFEST_FILENAME = "crop_manifest.json"


class OutDirUnsafeError(Exception):
    """out-dir would write inside campaigns/ or over a registry-pinned path."""


def _git_sha(cwd: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(cwd), stderr=subprocess.DEVNULL
        )
        return out.decode("utf-8").strip()
    except Exception:
        return "UNKNOWN"


def _pinned_paths_under(repo_root: Path) -> list[Path]:
    paths = []
    for entry in PINNED_MAP_REGISTRY.values():
        raw = entry.get("path")
        if not raw:
            continue
        try:
            paths.append((repo_root / raw).resolve())
        except Exception:
            continue
    return paths


def _assert_safe_out_dir(out_dir: Path, repo_root: Path, *, overwrite_scratch: bool) -> None:
    out_resolved = out_dir.resolve()
    campaigns_dir = (repo_root.resolve() / "campaigns").resolve()
    if out_resolved == campaigns_dir or campaigns_dir in out_resolved.parents:
        raise OutDirUnsafeError(
            f"--out-dir {out_resolved} is inside the registry's campaigns/ directory "
            f"({campaigns_dir}); refusing to write a derived crop there."
        )
    for pinned in _pinned_paths_under(repo_root):
        if pinned == out_resolved or out_resolved in pinned.parents or pinned.parent == out_resolved:
            raise OutDirUnsafeError(
                f"--out-dir {out_resolved} collides with a registry-pinned map path ({pinned}); "
                "refusing to write there."
            )

    if out_resolved.exists():
        existing = [p for p in out_resolved.iterdir()]
        if existing and not overwrite_scratch:
            raise OutDirUnsafeError(
                f"--out-dir {out_resolved} already exists and is non-empty "
                f"({len(existing)} entries); pass --overwrite-scratch to reuse it."
            )


def _resolve_input(key: str, repo_root: Path) -> Dict[str, Any]:
    """Registry-verified receipt; raises (fail-closed) on any drift."""
    return verify_pinned_map(key, base_dir=repo_root)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", required=True, type=Path,
                     help="Repo root to resolve registry-relative map paths against "
                          "(read-only; may be a different worktree than this tool's own).")
    ap.add_argument("--out-dir", required=True, type=Path,
                     help="Output directory (must not be inside <repo-root>/campaigns or "
                          "collide with any registry-pinned path).")
    ap.add_argument("--buffer-m", type=float, default=0.0)
    ap.add_argument("--selection", choices=SELECTION_MODES, default="any_point")
    ap.add_argument("--sample-spacing-m", type=float, default=DEFAULT_SAMPLE_SPACING_M)
    ap.add_argument("--overwrite-scratch", action="store_true",
                     help="Allow reusing a non-empty --out-dir.")
    args = ap.parse_args(argv)

    repo_root = args.repo_root.resolve()
    out_dir = args.out_dir

    try:
        _assert_safe_out_dir(out_dir, repo_root, overwrite_scratch=args.overwrite_scratch)
    except OutDirUnsafeError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    try:
        auto_receipt = _resolve_input("auto_map_of_record", repo_root)
        manual_receipt = _resolve_input("manual_grid0828", repo_root)
    except (MapRegistryDriftError, LookupError) as exc:
        print(f"FAIL-CLOSED (registry verification): {exc}", file=sys.stderr)
        return 3
    t_verify = time.time()

    auto_root = ET.parse(auto_receipt["resolved_path"]).getroot()
    manual_root = ET.parse(manual_receipt["resolved_path"]).getroot()
    t_parse = time.time()

    cropped_root, crop_report = crop_auto_to_manual_footprint(
        auto_root, manual_root,
        buffer_m=args.buffer_m, selection=args.selection,
        sample_spacing_m=args.sample_spacing_m,
    )
    t_crop = time.time()

    out_path = out_dir / OUTPUT_FILENAME
    write_xodr(ET.ElementTree(cropped_root), str(out_path))
    t_write = time.time()

    # ---------------------------------------------------------------- validation
    validations: Dict[str, Any] = {}
    output_root_reparsed: Optional[ET.Element] = None
    try:
        output_root_reparsed = ET.parse(str(out_path)).getroot()
        validations["xml_well_formed"] = {"ok": True}
    except Exception as exc:
        validations["xml_well_formed"] = {"ok": False, "error": str(exc)}

    validations["check_lane_link_targets_exist"] = check_lane_link_targets_exist(str(out_path))
    validations["check_road_link_reciprocity"] = check_road_link_reciprocity(str(out_path))
    validations["xodr_strict_validator"] = StrictXodrValidator().validate_path(str(out_path))
    validations["dangling_references"] = {
        "ok": crop_report["counts"]["dangling_references_found"] == 0,
        "details": crop_report["dangling_references"],
    }
    validations["controller_references_resolve"] = {
        "ok": crop_report["counts"]["unresolved_controller_references_found"] == 0,
        "details": crop_report["unresolved_controller_references"],
    }

    # no_unaccounted_top_level_loss: independently re-derived from the
    # SOURCE `auto_root` (parsed above, before any crop logic ran) and the
    # OUTPUT file re-parsed fresh from disk just now -- for every top-level
    # tag seen in the input, actual-kept-in-output + reported-dropped (from
    # the crop module's own report) must equal the input count. This is a
    # from-scratch proof, not a re-statement of the module's own counts.
    top_level_loss_detail: Dict[str, Any] = {}
    top_level_loss_ok = output_root_reparsed is not None
    if output_root_reparsed is not None:
        for tag, acct in crop_report["top_level_accounting"].items():
            actual_kept = len(output_root_reparsed.findall(tag))
            reported_dropped = acct["dropped_count"]
            input_count = acct["input_count"]
            ok = (actual_kept + reported_dropped) == input_count
            top_level_loss_detail[tag] = {
                "input_count": input_count,
                "actual_output_kept": actual_kept,
                "reported_dropped": reported_dropped,
                "ok": ok,
            }
            if not ok:
                top_level_loss_ok = False
    validations["no_unaccounted_top_level_loss"] = {"ok": top_level_loss_ok, "details": top_level_loss_detail}
    t_validate = time.time()

    hard_checks = {
        "xml_well_formed": bool(validations["xml_well_formed"]["ok"]),
        "zero_dangling_references": bool(validations["dangling_references"]["ok"]),
        "check_lane_link_targets_exist_ok": bool(validations["check_lane_link_targets_exist"]["ok"]),
        "check_road_link_reciprocity_ok": bool(validations["check_road_link_reciprocity"]["ok"]),
        "xodr_strict_validator_ok": bool(validations["xodr_strict_validator"]["ok"]),
        "controller_references_resolve": bool(validations["controller_references_resolve"]["ok"]),
        "no_unaccounted_top_level_loss": bool(validations["no_unaccounted_top_level_loss"]["ok"]),
        "zero_sampling_fallbacks": bool(crop_report["counts"]["sampling_fallback_count"] == 0),
    }
    manifest_status = "PASS" if all(hard_checks.values()) else "FAIL"

    output_sha256 = sha256_file(out_path)
    output_bytes = out_path.stat().st_size

    manifest: Dict[str, Any] = {
        "schema": "rq3_crop_manifest/v1",
        "tool": "tools/rq3_crop_auto_to_manual_footprint.py",
        "git_sha": _git_sha(_REPO_ROOT_OF_THIS_WORKTREE),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": manifest_status,
        "hard_checks": hard_checks,
        "args": {
            "repo_root": str(repo_root),
            "out_dir": str(out_dir.resolve()),
            "buffer_m": args.buffer_m,
            "selection": args.selection,
            "sample_spacing_m": args.sample_spacing_m,
        },
        "inputs": {
            "auto_map_of_record": {
                "registry_key": auto_receipt["registry_key"],
                "path": auto_receipt["resolved_path"],
                "sha256": auto_receipt["sha256_actual"],
                "bytes": auto_receipt["bytes_actual"],
                "verification_status": auto_receipt["verification_status"],
            },
            "manual_grid0828": {
                "registry_key": manual_receipt["registry_key"],
                "path": manual_receipt["resolved_path"],
                "sha256": manual_receipt["sha256_actual"],
                "bytes": manual_receipt["bytes_actual"],
                "verification_status": manual_receipt["verification_status"],
            },
        },
        "polygon_wkt": crop_report["polygon_wkt"],
        "polygon_bounds_auto_local": crop_report["polygon_bounds_auto_local"],
        "counts": crop_report["counts"],
        "junctions_dropped_reasons": crop_report["junctions_dropped_reasons"],
        "top_level_accounting": crop_report["top_level_accounting"],
        "output": {
            "path": str(out_path),
            "sha256": output_sha256,
            "bytes": output_bytes,
        },
        "validation": validations,
        "timing_s": {
            "registry_verify": round(t_verify - t0, 3),
            "parse_inputs": round(t_parse - t_verify, 3),
            "crop": round(t_crop - t_parse, 3),
            "write_output": round(t_write - t_crop, 3),
            "validate_output": round(t_validate - t_write, 3),
            "total": round(t_validate - t0, 3),
        },
    }

    manifest_path = out_dir / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps({"status": manifest_status, "output": str(out_path),
                       "manifest": str(manifest_path), "counts": crop_report["counts"]},
                      indent=2, sort_keys=True))
    return 0 if manifest_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
