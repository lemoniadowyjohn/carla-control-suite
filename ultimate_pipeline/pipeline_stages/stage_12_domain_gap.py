# REFAC_VERSION = "v5_preserve"
# NOTE: This file is auto-extracted from ultimate_pipeline/main_pipeline.py.
# It delegates to original helpers by injecting main_pipeline globals at runtime.

from __future__ import annotations

def _inject_main_pipeline_globals():
    # Import is inside to avoid import-time side effects/cycles.
    from ultimate_pipeline import main_pipeline as _mp  # type: ignore
    g = globals()
    for k, v in _mp.__dict__.items():
        if k.startswith("__"):
            continue
        if k in ("_inject_main_pipeline_globals",):
            continue
        # Don't overwrite locally-defined names (e.g., stage functions).
        g.setdefault(k, v)


DOMAIN_GAP_STATUS_SCHEMA = "domain_gap_stage_status/v1"


def _domain_gap_enabled(settings) -> bool:
    """Mirror the registry's ``DOMAIN_GAP.enabled_by`` predicate (NEW-339).

    ``enabled_by: ["ENABLE_DOMAIN_GAP", "UP_ENABLE_DOMAIN_GAP"]`` is OR-ed, so a
    run with only the env var set must still produce the status artifact --
    otherwise the signal reads MISSING instead of its real state.
    """
    if bool(getattr(settings, "ENABLE_DOMAIN_GAP", False)):
        return True
    return os.getenv("UP_ENABLE_DOMAIN_GAP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _write_domain_gap_stage_status(self, payload: dict) -> str:
    """Persist the DOMAIN_GAP signal artifact (atomic, fail-closed)."""
    body = {"schema": DOMAIN_GAP_STATUS_SCHEMA}
    body.update(payload)
    path = os.path.join(self.out_dir, "domain_gap_stage_status.json")
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    print(f"[STEP 12] domain_gap_stage_status.json -> {path}")
    return path


def _coord_report_status(label: str, xodr_path: str, out_path: str) -> dict:
    """Run one coordinate-report subprocess and record its real outcome.

    Both ``returncode`` and the produced file are checked: previously the
    subprocess ran with ``check=False`` and the outcome was discarded, so a
    crashed report still printed as if the artifact had been written.
    """
    import subprocess as _subprocess
    import sys as _sys

    cmd = [
        _sys.executable,
        "-m",
        "ultimate_pipeline.tools.xodr_coordinate_report",
        "--xodr",
        str(xodr_path),
        "--out",
        str(out_path),
    ]
    entry = {
        "label": label,
        "command": cmd,
        "returncode": None,
        "output_path": str(out_path),
        "output_exists": bool(os.path.isfile(out_path)),
        "ok": False,
        "error": None,
    }
    try:
        proc = _subprocess.run(cmd, check=False)
        entry["returncode"] = int(proc.returncode)
    except Exception as e:  # noqa: BLE001
        entry["error"] = str(e)
    entry["output_exists"] = bool(os.path.isfile(out_path))
    entry["ok"] = entry["returncode"] == 0 and entry["output_exists"]
    if not entry["ok"] and entry["error"] is None:
        if entry["returncode"] not in (0, None):
            entry["error"] = f"exit code {entry['returncode']}"
        elif entry["returncode"] == 0:
            entry["error"] = "report process exited 0 but produced no output file"
    return entry


def _domain_gap_score(summary: dict) -> float | None:
    """Best-effort aggregate of the whole-map geometry gap, or None."""
    try:
        geo = summary.get("whole_geometry_gap") or {}
        for key in ("mean", "avg", "mean_gap", "p95", "max"):
            if key in geo and isinstance(geo[key], (int, float)):
                return float(geo[key])
        return None
    except Exception:  # noqa: BLE001
        return None


def _step12_domain_gap(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    s = self.settings
    if not _domain_gap_enabled(s):
        print("\n⏭️ Domain-gap analysis disabled in settings.")
        # Registry skip_policy RECORD_IF_DISABLED: index marks the signal
        # NOT_APPLICABLE from the predicate, so no artifact is written here.
        return

    print("\n============== 📊 STEP 12: Domain Gap Analysis ==============")

    # Robust settings lookup (older settings.py may not define these attributes)
    manual_xodr = getattr(s, "MANUAL_MAP_XODR", None) or getattr(
        s, "MANUAL_REFERENCE_XODR", None
    )
    manual_tiles = (
        getattr(s, "MANUAL_TILES_DIR", None)
        or getattr(s, "MANUAL_TILES_ROOT", None)
        or ""
    )

    # Manual XODR is mandatory for any meaningful domain-gap computation.
    if not manual_xodr:
        print("⚠️ Domain gap ENABLED but MANUAL_MAP_XODR is not configured.")
        print("   → Skipping STEP 12. Set MANUAL_MAP_XODR in settings.py.")
        self.vreport.add("domain_gap", "skipped", "manual_xodr_not_configured")
        _write_domain_gap_stage_status(
            self,
            {
                "ok": False,
                "status": "BLOCKED_EXTERNAL",
                "reason": "manual_xodr_not_configured",
                "manual_xodr_present": False,
                "domain_gap_score": None,
            },
        )
        return

    if not os.path.exists(manual_xodr):
        print(f"⚠️ Manual reference XODR not found: {manual_xodr}")
        self.vreport.add("domain_gap", "skipped", "manual_xodr_missing")
        _write_domain_gap_stage_status(
            self,
            {
                "ok": False,
                "status": "BLOCKED_EXTERNAL",
                "reason": "manual_xodr_missing",
                "manual_xodr": str(manual_xodr),
                "manual_xodr_present": False,
                "domain_gap_score": None,
            },
        )
        return

    # Tiles are optional: whole-map gaps work without per-tile comparisons.
    if manual_tiles and not os.path.isdir(manual_tiles):
        print(
            f"⚠️ Manual tiles directory not found (per-tile gaps will be skipped): {manual_tiles}"
        )
        manual_tiles = ""

    auto_xodr = final_out
    auto_tiles = os.path.join(self.out_dir, "tiles")
    auto_tiles_meta = ""
    if not os.path.isdir(auto_tiles):
        # Tiling may be disabled; run_full_domain_gap will skip per-tile stages.
        auto_tiles = ""
    else:
        try:
            auto_tiles_meta_path = (
                Path(auto_tiles).parent / "tile_metadata.json"
                if Path(auto_tiles).name.lower() == "tiles"
                else Path(auto_tiles) / "tile_metadata.json"
            )
            if not auto_tiles_meta_path.is_file():
                from ultimate_pipeline.tiling.tile_extractor import (
                    freeze_tileset,
                    is_tileset_frozen,
                )

                if not is_tileset_frozen(str(auto_tiles)):
                    freeze_tileset(str(auto_tiles))
                TileMetadata.generate_metadata(
                    str(auto_tiles), str(auto_tiles_meta_path)
                )
            if auto_tiles_meta_path.is_file():
                auto_tiles_meta = str(auto_tiles_meta_path)
        except Exception as _e:
            print(
                f"[STEP 12] Failed to prepare deterministic auto tile metadata: {_e}"
            )
    perception_manual = getattr(s, "PERCEPTION_MANUAL_JSON", None)
    perception_auto = getattr(s, "PERCEPTION_AUTO_JSON", None)

    gap_out_dir = os.path.join(
        self.out_dir, getattr(s, "DOMAIN_GAP_OUT_DIR", "domain_gap")
    )
    os.makedirs(gap_out_dir, exist_ok=True)

    # Thesis evidence: coordinate reports (manual vs auto)
    coord_reports: dict = {}
    try:
        coord_manual = os.path.join(gap_out_dir, "coord_manual.json")
        coord_auto = os.path.join(gap_out_dir, "coord_auto.json")
        coord_reports["coord_manual"] = _coord_report_status(
            "coord_manual", manual_xodr, coord_manual
        )
        coord_reports["coord_auto"] = _coord_report_status(
            "coord_auto", auto_xodr, coord_auto
        )
        for name, entry in coord_reports.items():
            if entry["ok"]:
                print(f"[STEP 12] {name}.json -> {entry['output_path']}")
            else:
                print(
                    f"⚠️ [STEP 12] {name} report failed: {entry['error']} "
                    f"(returncode={entry['returncode']}, "
                    f"exists={entry['output_exists']})"
                )
    except Exception as _e:
        print(f"[STEP 12] coordinate report skipped: {_e}")
        coord_reports["error"] = str(_e)

    try:
        if auto_tiles_meta:
            os.environ["UP_AUTO_META"] = auto_tiles_meta
            os.environ["UP_AUTO_META_SOURCE"] = "main_pipeline_step12"
        combined_gap = run_full_domain_gap(
            manual_xodr=manual_xodr,
            auto_xodr=auto_xodr,
            manual_tiles=manual_tiles,
            auto_tiles=auto_tiles,
            perception_manual_json=perception_manual,
            perception_auto_json=perception_auto,
            output_dir=gap_out_dir,
            sumo_meta=getattr(self, "_sumo_repair_meta", None),
        )

        sdg = combined_gap.get("structural_domain_gap", {})
        pt = combined_gap.get("per_tile_structural_gap", {})

        # pt is keyed by TILE NAME (see run_full_domain_gap.py's
        # _combine_per_tile_structural_gap: {"tile_0_0.xodr": {"geometry":
        # {...}, "curvature": {...}}, ...}), not by metric name -- extract
        # each metric across all tiles into its own tile-keyed dict.
        per_tile_geometry = {
            tile: entry.get("geometry", {})
            for tile, entry in pt.items()
            if isinstance(entry, dict)
        }
        per_tile_curvature = {
            tile: entry.get("curvature", {})
            for tile, entry in pt.items()
            if isinstance(entry, dict)
        }

        summary = {
            "whole_geometry_gap": sdg.get("geometry", {}),
            "whole_curvature_gap": sdg.get("curvature", {}),
            "whole_intersection_gap": sdg.get("intersection", {}),
            "whole_semantic_gap": sdg.get("semantics", {}),
            "whole_road_class_gap": sdg.get("road_classification", {}),
            "whole_connectivity_gap": sdg.get("connectivity", {}),
            "per_tile_geometry_gap": per_tile_geometry,
            "per_tile_curvature_gap": per_tile_curvature,
            "tile_seam_statistics": self.vreport.data.get("seam_statistics", []),
        }

        # Persist summary to disk (artifact)
        gap_summary_path = os.path.join(gap_out_dir, "domain_gap_summary.json")
        with open(gap_summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        # Optional experiment tracking / artifact registry
        if hasattr(self, "artifact_recorder"):
            self.artifact_recorder.record(
                run_id=getattr(self, "run_id", None),
                artifact_type="domain_gap_summary",
                path=gap_summary_path,
            )

        # Also keep it inside ValidationReport (for final summary & LLM)
        self.vreport.add_dict("domain_gap_summary", summary)

        coord_entries = [v for v in coord_reports.values() if isinstance(v, dict)]
        coords_ok = bool(coord_entries) and all(
            bool(e.get("ok")) for e in coord_entries
        )
        payload = {
            "ok": coords_ok,
            "status": "PASS" if coords_ok else "INCOMPLETE",
            "manual_xodr_present": True,
            "domain_gap_score": _domain_gap_score(summary),
            "summary_path": gap_summary_path,
            "summary_written": os.path.isfile(gap_summary_path),
            "manual_tiles_present": bool(manual_tiles),
            "auto_tiles_present": bool(auto_tiles),
            "coordinate_reports": coord_reports,
            "error": None if coords_ok else "one or more coordinate reports failed",
        }
        _write_domain_gap_stage_status(self, payload)

        if coords_ok:
            print(f"✅ Domain-gap analysis complete → {gap_summary_path}")
        else:
            print(
                "⚠️ Domain-gap summary written but coordinate evidence is "
                "incomplete → domain_gap_stage_status.json marked INCOMPLETE"
            )

    except Exception as e:
        print(f"⚠️ Domain-gap analysis failed: {e}")
        self.vreport.add("domain_gap", "error", str(e))
        _write_domain_gap_stage_status(
            self,
            {
                "ok": False,
                "status": "INCOMPLETE",
                "manual_xodr_present": bool(manual_xodr),
                "domain_gap_score": None,
                "coordinate_reports": coord_reports,
                "error": str(e),
            },
        )

# ---------------- 🚦 QUALITY GATES WRAPPER + 🤖 LLM ----------------

