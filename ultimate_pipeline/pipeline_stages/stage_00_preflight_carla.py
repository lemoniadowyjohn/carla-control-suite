# REFAC_VERSION = "v4_2026-02-21"
# Auto-generated stage module extracted from ultimate_pipeline.main_pipeline
from __future__ import annotations

def _inject_main_pipeline_globals() -> None:
    """Populate this module's globals with symbols from ultimate_pipeline.main_pipeline.

    This avoids duplicating the monolith's import surface while keeping stage code unchanged.
    Import is performed lazily at runtime (after main_pipeline is loaded).
    """
    g = globals()
    if g.get("_UP_STAGE_GLOBALS_INJECTED"):
        return
    from ultimate_pipeline import main_pipeline as _mp
    for k, v in _mp.__dict__.items():
        if k not in g:
            g[k] = v
    g["_UP_STAGE_GLOBALS_INJECTED"] = True



def _connect_carla(self) -> None:
    _inject_main_pipeline_globals()
    print("\n============== 🚗 CARLA CONNECTION ==============")
    s = self.settings

    # Allow running the pipeline without CARLA (e.g., for pure XODR/metrics runs).
    if not getattr(s, "ENABLE_CARLA", True) or os.getenv(
        "UP_DISABLE_CARLA", ""
    ).strip().lower() in ("1", "true", "yes", "on"):
        self.client = None
        print(
            "⚠️ CARLA disabled (settings.ENABLE_CARLA=False or UP_DISABLE_CARLA=1)."
        )
        return

    # Crash-proof default on Windows: keep CARLA out of this orchestrator process.
    if self._carla_isolation_enabled():
        self.client = None
        host, port = self._carla_host_port()
        try:
            import socket

            with socket.create_connection((host, port), timeout=1.0):
                pass
            print(
                f"✅ CARLA RPC reachable at {host}:{port} (isolation mode: no in-proc client)."
            )
        except Exception as e:
            print(
                f"⚠️ CARLA RPC not reachable at {host}:{port} yet ({e}). Workers will retry when needed."
            )
        return

    # Non-isolation path: keep original behavior (unified manager, auto-recovery).
    try:
        from ultimate_pipeline.carla_tools.carla_recovery import (
            get_reliable_client,
        )  # local import by design

        self.client = get_reliable_client()
        self.client.set_timeout(300.0)
    except Exception as e:
        raise RuntimeError(
            "❌ CARLA connection failed. Start CARLA (server) first, or set ENABLE_CARLA=False "
            "to run offline-only stages (XODR/tiling/metrics).\n"
            f"Reason: {e}"
        ) from e

    print("✅ CARLA online and stable (via unified manager).")


def _carla_allowed(self, stage: str) -> bool:
    _inject_main_pipeline_globals()
    """
    Decide whether CARLA loading / visualization is allowed at a given stage.

    Prevents unstable or meaningless CARLA loads
    (e.g. before lanes, laneLinks, or semantics exist).
    """

    s = self.settings

    # Global kill switch
    if not getattr(s, "QA_AUTOVIS", False):
        return False

    # Explicit allow-list of stages
    allowed_stages = {
        "pre_lane_preview",  # visual only (no spawning)
        "topology_repair",
        "after_lane_repair",
        "final_spawn_validation",
    }

    if stage not in allowed_stages:
        return False

    # Pre-lane preview is visualization-only
    if stage == "pre_lane_preview":
        return True

    # Early CARLA tests must be explicitly enabled
    if stage != "final_spawn_validation":
        return getattr(s, "ENABLE_CARLA_TEST_EARLY", False)

    # Final validation is always allowed
    return True


def _dem_precheck(self) -> None:
    _inject_main_pipeline_globals()
    s = self.settings
    full_dem_path = s.DEM_TIF
    dem_info_initial = DEMDiagnostics.summarize(full_dem_path)
    self.vreport.add_dict("dem_diagnostics_initial", dem_info_initial)

    if not dem_info_initial.get("exists", False):
        print(
            "⚠️ DEM missing/invalid at initial path → will use flat elevation unless auto-download succeeds."
        )
    else:
        print(
            "🏔️ DEM summary (initial):",
            dem_info_initial["crs"],
            dem_info_initial["bounds"],
        )


def _stage_gate(self, stage: str, name: str, fn):
    _inject_main_pipeline_globals()
    """
    Run a quality check function at a specific pipeline stage.

    - Prints [QA][stage] name
    - Runs fn() and gets a dict report
    - Writes the report to <out_dir>/qa_stage_reports/{stage}__{name}.json
    - If env UP_STRICT_QUALITY_GATES=1 and report["ok"] is False, raises exception
    """
    print(f"\n[QA][{stage}] {name} ...")
    rep = fn()
    try:
        if getattr(self, "out_dir", None):
            qa_dir = os.path.join(self.out_dir, "qa_stage_reports")
            os.makedirs(qa_dir, exist_ok=True)
            path = os.path.join(qa_dir, f"{stage}__{name}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rep, f, indent=2, default=str)
            print(f"[QA][{stage}] wrote {path}")
    except Exception as e:
        print(f"[QA][{stage}] report write skipped: {e}")
    strict = os.getenv("UP_STRICT_QUALITY_GATES", "0").strip() in (
        "1",
        "true",
        "True",
    )
    ok = rep.get("ok", True) if isinstance(rep, dict) else True
    if strict and not ok:
        raise RuntimeError(f"[QA FAIL][{stage}] {name}: {rep}")
    return rep


