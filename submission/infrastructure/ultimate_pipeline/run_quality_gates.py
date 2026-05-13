#!/usr/bin/env python3

from ultimate_pipeline.utils.console_encoding import ensure_utf8_console
ensure_utf8_console()

import sys
import subprocess
from pathlib import Path

# Ensure repo root is on sys.path so package imports work regardless of CWD.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import xml.etree.ElementTree as ET
from ultimate_pipeline.quality.quality_gate_manager import QualityGateManager
from ultimate_pipeline.core.validation_report import ValidationReport


from ultimate_pipeline.utils.timestamped_print import enable_timestamped_print
enable_timestamped_print()

def run_quality_gates(xodr_path: str):
    print("\n=== Running Quality Gates ===\n")

    gov = subprocess.run(
        [sys.executable, "-m", "ultimate_pipeline.tools.validate_governance", "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    if gov.returncode != 0:
        print("❌ Governance validation failed")
        if gov.stdout:
            print(gov.stdout)
        if gov.stderr:
            print(gov.stderr)
        return {"governance": "failed"}

    try:
        root = ET.parse(xodr_path).getroot()
    except FileNotFoundError:
        print(f"❌ XODR not found: {xodr_path}")
        return {"xodr_missing": str(xodr_path)}
    except ET.ParseError as e:
        print(f"❌ XODR parse error: {e}")
        return {"xodr_parse_error": str(e)}

    vreport = ValidationReport()
    qgate = QualityGateManager(vreport)

    qgate.gate_xml_integrity(xodr_path)
    qgate.gate_elevation_smoothness(root)
    qgate.gate_physics_feasibility(root)
    qgate.gate_randomness_entropy(root)
    qgate.gate_semantic_overlap(root)
    qgate.gate_collision_mesh(root)

    failures = qgate.get_failures()

    print("\n=== Summary ===")
    if not failures:
        print("✔ All gates passed!")
    else:
        print("❌ Failures detected:")
        for k, v in failures.items():
            print(f"  - {k}: {v}")

    return failures


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("xodr")
    args = ap.parse_args()

    failures = run_quality_gates(args.xodr)
    raise SystemExit(0 if not failures else 2)
