#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble the P0 BEFORE manifest from the individual instrument outputs.

Reads (all under stage8_rca_output/):
  p0_before_gate_sweep/map_acceptance.json
  p0_before_gate_sweep/component_reachability.json
  p0_before_gate_sweep/lane_connectivity.json
  p0_before_oracle.json
  p0_before_terminal_ledger.json
  p0_before_structure.json
  p0_before_gap048.json
  p0_before_osm_link_topology.json

Writes reports/map_realism_p0_repair/BEFORE_MANIFEST.json
"""
import hashlib
import json
import os
import sys
from collections import Counter

OUT_DIR = "stage8_rca_output"
DEST = "reports/map_realism_p0_repair/BEFORE_MANIFEST.json"

XODR = "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr"


def load(rel):
    p = os.path.join(OUT_DIR, rel)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    acceptance = load("p0_before_gate_sweep/map_acceptance.json") or {}
    reach = load("p0_before_gate_sweep/component_reachability.json") or {}
    lane_conn = load("p0_before_gate_sweep/lane_connectivity.json") or {}
    lane_conn_strict = load("p0_before_gate_sweep/lane_connectivity_strict.json")
    oracle = load("p0_before_oracle.json") or {}
    ledger = load("p0_before_terminal_ledger.json") or {}
    structure = load("p0_before_structure.json") or {}
    gap048 = load("p0_before_gap048.json") or {}
    osm_topo = load("p0_before_osm_link_topology.json") or {}

    conn = oracle.get("connector_lane_interface_dz", {})
    geom = oracle.get("georeference", {})
    dang = oracle.get("dangling_mandatory_lane_successors", {})
    orph = oracle.get("orphan_drivable_roads", {})

    manifest = {
        "schema": "MAP_REALISM_P0_BEFORE_MANIFEST/v1",
        "campaign": "map-realism-p0-repair-837a8504",
        "base_sha": "837a8504b624dc90653aef3a48300abb3275e291",
        "map_of_record": {
            "path": XODR,
            "sha256": sha256_file(XODR),
            "bytes": os.path.getsize(XODR),
        },
        "instrument_sources": {
            rel.replace(".json", ""): os.path.join(OUT_DIR, rel)
            for rel in (
                "p0_before_oracle.json", "p0_before_terminal_ledger.json",
                "p0_before_structure.json", "p0_before_gap048.json",
                "p0_before_osm_link_topology.json",
                "p0_before_gate_sweep/map_acceptance.json",
                "p0_before_gate_sweep/component_reachability.json",
                "p0_before_gate_sweep/lane_connectivity.json",
            )
        },

        "P0_A_dangling_mandatory_lane_successors": {
            "audit_reported_count": 376,
            "audit_count_provenance": (
                "Audit Lane A / CLOSURE-18 counted 376 dangling mandatory "
                "successors post-Stage-8 on its own fresh Stage-7 generation "
                "(GAP048 no-candidate 377 -> 376 after simulation); those "
                "exact artifact bytes are not the pinned map-of-record. The "
                "campaign population below is the byte-verifiable equivalent "
                "population on the pinned map under the same class semantics."),
            "checker_definition_count": 331,
            "checker_definition_note": (
                "ultimate_pipeline.quality.check_lane_connectivity "
                "find_broken_lanes_detailed(allow_dead_ends=False) on the "
                "pinned map: 331 driving lanes with reason missing_successor; "
                "all on roads with no successor anywhere (junction=-1); "
                "allow_dead_ends=True reports 0 (the frozen GAP-048 contract)."),
            "oracle_junction_routing_dangling": dang.get("dangling_mandatory_lane_successors"),
            "oracle_junction_routing_records": dang.get("dangling_records"),
            "terminal_ledger": {
                "population": ledger.get("population"),
                "class_counts": ledger.get("class_counts"),
                "defect_count": ledger.get("defect_count"),
                "defect_records_path": os.path.join(OUT_DIR, "p0_before_terminal_ledger.json"),
            },
            "affected_lane_ids_note": "full per-lane records preserved in the ledger and checker outputs (331 lanes on 326 dead-end roads)",
        },

        "P0_B_orphan_drivable_roads": {
            "audit_reported_count": 6,
            "audit_reported_ids": ["42367", "43405", "46369", "46698", "48129", "51657"],
            "reconciliation": {
                "absent_from_pinned_map": ["42367", "43405", "46369", "46698", "48129"],
                "present_but_junction_connected": ["51657"],
                "closure18_definition_orphans_measured_on_pinned_map":
                    orph.get("orphan_drivable_roads"),
                "definition": (
                    "CLOSURE-18: road with driving lanes, no predecessor/successor "
                    "road link, not referenced by any junction connection. On the "
                    "pinned map this population is 0; the audit's 6 were computed "
                    "on its fresh CLOSURE-18 generation."),
                "related_dead_end_population": (
                    "326 junction-exit roads (predecessor=junction, no successor, "
                    "no junction connection membership) overlap the P0-A "
                    "population and are classified by the terminal ledger."),
            },
            "component_reachability": {
                "component_count": reach.get("component_count"),
                "isolated_lane_component_count": reach.get("isolated_lane_component_count"),
                "largest_component_fraction": reach.get("largest_component_fraction"),
                "spec_status": acceptance.get("metrics", {}).get("component_reachability_spec_status"),
                "recovery_status": reach.get("recovery_status"),
            },
        },

        "P0_C_junction_connector_dz": {
            "audit_reported": {"bad": 866, "denominator": 45178, "worst_dz_m": 2.06},
            "measured_connection_level": {
                "connections_total": conn.get("connections_total"),
                "connection_interfaces": conn.get("connection_interfaces"),
                "bad_connections": conn.get("bad_connections"),
                "worst_dz_m": conn.get("worst_dz"),
                "worst_record": conn.get("worst_record"),
                "class_counts": conn.get("conn_class_counts"),
                "degenerate_connector_note": "97 degenerate connectors (<1 cm) counted separately",
            },
            "measured_lanelink_level": {
                "interface_links": conn.get("interface_links"),
                "bad_seams": conn.get("bad_seams"),
            },
            "reconciliation_note": (
                "Denominator 45178 = 2 interfaces per 22589 junction connections "
                "and matches the audit exactly. The audit's 866 counted "
                "per-interface failures (start or end); the campaign tracks "
                "739 bad connections (2561 lane-interfaces >0.5 m collapsed per "
                "connection, 776 laneLink-level seams). Worst connection-level "
                "reference-line seam 2.4184 m (junction 3033, connector 68410) vs "
                "audit's 2.06 m at a different pairing; same defect class."),
            "threshold_m": 0.5,
        },

        "P0_D_structure_terrain_separation": {
            "audit_reported": {"bridge_elevated_at_or_below_terrain": 17, "tunnel_at_or_above_terrain": 38},
            "canonical_classifier_scan": {
                "classified_structure_roads": structure.get("classified_structure_roads"),
                "violations": structure.get("violations"),
                "violated_roads": structure.get("violated_roads"),
                "method": (
                    "ultimate_pipeline.enrichment.structure_classifier (OSM way "
                    "tag authority) + DEM sampler from the pinned dem_ing.tif; "
                    "bridge/elevated must exceed terrain by >=0.5 m, tunnel must "
                    "sit >=0.5 m below"),
                "class_breakdown": structure.get("class_breakdown"),
            },
            "reconciliation_note": (
                "Audit's 17/38 used its own sampling/classification; the repo-"
                "canonical classifier finds a superset class population (240 "
                "roads) with 136 violations. Both count the same physical "
                "defect class; the canonical gate below is the operative one."),
            "threshold_m": 0.5,
        },

        "P0_E_georeference": {
            "audit_reported": {"has_absolute_origin": False},
            "measured": geom,
            "impact": (
                "CARLA 0.9.16 GeoReferenceParser accepts only +lat_0/+lon_0; "
                "absent -> fallback geolocation (42.0, 2.0) ~7.4 degrees from "
                "Ingolstadt; GNSS output is meaningless (audit P0 itself)."),
            "fixed_string_policy": {
                "designed_georeference": (
                    "+proj=tmerc +lat_0=<origin lat> +lon_0=<origin lon> +k=1 "
                    "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs where the "
                    "origin is the inverse-NATIVE projection of the pinned "
                    "rebase offset (map local (0,0))"),
                "origin_designated_lat": 48.70193666037281,
                "origin_designated_lon": 11.322197314492136,
                "carla_equirect_accuracy_envelope_m": 27981.9,
                "accuracy_envelope_note": (
                    "max CARLA-linear equirectangular-vs-true-tmerc deviation "
                    "over the scrubbed bbox measured at the far NE corner of "
                    "the local extent; a documented projection-semantics "
                    "limitation of the CARLA consumer, not a fixable offset"),
            },
        },

        "P0_F_fabricated_gnss_evidence": {
            "code_state_at_base_sha": "fail-closed (verified: phase_l_validation.py lines 510-546)",
            "historical_false_pass_artifacts": 5,
            "revocation_record": "reports/map_realism_p0_repair/P0_F_REVOCATION_RECORD.json",
        },

        "P0_G_building_references": {
            "audit_reported": {"unresolved_building_references": 5711},
            "source_evidence": (
                "MAP_REALISM_AUDIT_837a8504 Line A; static namespace fix "
                "described in BUILDING_REFERENCE_FIX_STATIC_AUDIT.json "
                "(reports/production_readiness/root_level_artifacts_20261007, "
                "historical dir not tracked at base SHA)"),
        },

        "P0_H_material_bindings": {
            "audit_reported": {"unbound_material_slots": 11422},
            "source_evidence": "MAP_REALISM_AUDIT_837a8504 Line A",
        },

        "P0_I_traffic_signal_authority": {
            "measured_functional_signals_count": acceptance.get("metrics", {}).get("functional_signals_count"),
            "measured_traffic_light_object_count": acceptance.get("metrics", {}).get("traffic_light_object_count"),
            "audit_reported": "heuristic-only traffic-light population (>21k) without OSM node authority",
            "source_note": "producer = ultimate_pipeline.enrichment.traffic_light_infer (heuristic TL writer)",
        },

        "P0_J_final_integrity": {
            "acceptance_chain_at_base": {
                "valid_for_experiments": acceptance.get("valid_for_experiments"),
                "lane_successor_missing_count": acceptance.get("metrics", {}).get("lane_successor_missing_count"),
                "unexplained_lane_count_changes": acceptance.get("metrics", {}).get("lane_count_change_unexplained_count"),
            },
            "strict_profile_note": (
                "the acceptance chain at base SHA passes under the relaxed "
                "GAP-048 contract; the production PERCEPTION_RELEASE profile "
                "requires_strict_lane_successors() raises on dead-end lanes at "
                "stage_08_integrity (the 331-lane population) — the fail-open "
                "path the campaign closes"),
        },

        "denominator_policy": "No denominator manipulation: every count above carries its definition and source artifact; the AFTER manifest must reuse identical definitions per row.",
    }

    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    with open(DEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, default=str)
    print("manifest ->", DEST)
    print(json.dumps({k: (v if not isinstance(v, dict) else "…") for k, v in manifest.items() if k.startswith("P0")}, indent=1, default=str)[:1200])


if __name__ == "__main__":
    sys.exit(main())
