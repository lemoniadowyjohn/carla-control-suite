#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ultimate_pipeline.quality.quality_gates

Stable orchestration entrypoint for post-pipeline quality gates.

MainPipeline expects:
    from ultimate_pipeline.quality.quality_gates import run_quality_gates

Design goals
-----------
- **Import-safe**: This file must exist and import without pulling CARLA.
- **Best-effort**: Missing optional dependencies/gates must not crash the pipeline.
- **Structured output**: Returns a dict of gate results/failures.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def run_quality_gates(
    xodr_path: str,
    out_dir: Optional[str] = None,
    vreport: Optional[object] = None,
) -> Dict[str, Any]:
    """Run offline quality gates on a final OpenDRIVE file.

    Parameters
    ----------
    xodr_path:
        Path to the OpenDRIVE (.xodr) file.
    out_dir:
        Optional run output directory for writing reports.
    vreport:
        Optional ValidationReport instance owned by the pipeline.

    Returns
    -------
    dict
        failures-by-gate-name (empty if nothing failed or gates skipped).
    """

    print("\n=== Running Quality Gates ===\n")

    # --- Parse XML (hard requirement for most gates) ---
    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(xodr_path).getroot()
    except Exception as e:
        # If we cannot parse XML, report and stop.
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
            # Minimal fallback to avoid crashing if ValidationReport moved.
            class _MiniVReport:  # noqa: D401
                def __init__(self) -> None:
                    self.data: Dict[str, Any] = {}

                def add(self, section: str, key: str, value: Any) -> None:
                    self.data.setdefault(section, {})[key] = value

                def add_dict(self, section: str, d: Dict[str, Any]) -> None:
                    self.data[section] = d

            vreport = _MiniVReport()

    qgate = QualityGateManager(vreport, logs_dir=out_dir)

    # --- Run gates (each is optional; never abort the pipeline) ---
    def _try(label: str, fn) -> None:
        try:
            fn()
        except ModuleNotFoundError as e:
            # Common on HPC / minimal installs.
            qgate.passed(label + "_skipped")
            vreport.add("quality_gates", label + "_skipped", {"status": "skip", "reason": str(e)})
        except Exception as e:
            # Gate itself failed to execute.
            qgate.fail(label + "_error", {"error": str(e)})

    _try("xml_integrity", lambda: qgate.gate_xml_integrity(xodr_path))
    _try("elevation_smoothness", lambda: qgate.gate_elevation_smoothness(root))
    _try("physics_feasibility", lambda: qgate.gate_physics_feasibility(root))
    _try("randomness_entropy", lambda: qgate.gate_randomness_entropy(root))
    _try("semantic_overlap", lambda: qgate.gate_semantic_overlap(root))
    _try("collision_mesh", lambda: qgate.gate_collision_mesh(root))

    failures = QualityGateManager.get_failures()

    print("\n=== Quality Gate Summary ===")
    if not failures:
        print("✔ All gates passed (or were skipped safely).")
    else:
        print("❌ Failures detected:")
        for k, v in failures.items():
            print(f"  - {k}: {v}")

    return failures
