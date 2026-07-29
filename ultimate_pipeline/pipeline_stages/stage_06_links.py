# REFAC_VERSION = "v5_preserve"
# NOTE: This file is auto-extracted from ultimate_pipeline/main_pipeline.py.
# It delegates to original helpers by injecting main_pipeline globals at runtime.

from __future__ import annotations

import copy
import json
import math
import os
import shutil
import xml.etree.ElementTree as ET
from typing import Any, Dict, List


PROTECTED_STAGE6_TAGS = (
    "planView",
    "elevationProfile",
    "lateralProfile",
    "lanes",
    "signals",
    "objects",
    "LaneLinks",
)


def _stage6_governed_containment(settings_obj) -> bool:
    profile = str(getattr(settings_obj, "RELEASE_PROFILE", "") or "").strip().upper()
    if bool(getattr(settings_obj, "THESIS_STRICT", False)):
        return True
    if profile == "EXPERIMENTAL_UNSAFE":
        return False
    if profile and profile != "DEVELOPMENT":
        return True
    return False


def _road_dependencies(road: ET.Element) -> List[str]:
    deps: List[str] = ["road.length"]
    for tag in PROTECTED_STAGE6_TAGS:
        if road.find(tag) is not None:
            deps.append(tag)
    return deps


def _geom_value(geom: ET.Element | None) -> Dict[str, Any] | None:
    if geom is None:
        return None
    return {
        "attributes": dict(geom.attrib),
        "primitive": [child.tag for child in list(geom)],
        "xml": ET.tostring(geom, encoding="unicode"),
    }


def _geom_endpoint(geom: ET.Element | None) -> tuple[float, float, float] | None:
    if geom is None:
        return None
    try:
        x = float(geom.get("x", "0") or 0.0)
        y = float(geom.get("y", "0") or 0.0)
        hdg = float(geom.get("hdg", "0") or 0.0)
        length = float(geom.get("length", "0") or 0.0)
    except Exception:
        return None
    arc = geom.find("arc")
    if arc is not None:
        try:
            k = float(arc.get("curvature", "0") or 0.0)
        except Exception:
            k = 0.0
        if abs(k) > 1e-12:
            dx_local = math.sin(k * length) / k
            dy_local = (1.0 - math.cos(k * length)) / k
            return (
                x + math.cos(hdg) * dx_local - math.sin(hdg) * dy_local,
                y + math.sin(hdg) * dx_local + math.cos(hdg) * dy_local,
                hdg + k * length,
            )
    return (x + length * math.cos(hdg), y + length * math.sin(hdg), hdg)


def _predicted_delta(old_geom: ET.Element | None, new_geom: ET.Element | None) -> Dict[str, Any]:
    old_ep = _geom_endpoint(old_geom)
    new_ep = _geom_endpoint(new_geom)
    if old_ep is None or new_ep is None:
        return {
            "predicted_endpoint_displacement_m": None,
            "predicted_tangent_change_rad": None,
        }
    return {
        "predicted_endpoint_displacement_m": float(
            math.hypot(new_ep[0] - old_ep[0], new_ep[1] - old_ep[1])
        ),
        "predicted_tangent_change_rad": float(new_ep[2] - old_ep[2]),
    }


def _diagnostic_records_for_operation(
    before_root: ET.Element,
    after_root: ET.Element,
    *,
    operation: str,
    reason: str,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    before_roads = {
        str(road.get("id", "")): road
        for road in before_root.findall("road")
    }
    after_roads = {
        str(road.get("id", "")): road
        for road in after_root.findall("road")
    }
    for road_id, before_road in sorted(before_roads.items()):
        after_road = after_roads.get(road_id)
        if after_road is None:
            continue
        before_geoms = list(before_road.findall("./planView/geometry"))
        after_geoms = list(after_road.findall("./planView/geometry"))
        max_len = max(len(before_geoms), len(after_geoms))
        for idx in range(max_len):
            old_geom = before_geoms[idx] if idx < len(before_geoms) else None
            new_geom = after_geoms[idx] if idx < len(after_geoms) else None
            old_value = _geom_value(old_geom)
            new_value = _geom_value(new_geom)
            if old_value == new_value:
                continue
            rec: Dict[str, Any] = {
                "operation": operation,
                "mode": "READ_ONLY_DIAGNOSTIC",
                "affected_road": road_id,
                "geometry_index": idx,
                "old_value": old_value,
                "proposed_value": new_value,
                "reason": reason,
                "dependent_records_affected": _road_dependencies(before_road),
            }
            rec.update(_predicted_delta(old_geom, new_geom))
            records.append(rec)
    return records


def _observe_planview_operation(
    root: ET.Element,
    *,
    operation: str,
    reason: str,
    mutator,
) -> Dict[str, Any]:
    probe_root = copy.deepcopy(root)
    try:
        call_count = mutator(probe_root)
    except Exception as exc:
        return {
            "operation": operation,
            "mode": "READ_ONLY_DIAGNOSTIC",
            "call_count": 0,
            "error": str(exc),
            "proposals": [],
        }
    proposals = _diagnostic_records_for_operation(
        root,
        probe_root,
        operation=operation,
        reason=reason,
    )
    return {
        "operation": operation,
        "mode": "READ_ONLY_DIAGNOSTIC",
        "call_count": int(call_count or 0) if call_count is not None else len(proposals),
        "proposals": proposals,
    }


def _protected_stage6_signature(path: str) -> Dict[str, Any]:
    root = ET.parse(path).getroot()
    roads: Dict[str, Any] = {}
    for road in root.findall("road"):
        rid = str(road.get("id", ""))
        roads[rid] = {
            "length": road.get("length"),
            "protected": {
                tag: [
                    ET.tostring(child, encoding="unicode")
                    for child in road.findall(tag)
                ]
                for tag in PROTECTED_STAGE6_TAGS
            },
        }
    return {
        "roads": roads,
        "junctions": [
            ET.tostring(junction, encoding="unicode")
            for junction in root.findall("junction")
        ],
    }


def _semantic_stage6_diff(before_path: str, after_path: str) -> Dict[str, Any]:
    before = _protected_stage6_signature(before_path)
    after = _protected_stage6_signature(after_path)
    changed: List[Dict[str, Any]] = []
    before_roads = before["roads"]
    after_roads = after["roads"]
    for rid in sorted(set(before_roads) | set(after_roads)):
        if before_roads.get(rid) != after_roads.get(rid):
            changed.append({"domain": "road", "road_id": rid})
    if before["junctions"] != after["junctions"]:
        changed.append({"domain": "junctions"})
    return {
        "ok": not changed,
        "changed": changed,
        "protected_domains": [
            "planView",
            "road.length",
            "elevationProfile",
            "lateralProfile",
            "lanes",
            "junctions",
            "LaneLinks",
            "signals",
            "objects",
        ],
    }


def _copy_artifact(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)


def _write_stage6_containment_report(self, report: Dict[str, Any]) -> None:
    path = os.path.join(self.out_dir, "stage6_containment_runtime.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=True, sort_keys=True)


def _run_stage6_read_only_diagnostic(
    self,
    elev_out: str,
    geo_out: str,
    cont_out: str,
    root: ET.Element,
    *,
    min_len: float,
    max_len: float,
    max_curv: float,
) -> str:
    print("[STEP 6] READ_ONLY_DIAGNOSTIC containment active; Stage 6 will not mutate XODR.")
    observe_only = [
        _observe_planview_operation(
            root,
            operation="PlanViewSmoother.smooth_heading_jumps",
            reason="heading-only smoothing changes hdg without rebuilding dependent geometry",
            mutator=lambda r: PlanViewSmoother.smooth_heading_jumps(r, threshold_deg=12.0),
        ),
        _observe_planview_operation(
            root,
            operation="PlanViewSmoother.merge_small_geometries",
            reason="small geometry merge changes planView segmentation and road length",
            mutator=lambda r: PlanViewSmoother.merge_small_geometries(
                r, min_length=min_len, max_merged_length=max_len
            ),
        ),
        _observe_planview_operation(
            root,
            operation="PlanViewSmoother.merge_short_segments",
            reason="type-agnostic short segment merge can collapse Line/Arc boundaries",
            mutator=lambda r: PlanViewSmoother.merge_short_segments(r, min_len=min_len * 0.25),
        ),
        _observe_planview_operation(
            root,
            operation="PlanViewSmoother.clamp_curvature",
            reason="curvature-only clamp changes arc geometry without dependent record migration",
            mutator=lambda r: PlanViewSmoother.clamp_curvature(r, max_curv),
        ),
        _observe_planview_operation(
            root,
            operation="PlanViewSmoother.recompute_geometry_starts",
            reason="start recomputation rewrites x/y/hdg after dependent records may exist",
            mutator=lambda r: PlanViewSmoother.recompute_geometry_starts(r),
        ),
    ]

    _copy_artifact(elev_out, geo_out)
    MapPlotter.save_preview(geo_out, self.out_dir, stage="05_planview_merge")

    continuity_scan: Dict[str, Any] = {}
    try:
        r = MeshContinuityRepairer(geo_out)
        continuity_scan = r.scan_roads()
    except Exception as exc:
        continuity_scan = {"error": str(exc)}
    _copy_artifact(geo_out, cont_out)

    continuity_report = self._stage_gate(
        "06_continuity",
        "geometric_continuity",
        lambda: self.qgate.gate_geometric_continuity(cont_out),
    )

    semantic_diff = _semantic_stage6_diff(elev_out, cont_out)
    containment_report: Dict[str, Any] = {
        "schema": "stage6_containment_runtime_v1",
        "mode": "READ_ONLY_DIAGNOSTIC",
        "input_xodr": elev_out,
        "planview_output": geo_out,
        "continuity_output": cont_out,
        "operations_disabled": [
            "merge_short_segments",
            "merge_small_geometries",
            "smooth_heading_jumps",
            "clamp_curvature",
            "recompute_geometry_starts",
            "mesh continuity repair",
            "plan-view seam auto-repair",
        ],
        "observe_only_operations": observe_only,
        "mesh_continuity_scan": continuity_scan,
        "continuity_gate": continuity_report,
        "xodr_semantic_changes": semantic_diff,
    }
    _write_stage6_containment_report(self, containment_report)
    if not semantic_diff.get("ok", False):
        raise RuntimeError(
            "BLOCKED_STAGE_ORDER_VIOLATION: Stage 6 containment detected protected "
            f"XODR semantic changes: {semantic_diff.get('changed')}"
        )

    debug_path = os.path.join(self.out_dir, "continuity_debug.json")
    try:
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(continuity_scan, f, indent=2, default=str, ensure_ascii=True, sort_keys=True)
        print(f"✅ continuity_debug.json written → {debug_path}")
    except Exception as e:
        print(f"⚠️ Could not create continuity debug file: {e}")

    tree, protected_root = load_xodr(cont_out)
    MeshChecker.quick_check(protected_root)
    self.qgate.gate_physics_feasibility(protected_root)
    self.qgate.gate_randomness_entropy(protected_root)

    MapPlotter.save_preview(cont_out, self.out_dir, stage="05_continuity")
    heatmap_png = os.path.join(self.out_dir, "continuity_heatmap.png")
    HeatmapGenerator.run(cont_out, heatmap_png, debug_json=debug_path)
    MapPlotter.save_preview(cont_out, self.out_dir, stage="06_post_continuity_planview")

    print("[DEBUG] Lanes after STEP 6:", _count_lanes(cont_out))
    self.semantic_state["has_planview"] = True
    return cont_out

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


def _unsafe_planview_mutations_enabled(settings_obj) -> bool:
    from ultimate_pipeline.contracts.release_profile import unsafe_planview_mutations_enabled
    return unsafe_planview_mutations_enabled(settings_obj)


def _unsafe_short_segment_merge_enabled(settings_obj) -> bool:
    from ultimate_pipeline.contracts.release_profile import unsafe_short_segment_merge_enabled
    return unsafe_short_segment_merge_enabled(settings_obj)


def _unsafe_heading_only_smoothing_enabled(settings_obj) -> bool:
    from ultimate_pipeline.contracts.release_profile import unsafe_heading_only_smoothing_enabled
    return unsafe_heading_only_smoothing_enabled(settings_obj)


def _unsafe_small_geometry_merge_enabled(settings_obj) -> bool:
    from ultimate_pipeline.contracts.release_profile import unsafe_small_geometry_merge_enabled
    return unsafe_small_geometry_merge_enabled(settings_obj)


def _unsafe_curvature_only_clamp_enabled(settings_obj) -> bool:
    from ultimate_pipeline.contracts.release_profile import unsafe_curvature_only_clamp_enabled
    return unsafe_curvature_only_clamp_enabled(settings_obj)


def _unsafe_geometry_start_recompute_enabled(settings_obj) -> bool:
    from ultimate_pipeline.contracts.release_profile import unsafe_geometry_start_recompute_enabled
    return unsafe_geometry_start_recompute_enabled(settings_obj)


def _step6_planview_continuity(
    self,
    elev_out: str,
    geo_out: str,
    cont_out: str,
) -> str:
    _inject_main_pipeline_globals()
    s = self.settings
    unsafe = _unsafe_planview_mutations_enabled(s)
    print("\n============== 📐 STEP 6: PlanView & Continuity ==============")

    tree, root = load_xodr(elev_out)

    MIN_LEN = getattr(s, "MIN_GEOM_MERGE_LENGTH", 0.10)
    MAX_LEN = getattr(s, "MAX_GEOM_MERGE_LENGTH", 300.0)
    MAX_CURV = getattr(s, "CURVATURE_MAX_ALLOWED", 1.0)

    if _stage6_governed_containment(s):
        return _run_stage6_read_only_diagnostic(
            self,
            elev_out,
            geo_out,
            cont_out,
            root,
            min_len=MIN_LEN,
            max_len=MAX_LEN,
            max_curv=MAX_CURV,
        )

    heading_smoothing = _unsafe_heading_only_smoothing_enabled(s) if unsafe else False
    short_segment_merge = _unsafe_short_segment_merge_enabled(s) if unsafe else False
    small_geometry_merge = _unsafe_small_geometry_merge_enabled(s) if unsafe else False
    curvature_clamp = _unsafe_curvature_only_clamp_enabled(s) if unsafe else False
    geometry_start_recompute = _unsafe_geometry_start_recompute_enabled(s) if unsafe else False

    if heading_smoothing:
        try:
            print("🔥 Pre-smoothing geometry (heading jumps)…")
            num_smoothed = PlanViewSmoother.smooth_heading_jumps(
                root, threshold_deg=12.0
            )
            print(f"   → Smoothed {num_smoothed} heading discontinuities.")
        except Exception as e:
            print(f"⚠️ Heading smoothing skipped/failed: {e}")
    else:
        print("⏭️ Heading-only smoothing disabled (ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING=0).")

    if small_geometry_merge:
        merged = PlanViewSmoother.merge_small_geometries(
            root,
            min_length=MIN_LEN,
            max_merged_length=MAX_LEN,
        )
        print(f"   → Merged {merged} tiny segments (< {MIN_LEN} m).")
    else:
        print("⏭️ Small geometry merge disabled (ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE=0).")

    if short_segment_merge:
        removed = PlanViewSmoother.merge_short_segments(root, min_len=MIN_LEN * 0.25)
        print(f"   → Removed {removed} micro-fragments (< {MIN_LEN * 0.25:.2f} m).")
    else:
        print("⏭️ Short segment merge disabled (ENABLE_UNSAFE_SHORT_SEGMENT_MERGE=0).")

    if curvature_clamp:
        clamped = PlanViewSmoother.clamp_curvature(root, MAX_CURV)
        print(f"   → Curvature clamped: {clamped}")
    else:
        print("⏭️ Curvature-only clamp disabled (ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP=0).")

    # Recomputing s is allowed only in non-governed mode; governed mode returns above.
    PlanViewSmoother.recompute_s_values(root)
    if geometry_start_recompute:
        fixed = PlanViewSmoother.recompute_geometry_starts(root)
        print(f"   → Geometry start points fixed: {fixed}")
    else:
        print("⏭️ Geometry start recompute disabled (safe default).")

    save_xodr(tree, geo_out)
    print(f"✅ PlanView smoothed → {geo_out}")
    MapPlotter.save_preview(geo_out, self.out_dir, stage="05_planview_merge")

    # 6) continuity repair
    MeshContinuityRepairer.run(geo_out, cont_out)

    # Geometric continuity check (XY/heading at road joins)
    continuity_report = self._stage_gate(
        "06_continuity",
        "geometric_continuity",
        lambda: self.qgate.gate_geometric_continuity(cont_out),
    )

    if isinstance(continuity_report, dict) and not continuity_report.get(
        "ok", True
    ):
        enable_quarantine = os.getenv(
            "UP_ENABLE_ROAD_QUARANTINE", ""
        ).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if enable_quarantine:
            try:
                from ultimate_pipeline.geometry.quarantine_bad_roads import (
                    DEFAULT_THRESHOLDS,
                    quarantine_bad_roads,
                    write_quarantine_report,
                )

                def _env_float(name: str, default: float) -> float:
                    try:
                        return float(os.getenv(name, default))
                    except Exception:
                        return default

                thresholds = {
                    "continuity_dxy_max_m": _env_float(
                        "UP_QUARANTINE_CONTINUITY_DXY",
                        DEFAULT_THRESHOLDS["continuity_dxy_max_m"],
                    ),
                    "continuity_dhdg_max_deg": _env_float(
                        "UP_QUARANTINE_CONTINUITY_DHDG",
                        DEFAULT_THRESHOLDS["continuity_dhdg_max_deg"],
                    ),
                    "heading_jump_max_deg": _env_float(
                        "UP_QUARANTINE_HEADING_JUMP_DEG",
                        DEFAULT_THRESHOLDS["heading_jump_max_deg"],
                    ),
                    "curvature_abs_max": _env_float(
                        "UP_QUARANTINE_CURVATURE_ABS",
                        DEFAULT_THRESHOLDS["curvature_abs_max"],
                    ),
                    "curvature_jump_max": _env_float(
                        "UP_QUARANTINE_CURVATURE_JUMP",
                        DEFAULT_THRESHOLDS["curvature_jump_max"],
                    ),
                }
                max_fraction = _env_float("UP_QUARANTINE_MAX_FRACTION", 0.008)

                quarantine_report = quarantine_bad_roads(
                    cont_out,
                    cont_out,
                    continuity_report=continuity_report,
                    max_fraction=max_fraction,
                    thresholds=thresholds,
                )
                quarantine_report["continuity_issues"] = continuity_report.get(
                    "num_issues"
                )
                quarantine_report["max_fraction"] = max_fraction
                quarantine_path = os.path.join(
                    self.out_dir, "roads_quarantined.json"
                )
                write_quarantine_report(quarantine_path, quarantine_report)
                print(f"[STEP 6] Wrote roads_quarantined.json -> {quarantine_path}")

                self._stage_gate(
                    "06_continuity",
                    "road_quarantine",
                    lambda: quarantine_report,
                )
                self._stage_gate(
                    "06_continuity_quarantine",
                    "geometric_continuity",
                    lambda: self.qgate.gate_geometric_continuity(cont_out),
                )
            except Exception as e:
                print(f"[STEP 6] Quarantine failed (continuing): {e}")

    # continuity_debug.json
    debug_path = os.path.join(self.out_dir, "continuity_debug.json")
    try:
        r = MeshContinuityRepairer(cont_out)
        scan = r.scan_roads()
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(scan, f, indent=2)
        print(f"✅ continuity_debug.json written → {debug_path}")
    except Exception as e:
        print(f"⚠️ Could not create continuity debug file: {e}")

    # 7) micro-prune after continuity
    if unsafe and (small_geometry_merge or short_segment_merge or geometry_start_recompute):
        print("⚙️ Running Micro-Pruning on continuity output…")
        tree_mp, root_mp = load_xodr(cont_out)
        if small_geometry_merge:
            PlanViewSmoother.merge_small_geometries(
                root_mp, min_length=0.05, max_merged_length=s.MAX_SEGMENT_LENGTH_FIX
            )
        else:
            print("⏭️ Micro-prune small-geometry merge skipped (ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE=0).")
        if short_segment_merge:
            PlanViewSmoother.merge_short_segments(root_mp, min_len=0.25)
        else:
            print("⏭️ Micro-fragment removal skipped (ENABLE_UNSAFE_SHORT_SEGMENT_MERGE=0).")
        # Merge/prune can leave stale x/y/hdg starts; only recompute in explicit unsafe mode.
        if geometry_start_recompute:
            micro_prune_start_fixes = int(PlanViewSmoother.recompute_geometry_starts(root_mp))
        else:
            micro_prune_start_fixes = 0
            print("⏭️ Micro-prune geometry-start recompute skipped (ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE=0).")
        PlanViewSmoother.recompute_s_values(root_mp)
        save_xodr(tree_mp, cont_out)
        print(
            "✅ Micro-Pruning after continuity complete. "
            f"(geometry starts recomputed: {micro_prune_start_fixes})"
        )
    else:
        print("⏭️ Micro-Pruning disabled (no unsafe mutations).")
        micro_prune_start_fixes = 0

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
        try:
            large_seam_threshold_m = float(
                os.getenv("UP_PLANVIEW_LARGE_SEAM_THRESHOLD_M", "1.0")
            )
        except Exception:
            large_seam_threshold_m = 1.0

        precheck_report = check_planview_internal_seams(cont_out, eps_xy=seam_eps)
        precheck_max_seam_m = float(precheck_report.get("max_seam_m", 0.0) or 0.0)
        root_cause_recompute: Dict[str, Any] = {
            "applied": False,
            "trigger_max_seam_m": float(precheck_max_seam_m),
            "threshold_m": float(large_seam_threshold_m),
            "updated_geometry_starts": 0,
            "micro_prune_geometry_starts_recomputed": int(micro_prune_start_fixes),
        }
        if precheck_max_seam_m > large_seam_threshold_m and geometry_start_recompute:
            try:
                tree_fix, root_fix = load_xodr(cont_out)
                updated_starts = int(
                    PlanViewSmoother.recompute_geometry_starts(root_fix)
                )
                if updated_starts > 0:
                    PlanViewSmoother.recompute_s_values(root_fix)
                    save_xodr(tree_fix, cont_out)
                    root_cause_recompute["applied"] = True
                    root_cause_recompute["updated_geometry_starts"] = updated_starts
                print(
                    "[STEP 6] Large planView seams detected before gate "
                    f"(max={precheck_max_seam_m:.3f}m > {large_seam_threshold_m:.3f}m); "
                    f"recomputed geometry starts: {updated_starts}"
                )
            except Exception as e:
                print(
                    f"[STEP 6] Large-seam root-cause recompute failed (continuing): {e}"
                )

        seam_report = self._stage_gate(
            "06_continuity",
            "planview_internal_seams",
            lambda: check_planview_internal_seams(cont_out, eps_xy=seam_eps),
        )
        if isinstance(seam_report, dict):
            seam_report["root_cause_recompute"] = root_cause_recompute
            seam_report["precheck_max_seam_m"] = float(precheck_max_seam_m)
            seam_report["precheck_ok"] = bool(precheck_report.get("ok", False))
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
            and isinstance(seam_report, dict)
            and not seam_report.get("ok", True)
        ):
            repair_report = auto_repair_tiny_planview_seams_in_file(
                cont_out,
                eps_xy=seam_eps,
                max_repair_seam_m=auto_repair_max,
            )
            seam_report["auto_repair"] = repair_report
            if repair_report.get("fixed", False):
                seam_report = repair_report.get("after", seam_report)
            try:
                repair_path = os.path.join(
                    self.out_dir, "planview_internal_seams_step6_autorepair.json"
                )
                with open(repair_path, "w", encoding="utf-8") as f:
                    json.dump(
                        repair_report,
                        f,
                        indent=2,
                        default=str,
                        ensure_ascii=True,
                        sort_keys=True,
                    )
            except Exception as e:
                print(
                    f"[STEP 6] planView seam auto-repair report write skipped: {e}"
                )
        try:
            seam_report_path = os.path.join(
                self.out_dir, "planview_internal_seams_step6.json"
            )
            with open(seam_report_path, "w", encoding="utf-8") as f:
                json.dump(
                    seam_report,
                    f,
                    indent=2,
                    default=str,
                    ensure_ascii=True,
                    sort_keys=True,
                )
        except Exception as e:
            print(f"[STEP 6] planView seam report write skipped: {e}")

    # 8) quality checks
    tree, root = load_xodr(cont_out)
    MeshChecker.quick_check(root)
    self.qgate.gate_physics_feasibility(root)
    self.qgate.gate_randomness_entropy(root)

    MapPlotter.save_preview(cont_out, self.out_dir, stage="05_continuity")

    heatmap_png = os.path.join(self.out_dir, "continuity_heatmap.png")
    continuity_debug_json = debug_path
    HeatmapGenerator.run(
        cont_out,
        heatmap_png,
        debug_json=continuity_debug_json,
    )

    print("🖼️ Generating post-continuity previews…")
    MapPlotter.save_preview(
        cont_out, self.out_dir, stage="06_post_continuity_planview"
    )

    before = os.path.join(self.out_dir, "map_preview_05_planview_merge.png")
    after = os.path.join(self.out_dir, "map_preview_05_continuity.png")
    gif_out = os.path.join(self.out_dir, "planview_continuity_diff.gif")

    if os.path.exists(before) and os.path.exists(after):
        AnimatedDiff.run(before, after, gif_out)
    else:
        print(
            f"⚠️ AnimatedDiff skipped (missing previews): "
            f"before={os.path.exists(before)} ({before}), "
            f"after={os.path.exists(after)} ({after})"
        )

    print("[DEBUG] Lanes after STEP 6:", _count_lanes(cont_out))
    self.semantic_state["has_planview"] = True

    return cont_out

# ---------------- 7) 🛣️ LANES + SIDEWALKS ----------------
