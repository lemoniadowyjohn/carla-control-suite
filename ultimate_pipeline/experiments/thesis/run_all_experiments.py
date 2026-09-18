from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from ultimate_pipeline.experiments.thesis.run_vision_domain_gap import (
    topology_metrics_scope_template,
)


DEFAULT_OUT_ROOT = Path("artifacts/scenario_b/orchestration")
AUTO_XODR_GLOBS = ("08_final*.xodr", "*.xodr")
DEFAULT_RQ1_EVIDENCE = Path("artifacts/final_runs/scenario_b_audit/evidence/determinism/determinism_report.json")
DEFAULT_RQ2_EVIDENCE = Path("thesis_results/structural_gap_v1/run_01/full_report.json")
DEFAULT_RQ4_EVIDENCE = Path("thesis_results/rq4_variability/diversity_report.json")
DEFAULT_RQ5_EVIDENCE = Path("thesis_results/generalization/generalization_results.json")


class ContractError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        hints: Optional[Sequence[str]] = None,
        context: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.hints = list(hints or [])
        self.context = dict(context or {})


def _run(cmd: Sequence[str]) -> None:
    print("[RUN]", " ".join(str(part) for part in cmd))
    subprocess.check_call([str(part) for part in cmd])


def _discover_auto_xodr(auto_run_dir: Path) -> Optional[Path]:
    if not auto_run_dir.is_dir():
        return None
    for pattern in AUTO_XODR_GLOBS:
        candidates = sorted(
            auto_run_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
    return None


def _resolve_auto_xodr(args: argparse.Namespace) -> Tuple[Path, str]:
    if args.xodr_in:
        candidate = Path(args.xodr_in).expanduser()
        if not candidate.is_file():
            raise ContractError(
                "AUTO_XODR_NOT_FOUND",
                f"--xodr-in does not exist: {candidate}",
                hints=[
                    "Pass a valid --xodr-in path",
                    "or use --auto-run-dir / UP_AUTO_RUN_DIR for discovery",
                ],
                context={"xodr_in": str(candidate)},
            )
        return candidate, "cli:xodr-in"

    auto_run_dir_raw = (args.auto_run_dir or os.environ.get("UP_AUTO_RUN_DIR", "")).strip()
    if not auto_run_dir_raw:
        raise ContractError(
            "AUTO_XODR_UNRESOLVED",
            "Auto XODR is required for generated-map Scenario B capture.",
            hints=[
                "Provide --xodr-in <path-to-auto.xodr>",
                "or provide --auto-run-dir <auto-run-dir>",
                "or set UP_AUTO_RUN_DIR",
            ],
            context={"searched_globs": ",".join(AUTO_XODR_GLOBS)},
        )

    auto_run_dir = Path(auto_run_dir_raw).expanduser()
    resolved = _discover_auto_xodr(auto_run_dir)
    if resolved is None:
        raise ContractError(
            "AUTO_XODR_NOT_FOUND_IN_RUN_DIR",
            f"No .xodr file found in auto run dir: {auto_run_dir}",
            hints=[
                "Place generated .xodr outputs in the provided run dir",
                "or provide --xodr-in explicitly",
            ],
            context={
                "auto_run_dir": str(auto_run_dir),
                "searched_globs": ",".join(AUTO_XODR_GLOBS),
            },
        )
    return resolved, "auto-run-dir"


def _latest_pair_dir(out_root: Path) -> Path:
    pairs = sorted(out_root.glob("pair_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pairs:
        raise ContractError(
            "PAIR_OUTPUT_MISSING",
            "run_perception_pair produced no pair_* output directory.",
            hints=["Check run_perception_pair logs for runtime failures"],
            context={"out_root": str(out_root)},
        )
    return pairs[0]


def _write_contract_error(err: ContractError) -> None:
    payload = {
        "status": "contract_error",
        "code": err.code,
        "message": str(err),
        "hints": list(err.hints),
        "context": dict(err.context),
    }
    print(json.dumps(payload, indent=2), file=sys.stderr)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read_json_if_dict(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _is_within(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except Exception:
        try:
            return str(path.resolve()).startswith(str(root.resolve()))
        except Exception:
            return False


def _artifact_state(repo_root: Path, rel_path: Path, *, out_root: Optional[Path] = None) -> Dict[str, Any]:
    candidate = rel_path if rel_path.is_absolute() else (repo_root / rel_path)
    exists = bool(candidate.is_file())
    origin = "missing"
    if exists:
        if isinstance(out_root, Path) and _is_within(candidate, out_root):
            origin = "current_run"
        else:
            origin = "repo_existing"
    return {
        "path": str(candidate),
        "exists": bool(exists),
        "origin": origin,
        "current_run_exists": bool(origin == "current_run"),
        "repo_existing_exists": bool(origin == "repo_existing"),
    }


def _ensure_topology_metrics_scope(full_report_path: Path) -> Dict[str, Any]:
    """Ensure RQ2 structural full_report exposes explicit CRS-independent metric scope."""
    state: Dict[str, Any] = {
        "path": str(full_report_path),
        "exists": bool(full_report_path.is_file()),
        "updated": False,
        "present": False,
    }
    if not full_report_path.is_file():
        return state
    report = _read_json_if_dict(full_report_path)
    if not report:
        state["error"] = "full_report_not_json_dict"
        return state
    desired = topology_metrics_scope_template()
    existing = report.get("topology_metrics_scope")
    needs_update = not isinstance(existing, dict) or any(
        existing.get(k) != v for k, v in desired.items()
    )
    if needs_update:
        report["topology_metrics_scope"] = desired
        full_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        state["updated"] = True
    state["present"] = isinstance(report.get("topology_metrics_scope"), dict)
    return state


def _build_unified_rq_report(
    *,
    repo_root: Path,
    out_root: Path,
    auto_xodr: Path,
    auto_xodr_source: str,
    manual_town: str,
    pair_dir: Optional[Path],
    vision_gap_summary_path: Optional[Path],
    dry_run: bool,
) -> Dict[str, Any]:
    rq1 = _artifact_state(repo_root, DEFAULT_RQ1_EVIDENCE, out_root=out_root)
    rq2_full_report_path = (
        DEFAULT_RQ2_EVIDENCE
        if DEFAULT_RQ2_EVIDENCE.is_absolute()
        else (repo_root / DEFAULT_RQ2_EVIDENCE)
    )
    rq2_scope_state: Dict[str, Any] = {
        "path": str(rq2_full_report_path),
        "exists": bool(rq2_full_report_path.is_file()),
        "updated": False,
        "present": False,
        "skipped_in_dry_run": bool(dry_run),
    }
    if not dry_run:
        rq2_scope_state = _ensure_topology_metrics_scope(rq2_full_report_path)
    rq2 = _artifact_state(repo_root, DEFAULT_RQ2_EVIDENCE, out_root=out_root)
    rq4 = _artifact_state(repo_root, DEFAULT_RQ4_EVIDENCE, out_root=out_root)
    rq5 = _artifact_state(repo_root, DEFAULT_RQ5_EVIDENCE, out_root=out_root)

    pair_manifest_path = (
        pair_dir / "pair_manifest.json"
        if isinstance(pair_dir, Path)
        else (out_root / "pair_<latest>" / "pair_manifest.json")
    )
    pair_manifest = _read_json_if_dict(pair_manifest_path)
    pair_success = bool(pair_manifest.get("success", False))

    vision_summary = (
        _read_json_if_dict(vision_gap_summary_path)
        if isinstance(vision_gap_summary_path, Path)
        else {}
    )
    quantitative = (
        vision_summary.get("quantitative_metrics", {})
        if isinstance(vision_summary.get("quantitative_metrics", {}), dict)
        else {}
    )
    paired_files = int(quantitative.get("paired_files", 0) or 0)

    if dry_run:
        rq3_status = "NOT_EXECUTED_DRY_RUN"
    elif pair_success and paired_files > 0:
        rq3_status = "CAPTURED_WITH_METRICS_NOT_CLOSED"
    elif pair_success:
        rq3_status = "CAPTURED_NO_METRICS_NOT_CLOSED"
    elif pair_manifest_path.is_file():
        rq3_status = "PAIR_CAPTURE_FAILED"
    else:
        rq3_status = "NOT_EXECUTED"

    def _status_from_origin(artifact: Dict[str, Any], *, missing: str = "MISSING_EVIDENCE") -> str:
        origin = str(artifact.get("origin") or "missing")
        if origin == "current_run":
            return "CURRENT_RUN_EVIDENCE"
        if origin == "repo_existing":
            return "REPO_EXISTING_EVIDENCE_ONLY"
        return missing

    return {
        "schema_version": 1,
        "status": "ok",
        "scope": "scenario_b_orchestration",
        "auto_xodr": str(auto_xodr),
        "auto_xodr_source": str(auto_xodr_source),
        "manual_town": str(manual_town),
        "research_questions": {
            "RQ1_determinism": {
                "status": _status_from_origin(rq1),
                "evidence": rq1,
                "closure_claimed_by_this_orchestration": False,
            },
            "RQ2_structural_gap": {
                "status": _status_from_origin(rq2),
                "evidence": rq2,
                "topology_metrics_scope": topology_metrics_scope_template(),
                "topology_metrics_scope_state": rq2_scope_state,
                "scope_boundary": "planar_only_structural_gap",
                "closure_claimed_by_this_orchestration": False,
            },
            "RQ3_perceptual_gap": {
                "status": rq3_status,
                "pair_manifest": str(pair_manifest_path),
                "pair_manifest_exists": bool(pair_manifest_path.is_file()),
                "pair_success": bool(pair_success),
                "vision_gap_summary": (
                    str(vision_gap_summary_path) if isinstance(vision_gap_summary_path, Path) else ""
                ),
                "paired_files": int(paired_files),
                "closure_claimed_by_this_orchestration": False,
            },
            "RQ4_observed_variability": {
                "status": _status_from_origin(rq4, missing="DEFERRED"),
                "evidence": rq4,
                "closure_claimed_by_this_orchestration": False,
            },
            "RQ5_generalization": {
                "status": _status_from_origin(rq5, missing="DEFERRED"),
                "evidence": rq5,
                "closure_claimed_by_this_orchestration": False,
            },
        },
        "claim_boundary": (
            "Unified RQ plumbing report only. RQ2 evidence here is planar structural scope only. "
            "RQ3 and RQ5 are not closed by this orchestration alone."
        ),
    }


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "Scenario B orchestration entrypoint: generated-map perception pair "
            "against cooked Grid0828 plus optional diagnostic vision-gap summary."
        )
    )
    ap.add_argument("--xodr-in", default="", help="Explicit generated-map .xodr path")
    ap.add_argument(
        "--auto-run-dir",
        default="",
        help="Auto run directory used to discover generated-map .xodr files",
    )
    ap.add_argument(
        "--manual-town",
        default="Grid0828",
        choices=["Grid0828"],
        help="Cooked manual/reference town for Scenario B perception capture",
    )
    ap.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT), help="Stable output root")
    ap.add_argument("--duration", type=int, default=5, help="Capture duration in seconds")
    ap.add_argument("--fps", type=int, default=10, help="Capture FPS")
    ap.add_argument("--spawn-index", type=int, default=0, help="Spawn index for paired capture")
    ap.add_argument(
        "--skip-vision-gap-diagnostic",
        action="store_true",
        help="Skip the diagnostic image-count summary stage",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve inputs and emit plan without invoking CARLA-dependent subprocesses",
    )
    return ap.parse_args()


def main() -> int:
    args = _parse_args()
    out_root = Path(args.out_root).expanduser()
    out_root.mkdir(parents=True, exist_ok=True)
    repo_root = _repo_root()

    try:
        auto_xodr, auto_xodr_source = _resolve_auto_xodr(args)
    except ContractError as err:
        _write_contract_error(err)
        return 2

    perception_cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.run_perception_pair",
        "--manual-town",
        str(args.manual_town),
        "--xodr-in",
        str(auto_xodr),
        "--out-root",
        str(out_root),
        "--duration",
        str(int(args.duration)),
        "--fps",
        str(int(args.fps)),
        "--spawn-index",
        str(int(args.spawn_index)),
    ]

    if args.dry_run:
        vision_gap_summary_path: Optional[Path] = None
        dry_run_payload = {
            "status": "dry_run_ok",
            "scope": "scenario_b_orchestration",
            "auto_xodr": str(auto_xodr),
            "auto_xodr_source": auto_xodr_source,
            "manual_town": str(args.manual_town),
            "out_root": str(out_root),
            "commands": [perception_cmd],
            "vision_gap_diagnostic_enabled": not bool(args.skip_vision_gap_diagnostic),
            "claim_boundary": "Does not claim RQ3/RQ4/RQ5 closure.",
        }
        if not bool(args.skip_vision_gap_diagnostic):
            pair_probe = str(out_root / "pair_<latest>")
            vision_gap_summary_path = out_root / "vision_gap" / "vision_domain_gap_summary.json"
            dry_run_payload["commands"].append(
                [
                    sys.executable,
                    "-m",
                    "ultimate_pipeline.experiments.thesis.run_vision_domain_gap",
                    "--auto",
                    f"{pair_probe}/auto",
                    "--manual",
                    f"{pair_probe}/manual",
                    "--out",
                    str(out_root / "vision_gap"),
                ]
            )
        unified_payload = _build_unified_rq_report(
            repo_root=repo_root,
            out_root=out_root,
            auto_xodr=auto_xodr,
            auto_xodr_source=auto_xodr_source,
            manual_town=str(args.manual_town),
            pair_dir=None,
            vision_gap_summary_path=vision_gap_summary_path,
            dry_run=True,
        )
        unified_path = out_root / "unified_rq_report.json"
        unified_path.write_text(json.dumps(unified_payload, indent=2), encoding="utf-8")
        dry_run_payload["unified_rq_report"] = str(unified_path)
        (out_root / "evidence_summary.json").write_text(
            json.dumps(dry_run_payload, indent=2),
            encoding="utf-8",
        )
        return 0

    _run(perception_cmd)
    pair = _latest_pair_dir(out_root)
    vision_gap_summary_path: Optional[Path] = None

    summary_payload = {
        "status": "ok",
        "scope": "scenario_b_orchestration",
        "auto_xodr": str(auto_xodr),
        "auto_xodr_source": auto_xodr_source,
        "manual_town": str(args.manual_town),
        "pair": str(pair),
        "vision_gap_diagnostic_enabled": not bool(args.skip_vision_gap_diagnostic),
        "claim_boundary": "Does not claim RQ3/RQ4/RQ5 closure.",
    }

    if not bool(args.skip_vision_gap_diagnostic):
        auto = pair / "auto"
        manual = pair / "manual"
        _run(
            [
                sys.executable,
                "-m",
                "ultimate_pipeline.experiments.thesis.run_vision_domain_gap",
                "--auto",
                str(auto),
                "--manual",
                str(manual),
                "--out",
                str(out_root / "vision_gap"),
            ]
        )
        vision_gap_summary_path = out_root / "vision_gap" / "vision_domain_gap_summary.json"
        summary_payload["vision_gap_summary"] = str(vision_gap_summary_path)

    unified_payload = _build_unified_rq_report(
        repo_root=repo_root,
        out_root=out_root,
        auto_xodr=auto_xodr,
        auto_xodr_source=auto_xodr_source,
        manual_town=str(args.manual_town),
        pair_dir=pair,
        vision_gap_summary_path=vision_gap_summary_path,
        dry_run=False,
    )
    unified_path = out_root / "unified_rq_report.json"
    unified_path.write_text(json.dumps(unified_payload, indent=2), encoding="utf-8")
    summary_payload["unified_rq_report"] = str(unified_path)

    (out_root / "evidence_summary.json").write_text(
        json.dumps(summary_payload, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
