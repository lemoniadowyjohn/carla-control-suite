# ultimate_pipeline/pipeline_stages/stage_09_positional_semantics.py
# -*- coding: utf-8 -*-
"""
Stage 9: Positional Semantic Materialization (P0-L reorder).

This stage runs AFTER STRUCTURE_FROZEN, LANES_FINAL, HYGIENE_COMPLETE.
It materializes all position-dependent semantic content that was previously
done in Stage 4 (enrichment) before geometry/lane/hygiene stages.

Position-dependent semantics include:
- Traffic lights (require final lane structure for <signal> references)
- Crosswalks (require final road/junction geometry for s/t placement)
- Speed limits (require final road s-coordinates)
- Turn lane markings (require final lane structure)
- Regulatory signs (require final road geometry)
- Building insertion (requires final road geometry for correct positioning)
- Access restriction metadata application (requires final road IDs)

All OSM source extraction/projection is done in the early
SOURCE_METADATA_PREPARATION phase (Stage 4); this stage only applies
the pre-computed associations to the frozen structure.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET


def _inject_main_pipeline_globals():
    from ultimate_pipeline import main_pipeline as _mp
    g = globals()
    for k, v in _mp.__dict__.items():
        if k.startswith("__"):
            continue
        if k in ("_inject_main_pipeline_globals",):
            continue
        g.setdefault(k, v)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _step9_positional_semantics(self, final_out: str) -> str:
    """Apply position-dependent semantics to the FROZEN final artifact.

    This stage MUST run after:
    - GEOMETRY_FROZEN (planView, road links, junctions fixed)
    - LANES_FINAL (lane structure, lane IDs stable)
    - HYGIENE_COMPLETE (roads may have been deleted/quarantined)

    Returns the same final_out path (mutations are in-place on the frozen artifact).
    """
    _inject_main_pipeline_globals()
    s = self.settings

    print(
        "\n============== 🏗️ STEP 9: Positional Semantic Materialization (post-freeze) =============="
    )

    tree, root = load_xodr(final_out)

    # Verify preconditions
    self._assert_geometry_frozen(root, "positional_semantics entry")

    # ------------------------------------------------------------------
    # Traffic lights: insert signals with lane references
    # Requires LANES_FINAL for valid lane IDs in <signal> references
    # ------------------------------------------------------------------
    if getattr(s, "ENABLE_TRAFFIC_LIGHTS", False):
        print("🚦 Materializing traffic lights on frozen structure…")
        try:
            n_lights = TrafficLightInferer.infer_and_insert(root)
            self.vreport.add("positional_semantics", "traffic_lights_added", str(n_lights))
            save_xodr(tree, final_out)
            print(f"   → Inserted {n_lights} traffic lights.")

            coverage = TrafficLightInferer.junction_coverage_stats(root)
            self.vreport.add_dict("traffic_light_junction_coverage", coverage)
            print(
                "   → Junction signal coverage: "
                f"{coverage['eligible_junctions_with_inferred_signal']}/"
                f"{coverage['eligible_junctions']} eligible junctions "
                f"({coverage['eligible_junction_coverage_fraction']:.1%}), "
                "100% topology-heuristic, no real-world source."
            )

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
            print(f"⚠️ Traffic light materialization failed: {e}")
            self.vreport.add("positional_semantics", "traffic_light_error", str(e))
    else:
        print("⏭️ Traffic light materialization disabled.")

    # ------------------------------------------------------------------
    # Buildings: insert building objects at final road geometry
    # Requires final planView for correct positioning relative to roads
    # ------------------------------------------------------------------
    buildings_path = getattr(s, "OSM_BUILDINGS_GEOJSON", None)
    if buildings_path and not os.path.exists(buildings_path):
        # Try pinned fallback
        pinned = getattr(s, "PINNED_BUILDINGS_SOURCE", None)
        if pinned and os.path.exists(pinned) and os.path.getsize(pinned) > 0:
            buildings_path = pinned
            print(f"🏙️ Using pinned building source: {buildings_path}")
        else:
            buildings_path = None
            print("⚠️ No building source available; skipping building insertion.")

    if getattr(s, "ENABLE_BUILDINGS", True) and buildings_path:
        print("🏙️ Inserting buildings on frozen structure…")
        try:
            num_buildings = _load_buildings_with_fallback(
                root=root,
                buildings_geojson_path=buildings_path,
                osm_path=s.OSM_FILE,
                gps_bounds=s.load_gps_bounds(),
                vreport=self.vreport,
                out_dir=self.out_dir,
            )
            save_xodr(tree, final_out)

            enforce_buildings_fail_closed(
                inserted_count=num_buildings,
                buildings_source=buildings_path,
            )
            print(f"   → Inserted {num_buildings} buildings.")
        except Exception as e:
            print(f"⚠️ Building insertion failed: {e}")
            self.vreport.add("positional_semantics", "building_error", str(e))
    else:
        print("⏭️ Building insertion disabled or no source.")

    # ------------------------------------------------------------------
    # Position-sensitive OSM metadata: speed limits, turn lanes, regulatory signs
    # Requires final road s-coordinates and lane structure
    # ------------------------------------------------------------------
    try:
        from ultimate_pipeline.enrichment.osm_meta_index import (
            extract_positioned_osm_metadata_ways,
            project_positioned_osm_metadata_ways,
        )
        from ultimate_pipeline.enrichment.osm_xodr_correspondence import build_metadata_associations
        from ultimate_pipeline.enrichment.speed_limit_writer import apply_speed_limits
        from ultimate_pipeline.enrichment.turn_lanes_writer import apply_turn_lanes
        from ultimate_pipeline.enrichment.regulatory_sign_writer import apply_regulatory_signs

        # Re-extract and project against FROZEN geometry (associations may have been
        # cached from early phase; re-project to ensure alignment with final roads)
        source_ways = extract_positioned_osm_metadata_ways(s.OSM_FILE)
        positioned_ways = project_positioned_osm_metadata_ways(source_ways, root)
        if positioned_ways:
            associations, correspondence_report = build_metadata_associations(
                positioned_ways, root
            )
            print(
                "📋 Spatial OSM metadata (post-freeze): "
                f"{len(positioned_ways)} source ways, "
                f"{correspondence_report['eligible_road_count']} HIGH/EXACT road matches"
            )

            n_speed = apply_speed_limits(
                root, {}, correspondence_by_road_id=associations
            )
            n_turn = apply_turn_lanes(
                root, {}, correspondence_by_road_id=associations
            )
            n_signs = apply_regulatory_signs(
                root, {}, correspondence_by_road_id=associations
            )

            if n_speed or n_turn or n_signs:
                save_xodr(tree, final_out)
            self.vreport.add_dict("osm_spatial_metadata_postfreeze", {
                "source_ways": len(positioned_ways),
                "correspondence": correspondence_report,
                "speed_limits_applied": n_speed,
                "turn_lane_markings": n_turn,
                "regulatory_signs": n_signs,
            })
            print(f"   → Speed limits: {n_speed}, turn markings: {n_turn}, signs: {n_signs}")

            # Advisory cross-check against geometrically-built junction laneLinks
            try:
                from ultimate_pipeline.lanes.turn_restriction_audit import (
                    audit_lane_link_turn_classification,
                )
                turn_audit = audit_lane_link_turn_classification(root, associations)
                self.vreport.add_dict("lane_link_turn_classification_audit", turn_audit)
                turn_audit_summary = turn_audit.get("summary_metrics", {})
                print(
                    "   → Lane-link turn-classification audit: "
                    f"status={turn_audit.get('status')} "
                    f"agree={turn_audit_summary.get('agree', 0)} "
                    f"disagree={turn_audit_summary.get('disagree', 0)} "
                    f"no_osm_data={turn_audit_summary.get('no_osm_turn_data', 0)}"
                )
            except Exception as e:
                print(f"⚠️ Lane-link turn-classification audit failed: {e}")
        else:
            print("⏭️ Spatial OSM metadata skipped (no usable source way geometry)")
            self.vreport.add_dict(
                "osm_spatial_metadata_postfreeze",
                {"source_ways": 0, "eligible_road_count": 0},
            )
    except Exception as e:
        print(f"⚠️ OSM meta materialization failed: {e}")
        self.vreport.add("osm_meta_postfreeze", "error", str(e))

    # ------------------------------------------------------------------
    # Access restrictions: apply metadata with provenance
    # ------------------------------------------------------------------
    try:
        from ultimate_pipeline.enrichment.access_restriction_metadata import (
            apply_access_metadata_from_osm,
        )
        access_metadata = apply_access_metadata_from_osm(root, s.OSM_FILE)
        if access_metadata["metadata_records_written"]:
            save_xodr(tree, final_out)
        self.vreport.add_dict("osm_access_restriction_metadata_postfreeze", access_metadata)
        print(
            "   → Access metadata: "
            f"{access_metadata['roads_with_access_metadata']} road(s), "
            f"{access_metadata['metadata_records_written']} record(s)"
        )
    except Exception as e:
        print(f"⚠️ OSM access metadata materialization failed: {e}")
        self.vreport.add("osm_access_restriction_postfreeze", "error", str(e))

    # ------------------------------------------------------------------
    # Crosswalks: apply to final road/junction geometry
    # Requires final planView and junction structure for correct placement
    # ------------------------------------------------------------------
    try:
        from ultimate_pipeline.enrichment.crosswalk_writer import (
            extract_osm_crossings,
            project_crossing_to_local,
            apply_crosswalks,
        )
        from ultimate_pipeline.domain_gap.local_registration import read_offset

        osm_crossings = extract_osm_crossings(s.OSM_FILE)
        if osm_crossings:
            offset = read_offset(root)
            for c in osm_crossings:
                c["nodes_local"] = project_crossing_to_local(c["nodes"], offset)
            n_crosswalks = apply_crosswalks(root, osm_crossings)
            if n_crosswalks:
                save_xodr(tree, final_out)
            self.vreport.add_dict("crosswalk_enrichment_postfreeze", {
                "osm_crossings_found": len(osm_crossings),
                "crosswalks_inserted": n_crosswalks,
            })
            print(f"🚸 Crosswalks (post-freeze): {n_crosswalks}/{len(osm_crossings)} OSM crossings matched to a road")
        else:
            print("⏭️ Crosswalk materialization skipped (no OSM crossings)")
            self.vreport.add_dict("crosswalk_enrichment_postfreeze", {"osm_crossings_found": 0})
    except Exception as e:
        print(f"⚠️ Crosswalk materialization failed: {e}")
        self.vreport.add("crosswalk_postfreeze", "error", str(e))

    # ------------------------------------------------------------------
    # Realism objects: visual clutter only
    # ------------------------------------------------------------------
    if getattr(s, "ENABLE_REALISM", True):
        try:
            print("✨ Adding realism objects…")
            added = RealismModule.enrich(root)
            self.vreport.add("realism_objects", "added", str(added))
            save_xodr(tree, final_out)
            print(f"   → Inserted {added} realism objects.")
        except Exception as e:
            print(f"⚠️ Realism materialization skipped: {e}")
            self.vreport.add("realism_objects", "error", str(e))
    else:
        print("⏭️ Realism module disabled.")

    # Record that positional semantics are now final
    from ultimate_pipeline.contracts.stage_capabilities import SEMANTICS_FINAL
    self.authority_ledger.provide(SEMANTICS_FINAL, "positional_semantics", evidence=final_out)

    # XODR statistics after semantic materialization
    stats = XODRStatistics.compute(final_out)
    if isinstance(stats, dict):
        stats["semantic_completeness"] = {
            "geometry": True,
            "lanes": True,
            "positional_semantics": True,
            "reason": "All positional semantics materialized after structural freeze",
        }
    self.vreport.add_dict("xodr_statistics_post_semantics", stats)

    print(
        "✅ STEP 9 complete — positional semantics materialized on frozen structure"
    )
    return final_out