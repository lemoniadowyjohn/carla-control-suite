#!/usr/bin/env python3
"""CLI probe for RoadRunner and MATLAB installation capabilities."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ultimate_pipeline.roadrunner.capability_probe import (
    run_capability_probe,
)
from ultimate_pipeline.roadrunner.installation import probe_installation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe RoadRunner and MATLAB installation capabilities."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--report-file",
        type=str,
        default=None,
        help="Write JSON report to this file",
    )
    args = parser.parse_args(argv)

    installation = probe_installation()
    capability = run_capability_probe()

    if args.json:
        output = {
            "installation": {
                "roadrunner_executable": installation.roadrunner_executable,
                "roadrunner_release": installation.roadrunner_release,
                "matlab_executable": installation.matlab_executable,
                "matlab_release": installation.matlab_release,
                "roadrunner_api_available": installation.roadrunner_api_available,
                "automated_driving_toolbox": installation.automated_driving_toolbox,
                "scene_builder": installation.scene_builder,
                "roadrunner_scenario": installation.roadrunner_scenario,
                "asset_library_indication": installation.asset_library_indication,
                "grpc_proto_files": list(installation.grpc_proto_files),
                "cmd_roadrunner_api": installation.cmd_roadrunner_api,
                "supported_imports": list(installation.supported_imports),
                "supported_exports": list(installation.supported_exports),
                "authoring_functions": list(installation.authoring_functions),
            },
            "capability": {
                "overall_status": capability.overall_status,
                "results": [
                    {
                        "name": r.name,
                        "available": r.available,
                        "detail": r.detail,
                        "severity": r.severity,
                    }
                    for r in capability.results
                ],
            },
        }
        text = json.dumps(output, indent=2, sort_keys=True)
    else:
        lines: list[str] = []
        lines.append("=== RoadRunner Installation Probe ===")
        lines.append(f"RoadRunner executable : {installation.roadrunner_executable or 'NOT FOUND'}")
        lines.append(f"RoadRunner release    : {installation.roadrunner_release or 'unknown'}")
        lines.append(f"MATLAB executable     : {installation.matlab_executable or 'NOT FOUND'}")
        lines.append(f"MATLAB release        : {installation.matlab_release or 'unknown'}")
        lines.append(f"roadrunnerAPI         : {'yes' if installation.roadrunner_api_available else 'no'}")
        lines.append(f"Automated Driving     : {'yes' if installation.automated_driving_toolbox else 'no'}")
        lines.append(f"Scene Builder         : {'yes' if installation.scene_builder else 'no'}")
        lines.append(f"RoadRunner Scenario   : {'yes' if installation.roadrunner_scenario else 'no'}")
        lines.append(f"Asset Library         : {'yes' if installation.asset_library_indication else 'no'}")
        lines.append(f"gRPC .proto files     : {len(installation.grpc_proto_files)}")
        lines.append(f"CmdRoadRunnerApi      : {'yes' if installation.cmd_roadrunner_api else 'no'}")
        lines.append(f"Authoring functions   : {', '.join(installation.authoring_functions) or 'none'}")
        lines.append("")
        lines.append(f"Overall status: {capability.overall_status}")
        for r in capability.results:
            icon = "ok" if r.available else "MISSING"
            lines.append(f"  [{icon}] {r.name}: {r.detail}")
        text = "\n".join(lines)

    if args.report_file:
        Path(args.report_file).write_text(text, encoding="utf-8")
    else:
        print(text)

    if capability.overall_status == "blocked":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())