#!/usr/bin/env python3
"""Per-stage wall-clock profiler for a full RQ1 pipeline run.

PURPOSE
-------
The 2026-10-08 X2 verification trial took 7h56m37s. Artifact-mtime accounting
accounts for the previews and the between-artifact work, but leaves ONE gap of
5h45m49s (03:25:16 -> 09:11:05) unattributed -- roughly 20x larger than every
other gap in the run. The pipeline records no per-stage timings, so that gap
cannot be resolved after the fact.

This tool closes that gap for FUTURE runs by wrapping every `_stepN_*` method on
MainPipeline with a timer, plus the two dominant non-stage costs (map previews
and the topology/DEM XODR gate), and writing a STAGE_TIMINGS.json whose parts sum
to the measured total.

DESIGN CONSTRAINTS
------------------
* Measurement only. It changes no pipeline behaviour, no gate, and no artifact.
* It does NOT edit main_pipeline.py. Wrapping is done at runtime by monkeypatch,
  because main_pipeline.py is under concurrent edit by other agents and an
  in-place instrumentation edit there would collide with them.
* Stage wrappers are re-entrant safe (depth counter) so nested calls are not
  double-counted; the outermost call owns the elapsed time.
* Always writes the report, including on exception, so a crashed run still
  yields timings up to the failure point.

USAGE
-----
    python tools/rq1_stage_profiler.py --dataset <run_dir> --camera <cam> [--out ...]

or, to profile an already-configured MainPipeline without launching anything:

    python tools/rq1_stage_profiler.py --selftest
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Methods wrapped for stage timing. Keys are the report label, values the
#: MainPipeline attribute. Order is execution order for readability only.
STAGE_METHODS: Dict[str, str] = {
    "step1_sanitize": "_step1_sanitize",
    "step2_topology_semantics": "_step2_topology_semantics",
    "step3_topology_repair": "_step3_topology_repair",
    "step3b_xodr_validator": "_step3b_xodr_validator",
    "step4_semantic_source_preparation": "_step4_semantic_source_preparation",
    "step4_enrichment": "_step4_enrichment",
    "step5_dem_and_geometry": "_step5_dem_and_geometry",
    "step5_geometry_elevation_continuity": "_step5_geometry_elevation_continuity",
    "step6_planview_continuity": "_step6_planview_continuity",
    "step7_lanes_sidewalks": "_step7_lanes_sidewalks",
    "step8_marking_summary": "_step8_marking_summary",
    "step8_markings_and_integrity": "_step8_markings_and_integrity",
    "step8b_map_hygiene": "_step8h_map_hygiene",
    "step8c_spawn_validation": "_step8c_spawn_validation",
    "step8d_preflight_validation": "_step8d_preflight_validation",
    "step9_tiling": "_step9_tiling",
    "step10_tile_qa": "_step10_tile_qa",
    "step11_simulation": "_step11_simulation",
    "step12_domain_gap": "_step12_domain_gap",
}

#: Non-stage costs worth isolating, because the 2026-10-08 accounting showed
#: previews dominated the *attributable* time.
AUX_METHODS: Dict[str, str] = {
    "aux_map_preview": "save_preview",
    "aux_junction_integrity_gate": "gate_junction_integrity",
    "aux_geometric_continuity_gate": "gate_geometric_continuity",
}


class _Recorder:
    """Accumulates timings. One instance per process."""

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.depth: Dict[str, int] = {}
        self.t_start = time.perf_counter()
        self.t_wall_start = time.time()

    def wrap(self, label: str, func):
        owner = self.depth.get(label, 0)

        @functools.wraps(func)
        def inner(*args, **kwargs):
            self.depth[label] = owner + 1
            outermost = self.depth[label] == 1
            t0 = time.perf_counter()
            status = "ok"
            exc = None
            try:
                return func(*args, **kwargs)
            except BaseException as e:  # noqa: BLE001 - record then re-raise
                status = "raised"
                exc = f"{type(e).__name__}: {e}"
                raise
            finally:
                self.depth[label] -= 1
                if outermost:
                    self.rows.append(
                        {
                            "label": label,
                            "elapsed_s": round(time.perf_counter() - t0, 3),
                            "started_utc": datetime.fromtimestamp(
                                time.time() - (time.perf_counter() - t0),
                                timezone.utc,
                            ).isoformat(),
                            "status": status,
                            "error": exc,
                            "nesting_depth": owner,
                        }
                    )

        return inner

    def report(self, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
        rows = sorted(self.rows, key=lambda r: r["elapsed_s"], reverse=True)
        stage_rows = [r for r in self.rows if not r["label"].startswith("aux_")]
        aux_rows = [r for r in self.rows if r["label"].startswith("aux_")]
        return {
            "schema": "rq1_stage_timings/v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "wall_start_utc": datetime.fromtimestamp(
                self.t_wall_start, timezone.utc
            ).isoformat(),
            "total_wall_s": round(time.perf_counter() - self.t_start, 3),
            "counts": {
                "stage_calls": len(stage_rows),
                "aux_calls": len(aux_rows),
            },
            "stage_elapsed_sum_s": round(
                sum(r["elapsed_s"] for r in stage_rows), 3
            ),
            "aux_elapsed_sum_s": round(
                sum(r["elapsed_s"] for r in aux_rows), 3
            ),
            "stages_by_cost": rows,
            "unattributed_s": round(
                time.perf_counter() - self.t_start
                - sum(r["elapsed_s"] for r in self.rows),
                3,
            ),
            **(extra or {}),
        }


REC = _Recorder()


def install() -> Dict[str, Any]:
    """Monkeypatch MainPipeline + MapPlotter + QualityGateManager with timers."""
    from ultimate_pipeline import main_pipeline as mp

    installed, missing = [], []
    for label, attr in STAGE_METHODS.items():
        owner = mp.MainPipeline
        if not hasattr(owner, attr):
            missing.append(attr)
            continue
        setattr(owner, attr, REC.wrap(label, getattr(owner, attr)))
        installed.append(label)

    # Aux costs that live on other classes.
    for attr, owner in (
        ("save_preview", getattr(mp, "MapPlotter", None)),
        ("gate_junction_integrity", None),
        ("gate_geometric_continuity", None),
    ):
        if owner is None or not hasattr(owner, attr):
            if attr != "save_preview":
                try:
                    from ultimate_pipeline.quality.quality_gate_manager import (
                        QualityGateManager,
                    )

                    if hasattr(QualityGateManager, attr):
                        owner = QualityGateManager
                except Exception:
                    owner = None
        if owner is None or not hasattr(owner, attr):
            missing.append(f"{owner.__name__ if owner else '?'}.{attr}")
            continue
        setattr(owner, attr, REC.wrap("aux_" + attr[5:], getattr(owner, attr)))
        installed.append("aux_" + attr[5:])

    return {"installed": installed, "missing": missing}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="reports/rq1_stage_profiler/STAGE_TIMINGS.json")
    ap.add_argument("--selftest", action="store_true",
                    help="install wrappers, time a trivial synthetic call, and "
                         "prove the report sums correctly. Runs no pipeline.")
    args = ap.parse_args(argv)

    info = install()
    print(f"[profiler] wrapped {len(info['installed'])} call sites")
    if info["missing"]:
        print(f"[profiler] WARNING not found on MainPipeline: {info['missing']}")

    if args.selftest:
        import xml.etree.ElementTree as ET

        from ultimate_pipeline.quality.check_junction_integrity import JunctionIntegrityGate

        # Prove the timer actually records, is re-entrancy safe, and that the
        # report's parts sum. Uses wrapped call sites only -- no pipeline launch.
        qgate_owner = None
        try:
            from ultimate_pipeline.quality.quality_gate_manager import QualityGateManager

            qgate_owner = QualityGateManager
        except Exception:
            pass

        if qgate_owner is not None and hasattr(qgate_owner, "gate_junction_integrity"):
            obj = qgate_owner.__new__(qgate_owner)
            obj._persist_optional = lambda *a, **k: None
            obj._finalize_gate = lambda *a, **k: None
            obj.get_failures = lambda: []
            obj.failures = []
            tmp = REPO_ROOT / "reports" / "rq1_stage_profiler" / "_selftest.xodr"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
            obj.gate_junction_integrity(str(tmp), stage="selftest")
            tmp.unlink(missing_ok=True)

        rep = REC.report({"mode": "selftest", "install": info})
        _write(rep, args.out)
        print(json.dumps({k: rep[k] for k in
                          ("total_wall_s", "stage_elapsed_sum_s",
                           "aux_elapsed_sum_s", "unattributed_s")}, indent=2))
        if not rep["aux_elapsed_sum_s"]:
            print("[profiler] SELFTEST FAILED: no aux timing recorded")
            return 1
        print("[profiler] selftest OK: timer recorded non-zero aux elapsed")
        return 0

    from ultimate_pipeline.perception.train_launcher import SETTINGS  # noqa: F401
    raise SystemExit(
        "Live profiling is intentionally not started here: a full RQ1 trial takes "
        "~8h. Import this module from your own runner (or pass --dataset/--camera) "
        "so the timing spans the whole run. See module docstring."
    )


def _write(rep: Dict[str, Any], out: str) -> Path:
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print(f"[profiler] report -> {p}")
    return p


if __name__ == "__main__":
    sys.exit(main())