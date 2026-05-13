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
        # Keep stage-local symbols, but refresh imported dependencies from main_pipeline.
        if k in g and k in ("_step9_tiling",):
            continue
        g[k] = v


def _step9_tiling(self, final_out: str) -> Optional[str]:
    _inject_main_pipeline_globals()
    s = self.settings
    print("\n============== 🧩 STEP 9: Map Tiling (optional) ==============")

    # Early return when tiling is disabled
    if not getattr(s, "ENABLE_TILING", False):
        print("⏭️ Tiling disabled.")
        return None

    if not self.semantic_state.get("has_lanes", False):
        print(
            "⚠️ Tiling before lane semantics — tiles may be non-drivable by design"
        )

    tiling_input = final_out
    try:
        from ultimate_pipeline.quality.road_link_endpoint_errors import (
            write_road_link_endpoint_errors,
        )

        top_k = int(os.getenv("UP_ROAD_LINK_ENDPOINT_TOP_K", "50") or "50")
        endpoint_diag_path = os.path.join(self.out_dir, "road_link_endpoint_errors.json")
        endpoint_diag = write_road_link_endpoint_errors(
            xodr_path=tiling_input,
            out_json=endpoint_diag_path,
            top_k=max(1, top_k),
        )
        max_dxy = (endpoint_diag.get("summary") or {}).get("dxy_m", {}).get("max")
        print(
            "[STEP 9] road_link_endpoint_errors.json -> "
            f"{endpoint_diag_path} (max_dxy_m={max_dxy})"
        )
    except Exception as e:
        print(f"[STEP 9] Road link endpoint diagnostics failed (continuing): {e}")

    repair_links_enabled = str(
        os.getenv("UP_ENABLE_ROAD_LINK_TARGET_REPAIR", "0")
    ).strip().lower() in ("1", "true", "yes", "on")
    if repair_links_enabled:
        try:
            from ultimate_pipeline.quality.road_link_endpoint_errors import (
                repair_road_link_targets,
            )

            repaired_out = final_out.replace(".xodr", "_road_link_repaired.xodr")
            repair_log_jsonl = os.path.join(self.out_dir, "road_link_repair_log.jsonl")
            repair_summary_path = os.path.join(
                self.out_dir, "road_link_repair_summary.json"
            )
            repair_summary = repair_road_link_targets(
                xodr_path=tiling_input,
                output_path=repaired_out,
                repair_log_jsonl=repair_log_jsonl,
                bad_dxy_threshold_m=float(
                    os.getenv("UP_ROAD_LINK_REPAIR_BAD_DXY_M", "50") or "50"
                ),
                search_radius_start_m=float(
                    os.getenv("UP_ROAD_LINK_REPAIR_RADIUS_START_M", "10") or "10"
                ),
                search_radius_cap_m=float(
                    os.getenv("UP_ROAD_LINK_REPAIR_RADIUS_CAP_M", "30") or "30"
                ),
                search_radius_step_m=float(
                    os.getenv("UP_ROAD_LINK_REPAIR_RADIUS_STEP_M", "10") or "10"
                ),
            )
            with open(repair_summary_path, "w", encoding="utf-8") as f:
                json.dump(
                    repair_summary,
                    f,
                    indent=2,
                    ensure_ascii=True,
                    sort_keys=True,
                )
            tiling_input = str(repair_summary.get("output_path") or repaired_out)
            print(
                "[STEP 9] road link target repair "
                f"(applied={bool(repair_summary.get('applied', False))}, "
                f"num_repaired={int(repair_summary.get('num_repaired', 0) or 0)}) -> "
                f"{tiling_input}"
            )
        except Exception as e:
            print(f"[STEP 9] Road link target repair failed (continuing): {e}")

    graph_path: Optional[str] = None
    if True:  # Tiling enabled (checked above)
        tiles_dir = os.path.join(self.out_dir, "tiles")
        ensure_dir(tiles_dir)

        tiles, tile_health = TileExtractor.tile(
            tiling_input,
            tiles_dir,
            tile_size=s.TILE_SIZE,
            strict_semantics=getattr(self.settings, "STRICT_TILE_SEMANTICS", False),
        )
        # --- Post-tiling CARLA S-invariants gate (tiles) -------------------------
        # CARLA can crash or timeout if any tile contains negative s / sOffset
        # (e.g., <laneSection s="-...">). This scan is offline + deterministic.
        if getattr(self.settings, "ENABLE_LANESECTION_FIX", True):
            from glob import glob
            import shutil
            import csv
            from ultimate_pipeline.core.s_invariants import (
                scan_s_invariants,
                fix_s_invariants,
            )

            tile_paths = sorted(glob(os.path.join(tiles_dir, "tile_*.xodr")))
            backup_dir = os.path.join(
                self.out_dir, "tiles_backup_before_s_invariant_fix"
            )
            report_csv = os.path.join(self.out_dir, "xodr_negative_s_report.csv")

            fixed_n = 0
            rows = []

            for p in tile_paths:
                rep_before = scan_s_invariants(p)
                neg_before = int(rep_before.negative_s_count)
                mono_before = len(rep_before.monotonic_issues)

                neg_after = neg_before
                mono_after = mono_before
                did_fix = False

                # Only repair when needed (negative s / sOffset). Monotonic issues are reported.
                if neg_before > 0:
                    os.makedirs(backup_dir, exist_ok=True)
                    shutil.copy2(p, os.path.join(backup_dir, os.path.basename(p)))

                    tmp = p + ".tmp.sfixed"
                    fix_s_invariants(p, tmp)  # writes fixed file
                    shutil.move(tmp, p)  # replace tile in-place

                    did_fix = True
                    fixed_n += 1

                    rep_after = scan_s_invariants(p)
                    neg_after = int(rep_after.negative_s_count)
                    mono_after = len(rep_after.monotonic_issues)

                ex = ""
                if rep_before.negative_s_examples:
                    # keep it short; thesis logs should be readable
                    ex = str(rep_before.negative_s_examples[:2])

                rows.append(
                    {
                        "tile": os.path.basename(p),
                        "fixed_in_place": int(did_fix),
                        "negative_s_before": neg_before,
                        "negative_s_after": neg_after,
                        "monotonic_issues_before": mono_before,
                        "monotonic_issues_after": mono_after,
                        "examples": ex,
                    }
                )

            with open(report_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=[
                        "tile",
                        "fixed_in_place",
                        "negative_s_before",
                        "negative_s_after",
                        "monotonic_issues_before",
                        "monotonic_issues_after",
                        "examples",
                    ],
                )
                w.writeheader()
                w.writerows(rows)

            print(
                f"[INFO] Tile S-invariants: fixed {fixed_n}/{len(tile_paths)} tiles → {report_csv}"
            )
            if fixed_n > 0:
                print(f"📂 Backup of original tiles → {backup_dir}")
        # ------------------------------------------------------------------------

        from ultimate_pipeline.tiling.tile_metadata import TileMetadata

        metadata_path = os.path.join(self.out_dir, "tile_metadata.json")
        manifest_path = os.path.join(self.out_dir, "tile_manifest.json")

    # --- Windows crash-safety: run tile QA as subprocess batch (no libcarla in main process) ---
    # NOTE: tile_qa_batch.py exposes a CLI (main), not a Python function that accepts keywords.
    # So we run it via `python -m ...` and pass CLI args (NO `final_out=`).

    # (1) Always generate metadata first (tile_qa_batch reads it)
    TileMetadata.generate_metadata(
        tiles_dir=tiles_dir,
        output_json=metadata_path,
    )
    georef = {}
    try:
        georef = _read_georef_info(tiling_input)
    except Exception:
        georef = {}
    proj4_norm = str((georef or {}).get("norm") or "")
    proj4_params_complete = (georef or {}).get("params_complete")
    if not isinstance(proj4_params_complete, bool):
        proj4_params_complete = None
    TileMetadata.write_manifest(
        tiles_dir=tiles_dir,
        metadata_path=metadata_path,
        output_json=manifest_path,
        proj4_norm=proj4_norm,
        proj4_params_complete=proj4_params_complete,
        tile_size_m=float(getattr(s, "TILE_SIZE", 500.0)),
        buffer_m=float(getattr(s, "TILE_BUFFER_M", 50.0)),
        frame_method="native",
        transform=None,
    )

    # 🎯 Invariant: every produced tile MUST have metadata
    assert set(tile_health.keys()) == {
        os.path.splitext(os.path.basename(p))[0] for p in tiles
    }, "Tile/metadata mismatch — tiler and metadata out of sync"

    print(f"[INFO] Tile metadata written → {metadata_path}")
    print(f"[INFO] Tile manifest written -> {manifest_path}")
    print(f"Created {len(tiles)} tiles.")

    # (2) Build adjacency + scenarios (unchanged)
    from glob import glob

    tile_paths = sorted(glob(os.path.join(tiles_dir, "tile_*.xodr")))

    def _aggregate_tile_reports(check_fn):
        reports = []
        failed = []
        for p in tile_paths:
            rep = check_fn(p)
            reports.append({"tile": os.path.basename(p), "report": rep})
            if isinstance(rep, dict) and not rep.get("ok", True):
                failed.append(os.path.basename(p))
        return {
            "ok": len(failed) == 0,
            "total_tiles": len(tile_paths),
            "failed_tiles": failed,
            "tile_reports": reports,
        }

    if os.getenv("UP_ENABLE_PLANVIEW_SEAM_GATE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        from ultimate_pipeline.quality.check_geometric_continuity import (
            auto_repair_tiny_planview_seams_in_file,
            check_planview_internal_seams,
        )

        seam_eps = float(os.getenv("UP_PLANVIEW_SEAM_EPS_M", "0.2"))
        seam_tiles_report = self._stage_gate(
            "09_tiling",
            "planview_internal_seams_tiles",
            lambda: _aggregate_tile_reports(
                lambda p: check_planview_internal_seams(p, eps_xy=seam_eps)
            ),
        )
        strict_quality = os.getenv(
            "UP_STRICT_QUALITY_GATES", "0"
        ).strip().lower() in ("1", "true", "yes", "on")
        auto_repair_enabled = str(
            os.getenv(
                "UP_ENABLE_PLANVIEW_SEAM_AUTO_REPAIR",
                "1"
                if bool(
                    getattr(self.settings, "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR", True)
                )
                else "0",
            )
        ).strip().lower() in ("1", "true", "yes", "on")
        auto_repair_max = _resolve_planview_auto_repair_max_m(self.settings)
        if (
            (not strict_quality)
            and auto_repair_enabled
            and isinstance(seam_tiles_report, dict)
            and not seam_tiles_report.get("ok", True)
        ):
            failed_tiles = set(seam_tiles_report.get("failed_tiles", []) or [])
            auto_repairs = []
            for tile_path in tile_paths:
                tile_name = os.path.basename(tile_path)
                if tile_name not in failed_tiles:
                    continue
                repair = auto_repair_tiny_planview_seams_in_file(
                    tile_path,
                    eps_xy=seam_eps,
                    max_repair_seam_m=auto_repair_max,
                )
                auto_repairs.append({"tile": tile_name, "repair": repair})
            if auto_repairs:
                seam_tiles_report = _aggregate_tile_reports(
                    lambda p: check_planview_internal_seams(p, eps_xy=seam_eps)
                )
                seam_tiles_report["auto_repair"] = {
                    "attempted_tiles": len(auto_repairs),
                    "repairs": auto_repairs,
                }
            try:
                tiles_repair_path = os.path.join(
                    self.out_dir, "planview_internal_seams_tiles_autorepair.json"
                )
                with open(tiles_repair_path, "w", encoding="utf-8") as f:
                    json.dump(
                        auto_repairs,
                        f,
                        indent=2,
                        default=str,
                        ensure_ascii=True,
                        sort_keys=True,
                    )
            except Exception as e:
                print(
                    f"[STEP 9] planView seam tile auto-repair report write skipped: {e}"
                )
        try:
            seam_tiles_path = os.path.join(
                self.out_dir, "planview_internal_seams_tiles.json"
            )
            with open(seam_tiles_path, "w", encoding="utf-8") as f:
                json.dump(
                    seam_tiles_report,
                    f,
                    indent=2,
                    default=str,
                    ensure_ascii=True,
                    sort_keys=True,
                )
        except Exception as e:
            print(f"[STEP 9] planView seam tile report write skipped: {e}")

    if os.getenv("UP_ENABLE_GEOMETRIC_CONTINUITY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        from ultimate_pipeline.quality.check_geometric_continuity import (
            check_geometric_continuity,
        )

        self._stage_gate(
            "09_tiling",
            "geometric_continuity_tiles",
            lambda: _aggregate_tile_reports(check_geometric_continuity),
        )

    if os.getenv("UP_ENABLE_POST_TILING_INTEGRITY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        from ultimate_pipeline.quality.check_post_tiling_integrity import (
            check_post_tiling_integrity,
        )

        self._stage_gate(
            "09_tiling",
            "post_tiling_integrity",
            lambda: _aggregate_tile_reports(check_post_tiling_integrity),
        )

    if os.getenv("UP_ENABLE_LANE_WIDTH_CONTINUITY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        from ultimate_pipeline.quality.check_lane_width_continuity import (
            check_lane_width_continuity,
        )

        self._stage_gate(
            "09_tiling",
            "lane_width_continuity",
            lambda: _aggregate_tile_reports(check_lane_width_continuity),
        )

    graph = TileAdjacency.build_graph(tile_paths)

    adj_name = getattr(self.settings, "TILE_ADJ_JSON", "tile_adjacency.json")
    graph_path = os.path.join(self.out_dir, adj_name)
    TileAdjacency.save_graph(graph, graph_path)
    print(f"🕸️ Tile adjacency graph saved → {graph_path}")

    scenario_dir = os.path.join(self.out_dir, "scenarios")
    scenario_paths = AutoScenarioGenerator.generate_from_graph(
        adjacency_graph=graph,
        num_scenarios=int(getattr(self.settings, "AUTO_SCENARIO_COUNT", 50)),
        out_dir=scenario_dir,
        scenario_prefix="ingolstadt_auto",
    )
    print(f"🎯 Generated {len(scenario_paths)} auto-scenarios → {scenario_dir}")

    # (3) Subprocess tile QA batch runner (fixed: no import/run_tile_qa_batch(), no final_out kwarg)
    if os.getenv("UP_SKIP_TILE_QA", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
    ):
        qa_out_dir = os.path.join(self.out_dir, "tile_qa_subprocess")
        os.makedirs(qa_out_dir, exist_ok=True)
        status_path = os.path.join(self.out_dir, "tile_qa_status.json")
        status = {
            "status": "SKIP",
            "failure_reason": "tile_qa_skipped_by_env",
            "out_dir": qa_out_dir,
        }
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, ensure_ascii=True)
        try:
            self.vreport.add_dict("tile_qa_status", status)
        except Exception:
            pass
        print("⏭️ Tile QA skipped due to UP_SKIP_TILE_QA.")
        return graph_path
    if (
        getattr(self.settings, "TILE_QA_RUN_SUBPROCESS_BATCH", True)
        and str(getattr(self.settings, "TILE_QA_ISOLATION_MODE", "")).lower()
        == "subprocess"
    ):
        print(
            "[INFO] Tile QA isolation enabled → running subprocess batch runner (tile workers are separate processes)."
        )
        import subprocess
        import sys

        qa_out_dir = os.path.join(self.out_dir, "tile_qa_subprocess")
        os.makedirs(qa_out_dir, exist_ok=True)
        qa_log = os.path.join(qa_out_dir, "tile_qa_batch.log")

        cmd = [
            sys.executable,
            "-m",
            "ultimate_pipeline.tools.tile_qa_batch",
            "--tile_metadata",
            metadata_path,
            "--tiles_dir",
            tiles_dir,
            "--out_dir",
            qa_out_dir,
            "--timeout_s",
            str(getattr(self.settings, "TILE_QA_TIMEOUT_S", 300.0)),
            "--retries",
            str(getattr(self.settings, "TILE_QA_RETRIES", 2)),
            "--max_tile_attempts",
            str(getattr(self.settings, "TILE_QA_MAX_TILE_ATTEMPTS", 2)),
            "--restart_every_n",
            str(getattr(self.settings, "TILE_QA_RESTART_EVERY_N", 10)),
        ]

        # Optional flags supported by tile_qa_batch.py
        if getattr(self.settings, "TILE_QA_FIX_S_IN_WORKER", False):
            cmd.append("--fix_s")
        if getattr(self.settings, "TILE_QA_NO_SPAWN", False):
            cmd.append("--no_spawn")

        with open(qa_log, "w", encoding="utf-8") as f:
            rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT).returncode

        print(f"[INFO] Tile QA batch runner finished (rc={rc}) → {qa_out_dir}")
        if rc != 0:
            if os.getenv("UP_ALLOW_TILE_QA_FAIL", "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            ):
                status_path = os.path.join(self.out_dir, "tile_qa_status.json")
                status = {
                    "status": "FAIL",
                    "failure_reason": "tile_qa_failed_but_allowed",
                    "ok": True,
                    "allowed_failure": True,
                    "return_code": rc,
                    "log_path": qa_log,
                    "out_dir": qa_out_dir,
                }
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump(status, f, indent=2, ensure_ascii=True)
                try:
                    self.vreport.add_dict("tile_qa_status", status)
                except Exception:
                    pass
                print(
                    "⏭️ Tile QA failed but UP_ALLOW_TILE_QA_FAIL is set; continuing."
                )
            else:
                raise RuntimeError(
                    f"❌ Tile QA batch runner failed (rc={rc}). See log: {qa_log}"
                )

    # IMPORTANT: keep returning graph_path so the caller doesn't break
    return graph_path

# ---------------- 10) 🧪 TILE QA SUITE ----------------
