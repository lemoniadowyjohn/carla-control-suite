#!/usr/bin/env python3
# flake8: noqa
# ruff: noqa
# mypy: ignore-errors
# pylint: skip-file

from __future__ import annotations

# -*- coding: utf-8 -*-

"""
🚀 Ultimate OSM → OpenDRIVE → CARLA Pipeline (Monolithic, Clean, Drivable)

📋 Stages:
  0) 🎯 Determinism, paths, OSM/DEM checks, CARLA client
  1) 🧼 Sanitization (+ optional SUMO)
  2) 🕸️ Topology lint, structure scan, semantic risk scan
  3) 🔧 Topology repair
  4) 🏗️ Enrichment: roundabouts, traffic lights, buildings, realism
  5) 🏔️ DEM elevation + smoothing + geometry validator
  6) 📐 PlanView smoothing + mesh continuity + micro-prune
  7) 🛣️ Lane generation + lane/cross-section/offset repair + sidewalks
  8) 🔗 LaneLinks + markings + final integrity checks
  9) 🧩 Tiling + adjacency + auto-scenarios
 10) 🧪 Tile QA (seams + CarlaFinalTest + spawn QA + stress tester)
 11) 🔍 Road defect scan, local perception, screenshots
 12) 🎮 Interactive simulator (optional)
 13) 📊 Domain-gap analysis (classical; GNN / latent if enabled in separate module)
 14) 🚦 Quality gates wrapper + LLM QA

📝 This file is intentionally monolithic for final integration & thesis.
"""

# ---- ⚠️ Stability guard: disable CARLA tile QA on Windows ----
import platform as _platform

DISABLE_TILE_QA_ON_WINDOWS = _platform.system().lower().startswith("win")

import sys as _sys

if __name__ == "__main__" and ("--help" in _sys.argv or "-h" in _sys.argv):
    print("📘 Usage: python -m ultimate_pipeline.main_pipeline")
    raise SystemExit(0)

import os
import json
import hashlib
import importlib
import subprocess
import statistics
import sys
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import ultimate_pipeline.bootstrap_repo_root  # noqa: F401
import random
import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    import carla  # type: ignore
from ultimate_pipeline.utils.paths import city_dir
from ultimate_pipeline.quality.lane_width_invariants import default_report_path
from ultimate_pipeline.contracts.gate_runner import CumulativeGateRunner

from ultimate_pipeline.quality.lane_width_invariants import (
    enforce_lane_width_invariants_on_root,
    write_lane_width_invariants_report,
    enforce_lane_width_invariants,
    default_report_path,  # if you already have this elsewhere
)

_SETTINGS_CACHE = None
_CITY_NAME_CACHE = None


def _load_settings_module():
    from ultimate_pipeline.config import settings as _settings_mod

    return _settings_mod


def _get_settings():
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is None:
        _SETTINGS_CACHE = _load_settings_module().SETTINGS
    return _SETTINGS_CACHE


def _get_city_name() -> str:
    global _CITY_NAME_CACHE
    if _CITY_NAME_CACHE is None:
        _CITY_NAME_CACHE = str(getattr(_load_settings_module(), "CITY_NAME", ""))
    return _CITY_NAME_CACHE


class _LazySettingsProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(_get_settings(), name)


# Kept for stage modules that access `SETTINGS` via injected main_pipeline globals.
SETTINGS = _LazySettingsProxy()


# ============================================================
# 📦 IMPORT SANITY (avoid nested package shadowing)
def _preflight_import_sanity() -> None:
    try:
        pkg = importlib.import_module("ultimate_pipeline")
        pkg_file = Path(getattr(pkg, "__file__", "")).resolve()
    except Exception as exc:
        raise RuntimeError(f"❌ Failed to import ultimate_pipeline: {exc}") from exc

    nested_dir = Path(__file__).resolve().parent / "ultimate_pipeline"
    if nested_dir.exists() and pkg_file.is_file() and nested_dir in pkg_file.parents:
        raise RuntimeError(
            "⚠️ Nested duplicate package detected at "
            f"{nested_dir}. Run from the repo root with:\n"
            "  python -m ultimate_pipeline.main_pipeline\n"
            "and ensure imports resolve to the outer package."
        )
    if nested_dir.exists() and nested_dir not in pkg_file.parents:
        print(
            f"⚠️ [WARN] Nested duplicate package exists at {nested_dir}. "
            "Use `python -m ultimate_pipeline.main_pipeline` to avoid import shadowing."
        )


def _configure_windows_encoding() -> None:
    if sys.platform != "win32":
        return
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _validate_global_safety_settings(settings_obj: Any) -> None:
    """Run hard safety checks at runtime (not at import time)."""
    if getattr(settings_obj, "ENABLE_HPC_PERCEPTION", False) and not getattr(
        settings_obj, "ENABLE_HPC_EXPORT", False
    ):
        raise RuntimeError("❌ HPC perception enabled but dataset export disabled")

    if getattr(settings_obj, "ENABLE_LOCAL_PERCEPTION", False) or getattr(
        settings_obj, "ENABLE_HPC_PERCEPTION", False
    ):
        calib = getattr(settings_obj, "SENSOR_CALIB_JSON", None)
        if calib and not os.path.exists(calib):
            raise RuntimeError(
                f"❌ Perception enabled but SENSOR_CALIB_JSON not found: {calib}"
            )


# ----------------- 🎲 Determinism helpers -----------------


def enforce_determinism(seed: int = 42) -> None:
    """Set deterministic seeds for Python, NumPy, PyTorch, and CARLA randomness."""
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except Exception:
        pass
    print(f"✅ [INFO] Deterministic mode enabled (seed={seed})")


def _hash_file(path: str) -> str:
    """Simple SHA-256 hash helper for reproducibility metadata."""
    import hashlib

    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return "ERROR"


def _resolve_planview_auto_repair_max_m(settings_obj: Any) -> float:
    """
    Resolve seam auto-repair threshold with backward-compatible env precedence:
      1) UP_PLANVIEW_SEAM_AUTO_REPAIR_MAX_M
      2) UP_PLANVIEW_AUTO_REPAIR_MAX_M (legacy)
      3) settings.PLANVIEW_SEAM_AUTO_REPAIR_MAX_M
    """
    default_raw = str(getattr(settings_obj, "PLANVIEW_SEAM_AUTO_REPAIR_MAX_M", 0.05))
    chosen = os.getenv("UP_PLANVIEW_SEAM_AUTO_REPAIR_MAX_M")
    if chosen is None:
        chosen = os.getenv("UP_PLANVIEW_AUTO_REPAIR_MAX_M")
    if chosen is None:
        chosen = default_raw
    try:
        return float(chosen)
    except Exception:
        try:
            return float(default_raw)
        except Exception:
            return 0.05


def deep_clone(elem: ET.Element) -> ET.Element:
    """
    Attribute-preserving, recursive XML clone.
    🔗 REQUIRED for OpenDRIVE tiling correctness.
    """
    new = ET.Element(elem.tag, attrib=dict(elem.attrib))
    new.text = elem.text
    new.tail = elem.tail
    for child in elem:
        new.append(deep_clone(child))
    return new


def _count_lanes(xpath: str) -> int:
    try:
        r = ET.parse(xpath).getroot()
        return len(r.findall(".//lane"))
    except Exception:
        return -1


def safe_max(values):
    values = [v for v in values if v is not None]
    return max(values) if values else None


def is_real_geojson(path: str) -> bool:
    """
    Detect whether a file is real GeoJSON (FeatureCollection)
    or Overpass/OSM JSON masquerading as *.geojson.
    """
    import json

    try:
        with open(path, "r", encoding="utf-8") as f:
            head = json.load(f)
        return head.get("type") == "FeatureCollection"
    except Exception:
        return False


def _load_buildings_with_fallback(
    root,
    buildings_geojson_path: str,
    osm_path: str,
    gps_bounds: dict,
    vreport,
    out_dir: str | None = None,
):
    """
    Robust building loader with automatic fallback:
    1) Try GeoJSON
    2) If zero buildings → fallback to OSM XML
    """

    from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader
    from ultimate_pipeline.enrichment.building_extruder import BuildingExtruder

    def _write_building_enrichments_json(
        out_dir: str,
        buildings,
        *,
        z_default: float = 0.0,
    ) -> str | None:
        """
        Emit a deterministic enrichments JSON that can be consumed by:
          ultimate_pipeline/carla_tools/spawn_enrichments.py

        CARLA NOTE:
          OpenDRIVE <object type="building"> is not rendered as meshes by CARLA's runtime importer.
          This JSON enables optional proxy spawning for visual QA / thesis figures.
        """
        try:
            import json

            os.makedirs(os.path.join(out_dir, "enrichments"), exist_ok=True)
            out_path = os.path.join(
                out_dir, "enrichments", "buildings_enrichments.json"
            )

            items = []
            for b in buildings or []:
                fp = getattr(b, "footprint", None) or []
                if len(fp) < 3:
                    continue
                # Centroid (simple average). Deterministic and dependency-free.
                xs = [float(p[0]) for p in fp]
                ys = [float(p[1]) for p in fp]
                cx = sum(xs) / float(len(xs))
                cy = sum(ys) / float(len(ys))
                items.append(
                    {
                        "x": cx,
                        "y": cy,
                        "z": float(z_default),
                        "yaw": 0.0,
                        "type": "building",
                        "height": float(getattr(b, "height", 10.0) or 10.0),
                        "id": getattr(b, "id", None),
                        "name": getattr(b, "name", None),
                    }
                )

            payload = {"buildings": items, "metadata": {"count": len(items)}}
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            return out_path
        except Exception:
            return None

    # ---------------------------
    # 📂 Attempt 1: GeoJSON
    # ---------------------------
    buildings = []
    source = None
    enrichments_json_path = None

    loaded_geojson = 0
    loaded_osm = 0
    if buildings_geojson_path:
        if os.path.exists(buildings_geojson_path):
            geojson_like = is_real_geojson(buildings_geojson_path)
            try:
                buildings = OSMPolygonLoader.load_buildings_from_geojson(
                    buildings_geojson_path
                )
                loaded_geojson = len(buildings)
                source = "geojson" if geojson_like else "overpass_json"
                print(
                    f"🏙️ [BUILDINGS] Building JSON loader returned {len(buildings)} footprints"
                )
            except FileNotFoundError as e:
                print(f"⚠️ [BUILDINGS] Building loader: {e}. Continuing with 0 buildings.")
                vreport.add("warning", "buildings", f"Building JSON source missing: {e}")
                buildings = []
            except Exception as e:
                print(f"❌ [BUILDINGS] Building JSON loader failed: {e}")
                vreport.add("warning", "buildings", f"Building JSON load failed: {e}")
        else:
            msg = (
                f"OSM/GeoJSON source file not found: {buildings_geojson_path}. "
                "Ensure the Overpass JSON export is present at the expected path."
            )
            print(f"⚠️ [BUILDINGS] Building loader: {msg}. Continuing with 0 buildings.")
            vreport.add("warning", "buildings", f"Building JSON source missing: {msg}")

    inserted = 0
    if buildings:
        inserted = BuildingExtruder.insert_buildings(root, buildings)
        print(f"🏙️ [BUILDINGS] Inserted {inserted} buildings from GeoJSON")

        # Emit proxy-spawn artifact for CARLA visual QA (does not change stage contracts)
        if out_dir:
            p = _write_building_enrichments_json(out_dir, buildings)
            if p:
                enrichments_json_path = p
                vreport.add_dict("buildings_enrichments", {"json_path": p})

    # ---------------------------
    # 🔄 Fallback: OSM XML
    # ---------------------------
    if inserted == 0:
        print(
            "⚠️ [BUILDINGS] No buildings inserted from GeoJSON — falling back to OSM XML"
        )

        try:
            buildings = OSMPolygonLoader.load_buildings_from_osm(
                osm_path,
                ref_lat=gps_bounds["lat_min"],
                ref_lon=gps_bounds["lon_min"],
            )
            loaded_osm = len(buildings)
            print(f"🏙️ [BUILDINGS] OSM loader returned {len(buildings)} footprints")

            if buildings:
                inserted = BuildingExtruder.insert_buildings(root, buildings)
                source = "osm"
                print(f"🏙️ [BUILDINGS] Inserted {inserted} buildings from OSM XML")

                # Emit proxy-spawn artifact for CARLA visual QA
                if out_dir:
                    p = _write_building_enrichments_json(out_dir, buildings)
                    if p:
                        enrichments_json_path = p
                        vreport.add_dict("buildings_enrichments", {"json_path": p})

        except FileNotFoundError as e:
            print(f"⚠️ [BUILDINGS] Building loader: {e}. Continuing with 0 buildings.")
            vreport.add("warning", "buildings", f"OSM source missing: {e}")
        except Exception as e:
            print(f"❌ [BUILDINGS] OSM fallback failed: {e}")
            vreport.add("error", "buildings", f"OSM fallback failed: {e}")

    # ---------------------------
    # 📊 Final reporting
    # ---------------------------
    inserted_xodr_count = len(root.findall(".//object[@type='building']"))
    if inserted == 0:
        msg = "No buildings inserted from GeoJSON or OSM"
        print(f"❌ [BUILDINGS] {msg}")
        vreport.add("warning", "buildings", msg)
    vreport.add_dict(
        "buildings",
        {
            "inserted": inserted,
            "source": source,
            "buildings_loaded_geojson": int(loaded_geojson),
            "buildings_loaded_osm": int(loaded_osm),
            "buildings_inserted_xodr": int(inserted_xodr_count),
            "buildings_enrichments_json_path": enrichments_json_path,
        },
    )

    return inserted


# --------------- 📦 Core / pipeline imports ----------------

# core
from ultimate_pipeline.core.xodr_sanitizer import XODRSanitizer
from ultimate_pipeline.core.odr_io import (
    load_xodr,
    save_xodr,
    force_georeference,
    handle_georeference,
    write_georeference_provenance,
    check_original_has_valid_georeference,
)
from ultimate_pipeline.core.validation_report import ValidationReport
from ultimate_pipeline.core.run_manifest import update_run_manifest
from ultimate_pipeline.utils.file_hashing import safe_md5_file
from ultimate_pipeline.core.carla_utils import (
    ensure_carla_ready,
    carla_load_xodr_with_restart,
)
from ultimate_pipeline.core.crash_classifier import CrashClassifier
from ultimate_pipeline.core.file_utils import ensure_dir
from ultimate_pipeline.core.repair_diff import diff_log
from ultimate_pipeline.core.xodr_statistics import XODRStatistics

# recovery / carla client

# osm
from ultimate_pipeline.osm.osm_downloader import ensure_osm_exists, OSMDownloader

# dem
from ultimate_pipeline.dem.dem_diagnostics import DEMDiagnostics
from ultimate_pipeline.dem.dem_auto_downloader import ensure_dem_exists

# topology
from ultimate_pipeline.topology.topology_linter import TopologyLinter
from ultimate_pipeline.topology.sumo_repair import SUMORepair
from ultimate_pipeline.topology.topology_repair import TopologyRepair
from ultimate_pipeline.topology.structure_scanner import StructureScanner
from ultimate_pipeline.topology.semantic_verifier import SemanticVerifier
from ultimate_pipeline.topology.roundabout_reconstructor import RoundaboutReconstructor
from ultimate_pipeline.topology.roundabout_rebuilder import RoundaboutRebuilder
from ultimate_pipeline.topology.structure_prune_legacy import prune

# geometry / elevation
from ultimate_pipeline.geometry.elevation_smoother import ElevationSmoother
from ultimate_pipeline.enrichment.elevation_importer import (
    ElevationImporter,
    build_dem_qc_report,
    summarize_dem_raster_stats,
)
from ultimate_pipeline.geometry.planview_smoother import PlanViewSmoother
from ultimate_pipeline.geometry.mesh_continuity_repairer import MeshContinuityRepairer
from ultimate_pipeline.geometry.laneoffset_smoother import LaneOffsetSmoother
from ultimate_pipeline.geometry.laneoffset_normalizer import (
    LaneOffsetNormalizer,
    normalize_junction_laneoffsets,
)
from ultimate_pipeline.geometry.crosssection_repair import CrossSectionRepair
from ultimate_pipeline.geometry.lane_width_clamp import LaneWidthClamp
from ultimate_pipeline.geometry.lanesection_boundary_fixer import (
    LaneSectionBoundaryFixer,
)
from ultimate_pipeline.geometry.geometry_validator import GeometryValidator

# lanes / tile seam
from ultimate_pipeline.tile_validation.lane_seam_checker import LaneSeamChecker
from ultimate_pipeline.lanes.lane_repair import LaneRepair
from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder
from ultimate_pipeline.lanes.markings_builder import MarkingBuilder
from ultimate_pipeline.enrichment.lane_generator import LaneGenerator

# enrichment
from ultimate_pipeline.enrichment.sidewalk_builder import SidewalkBuilder
from ultimate_pipeline.enrichment.traffic_light_infer import TrafficLightInferer
from ultimate_pipeline.enrichment.building_extruder import BuildingExtruder
from ultimate_pipeline.enrichment.realism import RealismModule
from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader
from ultimate_pipeline.enrichment.osm2world_runner import (
    OSM2WorldRunner,
    is_osm2world_enabled,
)

# diagnostics
from ultimate_pipeline.diagnostics.pipeline_diagnostics import PipelineDiagnostics
from ultimate_pipeline.diagnostics.mesh_checker import MeshChecker
from ultimate_pipeline.diagnostics.xodr_cropper_gps import XODRCropperGPS

# visualization
from ultimate_pipeline.visualization.map_plotter import MapPlotter

# ---- Preview safety wrapper (matplotlib failures should not crash the pipeline) ----
try:
    _UP_ORIG_SAVE_PREVIEW = MapPlotter.save_preview

    def _up_safe_save_preview(*args, **kwargs):
        try:
            return _UP_ORIG_SAVE_PREVIEW(*args, **kwargs)
        except Exception as e:
            stage = kwargs.get("stage", None)
            out_dir = None
            try:
                if len(args) >= 2:
                    out_dir = args[1]
            except Exception:
                out_dir = None

            # Best-effort: write error artifact next to outputs
            if out_dir:
                try:
                    import os as _os

                    _os.makedirs(out_dir, exist_ok=True)
                    fname = (
                        f"map_preview_{stage}_ERROR.txt"
                        if stage
                        else "map_preview_ERROR.txt"
                    )
                    with open(
                        _os.path.join(out_dir, fname),
                        "w",
                        encoding="utf-8",
                        errors="replace",
                    ) as f:
                        f.write(str(e))
                except Exception:
                    pass

            print(f"⚠️ MapPlotter.save_preview failed (stage={stage}): {e}")
            return None

    # Preserve staticmethod behavior if MapPlotter.save_preview was declared as @staticmethod
    try:
        MapPlotter.save_preview = staticmethod(_up_safe_save_preview)
    except Exception:
        MapPlotter.save_preview = _up_safe_save_preview
except Exception:
    pass

from ultimate_pipeline.visualization.animated_diff import AnimatedDiff
from ultimate_pipeline.visualization.heatmap_generator import HeatmapGenerator
from ultimate_pipeline.visualization.lane_overlay import LaneOverlay
from ultimate_pipeline.visualization.cross_section_visualizer import (
    CrossSectionVisualizer,
)

# tiling
from ultimate_pipeline.tiling.tile_extractor import TileExtractor
from ultimate_pipeline.tiling.tile_adjacency import TileAdjacency
from ultimate_pipeline.tiling.tile_metadata import TileMetadata

# scenarios
from ultimate_pipeline.scenarios.auto_scenario_generator import AutoScenarioGenerator

# CARLA tools

# spawn / QA
from ultimate_pipeline.carla_tools.spawn_validator import SpawnValidator

# tile stress tester

# screenshots
from ultimate_pipeline.tiling.tile_adjacency import TileAdjacency

# quality gates
from ultimate_pipeline.quality.quality_gate_manager import QualityGateManager
from ultimate_pipeline.quality.check_xml_integrity import *
from ultimate_pipeline.quality.check_physics_feasibility import *
from ultimate_pipeline.quality.check_randomness_entropy import *
from ultimate_pipeline.quality.check_semantic_overlap import *
from ultimate_pipeline.quality.collision_mesh import *
from ultimate_pipeline.core.xodr_lightener import strip_heavy_xodr_layers
from ultimate_pipeline.ml.lane_gnn_refiner import LaneGNNRefiner
from ultimate_pipeline.quality.check_lane_section_successors import (
    repair_and_assert_lane_section_successors,
)

# optional schema checks
from ultimate_pipeline.quality.check_xodr_schema import (
    check_xml_uniqueness,
    validate_xodr_schema,
)

# single-road debug
from ultimate_pipeline.debug.single_road_extractor import SingleRoadExtractor
from ultimate_pipeline.tiling.tile_auto_forensics import TileAutoForensics

# LLM quality gate (final review)
from ultimate_pipeline.llm.llm_quality_gate import LLMQualityGate

# domain gap runner (your existing script)
from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap
from ultimate_pipeline.quality.check_lane_connectivity import (
    assert_all_lanes_have_successors,
    write_lane_connectivity_report,
    downgrade_broken_driving_lanes_to_none,
    autofix_missing_lane_successors,
)
from ultimate_pipeline.quality.check_lane_link_targets_exist import (
    check_lane_link_targets_exist,
)
from ultimate_pipeline.quality.carla_pruner import CarlaSafetyPruner
from ultimate_pipeline.quality.lane_width_invariants import (
    enforce_lane_width_invariants,
    default_report_path,
)
from ultimate_pipeline.core.georef_utils import (
    normalize_georeference,
    parse_georeference,
)

try:
    from ultimate_pipeline.map_fixes.xodr_junction_links import patch_junction_links
except Exception as exc:
    raise RuntimeError(
        "Failed to import patch_junction_links from "
        "ultimate_pipeline.map_fixes.xodr_junction_links. "
        "Ensure ultimate_pipeline/map_fixes/xodr_junction_links.py exists and defines "
        "patch_junction_links(in_xodr, out_xodr, report_json, tolerance_m=5.0)."
    ) from exc

if not callable(patch_junction_links):
    raise RuntimeError(
        "patch_junction_links import succeeded but is not callable. "
        "Check ultimate_pipeline/map_fixes/xodr_junction_links.py export."
    )


def run_junction_link_integrity_gate(
    *,
    input_xodr_path: str | Path,
    out_dir: str | Path,
    enable_patch: bool = True,
    tolerance_m: float = 5.0,
) -> Dict[str, Any]:
    """Apply the thesis junction-link integrity gate and return selected XODR/report."""
    in_path = Path(input_xodr_path).expanduser().resolve()
    out_root = Path(out_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    xodr_link_report_path = out_root / "xodr_link_integrity.json"
    patch_report_path = out_root / "junction_link_patch_report.json"

    lane_pre = check_lane_link_targets_exist(str(in_path))
    lane_pre_ok = bool(lane_pre.get("ok", False))
    lane_pre_issues = int(lane_pre.get("num_issues", 0) or 0)
    selected_xodr = in_path

    if not enable_patch:
        if not lane_pre_ok:
            raise RuntimeError(
                "Junction link integrity gate failed before patch and "
                "ENABLE_JUNCTION_LINK_PATCH is disabled."
            )
        report = {
            "roads_total": None,
            "junctions_total": None,
            "added_junction_links": 0,
            "missing_road_to_junction_links_before": 0,
            "missing_road_to_junction_links_after": 0,
            "remaining_unlinked_nonjunction_roads": 0,
            "suspicious_matches": [],
            "notes": [
                "Junction link patch stage skipped (ENABLE_JUNCTION_LINK_PATCH=false)."
            ],
            "remaining_unlinked_incoming_roads": 0,
            "output_xodr_path": str(in_path.name),
            "input_xodr_sha256": _hash_file(str(in_path)),
            "output_xodr_sha256": _hash_file(str(in_path)),
            "modified": False,
            "patch_enabled": False,
            "lane_link_target_gate_pre": {
                "ok": lane_pre_ok,
                "num_issues": lane_pre_issues,
            },
            "lane_link_target_gate_post": {
                "ok": lane_pre_ok,
                "num_issues": lane_pre_issues,
            },
        }
    else:
        patched_out = in_path.with_name(f"{in_path.stem}_linkpatched.xodr")
        report = patch_junction_links(
            in_xodr=in_path,
            out_xodr=patched_out,
            report_json=xodr_link_report_path,
            tolerance_m=float(tolerance_m),
        )
        selected_xodr = patched_out

        lane_post = check_lane_link_targets_exist(str(selected_xodr))
        lane_post_ok = bool(lane_post.get("ok", False))
        lane_post_issues = int(lane_post.get("num_issues", 0) or 0)
        report["patch_enabled"] = True
        report["lane_link_target_gate_pre"] = {
            "ok": lane_pre_ok,
            "num_issues": lane_pre_issues,
        }
        report["lane_link_target_gate_post"] = {
            "ok": lane_post_ok,
            "num_issues": lane_post_issues,
        }

        remaining_after = report.get("missing_road_to_junction_links_after")
        if remaining_after is None:
            remaining_after = report.get("remaining_unlinked_incoming_roads", 0)
        if int(remaining_after or 0) != 0:
            xodr_link_report_path.write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            patch_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            raise RuntimeError(
                "Junction link integrity gate failed after patch: "
                "missing_road_to_junction_links_after != 0. "
                f"See {xodr_link_report_path}"
            )
        if not lane_post_ok:
            xodr_link_report_path.write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            patch_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            raise RuntimeError(
                "Lane-link target existence gate failed after junction-link patch. "
                f"See {xodr_link_report_path}"
            )

    xodr_link_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    patch_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {"final_xodr": str(selected_xodr), "report": report}


class MainPipeline:
    def __init__(self, settings=None):
        self.settings = settings if settings is not None else _get_settings()
        _validate_global_safety_settings(self.settings)
        self.out_dir = self.settings.output_dir()
        ensure_dir(self.out_dir)

        # Optional preanchoring provenance (opt-in; default OFF)
        self._preanchor_manifest: dict = {"applied": False}
        self._sumo_repair_meta: dict = {"enabled": False}

        self.vreport = ValidationReport()
        self.qgate = QualityGateManager(self.vreport, logs_dir=self.settings.logs_dir())

        # 🚗 CARLA client (reliable, with recovery)
        self.client: Optional[carla.Client] = None
        # ---------------- 🧠 SEMANTIC STATE ----------------
        # What the pipeline can *guarantee* at each stage
        self.semantic_state = {
            "has_geometry": False,
            "has_elevation": False,
            "has_planview": False,
            "has_lanes": False,
        }
        self._run_stage: str = "init"
        self._gate_runner: CumulativeGateRunner | None = None

    def _write_run_status(
        self,
        *,
        status: str,
        stage: str,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        try:
            payload = {
                "status": str(status),
                "stage": str(stage),
                "message": message,
                "error": error,
                "out_dir": self.out_dir,
                "timestamp": datetime.now().isoformat(),
            }
            with open(
                os.path.join(self.out_dir, "run_status.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(payload, f, indent=2, ensure_ascii=True)
        except Exception:
            pass

    def _mark_stage(self, stage: str, *, message: str | None = None) -> None:
        self._run_stage = str(stage)
        self._write_run_status(status="running", stage=self._run_stage, message=message)

    # -----------------------------------------------------
    # 🚀 MAIN ENTRY
    # -----------------------------------------------------

    # -----------------------------------------------------
    # 🧨 CARLA isolation (prevents native fast-fail from killing orchestrator)
    # -----------------------------------------------------
    def _carla_isolation_enabled(self) -> bool:
        """
        On Windows, CARLA's native PythonAPI can hard-crash the *entire* process (0xC0000409).
        Isolation mode keeps the orchestrator process CARLA-free by running CARLA work in subprocesses.

        Defaults:
          - Windows: ON
          - non-Windows: OFF

        Overrides:
          - UP_CARLA_ISOLATION=0   -> force OFF
          - UP_CARLA_ISOLATION=1   -> force ON
          - UP_INTERACTIVE=1       -> force OFF (interactive sim needs in-proc CARLA)
        """
        interactive = os.getenv("UP_INTERACTIVE", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if interactive:
            return False

        env = os.getenv("UP_CARLA_ISOLATION", "").strip().lower()
        if env in ("0", "false", "no", "off"):
            return False
        if env in ("1", "true", "yes", "on"):
            return True

        return os.name == "nt"

    def _carla_host_port(self) -> tuple[str, int]:
        host = getattr(self.settings, "CARLA_HOST", "127.0.0.1")
        port = int(getattr(self.settings, "CARLA_PORT", 2000))
        return host, port

    @staticmethod
    def _read_georef_info(path: str) -> dict:
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            header = root.find("header")
            if header is None:
                return {"valid": False, "params_complete": False, "norm": "", "raw": ""}
            geo = header.find("geoReference")
            raw = geo.text if geo is not None and geo.text is not None else ""
            valid, params_complete, norm = parse_georeference(raw)
            return {
                "valid": bool(valid),
                "params_complete": bool(params_complete),
                "norm": str(norm or ""),
                "raw": str(raw or ""),
            }
        except Exception:
            return {"valid": False, "params_complete": False, "norm": "", "raw": ""}

    @staticmethod
    def _read_offset(path: str) -> dict:
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            header = root.find("header")
            if header is None:
                return {}
            off = header.find("offset")
            if off is None:
                return {}
            return {
                "x": float(off.get("x", "0.0")),
                "y": float(off.get("y", "0.0")),
                "z": float(off.get("z", "0.0")),
                "hdg": float(off.get("hdg", "0.0")),
            }
        except Exception:
            return {}

    @staticmethod
    def _offset_large(offset: dict, threshold_m: float = 100000.0) -> bool:
        try:
            x = float(offset.get("x", 0.0))
            y = float(offset.get("y", 0.0))
            return abs(x) >= threshold_m or abs(y) >= threshold_m
        except Exception:
            return False

    @staticmethod
    def _sha256_file(path: str) -> str:
        try:
            import hashlib

            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    def _maybe_preanchor_input_xodr(self, run_dir: Path) -> None:
        self._preanchor_manifest = {"applied": False}
        # Backward-compatible enablement:
        # - Prefer settings.PREANCHOR_INPUT_XODR (new)
        # - Fallback to env var so script-mode runs can't silently miss enablement
        env_enable = os.getenv("UP_PREANCHOR_INPUT_XODR", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if not (bool(getattr(self.settings, "PREANCHOR_INPUT_XODR", False)) or env_enable):
            return

        s = self.settings

        if not hasattr(s, "load_gps_bounds"):
            raise RuntimeError(
                "UP_PREANCHOR_INPUT_XODR=1 requires GPS bounds; settings.load_gps_bounds() not available"
            )

        gps_bounds = s.load_gps_bounds()
        if not isinstance(gps_bounds, dict):
            raise RuntimeError(
                "UP_PREANCHOR_INPUT_XODR=1 requires GPS bounds (lat_min/lat_max/lon_min/lon_max)"
            )
        try:
            lat_min = float(gps_bounds["lat_min"])
            lat_max = float(gps_bounds["lat_max"])
            lon_min = float(gps_bounds["lon_min"])
            lon_max = float(gps_bounds["lon_max"])
        except Exception as e:
            raise RuntimeError(
                "UP_PREANCHOR_INPUT_XODR=1 requires GPS bounds (lat_min/lat_max/lon_min/lon_max)"
            ) from e

        lat_center = (lat_min + lat_max) / 2.0
        lon_center = (lon_min + lon_max) / 2.0

        input_xodr = Path(str(getattr(s, "INPUT_XODR", "")))
        if not input_xodr.is_file():
            raise FileNotFoundError(
                f"UP_PREANCHOR_INPUT_XODR=1 but INPUT_XODR not found: {input_xodr}"
            )

        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        anchored = run_dir / "00_input_preanchored.xodr"

        from tools.preanchor_xodr import preanchor_xodr as _preanchor_xodr

        report = _preanchor_xodr(
            input_xodr,
            anchored,
            lat_center=float(lat_center),
            lon_center=float(lon_center),
        )

        input_sha256 = self._sha256_file(str(input_xodr))
        output_sha256 = self._sha256_file(str(anchored))

        report_payload = dict(report) if isinstance(report, dict) else {"report": report}
        report_payload.update(
            {
                "input_xodr_sha256": input_sha256,
                "output_xodr_sha256": output_sha256,
            }
        )

        preanchor_report_path = run_dir / "preanchor_report.json"
        preanchor_report_path.write_text(
            json.dumps(report_payload, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

        # Switch effective input for this run only (do not overwrite user config on disk)
        s.INPUT_XODR = str(anchored)

        self._preanchor_manifest = {
            "applied": True,
            "input_xodr_path": str(input_xodr),
            "input_xodr_sha256": input_sha256,
            "output_xodr_path": str(anchored),
            "output_xodr_sha256": output_sha256,
            "gps_center": {"lat_center": float(lat_center), "lon_center": float(lon_center)},
            "offset_written": report.get("offset_written") if isinstance(report, dict) else None,
            "bounds_written": report.get("bounds_written") if isinstance(report, dict) else None,
            "manual_crs": report.get("manual_crs") if isinstance(report, dict) else None,
        }

        # Small, easy-to-grep sentinel for evidence capture.
        try:
            (Path(run_dir) / "preanchor_applied.txt").write_text(
                "preanchor_applied=true\n",
                encoding="utf-8",
            )
        except Exception:
            pass

    def _write_crs_comparability(
        self,
        auto_xodr: str,
        policy_used: str,
        georef_decision: dict,
    ) -> str:
        """
        Write crs_comparability.json documenting CRS alignment between manual and auto XODR.

        This ensures manual and auto XODR are comparable in CRS without modifying
        manual coordinates. The report shows whether the auto map's geoReference
        matches the manual map after any policy-based overrides.

        Args:
            auto_xodr: Path to the auto (sanitized/working) XODR file
            policy_used: The geoReference policy applied ("preserve" or "force")
            georef_decision: Decision struct from handle_georeference()

        Returns:
            Path to the written crs_comparability.json
        """
        # Prefer explicit env overrides, then fall back to settings.MANUAL_MAP_XODR for consistency.
        manual_xodr = (
            os.getenv("UP_MANUAL_XODR_GRID0828")
            or os.getenv("UP_MANUAL_XODR")
            or str(getattr(self.settings, "MANUAL_MAP_XODR", "") or "")
        )
        # Relative paths fail silently in subprocesses — absolute path required.
        if manual_xodr and not os.path.isabs(manual_xodr):
            raise RuntimeError(
                f"UP_MANUAL_XODR must be an absolute path; got relative: {manual_xodr!r}. "
                "Set UP_MANUAL_XODR to the full absolute path of the manual reference XODR."
            )
        manual_present = bool(manual_xodr and os.path.isfile(manual_xodr))
        # Repo-local fallback for thesis strict: try well-known manual maps if env/settings are empty.
        # Strict still fails closed if nothing exists.
        if not manual_present:
            try:
                repo_root = Path(__file__).resolve().parents[1]
                for name in (
                    "manual_ingolstadt_grid0828.xodr",
                    "Grid0821.xodr",
                    "Grid0828.xodr",
                ):
                    c = repo_root / "manual_maps" / name
                    if c.exists() and c.is_file():
                        manual_xodr = str(c)
                        manual_present = True
                        break
            except Exception:
                pass

        thesis_strict = (
            os.getenv("UP_THESIS_STRICT", "").strip().lower() in ("1", "true", "yes", "on")
            or bool(getattr(self.settings, "THESIS_STRICT", False))
        )
        if thesis_strict and not manual_present:
            raise RuntimeError(
                "Thesis strict CRS comparability requires a manual reference XODR. "
                "Set UP_MANUAL_XODR to a valid .xodr path (or settings.MANUAL_MAP_XODR)."
            )

        # Read manual XODR info (read-only, no modifications)
        manual_info = {"valid": False, "params_complete": False, "norm": "", "raw": ""}
        manual_hash = ""
        if manual_present:
            manual_info = self._read_georef_info(manual_xodr)
            manual_hash = self._sha256_file(manual_xodr)

        # Read auto XODR info (current state after geoReference handling)
        auto_info = self._read_georef_info(auto_xodr)
        offset = self._read_offset(auto_xodr)
        offset_large = self._offset_large(offset)

        # Determine if override would be applied (for forced_to_manual policy)
        # This mirrors the logic in _maybe_override_final_georef
        would_force_to_manual = (
            manual_present
            and bool(manual_info["valid"])
            and bool(manual_info["norm"])
            and (not auto_info["params_complete"])
            and offset_large
        )

        # Determine effective policy description
        if policy_used == "preserve" and georef_decision["action"] == "kept":
            effective_policy = "preserve"
        elif policy_used == "force" or georef_decision["action"] in (
            "created",
            "patched",
        ):
            effective_policy = (
                "patched" if georef_decision["action"] == "patched" else "force"
            )
        else:
            effective_policy = policy_used

        # Check if override would force auto to match manual
        if would_force_to_manual:
            effective_policy = "forced_to_manual"

        # Check CRS match
        crs_match = (
            manual_present
            and manual_info["norm"]
            and auto_info["norm"]
            and manual_info["norm"] == auto_info["norm"]
        )

        report = {
            "schema_version": "1.0",
            "manual": {
                "xodr_path": manual_xodr if manual_present else None,
                "xodr_sha256": manual_hash if manual_present else None,
                "geoReference_norm": manual_info["norm"] if manual_present else None,
                "params_complete": manual_info["params_complete"]
                if manual_present
                else None,
                "present": manual_present,
            },
            "auto": {
                "xodr_path": auto_xodr,
                "geoReference_norm": auto_info["norm"],
                "params_complete": auto_info["params_complete"],
            },
            "offsets": {
                "x": offset.get("x", 0.0),
                "y": offset.get("y", 0.0),
                "z": offset.get("z", 0.0),
                "hdg": offset.get("hdg", 0.0),
                "offset_large": offset_large,
                "offset_large_threshold_m": 100000.0,
            },
            "policy": {
                "requested": policy_used,
                "effective": effective_policy,
                "would_force_to_manual": would_force_to_manual,
            },
            "comparability": {
                "crs_match": crs_match,
                "auto_proj4_matches_manual": crs_match,
                "manual_file_unchanged": True,  # We never modify manual
            },
            "georef_action": georef_decision["action"],
            "georef_reason": georef_decision["reason"],
        }

        out_path = os.path.join(self.out_dir, "crs_comparability.json")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=True)
        except Exception as exc:
            print(f"[WARN] Failed to write crs_comparability.json: {exc}")
            return ""

        return out_path

    def _maybe_override_final_georef(self, final_out: str) -> None:
        manual_xodr = (
            os.getenv("UP_MANUAL_XODR_GRID0828") or os.getenv("UP_MANUAL_XODR") or ""
        )
        manual_info = {"valid": False, "params_complete": False, "norm": "", "raw": ""}
        manual_hash = ""
        # Relative paths fail silently in subprocesses — absolute path required.
        if manual_xodr and not os.path.isabs(manual_xodr):
            raise RuntimeError(
                f"UP_MANUAL_XODR must be an absolute path; got relative: {manual_xodr!r}. "
                "Set UP_MANUAL_XODR to the full absolute path of the manual reference XODR."
            )
        manual_present = bool(manual_xodr and os.path.isfile(manual_xodr))
        if manual_present:
            manual_info = self._read_georef_info(manual_xodr)
            manual_hash = self._sha256_file(manual_xodr)

        auto_info = self._read_georef_info(final_out)
        offset = self._read_offset(final_out)
        auto_hash_before = self._sha256_file(final_out)

        apply_override = (
            manual_present
            and bool(manual_info["valid"])
            and bool(manual_info["norm"])
            and (not auto_info["params_complete"])
            and self._offset_large(offset)
        )
        provenance = {
            "action": "skipped",
            "reason": "",
            "manual_xodr": manual_xodr if manual_present else "",
            "manual_georef_raw": manual_info["raw"],
            "manual_proj4_norm": manual_info["norm"],
            "manual_params_complete": manual_info["params_complete"],
            "manual_xodr_sha256": manual_hash,
            "auto_georef_raw_before": auto_info["raw"],
            "auto_proj4_norm_before": auto_info["norm"],
            "auto_params_complete_before": auto_info["params_complete"],
            "auto_xodr_sha256_before": auto_hash_before,
            "offset": offset,
        }

        try:
            tree = ET.parse(final_out)
            root = tree.getroot()
            header = root.find("header")
            if header is None:
                header = ET.SubElement(root, "header")
            geo = header.find("geoReference")
            if geo is None:
                geo = ET.SubElement(header, "geoReference")
            if apply_override:
                geo.text = normalize_georeference(manual_info["norm"])
                tree.write(final_out, encoding="utf-8", xml_declaration=True)
                provenance["action"] = "applied"
                provenance["reason"] = "auto_georef_incomplete_and_offset_large"
            else:
                if auto_info["norm"]:
                    geo.text = normalize_georeference(auto_info["norm"])
                    tree.write(final_out, encoding="utf-8", xml_declaration=True)
                if not manual_present:
                    provenance["reason"] = "manual_xodr_missing"
                elif not manual_info["valid"]:
                    provenance["reason"] = "manual_georef_invalid"
                elif auto_info["params_complete"]:
                    provenance["reason"] = "auto_georef_complete"
                else:
                    provenance["reason"] = "offset_small_or_missing"
        except Exception as exc:
            provenance["action"] = "failed"
            provenance["reason"] = f"exception:{exc.__class__.__name__}"

        after_info = self._read_georef_info(final_out)
        auto_hash_after = self._sha256_file(final_out)
        provenance["auto_georef_raw_after"] = after_info["raw"]
        provenance["auto_proj4_norm_after"] = after_info["norm"]
        provenance["auto_xodr_sha256_after"] = auto_hash_after

        try:
            out_path = os.path.join(self.out_dir, "georef_override.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(provenance, f, indent=2, ensure_ascii=True)
            print(f"[STEP 8] georef_override.json -> {out_path}")
        except Exception:
            pass

    @staticmethod
    def _is_win_hard_crash_rc(rc: int) -> bool:
        # Normalize Windows signed return codes to unsigned.
        rc_u32 = int(rc) & 0xFFFFFFFF
        return rc_u32 in (
            0xC0000409,
            0xC0000005,
        )  # fastfail/stack overrun, access violation

    def _run_subprocess(
        self,
        cmd: list[str],
        *,
        log_path: Optional[str] = None,
        timeout_s: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> dict:
        """Run a subprocess; never raise; return a structured result."""
        import subprocess
        import time

        t0 = time.time()
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        try:
            if log_path:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
                    p = subprocess.run(
                        cmd,
                        stdout=lf,
                        stderr=subprocess.STDOUT,
                        timeout=timeout_s,
                        env=merged_env,
                    )
                rc = int(p.returncode)
                return {
                    "ok": rc == 0,
                    "return_code": rc,
                    "hard_crash": bool(self._is_win_hard_crash_rc(rc))
                    if os.name == "nt"
                    else False,
                    "log_path": log_path,
                    "elapsed_s": round(time.time() - t0, 3),
                    "cmd": cmd,
                }

            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                env=merged_env,
            )
            rc = int(p.returncode)
            return {
                "ok": rc == 0,
                "return_code": rc,
                "hard_crash": bool(self._is_win_hard_crash_rc(rc))
                if os.name == "nt"
                else False,
                "stdout": (p.stdout or "")[-4000:],
                "stderr": (p.stderr or "")[-4000:],
                "elapsed_s": round(time.time() - t0, 3),
                "cmd": cmd,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "return_code": None,
                "hard_crash": False,
                "timeout": True,
                "stdout": (getattr(exc, "stdout", "") or "")[-4000:],
                "stderr": (getattr(exc, "stderr", "") or "")[-4000:],
                "elapsed_s": round(time.time() - t0, 3),
                "cmd": cmd,
            }
        except Exception as exc:
            return {
                "ok": False,
                "return_code": None,
                "hard_crash": False,
                "exception": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.time() - t0, 3),
                "cmd": cmd,
            }

    def _carla_smoke_load_subprocess(
        self,
        *,
        xodr_path: str,
        label: str,
        spawn_ego: bool = False,
        tick_frames: int = 0,
        screenshot: bool = False,
        timeout_s: int = 180,
    ) -> dict:
        """
        Load an OpenDRIVE into CARLA in a subprocess and return smoke_suite.json payload.

        This is the safe replacement for in-process carla_load_xodr_with_restart() when isolation is enabled.
        """
        import json as _json
        from pathlib import Path as _Path

        host, port = self._carla_host_port()
        out_dir = _Path(self.out_dir) / "carla_smoke" / label
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            "-u",
            "-m",
            "ultimate_pipeline.tools.carla_smoke_suite",
            "--xodr",
            str(xodr_path),
            "--host",
            str(host),
            "--port",
            str(port),
            "--timeout",
            str(float(timeout_s)),
            "--out",
            str(out_dir),
        ]
        if spawn_ego:
            cmd.append("--spawn-ego")
        if tick_frames > 0:
            cmd += ["--tick-frames", str(int(tick_frames))]
        if screenshot:
            cmd.append("--screenshot")

        log_path = str(out_dir / "smoke_suite.log")
        run_res = self._run_subprocess(
            cmd, log_path=log_path, timeout_s=max(30, int(timeout_s) + 30)
        )
        payload_path = out_dir / "smoke_suite.json"
        payload: dict = {}
        try:
            if payload_path.exists():
                payload = _json.loads(
                    payload_path.read_text(encoding="utf-8", errors="replace")
                )
        except Exception:
            payload = {}

        return {
            "label": label,
            "xodr": str(xodr_path),
            "host": host,
            "port": port,
            "run": run_res,
            "payload_path": str(payload_path),
            "payload": payload,
        }

    def _write_tmp_worker(self, name: str, code: str) -> str:
        """Write a temporary worker script under out_dir and return its path.

        Prepends sys.path injection so worker scripts can import ultimate_pipeline modules.
        """
        tmp_dir = os.path.join(self.out_dir, "_tmp_workers")
        os.makedirs(tmp_dir, exist_ok=True)
        path = os.path.join(tmp_dir, f"{name}.py")

        # Prepend sys.path injection for stable imports
        # This ensures workers can import ultimate_pipeline regardless of cwd
        repo_root = Path(__file__).resolve().parents[1]  # ultimate_pipeline's parent
        preamble = f'''# Auto-generated worker script - DO NOT EDIT
import sys
from pathlib import Path
_repo_root = Path(r"{repo_root}")
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
# Original worker code follows:
'''
        with open(path, "w", encoding="utf-8") as f:
            f.write(preamble + code)
        return path

    def _run_carla_worker_script(
        self, *, name: str, code: str, timeout_s: int = 300
    ) -> dict:
        """Run a CARLA-using worker in a subprocess (safe for orchestrator)."""
        script_path = self._write_tmp_worker(name, code)
        log_path = os.path.join(self.out_dir, "_tmp_workers", f"{name}.log")
        cmd = [sys.executable, "-u", script_path]
        # Pass parent output dir so workers know where to write artifacts
        worker_env = {"UP_PARENT_OUT_DIR": self.out_dir}
        return self._run_subprocess(
            cmd, log_path=log_path, timeout_s=timeout_s, env=worker_env
        )

    def run(self) -> str:
        """Run the pipeline and return the output directory.

        📚 Research-grade behavior:
        - on success: returns self.out_dir
        - on failure: writes crash artifacts into self.out_dir and re-raises
        """
        try:
            settings_blob = json.dumps(
                {
                    k: getattr(self.settings, k)
                    for k in dir(self.settings)
                    if k.isupper() and not callable(getattr(self.settings, k))
                },
                sort_keys=True,
                default=str,
            )
            settings_hash = hashlib.sha256(settings_blob.encode("utf-8")).hexdigest()
            self.vreport.add_dict("settings_fingerprint", {"sha256": settings_hash})
            _configure_windows_encoding()
            _preflight_import_sanity()
            self._mark_stage("start")
            self._run_internal()
            try:
                from ultimate_pipeline.quality.pipeline_health_summary import (
                    write_pipeline_health_summary,
                )

                write_pipeline_health_summary(self.out_dir)
            except Exception as e:
                print(f"⚠️ Pipeline health summary skipped: {e}")
            self._write_run_status(status="ok", stage="done")
            return self.out_dir
        except Exception as e:
            # Keep console signal for local debugging
            print("❌ PIPELINE CRASHED:", e)
            traceback.print_exc()

            # Best-effort crash artifacts (thesis/reproducibility friendly)
            try:
                ensure_dir(self.out_dir)
                crash_txt = os.path.join(self.out_dir, "crash_traceback.txt")
                with open(crash_txt, "w", encoding="utf-8") as f:
                    f.write(traceback.format_exc())

                crash_json = os.path.join(self.out_dir, "crash_summary.json")
                with open(crash_json, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "exception_type": type(e).__name__,
                            "message": str(e),
                            "out_dir": self.out_dir,
                        },
                        f,
                        indent=2,
                    )
                self._write_run_status(
                    status="failed", stage=self._run_stage, error=str(e)
                )
            except Exception as artifact_exc:
                # Never mask the real failure due to artifact-writing issues.
                # Still surface artifact persistence failure for auditability.
                print(
                    f"⚠️ Failed to write crash/status artifacts while handling pipeline failure: {artifact_exc}",
                    flush=True,
                )

            # IMPORTANT: re-raise so callers (scripts/HPC) get a non-zero exit
            raise

    # -----------------------------------------------------
    # 🔧 INTERNAL PIPELINE
    # -----------------------------------------------------
    def _run_internal(self) -> None:
        s = self.settings
        print("🔥 Ultimate OSM→OpenDRIVE→CARLA pipeline (consolidated)")

        # ---------------------------------------------------------
        # 📚 ARCHIVE OLD RUNS (disk hygiene + provenance)
        # ---------------------------------------------------------
        from ultimate_pipeline.database.run_archiver import RunArchiver

        RunArchiver(
            keep_last_n=getattr(self.settings, "KEEP_LAST_RUNS", 10)
        ).archive_old_runs()
        print(f"📥 Input XODR: {s.INPUT_XODR}")
        print(f"📤 Output dir: {self.out_dir}")

        # ---------------------------------------------------------

        # ---------------------------------------------------------
        # 🧩 OSM→XODR bootstrap (only if INPUT_XODR is missing)
        # ---------------------------------------------------------
        # If INPUT_XODR is missing, attempt to generate a seed XODR from the city's OSM extract.
        # This prevents accidental reuse of previous-run 08_final*.xodr when you intend
        # to start from OSM for controlled experiments.
        if not os.path.isfile(s.INPUT_XODR):
            try:
                import json as _json
                from ultimate_pipeline.osm.osm_to_xodr_wrapper import (
                    convert_osm_to_xodr,
                )

                gps_bounds = getattr(s, "GPS_BOUNDS", None)
                if isinstance(gps_bounds, str):
                    try:
                        gps_bounds = _json.loads(gps_bounds)
                    except Exception:
                        gps_bounds = None

                if not isinstance(gps_bounds, dict):
                    gps_bounds = {
                        "lat_min": float(getattr(s, "LAT_MIN", 0.0)),
                        "lat_max": float(getattr(s, "LAT_MAX", 0.0)),
                        "lon_min": float(getattr(s, "LON_MIN", 0.0)),
                        "lon_max": float(getattr(s, "LON_MAX", 0.0)),
                    }

                osm_path = getattr(s, "OSM_XML_PATH", None)
                if not osm_path:
                    city_name = _get_city_name()
                    osm_path = city_dir(city_name) / "osm" / f"{city_name}.osm"

                ensure_osm_exists(gps_bounds=gps_bounds, osm_path=osm_path)

                seed_xodr_path = Path(s.INPUT_XODR)
                seed_xodr_path.parent.mkdir(parents=True, exist_ok=True)
                convert_osm_to_xodr(
                    osm_path=str(osm_path), xodr_path=str(seed_xodr_path)
                )
                print(f"🧩 Bootstrapped INPUT_XODR from OSM → {seed_xodr_path}")
            except Exception as e:
                print(f"⚠️ Failed to bootstrap XODR from OSM (will error below): {e}")

        # 🔍 INPUT_XODR EXISTENCE CHECK (fail-fast with clear message)
        if not os.path.isfile(s.INPUT_XODR):
            searched_paths = [
                f"UP_INPUT_XODR env: {os.getenv('UP_INPUT_XODR', '(not set)')}",
                f"Default city path: {city_dir(_get_city_name()) / f'{_get_city_name()}_dominik.xodr'}",
                f"Fallback patterns in: {s.BASE_OUTPUT_DIR}/**/08_final*.xodr, **/07_*.xodr",
            ]
            raise FileNotFoundError(
                f"❌ INPUT_XODR not found: {s.INPUT_XODR}\n\n"
                "🔍 Searched locations:\n  - " + "\n  - ".join(searched_paths) + "\n\n"
                "💡 Solutions:\n"
                "  1. Set UP_INPUT_XODR=/path/to/your.xodr\n"
                f"  2. Place a file at: {city_dir(_get_city_name()) / f'{_get_city_name()}_dominik.xodr'}\n"
                "  3. Run the OSM→OpenDRIVE conversion first to generate an .xodr"
            )

        # ---------------------------------------------------------
        # 📍 OPTIONAL PREANCHOR (opt-in; fixes baseline input frame)
        # ---------------------------------------------------------
        self._maybe_preanchor_input_xodr(Path(self.out_dir))

        # ---------------------------------------------------------
        # 🗄️ DATABASE SAFETY CHECK (single authority)
        # ---------------------------------------------------------
        try:
            from ultimate_pipeline.database.db_manager import Database
            import hashlib

            print("📂 Verifying pipeline database...")
            db = Database()
            db._validate_schema()

            schema_repr = repr(db.EXPECTED_SCHEMA).encode("utf-8")
            self._db_info = {
                "path": str(db.db_path),
                "schema_hash_sha256": hashlib.sha256(schema_repr).hexdigest(),
                "schema_hash_md5": hashlib.md5(schema_repr).hexdigest(),
                "status": "ok",
            }

            self.vreport.add_dict("database", self._db_info)
            print("✅ Database schema OK")

        except Exception as e:
            raise RuntimeError(
                "❌ Database initialization or schema validation failed.\n"
                "Fix the DB before running the pipeline.\n"
                f"Reason: {e}"
            )

        print(f"📥 Input XODR: {s.INPUT_XODR}")
        print(f"📤 Output dir: {self.out_dir}")

        # ---------------------------------------------------------
        # 🔐 SETTINGS SNAPSHOT (research / reproducibility artifact)
        # ---------------------------------------------------------
        settings_snapshot_path = os.path.join(self.out_dir, "settings_snapshot.json")
        try:
            settings_dict = s.to_dict()
            settings_dict["_database"] = self._db_info
            settings_dict["_thesis_protocol"] = {
                "bbox": getattr(s, "GPS_BOUNDS", None),
                "osm_source": str(getattr(s, "OSM_FILE", "")),
                "smoothing_params": {
                    "MIN_GEOM_MERGE_LENGTH": getattr(s, "MIN_GEOM_MERGE_LENGTH", None),
                    "MAX_GEOM_MERGE_LENGTH": getattr(s, "MAX_GEOM_MERGE_LENGTH", None),
                    "CURVATURE_MAX_ALLOWED": getattr(s, "CURVATURE_MAX_ALLOWED", None),
                },
                "quarantine_thresholds": {
                    "max_fraction": os.getenv("UP_QUARANTINE_MAX_FRACTION", "0.008"),
                    "continuity_dxy_max_m": os.getenv(
                        "UP_QUARANTINE_CONTINUITY_DXY", "1.0"
                    ),
                    "continuity_dhdg_max_deg": os.getenv(
                        "UP_QUARANTINE_CONTINUITY_DHDG", "10.0"
                    ),
                    "heading_jump_max_deg": os.getenv(
                        "UP_QUARANTINE_HEADING_JUMP_DEG", "30.0"
                    ),
                    "curvature_abs_max": os.getenv(
                        "UP_QUARANTINE_CURVATURE_ABS", "0.5"
                    ),
                    "curvature_jump_max": os.getenv(
                        "UP_QUARANTINE_CURVATURE_JUMP", "0.5"
                    ),
                },
                "cli_args": list(sys.argv),
            }

            with open(settings_snapshot_path, "w", encoding="utf-8") as f:
                json.dump(settings_dict, f, indent=2)

            settings_hash = _hash_file(settings_snapshot_path)
            settings_hash_md5 = safe_md5_file(settings_snapshot_path)

            print(f"📝 [INFO] Settings snapshot written → {settings_snapshot_path}")
            print(f"🔐 Settings hash (SHA-256): {settings_hash}")
            print(
                f"🔐 Settings schema version: {getattr(s, 'SETTINGS_SCHEMA_VERSION', 'UNKNOWN')}"
            )

            self.vreport.add("settings", "snapshot_sha256", settings_hash)
            if settings_hash_md5:
                self.vreport.add("settings", "snapshot_md5", settings_hash_md5)
            if hasattr(s, "SETTINGS_SCHEMA_VERSION"):
                self.vreport.add(
                    "settings", "schema_version", s.SETTINGS_SCHEMA_VERSION
                )

            # ---------------------------------------------------------
            # 📋 [INFO] RUN MANIFEST (provenance artifact; best-effort)
            # ---------------------------------------------------------
            try:
                manifest_path = update_run_manifest(
                    self.out_dir,
                    gps_bounds=getattr(s, "GPS_BOUNDS", None),
                    settings_snapshot_sha256=settings_hash,
                    settings_snapshot_md5=settings_hash_md5,
                    settings_schema_version=str(
                        getattr(s, "SETTINGS_SCHEMA_VERSION", "UNKNOWN")
                    )
                    if hasattr(s, "SETTINGS_SCHEMA_VERSION")
                    else "UNKNOWN",
                    files={
                        "OSM_FILE": str(getattr(s, "OSM_FILE", "")),
                        "DEM_TIF": str(getattr(s, "DEM_TIF", "")),
                        "SENSOR_CALIB_JSON": str(getattr(s, "SENSOR_CALIB_JSON", "")),
                        "INPUT_XODR": str(getattr(s, "INPUT_XODR", "")),
                        # Manual map path (supports multiple naming conventions)
                        "MANUAL_XODR": str(
                            getattr(
                                s,
                                "MANUAL_XODR",
                                getattr(
                                    s,
                                    "MANUAL_MAP_XODR",
                                    getattr(s, "MANUAL_XODR_PATH", ""),
                                ),
                            )
                        ),
                    },
                    notes={
                        "purpose": "thesis_provenance",
                        # Gate flags (best-effort; keys only appear if settings exist)
                        "strict_mode": bool(getattr(s, "STRICT_MODE", False)),
                        "sim_gate_enabled": bool(
                            getattr(s, "SIM_GATE_ENABLED", False)
                        ),
                        # CRS/offset discipline signals (populated if your settings define them)
                        "offset_policy": getattr(s, "OFFSET_POLICY", None),
                        "gps_anchor_override_allowed": getattr(
                            s, "GPS_ANCHOR_OVERRIDE_ALLOWED", None
                        ),
                    },
                )

                try:
                    manifest_obj = json.loads(
                        Path(manifest_path).read_text(encoding="utf-8")
                    )
                    preanchor_block = getattr(self, "_preanchor_manifest", None)
                    if not isinstance(preanchor_block, dict):
                        preanchor_block = {"applied": False}
                    if not bool(preanchor_block.get("applied", False)):
                        preanchor_block = {"applied": False}
                    manifest_obj["preanchor"] = preanchor_block
                    Path(manifest_path).write_text(
                        json.dumps(manifest_obj, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                except Exception as _e2:
                    print(f"⚠️ Failed to append preanchor provenance to manifest: {_e2}")
            except Exception as _e:
                print(f"⚠️ Run manifest update skipped: {_e}")

        except Exception as e:
            print(f"❌ FAILED to write settings snapshot: {e}")
            raise RuntimeError("Settings snapshot is mandatory for research runs")

        # ---------------------------------------------------------
        # 🔍 DEBUG PROBE: if you "freeze" after settings snapshot,
        # it's almost always determinism (torch import) or OSM download.
        # ---------------------------------------------------------
        import time

        print(
            "[INFO] [PROBE] settings snapshot done → entering determinism/OSM stage",
            flush=True,
        )
        t_probe = time.time()

        # Determinism
        if getattr(s, "DETERMINISTIC_MODE", True):
            t0 = time.time()
            print("[INFO] [PROBE] enforce_determinism() start", flush=True)
            enforce_determinism(s.DETERMINISTIC_SEED)
            print(
                f"[INFO] [PROBE] enforce_determinism() done in {time.time() - t0:.2f}s",
                flush=True,
            )
        else:
            print("[INFO] [PROBE] determinism disabled", flush=True)

        # Ensure OSM exists / is downloaded
        try:
            t0 = time.time()
            print("[INFO] [PROBE] ensure_osm_exists() start", flush=True)
            s.OSM_FILE = ensure_osm_exists(s.GPS_BOUNDS, s.OSM_FILE)
            print(
                f"[INFO] [PROBE] ensure_osm_exists() done in {time.time() - t0:.2f}s",
                flush=True,
            )
            try:

                def compute_md5(path):
                    h = hashlib.md5()
                    with open(path, "rb") as f:
                        for chunk in iter(lambda: f.read(1024 * 1024), b""):
                            h.update(chunk)
                    return h.hexdigest()

                osm_path = Path(s.OSM_FILE)
                if osm_path.is_file():
                    md5 = compute_md5(osm_path)
                    osm_archive_path = Path(self.out_dir) / "osm_archive.json"
                    with open(osm_archive_path, "w", encoding="utf-8") as f:
                        json.dump({"osm_md5": md5}, f, indent=2, sort_keys=True)
            except Exception:
                pass
        except Exception as e:
            print(f"⚠️ OSM auto-download / verification failed: {e}", flush=True)
            print(
                "   → Continuing with existing OSM_FILE path; some enrichment may be limited.",
                flush=True,
            )

        gps_bounds = s.load_gps_bounds()
        print(
            f"📍 GPS bounds: "
            f"lat {gps_bounds['lat_min']}–{gps_bounds['lat_max']}, "
            f"lon {gps_bounds['lon_min']}–{gps_bounds['lon_max']}"
        )

        # Stage filenames (XODR)
        sanitized = s.stage_path("01_sanitized")
        sumo_fixed = s.stage_path("02_sumo_fixed")
        topo_fixed = s.stage_path("03_topology")
        lanes_out = s.stage_path("07_lanes")
        final_out = s.stage_path("08_final")

        # Prepare DEM diagnostics
        self._dem_precheck()

        # ---------------------------------------------------------
        # 🚦 CARLA PREFLIGHT (reachability check + artifact)
        # ---------------------------------------------------------
        self._carla_reachable = False
        carla_disabled_env = os.getenv("UP_DISABLE_CARLA", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        carla_disabled_setting = not bool(getattr(s, "ENABLE_CARLA", True))

        if carla_disabled_env or carla_disabled_setting:
            # Explicitly disabled - write artifact and skip
            preflight_result = {
                "ok": False,
                "skip_reason": "carla_disabled",
                "UP_DISABLE_CARLA": os.getenv("UP_DISABLE_CARLA", ""),
                "ENABLE_CARLA": bool(getattr(s, "ENABLE_CARLA", True)),
                "timestamp": datetime.now().isoformat(),
            }
            self._carla_reachable = False
            print(
                "[PREFLIGHT] CARLA explicitly disabled; CARLA stages will be skipped."
            )
        else:
            # Run actual preflight check
            try:
                from ultimate_pipeline.tools.carla_preflight import run_preflight

                host = getattr(s, "CARLA_HOST", "127.0.0.1")
                port = int(getattr(s, "CARLA_PORT", 2000))
                preflight_result = run_preflight(
                    host=host,
                    port=port,
                    out_dir=self.out_dir,
                    timeout_s=10.0,
                    skip_api=self._carla_isolation_enabled(),  # In isolation mode, only TCP probe
                )
                self._carla_reachable = bool(preflight_result.get("ok", False))
                if self._carla_reachable:
                    print(f"[PREFLIGHT] CARLA reachable at {host}:{port}")
                else:
                    print(
                        f"[PREFLIGHT] CARLA unreachable ({preflight_result.get('error', 'unknown')}); CARLA stages will be skipped."
                    )
            except Exception as e:
                preflight_result = {
                    "ok": False,
                    "error": f"preflight_exception: {e}",
                    "timestamp": "",
                }
                self._carla_reachable = False
                print(
                    f"[PREFLIGHT] CARLA preflight failed: {e}; CARLA stages will be skipped."
                )

        # Write preflight artifact
        try:
            import json as _json

            preflight_path = os.path.join(self.out_dir, "carla_reachability.json")
            with open(preflight_path, "w", encoding="utf-8") as f:
                _json.dump(preflight_result, f, indent=2, ensure_ascii=True)
            print(f"[PREFLIGHT] carla_reachability.json -> {preflight_path}")
        except Exception as e:
            print(f"[PREFLIGHT] carla_reachability.json write failed: {e}")

        # Optional strictness: require CARLA server for thesis runs if explicitly requested.
        # Default OFF (backward compatible).
        require_carla = os.getenv("UP_REQUIRE_CARLA_FOR_THESIS", "").strip().lower() in ("1", "true", "yes", "on")
        if require_carla and bool(getattr(self.settings, "THESIS_STRICT", False)):
            if not bool(preflight_result.get("reachable")):
                raise RuntimeError(
                    "UP_REQUIRE_CARLA_FOR_THESIS=1 but CARLA server is unreachable (127.0.0.1:2000). "
                    "Start CARLA (CarlaUE4) or disable UP_REQUIRE_CARLA_FOR_THESIS."
                )

        # CARLA connection (only if reachable and not in isolation mode)
        if self._carla_reachable:
            self._connect_carla()
        else:
            print("[PREFLIGHT] Skipping _connect_carla() due to unreachable CARLA")

        # 1) 🧼 SANITIZE
        self._mark_stage("sanitize")
        self._step1_sanitize(sanitized)

        # (Optional) GPS QA crop (for your quick debug)
        # Thesis strict policy: GPS QA cropper has its own gps-anchor override logic.
        # In strict thesis runs we disable it fail-closed to preserve Option A offset discipline.
        thesis_strict = (
            os.getenv("UP_THESIS_STRICT", "").strip().lower() in ("1", "true", "yes", "on")
            or bool(getattr(s, "THESIS_STRICT", False))
        )
        if thesis_strict:
            print("⏭️ GPS QA crop disabled (thesis strict).")
            try:
                Path(self.out_dir, "gps_qa_crop_disabled_strict.txt").write_text(
                    "ENABLE_GPS_QA_CROP disabled due to UP_THESIS_STRICT/THESIS_STRICT\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
        else:
            if getattr(s, "ENABLE_GPS_QA_CROP", True):
                self._gps_qa_crop(sanitized)
            else:
                print("⏭️ GPS QA crop disabled by settings.")

        # 2) 🕸️ Topology + Structure + Semantics
        self._mark_stage("topology_semantics")
        working_topology = self._step2_topology_semantics(sanitized, sumo_fixed)

        # 3) 🔧 Topology repair
        self._mark_stage("topology_repair")
        topo_fixed = self._step3_topology_repair(working_topology, topo_fixed)

        # 4) 🏗️ Enrichment
        self._mark_stage("enrichment")
        topo_fixed = self._step4_enrichment(topo_fixed)

        # 5+6) 📐 Geometry authority (DEM + planView + continuity) + freeze
        self._mark_stage("geometry")
        geo_final = self._step5_geometry_elevation_continuity(topo_fixed)

        # 6) PlanView & continuity
        # cont_out = self._step6_planview_continuity(elev_out, geo_out, cont_out)

        # 7) 🛣️ Lane / cross-section / offsets / sidewalks
        self._mark_stage("lanes")
        lanes_out = self._step7_lanes_sidewalks(geo_final, lanes_out)
        if os.getenv("UP_ENABLE_LANE_WIDTH_CONTINUITY", "1").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            self._stage_gate(
                "07_lanes",
                "lane_width_continuity",
                lambda: self.qgate.gate_lane_width_continuity(lanes_out),
            )
        if os.getenv("UP_ENABLE_LANE_GEOMETRY_CONTINUITY", "1").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            self._stage_gate(
                "07_lanes",
                "lane_geometry_continuity",
                lambda: self.qgate.gate_lane_geometry_continuity(lanes_out),
            )

        # 8) 🔗 LaneLinks + markings + final integrity
        self._mark_stage("final_integrity")
        final_out = self._step8_markings_and_integrity(lanes_out, final_out)

        # 8B) Post-final elevation seam gate + origin sanity
        origin_report = self._stage_gate(
            "08_final",
            "origin_sanity",
            lambda: self.qgate.gate_origin_sanity(final_out),
        )
        try:
            origin_path = os.path.join(self.out_dir, "origin_sanity.json")
            with open(origin_path, "w", encoding="utf-8") as f:
                json.dump(origin_report, f, indent=2, default=str)
            print(f"[STEP 8] origin_sanity.json -> {origin_path}")
        except Exception as e:
            print(f"[STEP 8] origin_sanity.json write skipped: {e}")

        seam_report = self._stage_gate(
            "08_final",
            "elevation_seams",
            lambda: self.qgate.gate_elevation_seams(final_out),
        )
        seam_path = os.path.join(self.out_dir, "elevation_seam_report.json")
        try:
            with open(seam_path, "w", encoding="utf-8") as f:
                json.dump(seam_report, f, indent=2, default=str)
            print(f"[STEP 8] elevation_seam_report.json -> {seam_path}")
        except Exception as e:
            print(f"[STEP 8] elevation_seam_report.json write skipped: {e}")

        if isinstance(seam_report, dict) and not seam_report.get("ok", True):
            autofix_enabled = os.getenv(
                "UP_AUTOFIX_POSTPRUNE_ELEVATION", ""
            ).strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            dem_path = getattr(self.settings, "DEM_TIF", "")
            if autofix_enabled and dem_path and os.path.exists(dem_path):
                try:
                    from ultimate_pipeline.quality.autofix_postprune_elevation import (
                        apply_postprune_elevation_autofix,
                    )

                    fixed_out = final_out.replace(
                        ".xodr", "_autofix_postprune_elevation.xodr"
                    )
                    autofix_report = apply_postprune_elevation_autofix(
                        final_out,
                        dem_path,
                        fixed_out,
                    )
                    autofix_path = os.path.join(
                        self.out_dir, "elevation_autofix_report.json"
                    )
                    with open(autofix_path, "w", encoding="utf-8") as f:
                        json.dump(autofix_report, f, indent=2, default=str)
                    print(f"[STEP 8] elevation_autofix_report.json -> {autofix_path}")
                    final_out = fixed_out

                    seam_report = self._stage_gate(
                        "08_final_autofix",
                        "elevation_seams",
                        lambda: self.qgate.gate_elevation_seams(final_out),
                    )
                    with open(seam_path, "w", encoding="utf-8") as f:
                        json.dump(seam_report, f, indent=2, default=str)
                except Exception as e:
                    print(f"[STEP 8] elevation autofix failed: {e}")
            if not seam_report.get("ok", True):
                raise RuntimeError(
                    "❌ Elevation seam gate failed after final XODR generation."
                )

        # Map acceptance summary (gates perception if enabled)
        try:
            from ultimate_pipeline.quality.map_acceptance import build_map_acceptance

            map_acceptance = build_map_acceptance(
                {
                    "origin_sanity": origin_report,
                    "elevation_seams": seam_report,
                },
                run_id=os.path.basename(os.path.normpath(self.out_dir)),
                final_xodr_path=final_out,
                out_dir=self.out_dir,
            )
            self.map_acceptance = map_acceptance
            acc_path = os.path.join(self.out_dir, "map_acceptance.json")
            with open(acc_path, "w", encoding="utf-8") as f:
                json.dump(map_acceptance, f, indent=2, default=str)
            print(f"[STEP 8] map_acceptance.json -> {acc_path}")
        except Exception as e:
            print(f"[STEP 8] map_acceptance.json write skipped: {e}")

        # Map content fingerprint (final XODR after quarantine)
        try:
            from ultimate_pipeline.utils.map_fingerprint import (
                write_map_content_fingerprint,
            )

            fingerprint_path = write_map_content_fingerprint(self.out_dir, final_out)
            if fingerprint_path:
                print(f"[STEP 8] map_content_fingerprint.json -> {fingerprint_path}")
        except Exception as e:
            print(f"[STEP 8] map_content_fingerprint.json write skipped: {e}")

        # 8D) Optional preflight validation
        self._step8d_preflight_validation(final_out)
        self._write_determinism_fingerprint(final_out)

        # 8E) Junction link integrity gate
        self._mark_stage("junction_link_integrity")
        print("\n============== 🔗 Junction link integrity gate ==============")
        gate_result = run_junction_link_integrity_gate(
            input_xodr_path=final_out,
            out_dir=self.out_dir,
            enable_patch=bool(
                getattr(self.settings, "ENABLE_JUNCTION_LINK_PATCH", True)
            ),
        )
        final_out = str(gate_result.get("final_xodr", final_out))
        xodr_link_report = (
            gate_result.get("report", {}) if isinstance(gate_result, dict) else {}
        )
        xodr_link_report_path = Path(self.out_dir) / "xodr_link_integrity.json"
        added_links = int(
            xodr_link_report.get(
                "added_junction_links",
                xodr_link_report.get("junction_link_additions", 0),
            )
            or 0
        )
        if added_links > 0:
            print(f"[JUNCTION-GATE] Patched XODR selected -> {final_out}")
        else:
            patch_enabled = bool(
                getattr(self.settings, "ENABLE_JUNCTION_LINK_PATCH", True)
            )
            if patch_enabled:
                print(
                    f"[JUNCTION-GATE] No missing incoming-road junction links detected. Using {final_out}"
                )
            else:
                print(
                    f"[JUNCTION-GATE] Patch disabled; lane-link gate passed. Using {final_out}"
                )

        # 8F) Optional CARLA elevation verification hook (thesis evidence)
        self._step8f_optional_carla_elevation_validation(final_out)

        # 8G) Drivable-surface hole analysis
        self._mark_stage("drivable_surface_scan")
        if getattr(self.settings, "ENABLE_DRIVABLE_SURFACE_HOLE_SCAN", True):
            from ultimate_pipeline.quality.drivable_surface_scanner import (
                DrivableSurfaceScanner,
            )

            hole_threshold = float(
                getattr(self.settings, "DRIVABLE_SURFACE_HOLE_THRESHOLD_M", 0.5)
            )
            seam_threshold = float(
                getattr(self.settings, "DRIVABLE_SURFACE_SEAM_THRESHOLD_DEG", 5.0)
            )
            drop_threshold = float(
                getattr(self.settings, "DRIVABLE_SURFACE_DROP_THRESHOLD_M", 0.3)
            )

            def _scan_holes():
                return DrivableSurfaceScanner.scan(
                    final_out,
                    hole_threshold_m=hole_threshold,
                    seam_threshold_deg=seam_threshold,
                    drop_threshold_m=drop_threshold,
                )

            self._stage_gate("08G", "drivable_surface", _scan_holes)
        else:
            print("[STEP 8G] Drivable-surface hole scan disabled.")

        # 8H) Full-map parent/child metrics
        self._mark_stage("full_map_metrics")
        from ultimate_pipeline.quality.full_map_metrics import (
            FullMapMetricsScanner,
        )

        def _compute_metrics():
            return FullMapMetricsScanner.scan(final_out)

        self._stage_gate("08H", "full_map_metrics", _compute_metrics)

        # 9) 🧩 Tiling
        self._mark_stage("tiling")
        graph_path = self._step9_tiling(final_out)
        if graph_path:
            # Stage gate checks after tiling
            if os.getenv("UP_ENABLE_GEOMETRIC_CONTINUITY", "1").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            ):
                self._stage_gate(
                    "09_tiling",
                    "geometric_continuity",
                    lambda: self.qgate.gate_geometric_continuity(final_out),
                )
            self._stage_gate(
                "09_tiling",
                "elevation_continuity",
                lambda: self.qgate.gate_elevation_continuity(final_out),
            )

        # 10) 🧪 Tile QA suite (seams, CarlaFinalTest, spawn QA, stress test)
        self._mark_stage("tile_qa")
        self._step10_tile_qa(graph_path, final_out)

        # 10C/10D/10E – Road defects, perception, screenshots
        self._mark_stage("perception_screenshots")
        self._step10c_road_perception_screenshots(final_out)

        # 11) 🎮 Interactive sim (optional gate)
        self._mark_stage("interactive_sim")
        self._step11_simulation(final_out, graph_path)

        # 12) 📊 Domain gap analysis (classical, + latent if you extend run_full_domain_gap)
        self._mark_stage("domain_gap")
        self._step12_domain_gap(final_out)

        # 🚦 Quality gates wrapper (XML / physics / semantics etc.)
        self._mark_stage("quality_gates")
        self._run_quality_gates_wrapper(final_out)

        # Cumulative gate check (tally-all, fail-at-end)
        self._mark_stage("cumulative_gates")
        self._finalize_gates()

        # 📋 Final summary + 🤖 LLM review
        self._mark_stage("final_summary")
        self._final_summary_and_llm(final_out)

        # Write run summary manifest
        self._mark_stage("run_summary")
        self._write_run_summary(final_out)

    # -----------------------------------------------------
    # 🧱 Sub-blocks
    # -----------------------------------------------------

    def _connect_carla(self) -> None:
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

    def _step8f_optional_carla_elevation_validation(self, final_out: str) -> None:
        from ultimate_pipeline.pipeline_stages.stage_08_integrity import _step8f_optional_carla_elevation_validation as _impl
        return _impl(self, final_out)
    def _verify_continuity_stability(self, xodr_path: str) -> None:
        s = self.settings
        runs = int(getattr(s, "CONTINUITY_STABILITY_RUNS", 3))

        print(
            f"\n============== 🔄 CONTINUITY STABILITY CHECK ({runs} runs) =============="
        )

        scans = []
        for i in range(runs):
            try:
                r = MeshContinuityRepairer(xodr_path)
                scan = r.scan_roads()
                scans.append(scan)
                print(
                    f"   ✅ continuity scan run {i + 1}/{runs} ok (roads: {len(scan)})"
                )
            except Exception as e:
                print(f"   ❌ continuity scan run {i + 1} failed: {e}")
                self.vreport.add("continuity_stability", "scan_failed", str(e))
                return

        def _canonical(obj):
            if isinstance(obj, dict):
                return {k: _canonical(obj[k]) for k in sorted(obj.keys())}
            if isinstance(obj, list):
                return [_canonical(x) for x in obj]
            return obj

        base = _canonical(scans[0])
        stable = True
        for i in range(1, runs):
            if _canonical(scans[i]) != base:
                stable = False
                break

        out_json = os.path.join(self.out_dir, "continuity_stability.json")
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({"stable": stable, "runs": runs, "xodr": xodr_path}, f, indent=2)

        if stable:
            print(f"✅ Continuity stats stable across {runs} runs → {out_json}")
            self.vreport.add("continuity_stability", "stable", True)
        else:
            print(f"⚠️ Continuity stats NOT stable across runs → {out_json}")
            self.vreport.add("continuity_stability", "stable", False)

    def _assert_geometry_frozen(self, root: ET.Element, where: str) -> None:
        header = root.find("header")
        frozen = header is not None and header.get("geometryFrozen") == "true"
        if not frozen:
            raise RuntimeError(
                f"❌ Geometry is NOT frozen at {where}. "
                "You must run STEP 5+6 merged geometry authority before lanes."
            )

    def _dem_precheck(self) -> None:
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

    # ---------------- 🚦 STAGE GATE HELPER ----------------
    def _resolve_strict_quality_gates(self) -> bool:
        from ultimate_pipeline.contracts.release_profile import resolve_strict_quality_gates as _resolve

        profile_name = str(getattr(self.settings, "RELEASE_PROFILE", "") or "")
        env_val: str | None = os.getenv("UP_STRICT_QUALITY_GATES")
        return _resolve(profile_name, env_override=env_val)

    def _resolve_experimental_unsafe(self) -> bool:
        from ultimate_pipeline.contracts.release_profile import resolve_experimental_unsafe as _resolve

        profile_name = str(
            getattr(self.settings, "RELEASE_PROFILE", "structural_release")
            or "structural_release"
        )
        return _resolve(profile_name)

    def _stage_gate(self, stage: str, name: str, fn):
        """
        Run a quality check function at a specific pipeline stage.

        - Prints [QA][stage] name
        - Runs fn() and gets a dict report
        - Writes the report to <out_dir>/qa_stage_reports/{stage}__{name}.json
        - Delegates to CumulativeGateRunner (tally-all, fail-at-end)
        """
        print(f"\n[QA][{stage}] {name} ...")
        runner = self._gate_runner
        if runner is None:
            strict = self._resolve_strict_quality_gates()
            runner = CumulativeGateRunner(strict=strict)
            self._gate_runner = runner
        rep = runner.run(stage, name, fn)
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
        return rep

    def _finalize_gates(self) -> dict:
        """Call at the end of the pipeline to raise on any collected failures."""
        runner = self._gate_runner
        if runner is None:
            return {"total": 0, "passed": 0, "failed": 0, "results": []}
        summary = runner.finalize()
        try:
            if getattr(self, "out_dir", None):
                path = os.path.join(self.out_dir, "cumulative_gate_report.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, default=str)
                print(f"[QA] cumulative gate report -> {path}")
        except Exception as e:
            print(f"[QA] cumulative gate report write skipped: {e}")
        return summary

    def _verify_geometry_freeze_hash(self, xodr_path: str) -> str | None:
        """
        Verify that the geometry freeze hash embedded in *xodr_path* matches
        a live hash of the file content.

        Returns the expected hash if valid, or *None* on mismatch / missing
        header attribute.
        """
        import xml.etree.ElementTree as ET_xml
        import hashlib as _hlib

        try:
            tree = ET_xml.parse(xodr_path)
            root = tree.getroot()
            header = root.find("header")
            if header is None:
                print("[FREEZE-HASH] No <header> found — freeze hash not verified.")
                return None
            expected = header.get("geometryFreezeHash")
            if not expected:
                print("[FREEZE-HASH] No geometryFreezeHash attribute — freeze hash not verified.")
                return None
            actual = _hlib.sha256()
            with open(xodr_path, "rb") as f:
                actual.update(f.read())
            actual_hex = actual.hexdigest()
            if actual_hex != expected:
                print(
                    f"[FREEZE-HASH] MISMATCH: header={expected} live={actual_hex} "
                    f"— geometry may have drifted."
                )
                return None
            print(f"[FREEZE-HASH] Verified: {expected}")
            return expected
        except Exception as e:
            print(f"[FREEZE-HASH] Verification skipped: {e}")
            return None

    # ---------------- 1) 🧼 SANITIZE ----------------
    def _step1_sanitize(self, sanitized: str) -> None:
        from ultimate_pipeline.pipeline_stages.stage_01_sanitize import _step1_sanitize as _impl
        return _impl(self, sanitized)
    def _gps_qa_crop(self, sanitized: str) -> None:
        s = self.settings
        try:
            gps = s.load_gps_bounds()
            lat_center = (gps["lat_min"] + gps["lat_max"]) / 2.0
            lon_center = (gps["lon_min"] + gps["lon_max"]) / 2.0

            gps_crop_path = os.path.join(self.out_dir, "01_sanitized_GPS_QA_CROP.xodr")

            XODRCropperGPS().crop_gps(
                input_xodr=sanitized,
                output_xodr=gps_crop_path,
                lat_center=lat_center,
                lon_center=lon_center,
                r=800.0,
            )

            lane_count = _count_lanes(gps_crop_path)
            if lane_count <= 0:
                raise RuntimeError(
                    f"❌ GPS QA crop produced empty map ({gps_crop_path}). "
                    "Check crop radius or GPS bounds."
                )

            print(f"📍 GPS QA crop ready → {gps_crop_path} (lanes: {lane_count})")

        except Exception as e:
            print(f"⚠️ GPS QA crop failed (non-fatal): {e}")

    # ---------------- 2) 🕸️ TOPOLOGY + SEMANTICS ----------------
    def _step2_topology_semantics(self, sanitized: str, sumo_fixed: str) -> str:
        from ultimate_pipeline.pipeline_stages.stage_02_topology_semantics import _step2_topology_semantics as _impl
        return _impl(self, sanitized, sumo_fixed)
    def _step3_topology_repair(
        self, working_topology_input: str, topo_fixed: str
    ) -> str:
        from ultimate_pipeline.pipeline_stages.stage_03_topology_repair import _step3_topology_repair as _impl
        return _impl(self, working_topology_input, topo_fixed)
    def _step4_enrichment(self, topo_fixed: str) -> str:
        from ultimate_pipeline.pipeline_stages.stage_04_enrichment import _step4_enrichment as _impl
        return _impl(self, topo_fixed)
    # Delegated stage hooks contract anchors (kept in this canonical file for tests/docs):
    # _stage_gate("06_continuity", "geometric_continuity", ...)
    # _stage_gate("06_continuity", "planview_internal_seams", ...)
    # _stage_gate("09_tiling", "geometric_continuity", ...)
    # _stage_gate("09_tiling", "planview_internal_seams_tiles", ...)
    # Elevation std threshold source-of-truth expression:
    # getattr(s, "DEM_MIN_ELEVATION_STD", 0.0)
    def _step5_geometry_elevation_continuity(self, topo_fixed: str) -> str:
        from ultimate_pipeline.pipeline_stages.stage_05_geometry import _step5_geometry_elevation_continuity as _impl
        return _impl(self, topo_fixed)
    def _step5_dem_and_geometry(self, topo_fixed: str, elev_out: str) -> str:
        from ultimate_pipeline.pipeline_stages.stage_05_geometry import _step5_dem_and_geometry as _impl
        return _impl(self, topo_fixed, elev_out)
    def _step6_planview_continuity(
        self,
        elev_out: str,
        geo_out: str,
        cont_out: str,
    ) -> str:
        from ultimate_pipeline.pipeline_stages.stage_06_links import _step6_planview_continuity as _impl
        return _impl(self, elev_out, geo_out, cont_out)
    def _step7_lanes_sidewalks(self, cont_out: str, lanes_out: str) -> str:
        from ultimate_pipeline.pipeline_stages.stage_07_lanes import _step7_lanes_sidewalks as _impl
        return _impl(self, cont_out, lanes_out)
    def _step8_marking_summary(self, final_out: str) -> None:
        from ultimate_pipeline.pipeline_stages.stage_08_integrity import _step8_marking_summary as _impl
        return _impl(self, final_out)
    def _step8c_spawn_validation(self, final_out: str) -> None:
        from ultimate_pipeline.pipeline_stages.stage_08_integrity import _step8c_spawn_validation as _impl
        return _impl(self, final_out)
    def _step8_markings_and_integrity(self, lanes_out: str, final_out: str) -> str:
        from ultimate_pipeline.pipeline_stages.stage_08_integrity import _step8_markings_and_integrity as _impl
        return _impl(self, lanes_out, final_out)
    def _step8d_preflight_validation(self, final_out: str) -> None:
        from ultimate_pipeline.pipeline_stages.stage_08_integrity import _step8d_preflight_validation as _impl
        return _impl(self, final_out)
    def _step8c_carla_safety_prune(self, final_out: str) -> str:
        from ultimate_pipeline.pipeline_stages.stage_08_integrity import _step8c_carla_safety_prune as _impl
        return _impl(self, final_out)
    def _step9_tiling(self, final_out: str) -> Optional[str]:
        from ultimate_pipeline.pipeline_stages.stage_09_tiling import _step9_tiling as _impl
        return _impl(self, final_out)
    def _validate_full_map_spawn(self, final_out: str) -> None:
        if not SpawnValidator.check(self.client):
            raise RuntimeError("❌ FULL map has no valid spawn points")

        print("✅ FULL map loaded and spawn points validated (STEP 10).")
        self.vreport.add("drivability", "full_map_spawn", "ok")

        # ---------------------------------------------------------
        # 🎯 FULL MAP VALIDATION (ONLY IF ATTEMPTED)
        # ---------------------------------------------------------

    # ---------------- 10) 🧪 TILE QA SUITE ----------------
    # ---------------- 10) 🧪 TILE QA SUITE ----------------
    # ---------------- 10) 🧪 TILE QA SUITE ----------------
    # ---------------- 10) 🧪 TILE QA SUITE ----------------
    def _step10_tile_qa(self, graph_path: Optional[str], final_out: str) -> None:
        from ultimate_pipeline.pipeline_stages.stage_10_tile_qa import _step10_tile_qa as _impl
        return _impl(self, graph_path, final_out)
    def _ensure_carla_ready_for_step10c(self) -> "carla.World":
        """
        Reconnect to CARLA after tile QA and return a ready world.
        Raises RuntimeError if world is unavailable.
        """
        import time

        if self._carla_isolation_enabled():
            raise RuntimeError(
                "STEP10C in-proc CARLA path is disabled in isolation mode"
            )

        timeout = float(getattr(self.settings, "CARLA_TIMEOUT_S", 300.0))
        host = getattr(self.settings, "CARLA_HOST", "127.0.0.1")
        port = int(getattr(self.settings, "CARLA_PORT", 2000))

        if self.client is None:
            print("CARLA client missing at STEP10C -> reconnecting...")
            import carla  # type: ignore

            self.client = carla.Client(host, port)
            self.client.set_timeout(timeout)
        else:
            try:
                self.client.set_timeout(timeout)
            except Exception:
                pass

        for _ in range(10):
            world = None
            try:
                world = self.client.get_world()
                if world is not None:
                    try:
                        # CARLA 0.9.16: must use positional float, not keyword arg
                        world.wait_for_tick(float(timeout / 10.0))
                    except Exception:
                        pass
                    if world is not None:
                        return world
            except Exception:
                world = None
            time.sleep(1.0)

        raise RuntimeError("❌ STEP10C: CARLA world unavailable after reconnect.")

    # ---------------- 10C/D/E) 🔍 ROAD DEFECTS, PERCEPTION, SCREENSHOTS ----------------
    def _step10c_road_perception_screenshots(self, final_out: str) -> None:
        from ultimate_pipeline.pipeline_stages.stage_10_tile_qa import _step10c_road_perception_screenshots as _impl
        return _impl(self, final_out)
    def _step11_simulation(self, final_out: str, graph_path: Optional[str]) -> None:
        from ultimate_pipeline.pipeline_stages.stage_11_simulation import _step11_simulation as _impl
        return _impl(self, final_out, graph_path)
    def _step12_domain_gap(self, final_out: str) -> None:
        from ultimate_pipeline.pipeline_stages.stage_12_domain_gap import _step12_domain_gap as _impl
        return _impl(self, final_out)
    def _run_quality_gates_wrapper(self, final_out: str) -> None:
        s = self.settings
        if not getattr(s, "ENABLE_QUALITY_GATES_WRAPPER", True):
            print("\n⏭️ Quality gates wrapper disabled.")
            return
        print("\n============== 🚦 QUALITY GATE WRAPPER ==============")

        # Strict mode: re-raise exceptions from quality gates
        strict_mode = os.getenv("UP_STRICT_QUALITY_GATES", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        try:
            from ultimate_pipeline.quality.quality_gates import run_quality_gates
            from ultimate_pipeline.quality.quality_gates import DRIVABILITY_GATES

            failures = run_quality_gates(final_out, out_dir=self.out_dir)

            drivability_failures = sorted(set(failures.keys()) & set(DRIVABILITY_GATES))
            if drivability_failures:
                raise RuntimeError(
                    f"❌ Drivability gates failed: {drivability_failures}"
                )

            # In strict mode, raise on any gate failure.
            if strict_mode and failures:
                raise RuntimeError(
                    f"❌ Quality gate failures in strict mode: {sorted(failures.keys())}"
                )
        except Exception as e:
            if strict_mode:
                raise  # Re-raise in strict mode
            print(f"⚠️ Quality gates wrapper failed: {e}")

    def _run_geometric_continuity_gate(self, xodr_path: str, context: str) -> None:
        strict_mode = os.getenv("UP_STRICT_QUALITY_GATES", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        strict_fail_on_gate = bool(
            getattr(self.settings, "STRICT_FAIL_ON_GEOMETRIC_CONTINUITY_GATE", False)
        )
        strict_fail_env = os.getenv("UP_STRICT_FAIL_ON_GEOMETRIC_CONTINUITY_GATE")
        if strict_fail_env is not None and strict_fail_env.strip():
            strict_fail_on_gate = strict_fail_env.strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
        fail_closed = bool(strict_mode and strict_fail_on_gate)

        def _percentile(values: List[float], q: float) -> float:
            if not values:
                return 0.0
            ordered = sorted(float(v) for v in values)
            if len(ordered) == 1:
                return float(ordered[0])
            rank = (len(ordered) - 1) * float(q)
            lo = int(math.floor(rank))
            hi = int(math.ceil(rank))
            if lo == hi:
                return float(ordered[lo])
            frac = rank - lo
            return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)

        def _stats(values: List[float]) -> Dict[str, float]:
            return {
                "max": float(max(values)) if values else 0.0,
                "p95": float(_percentile(values, 0.95)),
                "p99": float(_percentile(values, 0.99)),
            }

        def _write_artifact(
            *,
            report: Dict[str, Any],
            error_text: str | None,
        ) -> None:
            issues = report.get("issues", []) if isinstance(report, dict) else []
            if not isinstance(issues, list):
                issues = []

            seam_values: List[float] = []
            jump_values: List[float] = []
            sample_road_ids: List[str] = []
            seen_ids = set()
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                try:
                    if "dxy" in issue:
                        seam_values.append(float(issue.get("dxy")))
                except Exception:
                    pass
                try:
                    if "dhdg" in issue:
                        jump_values.append(float(issue.get("dhdg")))
                except Exception:
                    pass
                for road_key in ("from_road", "to_road"):
                    rid = issue.get(road_key)
                    rid_text = str(rid).strip() if rid is not None else ""
                    if not rid_text or rid_text in seen_ids:
                        continue
                    seen_ids.add(rid_text)
                    sample_road_ids.append(rid_text)
                    if len(sample_road_ids) >= 10:
                        break

            report_ok = bool(report.get("ok", True)) if isinstance(report, dict) else False
            decision_pass = bool(report_ok and not error_text)
            if error_text:
                decision_reason = f"gate_error: {error_text}"
            elif decision_pass:
                decision_reason = "all observed seams/jumps within thresholds"
            else:
                decision_reason = (
                    f"{int(report.get('num_issues', len(issues)) or 0)} offending segments "
                    "exceed continuity thresholds"
                )

            artifact = {
                "stage": str(getattr(self, "_run_stage", "unknown")),
                "substage": str(context),
                "xodr_path": str(xodr_path),
                "thresholds": {
                    "max_seam_distance_m": float(report.get("eps_xy", 0.0) or 0.0),
                    "max_heading_jump_rad": float(report.get("eps_hdg", 0.0) or 0.0),
                },
                "observed": {
                    "seam_distance_m": _stats(seam_values),
                    "heading_jump_rad": _stats(jump_values),
                },
                "offending_segments": {
                    "count": int(report.get("num_issues", len(issues)) or 0),
                    "sample_road_ids": sample_road_ids,
                },
                "decision": {
                    "pass": decision_pass,
                    "reason": decision_reason,
                    "strict_mode": bool(strict_mode),
                    "strict_fail_on_geometric_continuity_gate": bool(
                        strict_fail_on_gate
                    ),
                    "fail_closed_active": bool(fail_closed),
                },
            }
            artifact_path = os.path.join(self.out_dir, "geometric_continuity_gate.json")
            try:
                with open(artifact_path, "w", encoding="utf-8") as f:
                    json.dump(artifact, f, indent=2, ensure_ascii=True, sort_keys=True)
            except Exception as write_exc:
                print(
                    f"[geometric_continuity] Gate artifact write failed ({context}): {write_exc}"
                )

        try:
            report = self.qgate.gate_geometric_continuity(xodr_path)
        except Exception as e:
            _write_artifact(report={}, error_text=str(e))
            if fail_closed:
                raise RuntimeError(
                    f"❌ Geometric continuity gate errored ({context}): {e}"
                ) from e
            print(f"[geometric_continuity] Gate errored ({context}): {e}")
            return

        _write_artifact(report=report, error_text=None)

        if not report.get("ok", True):
            if fail_closed:
                raise RuntimeError(
                    f"❌ Geometric continuity gate failed ({context}): "
                    f"{report.get('num_issues', 0)} issues"
                )
            if strict_mode:
                print(
                    f"[geometric_continuity] Gate failed ({context}); continuing "
                    "(strict mode, fail-closed disabled)."
                )
                return
            print(
                f"[geometric_continuity] Gate failed ({context}); continuing (non-strict mode)."
            )

    def _final_summary_and_llm(self, final_out: str) -> None:
        s = self.settings
        vreport_path = os.path.join(s.logs_dir(), "validation_report_full.json")
        print("\n============== 📋 FINAL SUMMARY ==============")

        stats = self.vreport.data.get("map_statistics", {})
        total_roads = stats.get("total_roads", "N/A")

        try:
            total_buildings = self.vreport.data.get("buildings", {}).get(
                "inserted", "N/A"
            )
        except Exception:
            total_buildings = "N/A"

        try:
            tl = self.vreport.data.get("enrichment", {}).get(
                "traffic_lights_added", "N/A"
            )
        except Exception:
            tl = "N/A"

        try:
            tiles_created = len(os.listdir(os.path.join(self.out_dir, "tiles")))
        except Exception:
            tiles_created = 0

        max_lat = max_hdg = max_dz = None
        if "seam_statistics" in self.vreport.data:
            seam_list = self.vreport.data["seam_statistics"]
            if seam_list:
                max_lat = safe_max(item["lat"] for item in seam_list)
                max_hdg = safe_max(item["hdg"] for item in seam_list)
                max_dz = safe_max(item["dz"] for item in seam_list)

        print(f"✅ Roads:              {total_roads}")
        print(f"✅ Buildings:          {total_buildings}")
        print(f"✅ Traffic lights:     {tl}")
        print(f"✅ Tiles created:      {tiles_created}")
        print(f"✅ Tile seam max lat:  {max_lat}")
        print(f"✅ Tile seam max hdg:  {max_hdg}")
        print(f"✅ Tile seam max dz:   {max_dz}")
        db_info = self.vreport.data.get("database", {})
        if db_info:
            print(f"✅ DB path:           {db_info.get('path')}")
            print(f"?o. DB schema sha256:  {db_info.get('schema_hash_sha256')}")
            print(f"?o. DB schema md5:     {db_info.get('schema_hash_md5')}")

        # Domain gap RMSE if available
        try:
            dg = self.vreport.data.get("domain_gap_summary", {})
            if dg:
                rmse = dg.get("whole_geometry_gap", {}).get("rmse_xy", "N/A")
                print(f"✅ Domain gap RMSE:    {rmse}")
        except Exception:
            pass

        # final map hash
        final_hash = _hash_file(final_out)
        final_md5 = safe_md5_file(final_out)
        self.vreport.add_dict(
            "output_hashes",
            {"final_xodr": {"path": final_out, "sha256": final_hash, "md5": final_md5}},
        )
        print(f"✅ Final map SHA-256:      {final_hash}")
        if final_md5:
            print(f"?o. Final map MD5:          {final_md5}")

        # ---------------------------------------------------------
        # 📋 [INFO] RUN MANIFEST (final outputs; best-effort)
        # ---------------------------------------------------------
        try:
            update_run_manifest(
                self.out_dir,
                outputs={
                    "final_xodr": final_out,
                    "validation_report": vreport_path,
                    "tile_metadata": os.path.join(self.out_dir, "tile_metadata.json"),
                },
            )
        except Exception as _e:
            print(f"⚠️ Final run manifest update skipped: {_e}")

        # Write audit summary (thesis runs)
        self._write_audit_summary(Path(self.out_dir))

        # Optional post-run drivability sanity (diagnostic by default).
        # Writes: carla_drivability_sanity.json
        # Optional repair (default OFF): UP_REPAIR_ROAD_LINK_ENDPOINTS=1
        try:
            enable = os.getenv("UP_WRITE_DRIVABILITY_SANITY", "").strip().lower() in ("1", "true", "yes", "on")
            if enable:
                from ultimate_pipeline.tools.post_run_carla_sanity import write_drivability_sanity
                # Prefer the last produced XODR if manifest has it, else INPUT_XODR.
                xodr_path = Path(getattr(self.settings, "OUTPUT_XODR", "") or getattr(self.settings, "INPUT_XODR", ""))
                if xodr_path and xodr_path.exists():
                    write_drivability_sanity(self.out_dir, xodr_path)
        except Exception:
            pass

        try:
            from ultimate_pipeline.utils.finalize_run_pack import (
                write_signature_json,
                write_success_txt,
            )

            key_paths = [
                final_out,
                os.path.join(self.out_dir, "tile_metadata.json"),
                vreport_path,
                os.path.join(self.out_dir, "domain_gap", "full_report.json"),
                os.path.join(self.out_dir, "domain_gap", "summary.csv"),
                os.path.join(self.out_dir, "perception_status.json"),
            ]
            write_signature_json(self.out_dir, key_paths)
            write_success_txt(self.out_dir, summary="main_pipeline")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to write mandatory finalization artifacts (signature/success marker): {exc}"
            ) from exc

        repair_diff_path = os.path.join(self.out_dir, "repair_diff.json")
        diff_log.save(repair_diff_path)
        print(f"[INFO] Repair diff saved to {repair_diff_path}")

        print("===========================================")
        print("✅ Pipeline completed successfully.")

        self.vreport.save_json(vreport_path)
        print(f"\n📝 Validation report written → {vreport_path}")

        # gate failure summary
        gate_failures = self.qgate.get_failures()
        gate_failures_path = os.path.join(self.out_dir, "gate_failures.json")
        with open(gate_failures_path, "w", encoding="utf-8") as f:
            json.dump(gate_failures, f, indent=2)
        print(f"[INFO] Quality gate summary written → {gate_failures_path}")

        # 🤖 LLM review
        if getattr(s, "ENABLE_LLM_REVIEW", False):
            try:
                llm = LLMQualityGate()
                if gate_failures:
                    md = llm.review_gate_failures(gate_failures)
                    out_md = os.path.join(self.out_dir, "quality_gates_review.md")
                    with open(out_md, "w", encoding="utf-8") as f:
                        f.write(md)
                    print(f"🤖 LLM review (failures) written → {out_md}")

                final_md = os.path.join(self.out_dir, "quality_full_review.md")
                llm.review(
                    xodr_path=final_out,
                    validation_report_path=vreport_path,
                    out_md_path=final_md,
                )
                print(f"🧠 Full LLM QA review written → {final_md}")
            except Exception as e:
                print(f"⚠️ LLM review failed (safe to ignore): {e}")
        else:
            print("[LLM] Review disabled by settings.")

    # ---------------- 📋 AUDIT SUMMARY ----------------
    def _write_audit_summary(self, run_dir: Path) -> None:
        """
        Minimal audit artifact for thesis runs:
        - Summarizes key QA metrics from existing JSON reports if present.
        - Does NOT change thresholds or gating. Purely observational.
        """
        def _safe_read(p: Path):
            try:
                if p.exists():
                    return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
            return None

        def _max_of_list(xs):
            try:
                xs = [float(x) for x in xs if x is not None]
                return max(xs) if xs else None
            except Exception:
                return None

        qa = Path(run_dir) / "qa_stage_reports"
        cont_geom = _safe_read(qa / "06_continuity__geometric_continuity.json")
        cont_seams = _safe_read(qa / "06_continuity__planview_internal_seams.json")
        elev_cont = _safe_read(qa / "05_elevation__elevation_continuity.json")
        road_link = _safe_read(Path(run_dir) / "road_link_endpoint_errors.json")
        crs_comp = _safe_read(Path(run_dir) / "crs_comparability.json")
        dem_qc = _safe_read(Path(run_dir) / "elevation_dem_qc.json")

        # Best-effort extraction: tolerate schema changes
        dxy = None
        dhdg = None
        seam = None
        elev_jumps = None
        elev_suspicious_ratio = None

        if isinstance(cont_geom, dict):
            dxy = _max_of_list(cont_geom.get("dxy_errors_m", []) or cont_geom.get("dxy", []) or [])
            dhdg = _max_of_list(cont_geom.get("dhdg_errors_rad", []) or cont_geom.get("dhdg", []) or [])

        if isinstance(cont_seams, dict):
            seam = _max_of_list(cont_seams.get("seam_errors_m", []) or cont_seams.get("seams_m", []) or [])

        if isinstance(elev_cont, dict):
            # Best-effort: issues might be a count or a list of details
            raw_issues = elev_cont.get("issue_count", elev_cont.get("issues", 0) or 0)
            if isinstance(raw_issues, list):
                elev_jumps = len(raw_issues)
            else:
                try:
                    elev_jumps = int(raw_issues or 0)
                except Exception:
                    elev_jumps = 0
            elev_suspicious_ratio = elev_cont.get("suspicious_ratio", None)

        road_link_max = None
        if isinstance(road_link, dict):
            if "max_abs_error_m" in road_link:
                try:
                    road_link_max = float(road_link.get("max_abs_error_m"))
                except Exception:
                    road_link_max = None
            elif isinstance(road_link.get("errors"), list):
                road_link_max = _max_of_list([e.get("abs_error_m") for e in road_link["errors"]])

        summary = {
            "run_dir": str(run_dir),
            "crs": {
                "manual_present": bool(crs_comp.get("manual", {}).get("present")) if isinstance(crs_comp, dict) else None,
                "crs_match": bool(crs_comp.get("comparability", {}).get("crs_match")) if isinstance(crs_comp, dict) else None,
            },
            "dem": {
                "bbox_intersects_dem_bounds_wgs84": dem_qc.get("bbox_intersects_dem_bounds_wgs84") if isinstance(dem_qc, dict) else None,
                "dem_nodata_ratio": dem_qc.get("dem_nodata_ratio") if isinstance(dem_qc, dict) else None,
                "header_offset_policy": dem_qc.get("header_offset_policy") if isinstance(dem_qc, dict) else None,
            },
            "continuity": {
                "max_dxy_m": dxy,
                "max_dhdg_rad": dhdg,
                "max_internal_seam_m": seam,
            },
            "elevation": {
                "continuity_issue_count": elev_jumps,
                "suspicious_ratio": elev_suspicious_ratio,
            },
            "topology": {
                "road_link_endpoint_max_abs_error_m": road_link_max,
            },
            "note": "Best-effort audit summary; does not affect QA gating.",
        }

        out = Path(run_dir) / "audit_summary.json"
        try:
            out.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            pass

    # ---------------- 🎲 DETERMINISM FINGERPRINT ----------------
    def _write_determinism_fingerprint(self, final_out: str) -> None:
        """Write a lightweight determinism fingerprint (best-effort)."""
        try:
            import hashlib
            import platform

            def _sha256_text(text: str) -> str:
                return hashlib.sha256(text.encode("utf-8")).hexdigest()

            def _read_text_norm(path: str) -> Optional[str]:
                if not os.path.exists(path):
                    return None
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = f.read()
                    return data.replace("\r\n", "\n").replace("\r", "\n")
                except Exception:
                    return None

            payload: Dict[str, Any] = {
                "final_xodr": None,
                "enrichments_json": None,
                "settings_snapshot": None,
                "seed": getattr(self.settings, "DETERMINISTIC_SEED", None),
                "seeds": {
                    "deterministic_seed": getattr(
                        self.settings, "DETERMINISTIC_SEED", None
                    ),
                    "python_hash_seed": os.getenv("PYTHONHASHSEED"),
                },
                "env": {k: v for k, v in os.environ.items() if k.startswith("UP_")},
                "python_version": sys.version,
                "os_info": platform.platform(),
                "git_commit": None,
            }
            try:
                payload["git_commit"] = (
                    subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
                    )
                    .decode("utf-8")
                    .strip()
                )
            except Exception:
                payload["git_commit"] = None

            xodr_text = _read_text_norm(final_out)
            if xodr_text is not None:
                payload["final_xodr"] = _sha256_text(xodr_text)

            enrichments_path = os.path.join(self.out_dir, "enrichments.json")
            enrichments_text = _read_text_norm(enrichments_path)
            if enrichments_text is not None:
                payload["enrichments_json"] = _sha256_text(enrichments_text)

            settings_snapshot_path = os.path.join(
                self.out_dir, "settings_snapshot.json"
            )
            settings_text = _read_text_norm(settings_snapshot_path)
            if settings_text is not None:
                payload["settings_snapshot"] = _sha256_text(settings_text)

            out_path = os.path.join(self.out_dir, "determinism_fingerprint.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=True)
        except Exception:
            pass

    def _write_bbox_contract_artifact(self, final_out: str) -> None:
        """Write run-root bbox.json anchored to final XODR output."""
        bbox_path = os.path.join(self.out_dir, "bbox.json")
        payload: Dict[str, Any] = {}
        try:
            gps = getattr(self.settings, "GPS_BOUNDS", None)
            if isinstance(gps, str):
                try:
                    gps = json.loads(gps)
                except Exception:
                    gps = None
            if not isinstance(gps, dict):
                try:
                    gps = self.settings.load_gps_bounds()
                except Exception:
                    gps = None
            if isinstance(gps, dict):
                payload["bbox"] = {
                    "lat_min": float(gps.get("lat_min")),
                    "lon_min": float(gps.get("lon_min")),
                    "lat_max": float(gps.get("lat_max")),
                    "lon_max": float(gps.get("lon_max")),
                }
        except Exception:
            pass

        georef_info = self._read_georef_info(final_out)
        payload.update(
            {
                "xodr_path": str(Path(final_out).name),
                "xodr_sha256": _hash_file(final_out),
                "xodr_geoReference": georef_info.get("raw", ""),
                "xodr_geoReference_norm": georef_info.get("norm", ""),
                "georeference_params_complete": bool(
                    georef_info.get("params_complete", False)
                ),
                "header_offset": self._read_offset(final_out),
            }
        )

        map_bbox = None
        map_bbox_wgs84 = None
        map_crs = None
        map_crs_source = ""
        map_crs_raw = ""
        try:
            from ultimate_pipeline.enrichment.elevation_importer import (
                _compute_xodr_planview_bbox,
                _infer_map_crs,
                _transform_bbox,
            )

            map_bbox = _compute_xodr_planview_bbox(final_out)
            map_crs, map_crs_source, map_crs_raw = _infer_map_crs(
                final_out, georef_info.get("raw", "")
            )
            if map_bbox is not None and map_crs is not None:
                try:
                    from pyproj import CRS, Transformer

                    wgs84 = CRS.from_user_input("EPSG:4326")
                    if map_crs == wgs84:
                        map_bbox_wgs84 = dict(map_bbox)
                    else:
                        tf = Transformer.from_crs(map_crs, wgs84, always_xy=True)
                        map_bbox_wgs84 = _transform_bbox(map_bbox, tf)
                except Exception:
                    map_bbox_wgs84 = None
        except Exception as exc:
            payload["bbox_compute_error"] = str(exc)

        payload.update(
            {
                "map_crs": str(map_crs) if map_crs is not None else "",
                "map_crs_source": str(map_crs_source or ""),
                "map_crs_raw": str(map_crs_raw or ""),
                "bbox_in_map_crs": map_bbox,
                "bbox_in_wgs84": map_bbox_wgs84,
            }
        )

        settings_snapshot_path = os.path.join(self.out_dir, "settings_snapshot.json")
        if os.path.exists(settings_snapshot_path):
            payload["settings_snapshot_path"] = "settings_snapshot.json"
            payload["settings_snapshot_sha256"] = _hash_file(settings_snapshot_path)
        else:
            payload["settings_snapshot_path"] = ""
            payload["settings_snapshot_sha256"] = ""

        hash_payload = dict(payload)
        hash_payload.pop("bbox_hash_sha256", None)
        payload["bbox_hash_sha256"] = hashlib.sha256(
            json.dumps(hash_payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        ).hexdigest()

        with open(bbox_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True, sort_keys=True)

    # ---------------- 📋 RUN SUMMARY MANIFEST ----------------
    def _write_run_summary(self, final_out: str) -> None:
        """
        Write a comprehensive run_summary.json with paths to all key artifacts,
        including preflight status if run.
        """
        from datetime import datetime, timezone

        s = self.settings
        summary_path = os.path.join(self.out_dir, "run_summary.json")

        # Collect artifact paths
        self._write_bbox_contract_artifact(final_out)
        input_osm_path = getattr(s, "OSM_FILE", "")
        bbox_path = os.path.join(self.out_dir, "bbox.json")
        if not os.path.exists(bbox_path):
            bbox_path = (
                os.path.join(s.data_dir(), "bbox.json") if hasattr(s, "data_dir") else ""
            )

        # Handle semantic xodr (if it exists)
        semantic_xodr = final_out.replace(".xodr", "_semantic.xodr")
        if not os.path.exists(semantic_xodr):
            semantic_xodr = ""

        # Preflight status
        preflight_status = None
        preflight_report_path = None
        carla_loadability_path = os.path.join(
            self.out_dir, "carla_loadability_status.json"
        )
        if os.path.exists(carla_loadability_path):
            try:
                with open(carla_loadability_path, "r", encoding="utf-8") as f:
                    loadability_data = json.load(f)
                    preflight_status = loadability_data.get("status")
                    preflight_report_path = loadability_data.get(
                        "preflight_report_path"
                    )
            except Exception:
                pass

        # Tile QA status (prefer STEP10 status, with legacy fallback)
        tile_qa_status = None
        tile_qa_status_path = None
        for candidate in ("step10_tile_qa_status.json", "tile_qa_status.json"):
            p = os.path.join(self.out_dir, candidate)
            if not os.path.exists(p):
                continue
            tile_qa_status_path = p
            try:
                with open(p, "r", encoding="utf-8") as f:
                    tile_qa_data = json.load(f) or {}
                if isinstance(tile_qa_data, dict):
                    tile_qa_status = tile_qa_data.get("status")
            except Exception:
                tile_qa_status = None
            break

        # Settings snapshot hash
        settings_hash = None
        settings_snapshot_path = os.path.join(self.out_dir, "settings_snapshot.json")
        if os.path.exists(settings_snapshot_path):
            settings_hash = _hash_file(settings_snapshot_path)

        run_summary = {
            "pipeline_version": "thesis_final",
            "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "run_dir": self.out_dir,
            "inputs": {
                "osm_file": input_osm_path,
                "bbox_json": bbox_path if os.path.exists(bbox_path) else None,
            },
            "outputs": {
                "final_xodr": final_out,
                "semantic_xodr": semantic_xodr if semantic_xodr else None,
            },
            "validation": {
                "preflight_status": preflight_status,
                "preflight_report": preflight_report_path,
                "tile_qa_status": tile_qa_status,
                "tile_qa_status_path": tile_qa_status_path,
            },
            "settings": {
                "snapshot_path": settings_snapshot_path,
                "snapshot_sha256": settings_hash,
                "snapshot_md5": safe_md5_file(settings_snapshot_path),
            },
        }

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(run_summary, f, indent=2, ensure_ascii=False)

        print(f"🧾 Run summary manifest written → {summary_path}")
        try:
            from ultimate_pipeline.utils.environment_snapshot import (
                write_environment_snapshot,
            )

            write_environment_snapshot(Path(self.out_dir) / "environment_snapshot.json")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to write mandatory environment snapshot artifact: {exc}"
            ) from exc

    def _run_carla_final_test_subprocess(
        self, xodr_path: str, *, tile_name: str
    ) -> Dict[str, Any]:
        """Run CARLA final validation in a child process.

        CARLA + the PythonAPI can occasionally terminate the interpreter on
        disconnect/reconnect (native crash). Running this in a subprocess keeps
        the *pipeline* alive and still yields a JSON report.
        """
        import sys
        import subprocess
        import json
        from pathlib import Path

        report_dir = Path(self.out_dir) / "logs" / "tile_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        out_json = report_dir / f"tile_{tile_name}_carla_final.json"

        cmd = [
            sys.executable,
            "-m",
            "ultimate_pipeline.carla_tools.carla_final_test",
            "--xodr",
            xodr_path,
            "--host",
            getattr(self.settings, "CARLA_HOST", "127.0.0.1"),
            "--port",
            str(getattr(self.settings, "CARLA_PORT", 2000)),
            "--timeout_s",
            str(getattr(self.settings, "CARLA_TILE_WORKER_RPC_TIMEOUT", 180.0)),
            "--retries",
            "1",
            "--no_spawn",
            "--json_out",
            str(out_json),
        ]

        cp = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        rep: Dict[str, Any] = {}
        if out_json.exists():
            try:
                rep = json.loads(out_json.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                rep = {"status": "invalid_json"}

        rep["subprocess_returncode"] = int(cp.returncode)
        rep["stdout_tail"] = (cp.stdout or "")[-4000:]

        if cp.returncode != 0 and rep.get("status") in (None, "ok", "success"):
            rep["status"] = "native_crash_or_nonzero"

        return rep


def main(argv: Optional[List[str]] = None) -> int:
    sentinel_path = os.getenv("UP_MAIN_PIPELINE_MAIN_CALLED_SENTINEL", "").strip()
    if sentinel_path:
        try:
            Path(sentinel_path).write_text("main_called", encoding="utf-8")
        except Exception:
            pass
    args = argv if argv is not None else sys.argv[1:]
    if "--help" in args or "-h" in args:
        print("📘 Usage: python -m ultimate_pipeline.main_pipeline")
        return 0
    MainPipeline().run()
    return 0


if __name__ == "__main__":
    import multiprocessing as _mp

    _mp.freeze_support()
    parent = _mp.parent_process()
    if parent is not None:
        raise SystemExit(0)
    raise SystemExit(main())
