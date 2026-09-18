from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    message: str
    details: Optional[dict] = None


from ultimate_pipeline.tools.artifact_locator import (
    resolve_run_dir,
    find_osm_artifact,
    find_xodr_artifact,
)


# ---------------------------
# Rich checks (run_dir-aware)
# ---------------------------

def osm_integrity_ok_run(run_dir: Path) -> CheckResult:
    """
    Best-effort OSM integrity.

    Pass if:
      - OSM artifacts exist in run_dir, OR
      - pipeline appears XODR-first (valid for your experiments)
    """
    if not run_dir.exists():
        return CheckResult(False, f"run_dir missing: {run_dir}")

    osm_path, _source = find_osm_artifact(run_dir)
    if osm_path:
        return CheckResult(True, f"OSM input found: {osm_path}", {"path": str(osm_path)})

    xodr, _x_source = find_xodr_artifact(run_dir)
    if xodr:
        return CheckResult(
            True,
            f"OSM not present in run_dir (pipeline may start from XODR); found {xodr}.",
            {"xodr": str(xodr)},
        )

    return CheckResult(False, "No OSM input artifact found in run_dir and no XODR outputs detected.")


def xodr_integrity_ok_run(run_dir: Path) -> CheckResult:
    if not run_dir.exists():
        return CheckResult(False, f"run_dir missing: {run_dir}")

    xodr, _source = find_xodr_artifact(run_dir)
    if xodr:
        return CheckResult(True, f"Using fallback XODR at {xodr}", {"path": str(xodr)})

    # fall back to env var (used by some test setups)
    env_p = os.environ.get("UP_TEST_XODR_PATH", "").strip()
    if env_p:
        ep = Path(env_p)
        if ep.exists() and ep.suffix.lower() == ".xodr":
            return CheckResult(True, f"XODR found via UP_TEST_XODR_PATH: {ep}", {"path": str(ep)})
        return CheckResult(False, f"UP_TEST_XODR_PATH set but invalid: {ep}")

    # try global outputs root as last resort
    return CheckResult(False, "No XODR found.")


def dem_integrity_ok_run(run_dir: Path) -> CheckResult:
    """
    DEM is often optional. Treat as soft-check unless explicitly configured.
    """
    env_dem = os.environ.get("UP_DEM_PATH", "").strip()
    if env_dem:
        p = Path(env_dem)
        if p.exists():
            return CheckResult(True, f"DEM found via UP_DEM_PATH: {p}", {"path": str(p)})
        return CheckResult(False, f"UP_DEM_PATH configured but missing: {p}")

    try:
        from ultimate_pipeline.config.settings import SETTINGS

        settings_dem = (
            getattr(SETTINGS, "DEM_PATH", None)
            or getattr(SETTINGS, "DEM_TIF", None)
            or getattr(SETTINGS, "DEM_FILE", None)
        )
        if settings_dem:
            p = Path(settings_dem)
            if p.exists():
                return CheckResult(True, f"DEM found via settings: {p}", {"path": str(p)})
            return CheckResult(False, f"DEM configured but missing: {p}")
    except Exception:
        pass

    # Look for common pipeline artifacts / reports that imply DEM step happened
    qa = run_dir / "qa_stage_reports"
    if qa.exists():
        dem_reports = list(qa.glob("*dem*")) + list(qa.glob("*DEM*"))
        if dem_reports:
            return CheckResult(True, "DEM-related QA reports present.", {"reports": [str(p) for p in dem_reports]})

    # soft pass
    return CheckResult(True, "DEM not configured (treated as optional).")


def domain_gap_ready_run(run_dir: Path) -> CheckResult:
    """
    “Ready” means: at least one XODR exists so structural gap metrics can run.
    """
    x = xodr_integrity_ok_run(run_dir)
    if not x.ok:
        return CheckResult(False, f"Not ready: {x.message}")
    return CheckResult(True, "Domain-gap prerequisites satisfied.", {"xodr": x.details})


# --------------------------------
# Thin wrappers (test compatibility)
# --------------------------------
# tests/test_pipeline_health.py expects:
#   osm_integrity_ok() -> (bool, str)
#   xodr_integrity_ok() -> (bool, str)
#   dem_integrity_ok() -> (bool, str)
#   domain_gap_ready() -> (bool, str)

def osm_integrity_ok() -> tuple[bool, str]:
    r = osm_integrity_ok_run(resolve_run_dir(None))
    return r.ok, r.message


def xodr_integrity_ok() -> tuple[bool, str]:
    r = xodr_integrity_ok_run(resolve_run_dir(None))
    return r.ok, r.message


def dem_integrity_ok() -> tuple[bool, str]:
    r = dem_integrity_ok_run(resolve_run_dir(None))
    return r.ok, r.message


def domain_gap_ready() -> tuple[bool, str]:
    r = domain_gap_ready_run(resolve_run_dir(None))
    return r.ok, r.message


# ---------------------------
# CLI (argparse only in main)
# ---------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--run_dir", type=str, default=None, help="Run directory to check")
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = resolve_run_dir(args.run_dir)

    results = {
        "osm": osm_integrity_ok_run(run_dir),
        "xodr": xodr_integrity_ok_run(run_dir),
        "dem": dem_integrity_ok_run(run_dir),
        "ready": domain_gap_ready_run(run_dir),
    }

    overall_ok = all(r.ok for r in results.values())

    if args.json:
        import json

        payload = {
            "run_dir": str(run_dir),
            "overall_ok": overall_ok,
            "checks": {k: {"ok": v.ok, "message": v.message, "details": v.details} for k, v in results.items()},
        }
        print(json.dumps(payload, indent=2))
    else:
        for k, v in results.items():
            print(f"[{k}] {'OK' if v.ok else 'FAIL'}: {v.message}")
        print(f"[overall] {'OK' if overall_ok else 'FAIL'}")

    return 0 if overall_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
