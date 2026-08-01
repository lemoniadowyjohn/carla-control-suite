#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ultimate_pipeline.quality.quality_gates

Stable orchestration entrypoint for post-pipeline quality gates.

This patch adds an **optional external validation gate** using libOpenDRIVE:
- Controlled by SETTINGS.ENABLE_LIBOPENDRIVE_VALIDATION
- Strictness controlled by SETTINGS.LIBOPENDRIVE_VALIDATION_STRICT
- Safe fallback (skip) when binary not present

MainPipeline expects:
    from ultimate_pipeline.quality.quality_gates import run_quality_gates
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

MIN_XODR_SIZE_BYTES = 10_000  # Minimum bytes for a real road-network XODR; stubs are ~796 bytes


DRIVABILITY_GATES = {
    "xml_integrity",
    "junction_integrity",
    "lane_link_targets",
    "carla_opendrive_compat",
    "xodr_strict_carla",
    # external validator (optional)
    "external_libopendrive",
}


def run_quality_gates(
    xodr_path: str,
    out_dir: Optional[str] = None,
    vreport: Optional[object] = None,
) -> Dict[str, Any]:
    print("\n=== Running Quality Gates ===\n")

    # --- Hard-stop: reject stub XODR files ---
    try:
        xodr_size = os.path.getsize(xodr_path)
    except OSError as e:
        return {"xodr_minimum_size": {"ok": False, "error": f"Cannot stat XODR file: {e}", "path": xodr_path}}
    if xodr_size < MIN_XODR_SIZE_BYTES:
        return {"xodr_minimum_size": {
            "ok": False,
            "error": f"stub XODR rejected: {xodr_size} bytes < {MIN_XODR_SIZE_BYTES} minimum",
            "path": xodr_path,
            "size_bytes": xodr_size,
        }}

    # --- Parse XML (hard requirement for most gates) ---
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(xodr_path).getroot()
    except Exception as e:
        return {"xml_parse": {"error": str(e), "path": xodr_path}}

    # --- Obtain ValidationReport + Manager ---
    try:
        from ultimate_pipeline.quality.quality_gate_manager import QualityGateManager
    except Exception as e:
        return {"quality_gate_manager_import": {"error": str(e)}}

    if vreport is None:
        try:
            from ultimate_pipeline.core.validation_report import ValidationReport
            vreport = ValidationReport()
        except Exception:
            class _MiniVReport:
                def __init__(self) -> None:
                    self.data: Dict[str, Any] = {}
                def add(self, section: str, key: str, value: Any) -> None:
                    self.data.setdefault(section, {})[key] = value
                def add_dict(self, section: str, d: Dict[str, Any]) -> None:
                    self.data[section] = d
            vreport = _MiniVReport()

    qgate = QualityGateManager(vreport, logs_dir=out_dir)

    def _try(label: str, fn) -> None:
        try:
            fn()
        except ModuleNotFoundError as e:
            qgate.passed(label + "_skipped")
            vreport.add("quality_gates", label + "_skipped", {"status": "skip", "reason": str(e)})
        except Exception as e:
            qgate.fail(label + "_error", {"error": str(e)})

    _try("xml_integrity", lambda: qgate.gate_xml_integrity(xodr_path))
    _try("junction_integrity", lambda: qgate.gate_junction_integrity(root, stage="final"))
    _try("carla_opendrive_compat", lambda: qgate.gate_carla_opendrive_compat(root))
    _try("xodr_strict_carla", lambda: qgate.gate_xodr_strict_carla(xodr_path))
    _try("elevation_smoothness", lambda: qgate.gate_elevation_smoothness(root))
    _try("physics_feasibility", lambda: qgate.gate_physics_feasibility(root))
    _try("randomness_entropy", lambda: qgate.gate_randomness_entropy(root))
    _try("semantic_overlap", lambda: qgate.gate_semantic_overlap(root))
    _try("collision_mesh", lambda: qgate.gate_collision_mesh(root))

    # --- Lane link targets check ---
    lane_link_result: Dict[str, Any] = {"status": "skipped"}
    try:
        from ultimate_pipeline.quality.check_lane_link_targets_exist import check_lane_link_targets_exist
        lane_link_result = check_lane_link_targets_exist(xodr_path)
        if not lane_link_result.get("ok", True):
            qgate.fail("lane_link_targets", lane_link_result)
        else:
            qgate.passed("lane_link_targets")
    except Exception as e:
        lane_link_result = {"status": "error", "error": str(e)}

    # --- Optional external libOpenDRIVE validation ---
    external_rep: Dict[str, Any] = {"status": "skipped"}
    try:
        from ultimate_pipeline.config.settings import SETTINGS
        if getattr(SETTINGS, "ENABLE_LIBOPENDRIVE_VALIDATION", False):
            from ultimate_pipeline.quality.check_external_libopendrive import run_external_libopendrive_validation
            external_rep = run_external_libopendrive_validation(
                xodr_path,
                out_dir=out_dir,
                validator_exe=getattr(SETTINGS, "LIBOPENDRIVE_VALIDATOR_EXE", None),
                strict=bool(getattr(SETTINGS, "LIBOPENDRIVE_VALIDATION_STRICT", False)),
                timeout_s=float(getattr(SETTINGS, "LIBOPENDRIVE_VALIDATOR_TIMEOUT_S", 20.0)),
            )
            # Record in vreport
            try:
                vreport.add("quality_gates", "external_libopendrive", external_rep)
            except Exception:
                pass
            if not external_rep.get("ok", True) and bool(getattr(SETTINGS, "LIBOPENDRIVE_VALIDATION_STRICT", False)):
                qgate.fail("external_libopendrive", external_rep)
            else:
                qgate.passed("external_libopendrive")
        else:
            # explicitly skipped
            try:
                vreport.add("quality_gates", "external_libopendrive", {"status": "skipped", "reason": "disabled"})
            except Exception:
                pass
            qgate.passed("external_libopendrive_skipped")
    except Exception as e:
        external_rep = {"status": "error", "error": str(e)}
        qgate.fail("external_libopendrive_error", external_rep)

    failures = qgate.get_failures()

    # --- Write artifacts ---
    artifacts: Dict[str, Any] = {
        "carla_compat_report": {},
        "strict_xodr_validation": {},
        "lane_link_check": lane_link_result,
        "external_libopendrive": external_rep,
    }

    try:
        from ultimate_pipeline.quality.check_carla_opendrive_compat import StrictCarlaOpendriveGate
        artifacts["carla_compat_report"] = {"issues": StrictCarlaOpendriveGate.validate(root), "xodr_path": xodr_path}
    except Exception as e:
        artifacts["carla_compat_report"] = {"error": str(e)}

    try:
        from ultimate_pipeline.quality.xodr_strict_validator import StrictXodrValidator
        validator = StrictXodrValidator(allow_spiral=True)
        artifacts["strict_xodr_validation"] = validator.validate_path(xodr_path)
    except Exception as e:
        artifacts["strict_xodr_validation"] = {"error": str(e)}

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        def _dump(name: str, data: Any) -> None:
            try:
                with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str)
            except Exception:
                pass
        _dump("carla_compat_report.json", artifacts["carla_compat_report"])
        _dump("strict_xodr_validation.json", artifacts["strict_xodr_validation"])
        _dump("lane_link_check.json", artifacts["lane_link_check"])
        _dump("external_libopendrive_report.json", artifacts["external_libopendrive"])

    print("\n=== Quality Gate Summary ===")
    if not failures:
        print("All gates passed (or were skipped safely).")
    else:
        print("Failures detected:")
        for k, v in failures.items():
            print(f"  - {k}: {v}")

    return failures
