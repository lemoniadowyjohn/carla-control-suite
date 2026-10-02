"""RQ2 production metric authority (STRUCTURAL DOMAIN GAP).

Single production-facing RQ2 API. All RQ2 evidence must flow through
``run_rq2_comparison``; alternate implementations (GeoAligner SE(2) path,
standalone CurvatureGap KL path, tile_matcher correspondence) remain available
as INDEPENDENT_ORACLEs but are NOT authoritative producers.

Thesis contract: research/thesis_rq_contract.yaml, RQ2 STRUCTURAL DOMAIN GAP.
Primary thesis metrics: lane_width_gap, curvature_gap,
curvature_wasserstein_gap, road_count_ratio, road_length_ratio,
junction_ratio, building_density_gap, frechet_distance, connectivity_gap,
semantic_object_gap.

Scopes (never mixed):
  - "manual_hull": governed local/manual-footprint methodology (PRIMARY).
    Auto is cropped to the convex hull of the manual map's planView geometry,
    both maps compared with manual as reference.
  - "whole_map": supplementary context only (uncropped full-network
    comparison; known scope artifact: full OSM extraction vs curated patch).

Curve-level correspondence (frechet_distance) is only defined for
"manual_hull": whole-map matching across disparate extents is
methodology-invalid, so whole_map reports frechet_distance as NOT_RUN.
"""

from __future__ import annotations

import hashlib
import math
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

from ultimate_pipeline.domain_gap import local_registration as _lr
from ultimate_pipeline.domain_gap.frechet_gap import compute_frechet_gap
from ultimate_pipeline.domain_gap.gap_analyzer import DomainGapAnalyzer
from ultimate_pipeline.domain_gap.map_stats_xodr import XODRMapStatsExtractor

SCOPES = ("manual_hull", "whole_map")

THESIS_PRIMARY_METRICS = (
    "lane_width_gap",
    "curvature_gap",
    "curvature_wasserstein_gap",
    "road_count_ratio",
    "road_length_ratio",
    "junction_ratio",
    "building_density_gap",
    "frechet_distance",
    "connectivity_gap",
    "semantic_object_gap",
)

_LFS_POINTER_PREFIX = b"version https://git-lfs"

DEFAULT_CONFIG: Dict[str, Any] = {
    "footprint": "hull",
    "lane_width_scale_m": 3.5,
    "frechet_spacing_m": 5.0,
    "frechet_match_threshold_m": 50.0,
    "frechet_coarse_step_m": 20.0,
    "frechet_dense_step_m": 1.0,
    "include_frechet": True,
    "include_connectivity": True,
    "include_semantic": True,
    "verify_shas": False,
    "expected_auto_sha256": None,
    "expected_manual_sha256": None,
}


@dataclass
class RQ2Result:
    scope: str
    primary: Dict[str, Any] = field(default_factory=dict)
    supplementary: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _candidate_commit() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            timeout=30,
        )
        sha = (out.stdout or "").strip()
        return sha or None
    except Exception:
        return None


def _require_finite(name: str, value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"rq2 authority: metric {name!r} is not numeric: {value!r}")
    if not math.isfinite(v):
        raise ValueError(f"rq2 authority: metric {name!r} is NaN/inf: {value!r}")
    return v


def _validate_inputs(
    auto_xodr: str, manual_xodr: str, scope: str, config: Dict[str, Any]
) -> Tuple[ET.Element, ET.Element]:
    if scope not in SCOPES:
        raise ValueError(
            f"rq2 authority: unsupported scope {scope!r}; must be one of {list(SCOPES)}"
        )
    for label, path in (("auto_xodr", auto_xodr), ("manual_xodr", manual_xodr)):
        if not path or not os.path.isfile(path):
            raise ValueError(f"rq2 authority: {label} not found: {path!r}")
        with open(path, "rb") as f:
            head = f.read(1024)
        if head.startswith(_LFS_POINTER_PREFIX):
            raise ValueError(
                f"rq2 authority: {label} is an unresolved Git-LFS pointer: {path!r} "
                "(MAP_LFS_UNRESOLVED)"
            )
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            raise ValueError(
                f"rq2 authority: {label} is not valid XML/XODR: {path!r}: {exc}"
            )
        if root.tag != "OpenDRIVE":
            raise ValueError(
                f"rq2 authority: {label} root tag is {root.tag!r}, expected 'OpenDRIVE' "
                f"(invalid XODR): {path!r}"
            )
    auto_root = ET.parse(auto_xodr).getroot()
    manual_root = ET.parse(manual_xodr).getroot()
    # Frame validation: both maps must carry a usable geoReference.
    try:
        auto_proj = _lr.read_georef_proj4(auto_root)
        manual_proj = _lr.read_georef_proj4(manual_root)
    except ValueError as exc:
        raise ValueError(f"rq2 authority: frame mismatch (geoReference): {exc}")
    _lr.read_offset(auto_root)
    _lr.read_offset(manual_root)
    if not auto_root.findall("road"):
        raise ValueError("rq2 authority: empty road network in auto_xodr")
    if not manual_root.findall("road"):
        raise ValueError("rq2 authority: empty road network in manual_xodr")
    if config.get("verify_shas"):
        exp_auto = config.get("expected_auto_sha256")
        exp_man = config.get("expected_manual_sha256")
        if exp_auto:
            actual = _sha256_file(auto_xodr)
            if actual.lower() != str(exp_auto).lower():
                raise ValueError(
                    "rq2 authority: wrong auto SHA "
                    f"(expected {exp_auto}, actual {actual})"
                )
        if exp_man:
            actual = _sha256_file(manual_xodr)
            if actual.lower() != str(exp_man).lower():
                raise ValueError(
                    "rq2 authority: wrong manual source SHA "
                    f"(expected {exp_man}, actual {actual})"
                )
    return auto_root, manual_root


def _ratio(auto_v: float, manual_v: float) -> Optional[float]:
    if not manual_v:
        return None
    v = auto_v / manual_v
    if not math.isfinite(v):
        raise ValueError(f"rq2 authority: non-finite ratio {auto_v}/{manual_v}")
    return round(v, 3)


def _materialize_scoped_auto(
    auto_xodr: str, manual_xodr: str, *, footprint: str = "hull"
) -> Tuple[str, Dict[str, Any]]:
    """Write the footprint-cropped auto network to a temp XODR file.

    Reuses local_registration primitives (same transforms, same crop rules,
    same building holder-road convention as compute_local_registration) so the
    scoped ConnectivityGap/SemanticGap inputs match the primary comparison
    exactly. Returns (temp path, crop provenance).
    """
    auto_root = ET.parse(auto_xodr).getroot()
    manual_root = ET.parse(manual_xodr).getroot()
    auto_off = _lr.read_offset(auto_root)
    auto_proj = _lr.read_georef_proj4(auto_root)
    manual_proj = _lr.read_georef_proj4(manual_root)
    if footprint == "hull":
        hull_pts = _lr.manual_geometry_convex_hull(manual_root)
        poly = _lr.transform_manual_points_to_auto_local(
            hull_pts, manual_proj, auto_proj, auto_off
        )
    elif footprint == "bbox":
        bbox = _lr.manual_geometry_bbox(manual_root)
        poly = _lr.transform_manual_bbox_to_auto_local(
            bbox, manual_proj, auto_proj, auto_off
        )
    else:  # pragma: no cover - guarded by scope validation
        raise ValueError(f"unsupported footprint {footprint!r}")
    auto_roads = auto_root.findall("road")
    kept_roads = _lr.crop_roads_to_polygon(auto_roads, poly)
    keep_j = _lr.kept_junction_ids(kept_roads)
    try:
        from ultimate_pipeline.config.settings import SETTINGS

        gps = SETTINGS.load_gps_bounds()
        bld_shift: Any = _lr.building_frame_shift_to_auto_local(
            osm_lat_min=gps["lat_min"],
            osm_lon_min=gps["lon_min"],
            auto_proj4=auto_proj,
            auto_offset=auto_off,
        )
        shift_source = "settings_gps_bounds"
    except Exception:
        bld_shift = (0.0, 0.0)
        shift_source = "unavailable_fallback_zero"
    all_buildings = _lr.collect_building_objects(auto_root)
    kept_buildings = _lr.crop_buildings_to_polygon(
        all_buildings, poly, shift=bld_shift
    )
    cropped = ET.Element("OpenDRIVE")
    for r in kept_roads:
        cropped.append(r)
    for j in auto_root.findall("junction"):
        if j.get("id") in keep_j:
            cropped.append(j)
    if kept_buildings:
        holder = ET.SubElement(
            cropped, "road", id="__cropped_buildings__", junction="-1", length="0"
        )
        objs = ET.SubElement(holder, "objects")
        for b in kept_buildings:
            objs.append(b)
    tmp = tempfile.NamedTemporaryFile(
        suffix="_rq2_scoped_auto.xodr", delete=False
    )
    tmp_path = tmp.name
    tmp.close()
    ET.ElementTree(cropped).write(tmp_path, encoding="utf-8", xml_declaration=True)
    return tmp_path, {
        "footprint_kind": footprint,
        "auto_roads_total": len(auto_roads),
        "auto_roads_kept": len(kept_roads),
        "building_frame_shift_source": shift_source,
        "full_auto_building_count": len(all_buildings),
        "cropped_auto_building_count": len(kept_buildings),
    }


def _check_required_metrics(primary: Dict[str, Any]) -> None:
    missing = [m for m in THESIS_PRIMARY_METRICS if m not in primary]
    if missing:
        raise ValueError(
            f"rq2 authority: missing required thesis metric(s): {missing}"
        )


def run_rq2_comparison(
    auto_xodr: str,
    manual_xodr: str,
    scope: str,
    config: Optional[Dict[str, Any]] = None,
) -> RQ2Result:
    """Run the authoritative RQ2 comparison for one explicit scope."""
    cfg: Dict[str, Any] = dict(DEFAULT_CONFIG)
    if config:
        unknown = set(config) - set(DEFAULT_CONFIG)
        if unknown:
            raise ValueError(
                f"rq2 authority: unknown config key(s): {sorted(unknown)}"
            )
        cfg.update(config)

    _validate_inputs(auto_xodr, manual_xodr, scope, cfg)

    auto_sha = _sha256_file(auto_xodr)
    manual_sha = _sha256_file(manual_xodr)
    with open(os.path.abspath(__file__), "r", encoding="utf-8") as f:
        authority_impl_sha = _sha256_text(f.read())

    provenance: Dict[str, Any] = {
        "authority": "ultimate_pipeline/domain_gap/rq2_metric_authority.py",
        "authority_impl_sha256": authority_impl_sha,
        "candidate_commit": _candidate_commit(),
        "auto_xodr": os.path.abspath(auto_xodr),
        "auto_sha256": auto_sha,
        "manual_xodr": os.path.abspath(manual_xodr),
        "manual_sha256": manual_sha,
        "scope": scope,
        "config": {
            k: cfg[k]
            for k in (
                "footprint",
                "lane_width_scale_m",
                "frechet_spacing_m",
                "frechet_match_threshold_m",
                "frechet_coarse_step_m",
                "frechet_dense_step_m",
            )
        },
    }

    primary: Dict[str, Any] = {}
    supplementary: Dict[str, Any] = {}

    if scope == "manual_hull":
        footprint = cfg["footprint"]
        if footprint not in ("hull", "bbox"):
            raise ValueError(
                f"rq2 authority: footprint must be 'hull' or 'bbox', got {footprint!r}"
            )
        provenance["scope_definition"] = (
            "auto cropped to manual footprint polygon "
            f"({footprint}); manual is reference; governed local methodology"
        )
        result = _lr.compute_local_registration(
            auto_xodr, manual_xodr, footprint=footprint
        )
        summary = _lr.local_structural_summary(result)
        net = summary["road_network_structural"]
        primary["lane_width_gap"] = _require_finite(
            "lane_width_gap", net["lane_width_gap"]
        )
        primary["curvature_gap"] = _require_finite(
            "curvature_gap", net["curvature_gap"]
        )
        primary["curvature_wasserstein_gap"] = _require_finite(
            "curvature_wasserstein_gap", net["curvature_wasserstein_gap"]
        )
        for key in (
            "road_length_ratio_auto_over_manual",
            "junction_ratio_auto_over_manual",
            "road_count_ratio_auto_over_manual",
        ):
            val = net[key]
            if val is None:
                raise ValueError(f"rq2 authority: metric {key} is None (empty ref)")
            _require_finite(key, val)
        primary["road_length_ratio"] = net["road_length_ratio_auto_over_manual"]
        primary["junction_ratio"] = net["junction_ratio_auto_over_manual"]
        primary["road_count_ratio"] = net["road_count_ratio_auto_over_manual"]
        primary["building_density_gap"] = _require_finite(
            "building_density_gap",
            summary["building_density_comparison"]["building_density_gap"],
        )
        provenance["matching_parameters"] = {
            "scope_rule": "road kept if planView-geometry centroid inside manual footprint polygon",
            "building_rule": "frame-shifted cornerGlobal centroid inside footprint polygon",
            "building_frame_shift_source": result.provenance.get(
                "building_frame_shift_source"
            ),
            "lane_width_scale_m": cfg["lane_width_scale_m"],
        }
        provenance["sampling_parameters"] = {
            "curvature": "map_stats collection (paramPoly3/arc sampling per geometry)",
            "lane_width": "map_stats lane-width collection",
        }

        if cfg.get("include_frechet", True):
            frech = compute_frechet_gap(
                auto_xodr,
                manual_xodr,
                spacing_m=float(cfg["frechet_spacing_m"]),
                match_threshold_m=float(cfg["frechet_match_threshold_m"]),
                footprint=footprint,
                coarse_step_m=float(cfg["frechet_coarse_step_m"]),
                dense_step_m=float(cfg["frechet_dense_step_m"]),
            )
            for k in ("mean_m", "median_m", "p90_m"):
                if frech.get(k) is not None:
                    _require_finite(f"frechet_{k}", frech[k])
            primary["frechet_distance"] = frech
            provenance["matching_parameters"]["frechet_matching"] = (
                "elevation_gap._match_roads on coarse profiles in manual frame; "
                f"match_threshold_m={cfg['frechet_match_threshold_m']}"
            )
            provenance["sampling_parameters"]["frechet"] = (
                f"dense_step_m={cfg['frechet_dense_step_m']}, "
                f"spacing_m={cfg['frechet_spacing_m']}"
            )
        else:
            primary["frechet_distance"] = {"status": "NOT_RUN", "reason": "disabled by config"}

        scoped_path, crop_prov = _materialize_scoped_auto(
            auto_xodr, manual_xodr, footprint=footprint
        )
        provenance["scope_crop"] = crop_prov
        try:
            if cfg.get("include_connectivity", True):
                from ultimate_pipeline.domain_gap.connectivity_gap import (
                    ConnectivityGap,
                )

                conn = ConnectivityGap.compute(manual_xodr, scoped_path)
                if conn.get("disabled"):
                    raise ValueError(
                        "rq2 authority: connectivity computation disabled: "
                        f"{conn.get('error')}"
                    )
                primary["connectivity_gap"] = conn.get("gap", conn)
                supplementary["connectivity_detail"] = {
                    "manual": conn.get("manual"),
                    "auto_scoped": conn.get("auto"),
                }
            else:
                primary["connectivity_gap"] = {"status": "NOT_RUN"}
            if cfg.get("include_semantic", True):
                from ultimate_pipeline.domain_gap.semantic_gap import SemanticGap

                sem = SemanticGap.compare(manual_xodr, scoped_path)
                primary["semantic_object_gap"] = sem
            else:
                primary["semantic_object_gap"] = {"status": "NOT_RUN"}
        finally:
            try:
                os.remove(scoped_path)
            except OSError:
                pass
        supplementary["footprint"] = summary["footprint"]
        supplementary["construction_differences_excluded"] = summary[
            "construction_differences_excluded"
        ]

    elif scope == "whole_map":
        provenance["scope_definition"] = (
            "SUPPLEMENTARY context only: full uncropped networks compared; "
            "known scope artifact (full OSM extraction vs curated manual patch)"
        )
        manual_stats = XODRMapStatsExtractor.from_file(manual_xodr)
        auto_stats = XODRMapStatsExtractor.from_file(auto_xodr)
        if manual_stats.num_roads == 0 or auto_stats.num_roads == 0:
            raise ValueError("rq2 authority: empty road network in whole_map scope")
        scores = DomainGapAnalyzer.compare_xodr_to_xodr(
            manual_stats,
            auto_stats,
            lane_width_scale_m=float(cfg["lane_width_scale_m"]),
        )
        primary["lane_width_gap"] = _require_finite(
            "lane_width_gap", scores.lane_width_gap
        )
        primary["curvature_gap"] = _require_finite(
            "curvature_gap", scores.curvature_gap
        )
        primary["curvature_wasserstein_gap"] = _require_finite(
            "curvature_wasserstein_gap", scores.curvature_wasserstein_gap
        )
        primary["road_length_ratio"] = _ratio(
            auto_stats.total_road_length, manual_stats.total_road_length
        )
        primary["junction_ratio"] = _ratio(
            float(auto_stats.num_junctions), float(manual_stats.num_junctions)
        )
        primary["road_count_ratio"] = _ratio(
            float(auto_stats.num_roads), float(manual_stats.num_roads)
        )
        primary["building_density_gap"] = _require_finite(
            "building_density_gap", scores.building_density_gap
        )
        primary["frechet_distance"] = {
            "status": "NOT_RUN",
            "reason": "curve correspondence across disparate whole-map extents is methodology-invalid",
        }
        if cfg.get("include_connectivity", True):
            from ultimate_pipeline.domain_gap.connectivity_gap import ConnectivityGap

            conn = ConnectivityGap.compute(manual_xodr, auto_xodr)
            if conn.get("disabled"):
                raise ValueError(
                    "rq2 authority: connectivity computation disabled: "
                    f"{conn.get('error')}"
                )
            primary["connectivity_gap"] = conn.get("gap", conn)
        else:
            primary["connectivity_gap"] = {"status": "NOT_RUN"}
        if cfg.get("include_semantic", True):
            from ultimate_pipeline.domain_gap.semantic_gap import SemanticGap

            primary["semantic_object_gap"] = SemanticGap.compare(
                manual_xodr, auto_xodr
            )
        else:
            primary["semantic_object_gap"] = {"status": "NOT_RUN"}
        supplementary["whole_map_counts"] = {
            "auto_roads": auto_stats.num_roads,
            "manual_roads": manual_stats.num_roads,
            "auto_total_length_m": auto_stats.total_road_length,
            "manual_total_length_m": manual_stats.total_road_length,
            "auto_junctions": auto_stats.num_junctions,
            "manual_junctions": manual_stats.num_junctions,
            "auto_buildings": auto_stats.num_buildings,
            "manual_buildings": manual_stats.num_buildings,
        }
        provenance["matching_parameters"] = {
            "scope_rule": "none (full networks)",
            "lane_width_scale_m": cfg["lane_width_scale_m"],
        }
        provenance["sampling_parameters"] = {
            "curvature": "map_stats collection (paramPoly3/arc sampling per geometry)",
            "lane_width": "map_stats lane-width collection",
        }
    else:  # pragma: no cover - guarded by _validate_inputs
        raise ValueError(f"rq2 authority: unsupported scope {scope!r}")

    _check_required_metrics(primary)
    return RQ2Result(scope=scope, primary=primary, supplementary=supplementary, provenance=provenance)
