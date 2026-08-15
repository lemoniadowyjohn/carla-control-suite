# REFAC_VERSION = "v5_preserve"
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
        # Don't overwrite locally-defined names (e.g., stage functions).
        g.setdefault(k, v)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _offline_only_enabled(settings) -> bool:
    return bool(getattr(settings, "OFFLINE_ONLY", False)) or _env_flag("UP_OFFLINE_ONLY")


def resolve_buildings_geojson_for_stage4(
    *,
    settings,
    gps_bounds,
    buildings_path: str | None,
    downloader_factory=None,
) -> str | None:
    if not buildings_path:
        return None
    if os.path.exists(buildings_path):
        print(f"🏙️ buildings.geojson already present → {buildings_path}")
        return buildings_path
    if _offline_only_enabled(settings):
        print(
            "🏙️ buildings.geojson missing and offline mode is enabled → "
            "skipping download; OSM XML fallback will be used."
        )
        return None

    print("🏙️ buildings.geojson missing → auto-downloading…")
    os.makedirs(os.path.dirname(buildings_path), exist_ok=True)
    try:
        if downloader_factory is None:
            downloader_factory = globals()["OSMDownloader"]
        downloader_factory().ensure_osm_geojson_exists(gps_bounds, buildings_path)
        print(f"   📥 buildings.geojson downloaded → {buildings_path}")
        return buildings_path
    except Exception as e:
        print(f"   ❌ Failed to download buildings.geojson: {e}")
        print("   ⚠️ No buildings will be inserted.")
        return None


def _step4_enrichment(self, topo_fixed: str) -> str:
    _inject_main_pipeline_globals()
    s = self.settings
    print(
        "\n============== 🏗️ STEP 4: Enrichment (Roundabouts, TL, Buildings, Realism) =============="
    )

    tree, root = load_xodr(topo_fixed)
    gps = s.load_gps_bounds()

    # Roundabout reconstruction
    if getattr(s, "ENABLE_ROUNDABOUT_RECONSTRUCTION", False):
        print("🔄 Reconstructing roundabouts…")
        rb_meta = RoundaboutReconstructor.reconstruct(root, out_dir=self.out_dir)
        self.vreport.add_dict("roundabout_reconstruction", rb_meta)
        save_xodr(tree, topo_fixed)
    else:
        print("⏭️ Roundabout reconstruction disabled.")

    # Tag roundabouts
    try:
        print("🧪 Tagging roundabouts for visualization…")
        rb_tags = RoundaboutRebuilder.tag_roundabouts(root)
        self.vreport.add_dict("roundabout_tags", rb_tags)
        save_xodr(tree, topo_fixed)
        print("   → Roundabouts tagged for preview.")
    except Exception as e:
        print(f"⚠️ Roundabout tagging skipped: {e}")
        self.vreport.add("roundabouts", "tagging_failed", str(e))

    # Traffic lights
    if getattr(s, "ENABLE_TRAFFIC_LIGHTS", False):
        print("🚦 Inferring traffic lights…")
        try:
            n_lights = TrafficLightInferer.infer_and_insert(root)
            self.vreport.add("enrichment", "traffic_lights_added", str(n_lights))
            save_xodr(tree, topo_fixed)
            print(f"   → Inserted {n_lights} traffic lights.")

            print("🧪 Validating traffic light → lane references…")
            bad_refs = TrafficLightInferer.validate_signal_references(root)
            if bad_refs:
                print("❌ Invalid signal references found:")
                for br in bad_refs:
                    print("   -", br)
                self.vreport.add_dict(
                    "traffic_light_reference_errors",
                    {"issues": bad_refs},
                )
                print("⚠️ These must be fixed to guarantee drivable map behavior.")
        except Exception as e:
            print(f"⚠️ Traffic light inference failed: {e}")
            self.vreport.add("enrichment", "traffic_light_error", str(e))
    else:
        print("⏭️ Traffic light inference disabled.")

    # Buildings: ensure buildings.geojson exists
    buildings_path = resolve_buildings_geojson_for_stage4(
        settings=s,
        gps_bounds=gps,
        buildings_path=s.OSM_BUILDINGS_GEOJSON,
    )

    # Building extrusion
    if getattr(s, "ENABLE_BUILDINGS", True):
        print("🏙️ Inserting buildings with automatic fallback…")

        num_buildings = _load_buildings_with_fallback(
            root=root,
            buildings_geojson_path=buildings_path,
            osm_path=s.OSM_FILE,
            gps_bounds=gps,
            vreport=self.vreport,
            out_dir=self.out_dir,
        )

        save_xodr(tree, topo_fixed)
    else:
        print("⏭️ Building extrusion disabled.")

    # Realism
    if getattr(s, "ENABLE_REALISM", True):
        try:
            print("✨ Adding realism objects…")
            added = RealismModule.enrich(root)
            self.vreport.add("realism_objects", "added", str(added))
            save_xodr(tree, topo_fixed)
            print(f"   → Inserted {added} realism objects.")
        except Exception as e:
            print(f"⚠️ Realism enrichment skipped: {e}")
            self.vreport.add("realism_objects", "error", str(e))
    else:
        print("⏭️ Realism module disabled.")

    # OSM metadata enrichment: speed limits, turn:lanes, regulatory signs
    # Uses osm_meta_index to map OSM way IDs → XODR road IDs (they are equal).
    try:
        from ultimate_pipeline.enrichment.osm_meta_index import build_osm_meta_index
        from ultimate_pipeline.enrichment.speed_limit_writer import apply_speed_limits
        from ultimate_pipeline.enrichment.turn_lanes_writer import apply_turn_lanes
        from ultimate_pipeline.enrichment.regulatory_sign_writer import apply_regulatory_signs

        osm_meta = build_osm_meta_index(s.OSM_FILE)
        if osm_meta:
            print(f"📋 OSM meta index: {len(osm_meta)} ways with enrichment tags")

            n_speed = apply_speed_limits(root, osm_meta)
            n_turn = apply_turn_lanes(root, osm_meta)
            n_signs = apply_regulatory_signs(root, osm_meta)

            if n_speed or n_turn or n_signs:
                save_xodr(tree, topo_fixed)
            self.vreport.add_dict("osm_meta_enrichment", {
                "ways_indexed": len(osm_meta),
                "speed_limits_inserted": n_speed,
                "turn_lane_markings": n_turn,
                "regulatory_signs": n_signs,
            })
            print(f"   → Speed limits: {n_speed}, turn markings: {n_turn}, signs: {n_signs}")
        else:
            print("⏭️ OSM meta enrichment skipped (no OSM file or no enrichment tags found)")
            self.vreport.add_dict("osm_meta_enrichment", {"ways_indexed": 0})
    except Exception as e:
        print(f"⚠️ OSM meta enrichment failed: {e}")
        self.vreport.add("osm_meta_enrichment", "error", str(e))

    # XODR statistics after enrichment
    stats = XODRStatistics.compute(topo_fixed)
    # Important: STEP 4 is pre-lane by design
    if isinstance(stats, dict):
        stats["semantic_completeness"] = {
            "geometry": True,
            "lanes": False,
            "reason": "Lane generation occurs in STEP 7",
        }

    self.vreport.add_dict("xodr_statistics", stats)
    print("[INFO] XODR statistics:")
    print(json.dumps(stats, indent=2))
    try:
        header = root.find("header")
        geo_node = header.find("geoReference") if header is not None else None
        geo_text = (geo_node.text or "").strip() if geo_node is not None else ""
        proj_text = str(getattr(OSMPolygonLoader, "PROJ_STRING", "")).strip()
        georef_proj_match = (
            bool(geo_text) and bool(proj_text) and (geo_text == proj_text)
        )
        self.vreport.add_dict(
            "georef_proj_consistency",
            {
                "xodr_geoReference": geo_text,
                "osm_polygon_loader_proj_string": proj_text,
                "match": georef_proj_match,
            },
        )
        if (geo_text and proj_text) and (not georef_proj_match):
            self.vreport.add(
                "warning",
                "georef_proj_consistency",
                "XODR geoReference does not match OSMPolygonLoader.PROJ_STRING",
            )
    except Exception as e:
        self.vreport.add("warning", "georef_proj_consistency", f"check_failed:{e}")

    # OSM2World: optional 3D scene geometry artifacts (for visual QA / thesis figures)
    enable_osm2world = is_osm2world_enabled() or bool(
        getattr(s, "ENABLE_OSM2WORLD", False)
    )
    if enable_osm2world:
        # Allow enabling via Settings (UP_ENABLE_OSM2WORLD) by mirroring into env vars used by the runner.
        os.environ.setdefault("ENABLE_OSM2WORLD", "1")
        if getattr(s, "OSM2WORLD_HOME", ""):
            os.environ.setdefault("OSM2WORLD_HOME", str(s.OSM2WORLD_HOME))
        if getattr(s, "OSM2WORLD_OUTPUTS", ""):
            os.environ.setdefault("OSM2WORLD_OUTPUTS", str(s.OSM2WORLD_OUTPUTS))
        if getattr(s, "OSM2WORLD_TIMEOUT_SEC", 0):
            os.environ.setdefault(
                "OSM2WORLD_TIMEOUT_SEC", str(s.OSM2WORLD_TIMEOUT_SEC)
            )
        if getattr(s, "OSM2WORLD_CONFIG", ""):
            os.environ.setdefault("OSM2WORLD_CONFIG", str(s.OSM2WORLD_CONFIG))
        print("\n🌿 OSM2World: generating scene geometry artifacts...")
        try:
            osm2world_out = os.path.join(self.out_dir, "osm2world")
            os.makedirs(osm2world_out, exist_ok=True)
            runner = OSM2WorldRunner(
                osm_path=s.OSM_FILE,
                output_dir=osm2world_out,
            )
            osm2world_result = runner.run()
            self.vreport.add_dict("osm2world", osm2world_result.to_dict())
            # Stable handoff artifact for downstream Unreal import/placement.
            manifest_path = os.path.join(osm2world_out, "osm2world_manifest.json")
            manifest = {
                "generated_at_utc": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "status": osm2world_result.status,
                "reason": osm2world_result.reason,
                "outputs": dict(osm2world_result.outputs or {}),
                "proj_string": str(getattr(OSMPolygonLoader, "PROJ_STRING", "")),
                "gps_bounds": gps,
                "note": "Not integrated into Unreal by default",
            }
            with open(manifest_path, "w", encoding="utf-8") as mf:
                json.dump(manifest, mf, indent=2, sort_keys=True)
            self.vreport.add("osm2world", "manifest", manifest_path)
            if osm2world_result.status == "ok":
                print(f"   ✅ OSM2World: {osm2world_result.reason}")
                for name, path in osm2world_result.outputs.items():
                    print(f"      → {name}: {path}")
            elif osm2world_result.status == "skipped":
                print(f"   ⏭️ OSM2World skipped: {osm2world_result.reason}")
            else:
                print(f"   ⚠️ OSM2World failed: {osm2world_result.reason}")
        except Exception as e:
            print(f"   ❌ OSM2World exception: {e}")
            self.vreport.add("osm2world", "exception", str(e))
    else:
        print(
            "⏭️ OSM2World disabled (set ENABLE_OSM2WORLD=1 or UP_ENABLE_OSM2WORLD=1 to enable)"
        )

    # semantic contract: enrichment is geometry-only (lanes later)
    self.semantic_state.update(
        {
            "has_geometry": True,
            "has_elevation": False,
            "has_planview": False,
            "has_lanes": False,
        }
    )
    print(
        "✅ STEP 4 complete — geometry-only semantics (lanes are generated in STEP 7)"
    )

    return topo_fixed

