# REFAC_VERSION = "v5_preserve"
# NOTE: This file is auto-extracted from ultimate_pipeline/main_pipeline.py.
# It delegates to original helpers by injecting main_pipeline globals at runtime.

from __future__ import annotations

import os
import hashlib


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


def _resolve_preferred_dem_path(settings, dem_path: str | None) -> tuple[str | None, bool]:
    import os

    expanded_path = str(
        getattr(settings, "DEM_EXPANDED_TIF_PATH", "")
        or os.getenv("UP_DEM_EXPANDED_TIF_PATH", "")
        or ""
    ).strip()
    if expanded_path and os.path.isfile(expanded_path):
        return expanded_path, True
    return dem_path, False


def _step5_geometry_elevation_continuity(self, topo_fixed: str) -> str:
    """
    📐 GEOMETRY AUTHORITY (merged STEP 5 + STEP 6, hardened order)

    1) Step 6 establishes horizontal (planView) geometry first
    2) Freeze XY geometry before any elevation pass
    3) Step 5 applies DEM elevation on frozen XY (no horizontal drift)
    """
    _inject_main_pipeline_globals()
    s = self.settings

    elev_out = s.stage_path("04_elevation")
    geo_out = s.stage_path("05_planview")
    cont_out = s.stage_path("06_continuity")

    # STEP 6 FIRST: 📐 planView smoothing + continuity + micro-prune
    # Establish horizontal geometry BEFORE elevation is sampled.
    cont_out = self._step6_planview_continuity(topo_fixed, geo_out, cont_out)

    # Stage 6 may move through-road endpoints after topology has fixed
    # junction connector positions. Rebuild displaced connectors before freeze.
    # Structural/release runs must not mutate connectors unless explicitly opted in.
    connector_rebuild_enabled = os.getenv(
        "UP_ENABLE_JUNCTION_CONNECTOR_REBUILD", "0"
    ).strip().lower() in ("1", "true", "yes", "on")
    if connector_rebuild_enabled:
        try:
            from ultimate_pipeline.topology.junction_connector_rebuild import (
                rebuild_displaced_junction_connectors_in_file,
            )
            from ultimate_pipeline.contracts.release_profile import (
                straight_chord_connector_fallback_enabled,
            )

            connector_rebuild_report_path = os.path.join(
                self.out_dir, "junction_connector_rebuild_report.json"
            )
            connector_risk_path = os.path.join(
                self.out_dir, "junction_connector_risk.json"
            )
            connector_rebuild_report = rebuild_displaced_junction_connectors_in_file(
                cont_out,
                cont_out,
                report_path=connector_rebuild_report_path,
                risk_report_path=connector_risk_path,
                start_gap_threshold_m=float(
                    os.getenv("UP_JUNCTION_CONNECTOR_REBUILD_START_GAP_M", "2.0")
                ),
                max_after_gap_m=float(
                    os.getenv("UP_JUNCTION_CONNECTOR_REBUILD_MAX_AFTER_GAP_M", "0.5")
                ),
                max_abs_curvature=float(
                    os.getenv("UP_JUNCTION_CONNECTOR_REBUILD_MAX_ABS_CURV", "1.0")
                ),
                allow_straight_chord_fallback=straight_chord_connector_fallback_enabled(
                    self.settings
                ),
            )
            self.vreport.add_dict(
                "junction_connector_rebuild", connector_rebuild_report
            )
            print(
                "[STEP 6] Junction connector rebuild: "
                f"attempted={connector_rebuild_report.get('attempted', 0)} "
                f"rebuilt={connector_rebuild_report.get('rebuilt', 0)} "
                f"reverted={connector_rebuild_report.get('reverted', 0)} "
                f"start_gap_after={connector_rebuild_report.get('start_gap_over_threshold_after', 0)} "
                f"-> {connector_rebuild_report_path}"
            )
            strict_quality = os.getenv(
                "UP_STRICT_QUALITY_GATES", "0"
            ).strip().lower() in ("1", "true", "yes", "on")
            if strict_quality and not bool(connector_rebuild_report.get("ok", False)):
                raise RuntimeError(
                    "Junction connector rebuild failed in strict mode; "
                    f"see {connector_rebuild_report_path}"
                )
        except Exception as e:
            print(f"[STEP 6] Junction connector rebuild failed (continuing): {e}")
            if os.getenv("UP_STRICT_QUALITY_GATES", "0").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            ):
                raise
    else:
        print("[STEP 6] Junction connector rebuild disabled.")

    # 🧊 Freeze horizontal geometry BEFORE elevation is applied.
    # This ensures DEM samples z at the final XY positions.
    frozen_before_elev = s.stage_path("06_geometry_frozen")
    tree, root = load_xodr(cont_out)

    header = root.find("header")
    if header is None:
        header = ET.SubElement(root, "header")

    header.set("geometryFrozen", "true")

    # Hash the *frozen output file's own* serialized bytes (with
    # geometryFrozen set but before geometryFreezeHash exists), not
    # cont_out's bytes -- _verify_geometry_freeze_hash later re-hashes
    # frozen_before_elev itself, so the embedded hash must be reproducible
    # from that file's own content, not a different (pre-freeze) file's.
    save_xodr(tree, frozen_before_elev)
    freeze_hash = hashlib.sha256()
    with open(frozen_before_elev, "rb") as f:
        freeze_hash.update(f.read())
    freeze_hex = freeze_hash.hexdigest()
    header.set("geometryFreezeHash", freeze_hex)

    save_xodr(tree, frozen_before_elev)
    print(f"🧊 Horizontal geometry frozen before elevation → {frozen_before_elev}")
    print(f"🔒 Freeze hash: {freeze_hex}")

    freeze_report_path = os.path.join(self.out_dir, "geometry_freeze_hash.json")
    try:
        import json
        with open(freeze_report_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "freeze_hash": freeze_hex,
                    "frozen_xodr": frozen_before_elev,
                    "source_xodr": cont_out,
                },
                f,
                indent=2,
            )
        print(f"[FREEZE] geometry_freeze_hash.json -> {freeze_report_path}")
    except Exception as e:
        print(f"[FREEZE] geometry_freeze_hash.json write skipped: {e}")

    # Verify determinism
    self._verify_continuity_stability(frozen_before_elev)

    # STEP 5: 🏔️ DEM elevation + smoothing + geometry validator
    # Applied on frozen XY — elevation is vertical-only and does not drift horizontally.
    elev_out = self._step5_dem_and_geometry(frozen_before_elev, elev_out)

    return elev_out


# ---------------- 5) 🏔️ DEM + GEOMETRY ----------------


def _step5_dem_and_geometry(self, topo_fixed: str, elev_out: str) -> str:
    _inject_main_pipeline_globals()
    s = self.settings
    print("\n============== 🏔️ STEP 5: Elevation Smoothing ==============")

    if os.path.isfile(topo_fixed):
        self._verify_geometry_freeze_hash(topo_fixed)

    gps = s.GPS_BOUNDS
    # Pre-compute thesis strict mode for early fail-closed enforcement
    _thesis_strict_early = bool(getattr(s, "THESIS_STRICT", False)) or (
        os.getenv("UP_THESIS_STRICT", "").strip().lower() in ("1", "true", "yes", "on")
    )
    _strict_dem_early = bool(getattr(s, "DEM_STRICT_MODE", True))

    configured_expanded_dem = str(getattr(s, "DEM_EXPANDED_TIF_PATH", "") or "").strip()
    dem_path = None
    dem_expanded_used = False
    preferred_dem_path, preferred_dem_is_expanded = _resolve_preferred_dem_path(s, None)
    if preferred_dem_path:
        dem_path = preferred_dem_path
        dem_expanded_used = preferred_dem_is_expanded
        print(f"[DEM] Using expanded DEM for full coverage: {preferred_dem_path}")
    else:
        if configured_expanded_dem:
            print(
                f"[DEM] Expanded DEM not found at {configured_expanded_dem}, "
                "falling back to original DEM coverage path."
            )

        # DEM auto-download
        if s.ENABLE_DEM_AUTO_DOWNLOAD:
            try:
                dem_path = ensure_dem_exists(
                    gps_bounds=gps,
                    dem_path=s.DEM_TIF,
                    dem_type=s.DEM_PROVIDER,
                    api_key=s.OPENTOPO_API_KEY,
                )
            except Exception as e:
                # Fail closed in thesis-strict or DEM-strict mode
                if _thesis_strict_early or _strict_dem_early:
                    raise RuntimeError(
                        f"DEM auto-download failed in strict mode (THESIS_STRICT={_thesis_strict_early}, "
                        f"DEM_STRICT_MODE={_strict_dem_early}): {e}"
                    ) from e
                print(f"⚠️ DEM auto-download failed: {e}")
                print("   → Continuing with flat elevation.")
                dem_path = None
        else:
            print("⚠️ DEM auto-download disabled. Using existing DEM only.")
            dem_path = s.DEM_TIF if os.path.exists(s.DEM_TIF) else None
            # Fail closed if DEM doesn't exist in thesis-strict or DEM-strict mode
            if dem_path is None and (_thesis_strict_early or _strict_dem_early):
                raise RuntimeError(
                    f"DEM not found at {s.DEM_TIF} and auto-download disabled. "
                    f"Cannot proceed in strict mode (THESIS_STRICT={_thesis_strict_early}, "
                    f"DEM_STRICT_MODE={_strict_dem_early})."
                )
        dem_path, dem_expanded_used = _resolve_preferred_dem_path(s, dem_path)

    # diagnostics AFTER download
    if dem_path and os.path.exists(dem_path):
        dem_info = DEMDiagnostics.summarize(dem_path)
        self.vreport.add_dict("dem_diagnostics", dem_info)
        if not dem_info.get("exists", False):
            # Fail closed if DEM invalid in thesis-strict or DEM-strict mode
            if _thesis_strict_early or _strict_dem_early:
                raise RuntimeError(
                    f"DEM exists at {dem_path} but appears invalid. Cannot proceed in strict mode "
                    f"(THESIS_STRICT={_thesis_strict_early}, DEM_STRICT_MODE={_strict_dem_early}). "
                    f"DEM diagnostics: {dem_info}"
                )
            print("⚠️ DEM exists but appears invalid → flat elevation fallback.")
            use_dem = False
            self.vreport.add_dict("elevation_stats", {"DEM_disabled": True})
        else:
            print("🏔️ DEM summary:")
            print(f"   CRS:    {dem_info['crs']}")
            print(f"   Bounds: {dem_info['bounds']}")
            use_dem = True
    else:
        # Fail closed if no DEM in thesis-strict or DEM-strict mode
        if _thesis_strict_early or _strict_dem_early:
            raise RuntimeError(
                f"No DEM file available at {dem_path}. Cannot proceed in strict mode "
                f"(THESIS_STRICT={_thesis_strict_early}, DEM_STRICT_MODE={_strict_dem_early}). "
                "Provide a valid DEM or set DEM_STRICT_MODE=False for flat elevation fallback."
            )
        print("⚠️ No DEM file available → using flat elevation (0.0 m).")
        dem_info = {"exists": False}
        self.vreport.add_dict("dem_diagnostics", dem_info)
        use_dem = False
        self.vreport.add_dict("elevation_stats", {"DEM_disabled": True})

    tree, root = load_xodr(topo_fixed)
    strict_dem = bool(getattr(s, "DEM_STRICT_MODE", True))
    allow_flat_fallback = not bool(getattr(s, "FAIL_ON_FLAT_ELEVATION", True))
    strict_quality = os.getenv("UP_STRICT_QUALITY_GATES", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    dem_qc_report_path = os.path.join(self.out_dir, "elevation_dem_qc.json")

    def _flat_sampler_or_raise(reason: str, exc: Exception | None = None):
        if allow_flat_fallback:
            print(f"⚠️ {reason}")
            print("   → Falling back to flat elevation (0.0 m).")
            flat_sampler = lambda x, y: 0.0
            try:
                setattr(flat_sampler, "_dem_fallback_active", True)
            except Exception:
                pass
            return flat_sampler
        msg = (
            f"❌ {reason}. Flat elevation fallback is disabled "
            "(FAIL_ON_FLAT_ELEVATION=True)."
        )
        if exc is None:
            raise RuntimeError(msg)
        raise RuntimeError(msg) from exc

    # Elevation sampler
    if use_dem:
        try:
            sampler = ElevationImporter.make_raster_sampler(
                dem_path,
                xodr_path=topo_fixed,  # For CRS/UTM zone detection
            )
            print(f"[DEM] Sampler active: {dem_path}")
        except Exception as e:
            if strict_dem:
                raise RuntimeError(
                    f"❌ Failed to load DEM sampler in strict mode: {e}"
                ) from e
            sampler = _flat_sampler_or_raise(f"Failed to load DEM sampler → {e}", e)
    else:
        sampler = _flat_sampler_or_raise("No valid DEM available for elevation import")

    dem_raster_stats = {
        "dem_raster_min": None,
        "dem_raster_max": None,
        "dem_raster_range": None,
        "dem_raster_count": 0,
    }
    if use_dem and dem_path and os.path.exists(dem_path):
        try:
            dem_raster_stats = summarize_dem_raster_stats(dem_path)
        except Exception as e:
            print(f"⚠️ DEM raster stats unavailable: {e}")

    # DEM full coverage (thesis-citable) — run BEFORE applying DEM to the map
    if use_dem and dem_path and os.path.exists(dem_path):
        try:
            from ultimate_pipeline.quality.check_dem_full_coverage import (
                check_dem_full_coverage,
            )

            full_cov_threshold = float(getattr(s, "DEM_FULL_COVERAGE_THRESHOLD", 0.6))
            step_m = float(getattr(s, "DEM_FULL_COVERAGE_STEP_M", 2.0))
            max_samples = int(getattr(s, "DEM_FULL_COVERAGE_MAX_SAMPLES", 250000))
            full_cov_out = os.path.join(self.out_dir, "dem_full_coverage.json")

            # Best-effort: pass proj4 from geoReference if present (helps CRS transforms)
            geo_ref = None
            try:
                geo_el = root.find(".//geoReference")
                if geo_el is not None and (geo_el.text or "").strip():
                    geo_ref = geo_el.text.strip()
            except Exception:
                geo_ref = None

            full_cov = check_dem_full_coverage(
                xodr_path=topo_fixed,
                dem_tif_path=dem_path,
                out_json=full_cov_out,
                step_m=step_m,
                max_samples=max_samples,
                xodr_crs_proj4=geo_ref,
                threshold=full_cov_threshold,
                sampler=sampler,
            )

            # Back-compat / runbook: some workflows expect this filename.
            try:
                import shutil

                qc_out = os.path.join(self.out_dir, "elevation_dem_qc.json")
                if qc_out != full_cov_out:
                    shutil.copyfile(full_cov_out, qc_out)
            except Exception:
                pass

            # AUTO-EXPAND DEM if coverage insufficient and flag is set
            auto_expand_dem = os.getenv("UP_AUTO_EXPAND_DEM", "").strip().lower() in (
                "1", "true", "yes", "on"
            )
            projected_bbox = full_cov.get("projected_bbox_wgs84")
            dem_bounds = full_cov.get("dem_bounds_wgs84")

            # Check if DEM fully covers map bbox
            dem_covers_map = True
            if projected_bbox and dem_bounds:
                dem_covers_map = (
                    dem_bounds.get("minx", float("inf")) <= projected_bbox.get("minx", 0) and
                    dem_bounds.get("miny", float("inf")) <= projected_bbox.get("miny", 0) and
                    dem_bounds.get("maxx", float("-inf")) >= projected_bbox.get("maxx", 0) and
                    dem_bounds.get("maxy", float("-inf")) >= projected_bbox.get("maxy", 0)
                )

            if not dem_covers_map and auto_expand_dem and projected_bbox:
                print("🔄 DEM does not cover full map bbox. Attempting auto-expand...")
                try:
                    from ultimate_pipeline.dem.dem_auto_downloader import ensure_dem_covers_bbox

                    # Dynamic margin: max(0.01, 0.05 * bbox_span) to avoid edge misses on large bboxes
                    bbox_span = max(
                        projected_bbox.get("maxx", 0) - projected_bbox.get("minx", 0),
                        projected_bbox.get("maxy", 0) - projected_bbox.get("miny", 0),
                    )
                    default_margin = max(0.01, 0.05 * bbox_span)
                    margin_deg = float(os.getenv("UP_DEM_EXPAND_MARGIN_DEG", str(default_margin)))
                    expanded_dem_dir = os.getenv("UP_DEM_EXPANDED_DIR", "") or os.path.join(
                        os.path.dirname(dem_path), "expanded"
                    )

                    # Prefer explicit env var for OpenTopography key; fall back to settings.
                    api_key = (
                        os.getenv("OPENTOPO_API_KEY")
                        or os.getenv("UP_OPENTOPO_API_KEY")
                        or getattr(s, "OPENTOPO_API_KEY", "")
                    )

                    expanded_dem_path = ensure_dem_covers_bbox(
                        projected_bbox_wgs84=projected_bbox,
                        dem_path=dem_path,
                        dem_type=s.DEM_PROVIDER,
                        api_key=api_key,
                        margin_deg=margin_deg,
                        expanded_dem_dir=expanded_dem_dir,
                    )

                    if expanded_dem_path and os.path.exists(expanded_dem_path):
                        print(f"   ✅ Expanded DEM ready: {expanded_dem_path}")
                        dem_path = expanded_dem_path
                        dem_expanded_used = True

                        # Re-create sampler with expanded DEM
                        sampler = ElevationImporter.make_raster_sampler(
                            dem_path,
                            xodr_path=topo_fixed,
                        )
                        print(f"[DEM] Sampler updated to use expanded DEM")

                        # Re-run coverage check
                        full_cov = check_dem_full_coverage(
                            xodr_path=topo_fixed,
                            dem_tif_path=dem_path,
                            out_json=full_cov_out,
                            step_m=step_m,
                            max_samples=max_samples,
                            xodr_crs_proj4=geo_ref,
                            threshold=full_cov_threshold,
                            sampler=sampler,
                        )
                        # Update qc copy
                        try:
                            if qc_out != full_cov_out:
                                shutil.copyfile(full_cov_out, qc_out)
                        except Exception:
                            pass

                except Exception as expand_e:
                    print(f"   ⚠️ DEM auto-expand failed: {expand_e}")
                    thesis_strict = bool(getattr(s, "THESIS_STRICT", False)) or (
                        os.getenv("UP_THESIS_STRICT", "").strip().lower() in ("1", "true", "yes", "on")
                    )
                    if thesis_strict:
                        raise RuntimeError(
                            "THESIS_STRICT with UP_AUTO_EXPAND_DEM=1 requires successful DEM download. "
                            f"Auto-expand failed: {expand_e} (check OPENTOPO_API_KEY)."
                        )

            # Record + gate
            self._stage_gate("05_elevation", "dem_full_coverage", lambda: full_cov)

            if not bool(full_cov.get("ok", True)):
                strict_cov = bool(getattr(s, "DEM_FULL_COVERAGE_STRICT", True))
                if strict_cov or strict_dem:
                    raise RuntimeError(
                        f"DEM full coverage gate failed: ratio={full_cov.get('coverage_ratio')} threshold={full_cov_threshold}"
                    )

                print("⚠️ DEM full coverage below threshold → skipping DEM application")
                use_dem = False
                self.vreport.add_dict("elevation_stats", {"DEM_disabled": True})
                sampler = _flat_sampler_or_raise(
                    f"DEM full coverage below threshold (ratio={full_cov.get('coverage_ratio')}, threshold={full_cov_threshold})"
                )

        except Exception as e:
            strict_cov = bool(getattr(s, "DEM_FULL_COVERAGE_STRICT", True))
            if strict_cov or strict_dem:
                raise
            print(
                f"⚠️ DEM full coverage check failed; continuing without DEM. Reason: {e}"
            )
            use_dem = False
            self.vreport.add_dict("elevation_stats", {"DEM_disabled": True})
            sampler = _flat_sampler_or_raise(f"DEM full coverage check failed: {e}", e)

    # Apply DEM elevation
    dem_apply_stats = {
        "sampled_points": 0,
        "nodata_points": 0,
        "sample_values": [],
        "sampled_road_ids": [],
        "nodata_road_ids": [],
        "applied_road_ids": [],
        "fallback_road_ids": [],
    }
    try:
        collected = ElevationImporter.apply_dem(root, sampler, collect_qc=True)
        if isinstance(collected, dict):
            dem_apply_stats = collected
        print("✅ DEM elevation applied to map.")
    except Exception as e:
        # In thesis strict, fail immediately instead of continuing with a flat map
        # (which then triggers confusing downstream suspicious_flat_sampling errors).
        thesis_strict = bool(getattr(s, "THESIS_STRICT", False)) or (
            os.getenv("UP_THESIS_STRICT", "").strip().lower() in ("1", "true", "yes", "on")
        )
        if thesis_strict:
            raise
        print(f"⚠️ DEM application failed: {e}")
        print("   → Map will remain flat for this stage.")

    nodata_ratio_fail_threshold = float(
        getattr(s, "DEM_NODATA_RATIO_FAIL_THRESHOLD", 0.2)
    )
    suspicious_raster_range_threshold = float(
        getattr(s, "DEM_SUSPICIOUS_RASTER_RANGE_THRESHOLD", 0.5)
    )
    flat_sample_range_threshold = float(
        getattr(s, "DEM_FLAT_SAMPLE_RANGE_THRESHOLD", 0.05)
    )
    auto_reproject_enabled = str(
        os.getenv(
            "UP_AUTO_REPROJECT_DEM_ON_QC_FAIL",
            "1" if bool(getattr(s, "AUTO_REPROJECT_DEM_ON_QC_FAIL", False)) else "0",
        )
    ).strip().lower() in ("1", "true", "yes", "on")

    def _augment_dem_qc_report(report: dict, sampler_obj, dem_path_value: str) -> None:
        sampling_error_counts = getattr(sampler_obj, "_sampling_error_counts", {}) or {}
        sampled_points_current = int(report.get("sampled_points", 0) or 0)

        def _ratio(key: str) -> float:
            try:
                count = int(sampling_error_counts.get(key, 0) or 0)
            except Exception:
                count = 0
            if sampled_points_current <= 0:
                return 0.0
            return float(count / sampled_points_current)

        report.update(
            {
                "dem_path": str(dem_path_value) if dem_path_value else "",
                "dem_path_used": str(dem_path_value) if dem_path_value else "",
                "dem_expanded_used": bool(report.get("dem_expanded_used", False)),
                "strict_dem": bool(strict_dem),
                "strict_quality_gates": bool(strict_quality),
                "map_crs": str(getattr(sampler_obj, "_map_crs", "")),
                "map_crs_source": str(getattr(sampler_obj, "_map_crs_source", "")),
                "dem_crs": str(getattr(sampler_obj, "_dem_crs", "")),
                "crs_transform_applied": bool(
                    getattr(sampler_obj, "_crs_transform_applied", False)
                ),
                "crs_mismatch_detected": bool(
                    getattr(sampler_obj, "_crs_mismatch_detected", False)
                ),
                "auto_reproject_enabled": bool(auto_reproject_enabled),
                "auto_reproject_attempted": bool(
                    report.get("auto_reproject_attempted", False)
                ),
                "auto_reproject_succeeded": bool(
                    report.get("auto_reproject_succeeded", False)
                ),
                "header_offset": getattr(sampler_obj, "_header_offset", None),
                "header_offset_original": getattr(
                    sampler_obj, "_header_offset_original", None
                ),
                "effective_offset_used": getattr(
                    sampler_obj, "_effective_offset_used", None
                ),
                "header_offset_error_m": getattr(
                    sampler_obj, "_header_offset_error_m", None
                ),
                "header_offset_policy": str(
                    getattr(sampler_obj, "_header_offset_policy", "")
                ),
                "header_offset_source": str(
                    getattr(sampler_obj, "_header_offset_source", "")
                ),
                "local_raw_bbox": getattr(sampler_obj, "_local_raw_bbox", None),
                "projected_bbox_utm": getattr(
                    sampler_obj, "_projected_bbox_utm", None
                ),
                "projected_bbox_wgs84": getattr(
                    sampler_obj, "_projected_bbox_wgs84", None
                ),
                "dem_bounds_wgs84": getattr(sampler_obj, "_dem_bounds_wgs84", None),
                "bbox_intersects_dem_bounds_wgs84": getattr(
                    sampler_obj, "_bbox_intersects_dem_bounds_wgs84", None
                ),
                "transform_error_points": int(
                    sampling_error_counts.get("transform_error_points", 0) or 0
                ),
                "raster_index_error_points": int(
                    sampling_error_counts.get("raster_index_error_points", 0) or 0
                ),
                "out_of_bounds_points": int(
                    sampling_error_counts.get("out_of_bounds_points", 0) or 0
                ),
                "real_nodata_points": int(
                    sampling_error_counts.get("real_nodata_points", 0) or 0
                ),
                "transform_error_ratio": float(_ratio("transform_error_points")),
                "raster_index_error_ratio": float(_ratio("raster_index_error_points")),
                "out_of_bounds_ratio": float(_ratio("out_of_bounds_points")),
                "real_nodata_ratio": float(_ratio("real_nodata_points")),
            }
        )
        if float(report.get("dem_nodata_ratio", 0.0)) >= 0.95:
            report.update(
                {
                    "map_bbox_in_map_crs": getattr(
                        sampler_obj, "_map_bbox_in_map_crs", None
                    ),
                    "map_bbox_transformed_to_dem_crs": getattr(
                        sampler_obj, "_map_bbox_transformed_to_dem_crs", None
                    ),
                    "dem_bounds_in_dem_crs": getattr(
                        sampler_obj, "_dem_bounds_in_dem_crs", None
                    ),
                    "bbox_intersects_dem_bounds": getattr(
                        sampler_obj, "_bbox_intersects_dem_bounds", None
                    ),
                }
            )
            if report.get("bbox_intersects_dem_bounds") is False and not report.get(
                "likely_cause"
            ):
                report["likely_cause"] = "CRS_or_georef_mismatch"
            elif getattr(sampler_obj, "_likely_cause", ""):
                report["likely_cause"] = str(getattr(sampler_obj, "_likely_cause"))

    sampling_frame = str(getattr(sampler, "_sampling_frame", "local"))
    dem_qc_report = build_dem_qc_report(
        sampled_points=int(dem_apply_stats.get("sampled_points", 0)),
        nodata_points=int(dem_apply_stats.get("nodata_points", 0)),
        sample_values=list(dem_apply_stats.get("sample_values", [])),
        dem_present=bool(use_dem and dem_path and os.path.exists(dem_path)),
        sampling_frame=sampling_frame,
        dem_raster_min=dem_raster_stats.get("dem_raster_min"),
        dem_raster_max=dem_raster_stats.get("dem_raster_max"),
        nodata_ratio_fail_threshold=nodata_ratio_fail_threshold,
        suspicious_raster_range_threshold=suspicious_raster_range_threshold,
        flat_sample_range_threshold=flat_sample_range_threshold,
    )
    dem_qc_report["dem_expanded_used"] = bool(dem_expanded_used)
    _augment_dem_qc_report(dem_qc_report, sampler, str(dem_path) if dem_path else "")

    strict_failure = (strict_dem or strict_quality) and not bool(
        dem_qc_report.get("ok", True)
    )
    if (
            strict_failure
            and auto_reproject_enabled
            and str(dem_qc_report.get("reason", "")).startswith(
        "dem_nodata_ratio_exceeds_threshold"
    )
            and dem_qc_report.get("bbox_intersects_dem_bounds") is False
            and dem_path
    ):
        dem_qc_report["auto_reproject_attempted"] = True
        reproject_report = ElevationImporter.reproject_dem_to_map_crs(
            str(dem_path), xodr_path=topo_fixed
        )
        dem_qc_report["auto_reproject_report"] = reproject_report
        if bool(reproject_report.get("ok", False)):
            retried_dem_path = str(reproject_report.get("output_dem_path", ""))
            if retried_dem_path:
                print(
                    "[DEM] Auto-reproject retry enabled and mismatch suspected; "
                    f"retrying DEM sampling with {retried_dem_path}"
                )
                prior_report = dict(dem_qc_report)
                try:
                    tree, root = load_xodr(topo_fixed)
                    sampler = ElevationImporter.make_raster_sampler(
                        retried_dem_path,
                        xodr_path=topo_fixed,
                    )
                    retry_stats = {
                        "sampled_points": 0,
                        "nodata_points": 0,
                        "sample_values": [],
                    }
                    retry_collected = ElevationImporter.apply_dem(
                        root, sampler, collect_qc=True
                    )
                    if isinstance(retry_collected, dict):
                        retry_stats = retry_collected
                    dem_apply_stats = dict(retry_stats)
                    dem_raster_stats = summarize_dem_raster_stats(retried_dem_path)
                    dem_qc_report = build_dem_qc_report(
                        sampled_points=int(retry_stats.get("sampled_points", 0)),
                        nodata_points=int(retry_stats.get("nodata_points", 0)),
                        sample_values=list(retry_stats.get("sample_values", [])),
                        dem_present=True,
                        sampling_frame=str(
                            getattr(sampler, "_sampling_frame", "local")
                        ),
                        dem_raster_min=dem_raster_stats.get("dem_raster_min"),
                        dem_raster_max=dem_raster_stats.get("dem_raster_max"),
                        nodata_ratio_fail_threshold=nodata_ratio_fail_threshold,
                        suspicious_raster_range_threshold=suspicious_raster_range_threshold,
                        flat_sample_range_threshold=flat_sample_range_threshold,
                    )
                    dem_qc_report["dem_expanded_used"] = bool(dem_expanded_used)
                    dem_qc_report["auto_reproject_attempted"] = True
                    dem_qc_report["auto_reproject_succeeded"] = True
                    dem_qc_report["auto_reproject_initial_qc"] = prior_report
                    _augment_dem_qc_report(dem_qc_report, sampler, retried_dem_path)
                    dem_path = retried_dem_path
                    strict_failure = (strict_dem or strict_quality) and not bool(
                        dem_qc_report.get("ok", True)
                    )
                except Exception as retry_exc:
                    dem_qc_report["auto_reproject_succeeded"] = False
                    dem_qc_report["auto_reproject_retry_error"] = str(retry_exc)
        else:
            dem_qc_report["auto_reproject_succeeded"] = False

    def _write_dem_qc_report(report_obj: dict) -> None:
        try:
            with open(dem_qc_report_path, "w", encoding="utf-8") as f:
                json.dump(report_obj, f, indent=2, ensure_ascii=True, sort_keys=True)
        except Exception as e:
            print(f"⚠️ Failed to write DEM QC report: {e}")

    _write_dem_qc_report(dem_qc_report)
    self.vreport.add_dict("elevation_dem_qc", dem_qc_report)
    if (strict_dem or strict_quality) and not bool(dem_qc_report.get("ok", True)):
        hint = ""
        if dem_qc_report.get("bbox_intersects_dem_bounds") is False:
            hint = (
                " Map sample bbox does not intersect DEM bounds after CRS transform. "
                "Check XODR geoReference / map CRS. Consider enabling "
                "UP_AUTO_REPROJECT_DEM_ON_QC_FAIL=1."
            )
        actionable_hint = ""
        out_of_bounds_ratio = float(dem_qc_report.get("out_of_bounds_ratio", 0.0) or 0.0)
        if (
            dem_qc_report.get("bbox_intersects_dem_bounds_wgs84") is False
            or out_of_bounds_ratio >= 1.0
        ):
            actionable_hint = (
                " Map bbox is outside DEM bounds (likely header offset mismatch). "
                "Fix by rerunning with UP_PREANCHOR_INPUT_XODR=1 (uses GPS-anchored offset). "
                "Alternatively, set UP_USE_GPS_ANCHOR_OFFSET=1 to override offset directly. "
                "For planar-only analysis (no elevation), set UP_DEM_STRICT_MODE=0."
            )
        raise RuntimeError(
            "DEM sampling QC failed in strict mode: "
            f"{dem_qc_report.get('reason')} (see {dem_qc_report_path}).{hint}{actionable_hint}"
        )

    save_xodr(tree, topo_fixed)

    # DEM coverage gate (only if DEM was used)
    if use_dem and dem_path and os.path.exists(dem_path):
        self._stage_gate(
            "05_elevation",
            "dem_coverage",
            lambda: self.qgate.gate_dem_coverage(
                topo_fixed,
                dem_path,
                threshold=float(getattr(s, "DEM_FULL_COVERAGE_THRESHOLD", 0.6)),
            ),
        )

    # Elevation smoothing
    ElevationSmoother.smooth(root)
    elev_a_vals = []
    for elev in root.findall(".//elevationProfile/elevation"):
        try:
            elev_a_vals.append(float(elev.get("a", "0.0")))
        except Exception:
            continue
    min_variance = float(getattr(s, "DEM_MIN_ELEVATION_VARIANCE", 0.0))
    variance = float(np.var(np.array(elev_a_vals, dtype=float))) if elev_a_vals else 0.0
    var_report = {
        "ok": variance >= min_variance,
        "variance": variance,
        "min_variance": min_variance,
        "sample_count": int(len(elev_a_vals)),
    }
    self._stage_gate("05_elevation", "elevation_variance", lambda: var_report)
    if strict_dem and not var_report["ok"]:
        raise RuntimeError(
            f"Elevation variance below threshold after smoothing: {variance} < {min_variance}"
        )
    elev_mean = statistics.mean(elev_a_vals) if elev_a_vals else 0.0
    elev_stddev = statistics.pstdev(elev_a_vals) if elev_a_vals else 0.0
    self.vreport.add_dict(
        "elevation_stats",
        {
            "mean": float(elev_mean),
            "stddev": float(elev_stddev),
            "count": int(len(elev_a_vals)),
        },
    )
    min_elevation_std_cfg = float(getattr(s, "DEM_MIN_ELEVATION_STD", 0.0))
    enforce_strict_std_default = str(
        os.getenv("UP_DEM_STRICT_ENFORCE_MIN_STD_DEFAULT", "0")
    ).strip().lower() in ("1", "true", "yes", "on")
    from ultimate_pipeline.config.settings import SETTINGS as GLOBAL_SETTINGS

    strict_std_default = float(
        os.getenv(
            "UP_DEM_STRICT_MIN_ELEVATION_STD_DEFAULT",
            str(
                getattr(
                    s,
                    "DEM_STRICT_MIN_ELEVATION_STD_DEFAULT",
                    getattr(GLOBAL_SETTINGS, "DEM_STRICT_MIN_ELEVATION_STD_DEFAULT"),
                )
            ),
        )
    )
    min_elevation_std = float(min_elevation_std_cfg)
    threshold_source = "settings.DEM_MIN_ELEVATION_STD"
    if (
        bool(strict_dem)
        and enforce_strict_std_default
        and float(min_elevation_std_cfg) <= 0.0
    ):
        min_elevation_std = float(strict_std_default)
        threshold_source = "strict_default"
    print(
        "[STEP 5] Elevation stddev threshold effective: "
        f"{float(min_elevation_std)} (source={threshold_source}, "
        f"strict_dem={bool(strict_dem)}, enforce_strict_default={bool(enforce_strict_std_default)})"
    )
    std_report = {
        "ok": float(elev_stddev) >= float(min_elevation_std),
        "stddev": float(elev_stddev),
        "min_stddev": float(min_elevation_std),
        "min_stddev_configured": float(min_elevation_std_cfg),
        "strict_dem": bool(strict_dem),
        "enforce_strict_default": bool(enforce_strict_std_default),
        "strict_default_min_stddev": float(strict_std_default),
        "effective_threshold_source": str(threshold_source),
        "fail_on_flat_elevation": bool(getattr(s, "FAIL_ON_FLAT_ELEVATION", True)),
    }
    self._stage_gate("05_elevation", "elevation_stddev", lambda: std_report)
    if not std_report["ok"]:
        msg = (
            "Elevation stddev below configured threshold after smoothing: "
            f"{float(elev_stddev)} < {float(min_elevation_std)}"
        )
        if bool(getattr(s, "FAIL_ON_FLAT_ELEVATION", True)) or bool(strict_dem):
            raise RuntimeError(msg)
        print(f"⚠️ {msg} (continuing with FAIL_ON_FLAT_ELEVATION=False)")
        self.vreport.add("elevation_stats", "flat_dem_warning", True)
        self.vreport.add("elevation_stats", "flat_dem_warning_reason", msg)

    # Always write the smoothed elevation first. Optional link-offset
    # correction is canonicalized inside gate_elevation_continuity() so the
    # deterministic repair is applied exactly once and reported from one place.
    save_xodr(tree, elev_out)

    print(f"✅ Elevation smoothed → {elev_out}")

    if s.QA_AUTOVIS and self._carla_allowed("pre_lane_preview"):
        if self._carla_isolation_enabled():
            print("⏭️ CARLA QA preview skipped (isolation mode).")
        else:
            from ultimate_pipeline.diagnostics.carla_quick_load import (
                CarlaValidator,
            )

            CarlaValidator.quick_visual_check(
                elev_out, message="After STEP 5 — Elevation Smoothing"
            )
    else:
        if s.QA_AUTOVIS:
            print("⏭️ CARLA QA preview skipped (pre-lane stage).")

    suspicious_report_path = os.path.join(self.out_dir, "elevation_suspicious_report.json")
    suspicious_slope_threshold = float(
        getattr(s, "DEM_SUSPICIOUS_SLOPE_THRESHOLD", 0.25)
    )
    suspicious_jump_threshold_m = float(
        getattr(s, "DEM_SUSPICIOUS_JUMP_THRESHOLD_M", 0.5)
    )
    suspicious_top_k = int(getattr(s, "DEM_SUSPICIOUS_TOP_K", 10))
    strict_dem_suspicious_fail = bool(
        getattr(s, "STRICT_DEM_SUSPICIOUS_FAIL", False)
    )
    suspicious_ratio_fail_threshold = float(
        getattr(s, "DEM_SUSPICIOUS_RATIO_FAIL_THRESHOLD", 0.25)
    )
    suspicious_report = PipelineDiagnostics.check_elevation(
        root,
        "after elevation smoothing",
        report_path=suspicious_report_path,
        slope_threshold=suspicious_slope_threshold,
        jump_threshold_m=suspicious_jump_threshold_m,
        top_k=suspicious_top_k,
        nodata_road_ids=list(dem_apply_stats.get("nodata_road_ids", [])),
        fallback_road_ids=list(dem_apply_stats.get("fallback_road_ids", [])),
        strict_fail=bool(strict_dem_suspicious_fail),
        suspicious_ratio_fail_threshold=suspicious_ratio_fail_threshold,
    )
    self.vreport.add_dict("elevation_suspicious_report", suspicious_report)
    summary_metrics = (
        suspicious_report.get("summary_metrics", {})
        if isinstance(suspicious_report, dict)
        else {}
    )
    if not isinstance(summary_metrics, dict):
        summary_metrics = {}
    dem_qc_report["elevation_suspicious_report_path"] = str(suspicious_report_path)
    dem_qc_report["suspicious_total"] = int(
        suspicious_report.get("total_suspicious", 0)
    )
    dem_qc_report["suspicious_ratio"] = float(
        suspicious_report.get("suspicious_ratio", 0.0)
    )
    dem_qc_report["suspicious_counts_by_category"] = dict(
        suspicious_report.get("counts_by_category", {})
    )
    dem_qc_report["suspicious_thresholds"] = dict(
        suspicious_report.get("thresholds", {})
    )
    dem_qc_report["elevation_profile_metrics"] = {
        "z_min": summary_metrics.get("z_min"),
        "z_max": summary_metrics.get("z_max"),
        "z_std": summary_metrics.get("z_std"),
        "z_p01": summary_metrics.get("z_p01"),
        "z_p99": summary_metrics.get("z_p99"),
        "slope_abs_mean": summary_metrics.get("slope_abs_mean"),
        "slope_abs_p95": summary_metrics.get("slope_abs_p95"),
        "slope_abs_p99": summary_metrics.get("slope_abs_p99"),
        "slope_abs_max": summary_metrics.get("slope_abs_max"),
        "jump_abs_p95": summary_metrics.get("jump_abs_p95"),
        "jump_abs_p99": summary_metrics.get("jump_abs_p99"),
        "jump_abs_max": summary_metrics.get("jump_abs_max"),
    }
    _write_dem_qc_report(dem_qc_report)
    self.vreport.add_dict("elevation_dem_qc", dem_qc_report)
    self.qgate.gate_elevation_smoothness(root)

    # Elevation continuity check (Z-seams at road joins)
    self._stage_gate(
        "05_elevation",
        "elevation_continuity",
        lambda: self.qgate.gate_elevation_continuity(elev_out),
    )

    # Geometry validator
    print("\n============== 📐 STEP 5B: Geometry Validator ==============")
    tree, root = load_xodr(elev_out)

    try:
        max_curv = getattr(s, "CURVATURE_MAX_ALLOWED", 0.45)
        clamped = PlanViewSmoother.clamp_curvature(root, max_curv)
        print(
            f"[STEP 5B] Curvature clamp applied: {clamped} geometries clamped "
            f"to |k| <= {max_curv}"
        )
    except Exception as e:
        print(f"⚠️ Curvature clamp failed: {e}")

    debug_json = os.path.join(
        os.path.dirname(elev_out), "geometry_validator_debug.json"
    )
    geom_report = GeometryValidator.validate(root, debug_json_path=debug_json)
    self.qgate.attach_geometry_validator(geom_report)
    save_xodr(tree, elev_out)
    print("✅ Geometry validator complete →", elev_out)
    self.semantic_state["has_elevation"] = True

    return elev_out


# ---------------- 6) 📐 PLANVIEW & CONTINUITY ----------------
