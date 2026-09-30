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


def _read_domain_gap_report(output_dir: str) -> Dict[str, Any]:
    """Read the domain gap full_report.json from disk."""
    report_path = os.path.join(output_dir, "full_report.json")
    if not os.path.exists(report_path):
        return {}
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _evaluate_mandatory_metrics(gap_report: Dict[str, Any], profile: str) -> Tuple[bool, List[str]]:
    """Evaluate mandatory metrics for a given profile.

    Returns (all_passed, list_of_failed_metrics).
    """
    # Define mandatory metrics per profile
    mandatory_per_profile = {
        "map_build_only": [],
        "thesis_research": ["geometry", "curvature", "intersection"],
        "diagnostic": [],
    }
    mandatory = mandatory_per_profile.get(profile, ["geometry", "curvature", "intersection"])
    
    failed = []
    for metric in mandatory:
        metric_data = gap_report.get("gaps", {}).get(metric, {})
        status = metric_data.get("status", "failed")
        if status != "computed":
            failed.append(f"{metric}: {status}")
    
    return len(failed) == 0, failed


def _step12_domain_gap(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    s = self.settings
    if not getattr(s, "ENABLE_DOMAIN_GAP", False):
        print("\n⏭️ Domain-gap analysis disabled in settings.")
        return

    print("\n============== 📊 STEP 12: Domain Gap Analysis ==============")

    # Determine pipeline profile
    profile = getattr(s, "DOMAIN_GAP_PROFILE", "thesis_research")

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
        return

    if not os.path.exists(manual_xodr):
        print(f"⚠️ Manual reference XODR not found: {manual_xodr}")
        self.vreport.add("domain_gap", "skipped", "manual_xodr_missing")
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
    # NEW-233: Verify coordinate report subprocesses
    coord_manual_path = os.path.join(gap_out_dir, "coord_manual.json")
    coord_auto_path = os.path.join(gap_out_dir, "coord_auto.json")
    coord_reports_ok = True
    try:
        import subprocess as _subprocess
        import sys as _sys

        for label, xodr_path, out_path in [
            ("manual", manual_xodr, coord_manual_path),
            ("auto", auto_xodr, coord_auto_path),
        ]:
            result = _subprocess.run(
                [
                    _sys.executable,
                    "-m",
                    "ultimate_pipeline.tools.xodr_coordinate_report",
                    "--xodr",
                    str(xodr_path),
                    "--out",
                    out_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"[STEP 12] ERROR: {label} coordinate report failed (rc={result.returncode}): {result.stderr}")
                coord_reports_ok = False
            else:
                # Verify output file exists and is valid JSON
                if not os.path.exists(out_path):
                    print(f"[STEP 12] ERROR: {label} coordinate report output missing: {out_path}")
                    coord_reports_ok = False
                else:
                    try:
                        with open(out_path, "r") as f:
                            json.load(f)
                        print(f"[STEP 12] {label} coordinate report OK -> {out_path}")
                    except Exception as je:
                        print(f"[STEP 12] ERROR: {label} coordinate report invalid JSON: {je}")
                        coord_reports_ok = False
    except Exception as _e:
        print(f"[STEP 12] coordinate report skipped: {_e}")
        coord_reports_ok = False

    if not coord_reports_ok:
        if profile in ("thesis_research",):
            raise RuntimeError("Coordinate report subprocess failed in thesis profile")
        else:
            print("[STEP 12] WARNING: Coordinate report issues (non-thesis profile)")

    try:
        if auto_tiles_meta:
            os.environ["UP_AUTO_META"] = auto_tiles_meta
            os.environ["UP_AUTO_META_SOURCE"] = "main_pipeline_step12"
        # Run domain gap analysis
        exit_code = run_full_domain_gap(
            manual_xodr=manual_xodr,
            auto_xodr=auto_xodr,
            manual_tiles=manual_tiles,
            auto_tiles=auto_tiles,
            perception_manual_json=perception_manual,
            perception_auto_json=perception_auto,
            output_dir=gap_out_dir,
            sumo_meta=getattr(self, "_sumo_repair_meta", None),
        )

        # Read the generated gap report
        gap_report = _read_domain_gap_report(gap_out_dir)
        
        # NEW-232: Stage 12 failure propagation based on profile
        all_passed, failed_metrics = _evaluate_mandatory_metrics(gap_report, profile)
        
        if exit_code != 0:
            error_msg = f"run_full_domain_gap exited with code {exit_code}"
            if profile == "map_build_only":
                print(f"⚠️ {error_msg} (map_build_only profile: logging only)")
                self.vreport.add("domain_gap", "warning", error_msg)
            else:
                raise RuntimeError(f"Domain-gap analysis failed: {error_msg}")
        
        if not all_passed:
            error_msg = f"Mandatory metrics failed for profile '{profile}': {', '.join(failed_metrics)}"
            if profile == "map_build_only":
                print(f"⚠️ {error_msg} (map_build_only profile: logging only)")
                self.vreport.add("domain_gap", "warning", error_msg)
            else:
                raise RuntimeError(f"Domain-gap mandatory metrics failed: {error_msg}")

        # Also verify coordinate reports if present
        if not coord_reports_ok:
            error_msg = "Coordinate report generation failed"
            if profile in ("thesis_research",):
                raise RuntimeError(error_msg)
            else:
                print(f"⚠️ {error_msg} (non-thesis profile)")

        sdg = gap_report.get("structural_domain_gap", {})
        pt = gap_report.get("per_tile_structural_gap", {})

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

        print(f"✅ Domain-gap analysis complete → {gap_summary_path}")

    except Exception as e:
        print(f"⚠️ Domain-gap analysis failed: {e}")
        self.vreport.add("domain_gap", "error", str(e))
        if profile in ("thesis_research",):
            raise

# ---------------- 🚦 QUALITY GATES WRAPPER + 🤖 LLM ----------------

