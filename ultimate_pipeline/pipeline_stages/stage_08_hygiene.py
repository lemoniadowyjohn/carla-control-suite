# REFAC_VERSION = "v1_c10"
# C10: offline map-hygiene repairs wired into the pipeline (islands,
# degenerate lanes, genuine z-seams). See quality/map_hygiene.py.
#
# NOTE: This file is auto-extracted from ultimate_pipeline/main_pipeline.py.
# It delegates to original helpers by injecting main_pipeline globals at runtime.

from __future__ import annotations

import os


def _inject_main_pipeline_globals():
    # Import is inside to avoid import-time side effects/cycles.
    from ultimate_pipeline import main_pipeline as _mp  # type: ignore
    g = globals()
    for k, v in _mp.__dict__.items():
        if k.startswith("__"):
            continue
        if k in ("_inject_main_pipeline_globals",):
            continue
        g.setdefault(k, v)


def _step8h_map_hygiene(self, final_out: str) -> str:
    """Apply C10 offline map-hygiene repairs to the final XODR (post
    junction-link patch) and return the repaired artifact path.

    Order matters: island quarantine may delete roads (so it runs first,
    when references are fewest), then degenerate-lane flooring, then
    z-seam chaining (uses C9's corrected elevation-continuity checker for
    before/after). Each repair writes its own artifact + JSON report so the
    run is fully auditable and reversible. If a repair decides it cannot
    act safely, the input artifact is kept and the reason is recorded.
    """
    _inject_main_pipeline_globals()
    import json
    from pathlib import Path as _Path

    if not bool(getattr(self.settings, "ENABLE_MAP_HYGIENE", True)):
        print("[STEP 8H] Map hygiene disabled (ENABLE_MAP_HYGIENE=false).")
        return str(final_out)

    print("\n============== 🧹 STEP 8H: Map hygiene (C10) ==============")
    from ultimate_pipeline.quality.map_hygiene import (
        quarantine_island_roads,
        repair_degenerate_lanes,
        repair_true_zseams,
    )

    out_dir = _Path(self.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    input_path = _Path(str(final_out))
    if not input_path.is_file():
        raise FileNotFoundError(
            f"[STEP 8H] Input XODR missing for map hygiene: {input_path}"
        )

    reports: dict = {}

    # ---- 8H-1: island quarantine --------------------------------------
    island_out = out_dir / "08h1_island_quarantined.xodr"
    island_report = quarantine_island_roads(
        str(input_path), str(island_out)
    )
    total_roads = int(island_report.get("total_roads", 0) or 0)
    quarantined_count = int(island_report.get("count", 0) or 0)
    max_fraction = float(
        os.getenv("UP_MAP_HYGIENE_MAX_QUARANTINE_FRACTION", "0.25")
    )
    if total_roads > 0 and quarantined_count > int(max_fraction * total_roads):
        # Safety valve: quarantine removing >25% of the map smells like a
        # broken connectivity graph, not real islands. Keep the input.
        island_report["action"] = "skipped_suspicious_fraction"
        island_report["skipped_reason"] = (
            f"quarantine would remove {quarantined_count}/{total_roads} roads "
            f"(>{max_fraction:.0%}); connectivity graph likely broken"
        )
        reports["island_quarantine"] = island_report
        print(f"⚠️ [STEP 8H] {island_report['skipped_reason']}")
        current_path = input_path
    else:
        island_report["action"] = "applied"
        reports["island_quarantine"] = island_report
        current_path = island_out
        print(
            f"[STEP 8H] Islands quarantined: {quarantined_count} roads "
            f"(components {island_report.get('component_sizes_before')})"
        )

    # ---- 8H-2: degenerate-lane floor repair ----------------------------
    lanes_out = out_dir / "08h2_degenerate_lanes_repaired.xodr"
    lane_report = repair_degenerate_lanes(str(current_path), str(lanes_out))
    reports["degenerate_lanes"] = lane_report
    current_path = lanes_out
    print(
        f"[STEP 8H] Degenerate lanes repaired: "
        f"{int(lane_report.get('repaired_count', 0) or 0)}"
    )

    # ---- 8H-3: genuine z-seam chaining ---------------------------------
    zseam_out = out_dir / "08h3_zseams_repaired.xodr"
    zseam_report = repair_true_zseams(str(current_path), str(zseam_out))
    reports["true_zseams"] = zseam_report
    current_path = zseam_out
    print(
        f"[STEP 8H] Genuine z-seams: before="
        f"{int(zseam_report.get('issues_before', 0) or 0)} after="
        f"{int(zseam_report.get('issues_after', 0) or 0)} "
        f"(roads modified={int(zseam_report.get('roads_modified', 0) or 0)})"
    )

    combined = {
        "ok": all(bool(r.get("ok", True)) for r in reports.values()),
        "input_xodr": str(input_path),
        "output_xodr": str(current_path),
        "stages": reports,
    }
    combined_path = out_dir / "map_hygiene_report.json"
    try:
        combined_path.write_text(
            json.dumps(combined, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[STEP 8H] map_hygiene_report.json write failed: {exc}")
    print(f"[STEP 8H] map_hygiene_report.json -> {combined_path}")

    self.map_hygiene_report = combined
    return str(current_path)
