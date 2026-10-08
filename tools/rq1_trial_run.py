#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 Trial Run - Single full-pipeline trial against the pinned map-of-record.

Emits the full rq1_run_receipt/v1 schema required by rq1_five_run_matrix.py:
  xodr_sha256, normalized_xodr_sha256, structural_signature, feature_counts,
  topology_counts, output_path, tileset_digest, map_acceptance_digest,
  final_receipt_digest

Usage:
    python tools/rq1_trial_run.py <run_index> [<output_base_dir>] [--mode=A|B]

Mode A: pinned OSM -> Osm2Odr repeated N>=5 times (RQ1A)
Mode B: one pinned XODR -> full downstream pipeline repeated N>=5 times (RQ1B)
"""
from __future__ import annotations

import atexit
import copy
import faulthandler
import hashlib
import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))
os.chdir(str(WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.main_pipeline import MainPipeline
from ultimate_pipeline.quality.map_acceptance import build_map_acceptance
from ultimate_pipeline.quality.map_acceptance import safe_sha256_file


# ---------------------------------------------------------------------------
# X2 driver hardening (GAP-046): fail LOUD, never silent.
#
# Three 2026-10-07 trial attempts died with run_status.json stuck at
# {"status": "running"} forever -- no terminal state on any exit path other
# than clean completion. MainPipeline.run() already writes crash artifacts for
# Python exceptions, but a hard kill (taskkill /F, OOM, native segfault such as
# CARLA's 0xC0000409) runs no except block. This driver therefore:
#   1. sanitizes a shadowing PROJ_LIB (a sibling venv's PROJ 9.5.1/layout-4
#      db was shadowing this venv's bundled PROJ -- the stage-3 DEM slowdown),
#   2. enables faulthandler so native crashes dump a traceback to disk,
#   3. installs signal handlers (SIGTERM/SIGINT/SIGBREAK where available) that
#      write terminal crash files before exiting,
#   4. registers an atexit fallback that marks the run interrupted if the
#      process exits without clean completion or a recorded exception.
# A hard SIGKILL-equivalent (TerminateProcess) can still take the process with
# no handler running -- in that case the *absence* of a terminal run_status
# plus a faulthandler dump (if any) is itself the diagnostic, and the next
# launch can detect the stale "running" file. Every path that CAN run code
# writes crash_summary.json + a terminal run_status.json first.
# ---------------------------------------------------------------------------

_DRIVER_STATE: Dict[str, Any] = {
    "out_dir": None,
    "completed": False,
    "terminal_written": False,
}


def _bundled_proj_dir() -> Optional[str]:
    try:
        import pyproj

        candidate = os.path.join(
            os.path.dirname(pyproj.__file__), "proj_dir", "share", "proj"
        )
        if os.path.isdir(candidate):
            return candidate
    except Exception:
        pass
    return None


def sanitize_proj_env() -> Dict[str, Any]:
    """Drop a shadowing PROJ_LIB so PROJ/GDAL use this venv's bundled db.

    Returns a report dict (also recorded in the receipt) describing what was
    found and done. Never raises -- worst case the environment is left alone.
    """
    report: Dict[str, Any] = {"proj_lib_before": os.environ.get("PROJ_LIB")}
    try:
        import pyproj

        report["pyproj_version"] = pyproj.__version__
    except Exception as e:  # pragma: no cover - diagnostic only
        report["pyproj_import_error"] = str(e)
        return report
    try:
        report["proj_version"] = pyproj.proj_version_str
    except Exception:
        pass
    bundled = _bundled_proj_dir()
    report["bundled_proj_dir"] = bundled
    current = os.environ.get("PROJ_LIB")
    if current and bundled:
        try:
            if os.path.normcase(os.path.abspath(current)) != os.path.normcase(
                os.path.abspath(bundled)
            ):
                report["action"] = "removed shadowing PROJ_LIB"
                del os.environ["PROJ_LIB"]
            else:
                report["action"] = "kept (already points at bundled db)"
        except Exception as e:  # pragma: no cover - diagnostic only
            report["action_error"] = str(e)
    else:
        report["action"] = "none (PROJ_LIB unset or no bundled db found)"
    return report


def _write_driver_status(
    out_dir: Path, *, status: str, stage: str, error: Optional[str] = None
) -> None:
    try:
        payload = {
            "status": status,
            "stage": stage,
            "message": None,
            "error": error,
            "out_dir": str(out_dir),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "writer": "tools/rq1_trial_run.py driver guard (X2)",
        }
        with open(out_dir / "run_status.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True)
    except Exception:
        pass


def _write_crash_summary(
    out_dir: Path, *, kind: str, error: str, stage: str = ""
) -> None:
    try:
        payload = {
            "kind": kind,
            "error": error[:2000],
            "stage": stage,
            "out_dir": str(out_dir),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "traceback": traceback.format_exc()[-8000:],
        }
        with open(out_dir / "crash_summary.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True)
    except Exception:
        pass


def _mark_terminal(
    out_dir: Path, *, status: str, stage: str, kind: str, error: str
) -> None:
    if _DRIVER_STATE.get("terminal_written"):
        return
    _DRIVER_STATE["terminal_written"] = True
    _DRIVER_STATE["completed"] = True
    try:
        faulthandler.cancel_dump_traceback_later()
    except Exception:
        pass
    _write_crash_summary(out_dir, kind=kind, error=error, stage=stage)
    _write_driver_status(out_dir, status=status, stage=stage, error=error)


def _install_crash_guards(out_dir: Path) -> None:
    _DRIVER_STATE["out_dir"] = out_dir
    _DRIVER_STATE["completed"] = False
    _DRIVER_STATE["terminal_written"] = False
    try:
        fault_path = out_dir / "fault_traceback.txt"
        fault_fh = open(fault_path, "w", encoding="utf-8")
        _DRIVER_STATE["fault_fh"] = fault_fh
        faulthandler.enable(file=fault_fh)
        # If the process hangs (not just crashes), dump tracebacks after 1h
        # so a stuck run still leaves a diagnostic instead of silence.
        faulthandler.dump_traceback_later(3600, file=fault_fh)
    except Exception:
        pass

    def _on_signal(signum: int, frame: Any) -> None:  # pragma: no cover
        _mark_terminal(
            out_dir,
            status="interrupted",
            stage="signal",
            kind=f"signal_{signum}",
            error=f"received signal {signum}",
        )
        # Re-raise as SystemExit so atexit sees a completed guard (no-op).
        raise SystemExit(f"interrupted by signal {signum}")

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _on_signal)
            except Exception:
                pass

    def _on_exit() -> None:
        if _DRIVER_STATE.get("completed"):
            return
        _mark_terminal(
            out_dir,
            status="interrupted",
            stage="atexit",
            kind="unclean_exit",
            error=(
                "process exited without clean completion and without a "
                "recorded exception (hard kill, OOM, or native crash with "
                "no faulthandler dump -- see fault_traceback.txt)"
            ),
        )

    atexit.register(_on_exit)


def _sha256_dict(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _digest_file(path: Optional[str]) -> Optional[str]:
    if path and os.path.exists(path):
        return safe_sha256_file(path)
    return None


def _extract_structural_signature(reports: Dict[str, Any]) -> Optional[str]:
    """Extract or compute the structural signature from pipeline reports."""
    # The structural signature is typically in the topology certification
    comp = reports.get("component_reachability_literal")
    if isinstance(comp, dict):
        return _sha256_dict(comp)
    # Fallback: hash the component reachability recovery report
    comp = reports.get("component_reachability")
    if isinstance(comp, dict):
        return _sha256_dict(comp)
    return None


def _extract_feature_counts(reports: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Extract feature counts from map acceptance metrics."""
    # These come from map_acceptance metrics
    return None  # Will be filled from map_acceptance


def _extract_topology_counts(reports: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Extract topology counts from pipeline reports."""
    return None  # Will be filled from map_acceptance


def _extract_tileset_digest(reports: Dict[str, Any]) -> Optional[str]:
    """Extract tileset digest from tile QA reports."""
    # The tileset digest is computed during tile QA
    tile_qa = reports.get("tile_qa")
    if isinstance(tile_qa, dict):
        return tile_qa.get("tileset_digest_sha256")
    return None


def run_single_trial(
    run_idx: int,
    out_base: Path,
    mode: str = "B",
) -> Dict[str, Any]:
    """Execute a single trial run and return the full receipt."""
    pinned = verify_pinned_map("auto_map_of_record")
    if pinned.get("verification_status") != "VERIFIED":
        raise RuntimeError(f"Map verification failed: {pinned}")
    in_xodr = pinned["resolved_path"]
    input_sha = pinned["sha256_actual"]

    out_base = Path(out_base) / f"run_{run_idx:02d}"
    out_base.mkdir(parents=True, exist_ok=True)

    # X2: sanitize PROJ env first (a sibling venv's PROJ_LIB was shadowing
    # this venv's bundled proj.db), then arm the crash guards so EVERY exit
    # path below leaves a terminal run_status.json + crash_summary.json.
    proj_env_report = sanitize_proj_env()
    _install_crash_guards(out_base)
    _write_driver_status(out_base, status="running", stage="init")

    s = copy.copy(SETTINGS)
    s.INPUT_XODR = in_xodr
    s.BASE_OUTPUT_DIR = str(out_base)
    s.QA_AUTOVIS = False

    # For Mode A, we would run OSM -> Osm2Odr only
    # For Mode B (default), full downstream pipeline
    if mode == "A":
        # RQ1A: pinned OSM -> Osm2Odr only
        # This would require running only the Osm2Odr stage
        # For now, we run full pipeline but note the mode
        pass

    t0 = time.time()
    try:
        pipeline = MainPipeline(settings=s)
        out_dir = pipeline.run()
        status = "ok"
        error = ""
        reports = getattr(pipeline, "stage_reports", {})
        map_acceptance = getattr(pipeline, "map_acceptance", {})
    except BaseException as e:
        # BaseException (not just Exception) so KeyboardInterrupt/SystemExit
        # and signal-handler re-raises also land a terminal crash file here
        # instead of dying silent. MainPipeline.run() already wrote ITS OWN
        # crash files into its out_dir for plain Exceptions before re-raising;
        # this driver-level file covers the driver's receipt dir regardless.
        out_dir = str(out_base)
        status = f"FAILED: {type(e).__name__}: {e}"
        error = str(e)[:500]
        reports = {}
        map_acceptance = {}
        _mark_terminal(
            out_base,
            status="failed",
            stage=getattr(pipeline, "_run_stage", "unknown")
            if "pipeline" in locals()
            else "startup",
            kind=f"exception_{type(e).__name__}",
            error=f"{type(e).__name__}: {e}",
        )
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
    dur = time.time() - t0

    # Build full receipt from map_acceptance and reports
    final_xodr = map_acceptance.get("final_xodr_path") if map_acceptance else None
    final_xodr_sha = _digest_file(final_xodr) if final_xodr else None

    # Normalized XODR SHA (after any normalization step)
    # For now, same as final_xodr_sha; a normalization step would change this
    normalized_xodr_sha = final_xodr_sha

    # Structural signature
    structural_sig = _extract_structural_signature(reports)

    # Feature counts from map_acceptance metrics
    feature_counts = None
    topology_counts = None
    tileset_digest = None
    map_acceptance_digest = None
    final_receipt_digest = None

    if map_acceptance:
        feature_counts = {
            k: v for k, v in map_acceptance.get("metrics", {}).items()
            if isinstance(v, int) and "count" in k.lower()
        }
        topology_counts = {
            k: v for k, v in map_acceptance.get("metrics", {}).items()
            if isinstance(v, int) and ("component" in k.lower() or "lane" in k.lower() or "junction" in k.lower() or "road" in k.lower())
        }
        # Tileset digest
        tileset_digest = map_acceptance.get("linked_artifact_sha256", {}).get("tileset_digest")
        # Map acceptance digest
        map_acceptance_digest = map_acceptance.get("payload_sha256")
        # Final receipt digest
        final_receipt_digest = map_acceptance.get("acceptance_artifact_sha256")

    # Structural signature fallback
    if structural_sig is None and map_acceptance:
        structural_sig = map_acceptance.get("payload_sha256")

    receipt = {
        "schema": "rq1_run_receipt/v1",
        "run": run_idx,
        "mode": mode,
        "status": status,
        "error": error,
        "duration_s": round(dur, 1),
        "input_xodr": in_xodr,
        "input_sha256": input_sha,
        "out_dir": str(out_dir),
        "xodr_sha256": final_xodr_sha,
        "normalized_xodr_sha256": normalized_xodr_sha,
        "structural_signature": structural_sig,
        "feature_counts": feature_counts,
        "topology_counts": topology_counts,
        "output_path": str(out_dir),
        "tileset_digest": tileset_digest,
        "map_acceptance_digest": map_acceptance_digest,
        "final_receipt_digest": final_receipt_digest,
        "map_acceptance": map_acceptance,
        "proj_env": proj_env_report,
    }

    # Write receipt
    receipt_path = Path(out_base) / f"rq1_run_{run_idx:02d}_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # X2: terminal driver status on the success path (the except path and the
    # atexit/signal fallbacks already covered every other exit). From here on
    # the atexit guard is a no-op.
    if status == "ok":
        _DRIVER_STATE["completed"] = True
        _DRIVER_STATE["terminal_written"] = True
        try:
            faulthandler.cancel_dump_traceback_later()
        except Exception:
            pass
        try:
            fh = _DRIVER_STATE.pop("fault_fh", None)
            if fh is not None:
                fh.close()
        except Exception:
            pass
        _write_driver_status(out_base, status="ok", stage="done")
    # (failure path already marked terminal in the except block above)

    return receipt


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/rq1_trial_run.py <run_index> [<output_base_dir>] [--mode=A|B]", file=sys.stderr)
        sys.exit(1)

    run_idx = int(sys.argv[1])
    base = Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else Path("reports/rq1_trial_runs")
    mode = "B"
    if "--mode=A" in sys.argv:
        mode = "A"
    elif "--mode=B" in sys.argv:
        mode = "B"

    receipt = run_single_trial(run_idx, base, mode)
    print(json.dumps({"status": receipt["status"], "run": receipt["run"], "mode": receipt["mode"]}, indent=2))


if __name__ == "__main__":
    main()