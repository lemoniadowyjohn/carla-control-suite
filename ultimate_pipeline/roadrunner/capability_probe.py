"""Capability probe for RoadRunner and MATLAB backends.

All detection is performed through filesystem probes and subprocess
invokes. Importing this module must never require RoadRunner or MATLAB
to be installed or on PATH.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .installation import InstallationReport, probe_installation

logger = logging.getLogger(__name__)

_REQUIRED_CAPABILITIES = (
    "roadrunner_executable",
    "matlab_executable",
    "roadrunner_api",
    "automated_driving_toolbox",
    "scene_builder",
    "roadrunner_scenario",
    "grpc_proto_files",
    "cmd_roadrunner_api",
)


@dataclass(frozen=True)
class CapabilityResult:
    """Outcome of a single capability check."""

    name: str
    available: bool
    detail: str
    severity: str  # "none" | "warning" | "error"


@dataclass(frozen=True)
class CapabilityReport:
    """Aggregated capability probe results."""

    results: tuple[CapabilityResult, ...]
    overall_status: str  # "available" | "degraded" | "blocked"
    installation: InstallationReport

    def missing(self) -> tuple[CapabilityResult, ...]:
        """Return only the unavailable capability results."""
        return tuple(r for r in self.results if not r.available)

    def errors(self) -> tuple[CapabilityResult, ...]:
        """Return only severity=error results."""
        return tuple(r for r in self.results if r.severity == "error")


def _check_roadrunner_executable(report: InstallationReport) -> CapabilityResult:
    if report.roadrunner_executable is not None:
        return CapabilityResult(
            name="roadrunner_executable",
            available=True,
            detail=f"Found at {report.roadrunner_executable}",
            severity="none",
        )
    return CapabilityResult(
        name="roadrunner_executable",
        available=False,
        detail="RoadRunner executable not found on PATH or in known install locations.",
        severity="error",
    )


def _check_roadrunner_release(report: InstallationReport) -> CapabilityResult:
    if report.roadrunner_release is not None:
        return CapabilityResult(
            name="roadrunner_release",
            available=True,
            detail=f"Detected release: {report.roadrunner_release}",
            severity="none",
        )
    return CapabilityResult(
        name="roadrunner_release",
        available=False,
        detail="RoadRunner release could not be determined.",
        severity="warning",
    )


def _check_matlab_executable(report: InstallationReport) -> CapabilityResult:
    if report.matlab_executable is not None:
        return CapabilityResult(
            name="matlab_executable",
            available=True,
            detail=f"Found at {report.matlab_executable}",
            severity="none",
        )
    return CapabilityResult(
        name="matlab_executable",
        available=False,
        detail="MATLAB executable not found on PATH.",
        severity="error",
    )


def _check_matlab_release(report: InstallationReport) -> CapabilityResult:
    if report.matlab_release is not None:
        return CapabilityResult(
            name="matlab_release",
            available=True,
            detail=f"Detected release: {report.matlab_release}",
            severity="none",
        )
    return CapabilityResult(
        name="matlab_release",
        available=False,
        detail="MATLAB release could not be determined.",
        severity="warning",
    )


def _check_roadrunner_api(report: InstallationReport) -> CapabilityResult:
    if report.roadrunner_api_available:
        return CapabilityResult(
            name="roadrunner_api",
            available=True,
            detail="roadrunnerAPI detected in installation metadata.",
            severity="none",
        )
    return CapabilityResult(
        name="roadrunner_api",
        available=False,
        detail="roadrunnerAPI not indicated by installation probes.",
        severity="error",
    )


def _check_automated_driving_toolbox(report: InstallationReport) -> CapabilityResult:
    if report.automated_driving_toolbox:
        return CapabilityResult(
            name="automated_driving_toolbox",
            available=True,
            detail="Automated Driving Toolbox indicated by installation metadata.",
            severity="none",
        )
    if report.roadrunner_executable is not None:
        return CapabilityResult(
            name="automated_driving_toolbox",
            available=False,
            detail="RoadRunner found but Automated Driving Toolbox not indicated.",
            severity="warning",
        )
    return CapabilityResult(
        name="automated_driving_toolbox",
        available=False,
        detail="Automated Driving Toolbox not detected.",
        severity="error",
    )


def _check_scene_builder(report: InstallationReport) -> CapabilityResult:
    if report.scene_builder:
        return CapabilityResult(
            name="scene_builder",
            available=True,
            detail="Scene Builder detected in installation metadata.",
            severity="none",
        )
    return CapabilityResult(
        name="scene_builder",
        available=False,
        detail="Scene Builder not indicated by installation probes.",
        severity="warning",
    )


def _check_roadrunner_scenario(report: InstallationReport) -> CapabilityResult:
    if report.roadrunner_scenario:
        return CapabilityResult(
            name="roadrunner_scenario",
            available=True,
            detail="RoadRunner Scenario detected in installation metadata.",
            severity="none",
        )
    return CapabilityResult(
        name="roadrunner_scenario",
        available=False,
        detail="RoadRunner Scenario not indicated.",
        severity="warning",
    )


def _check_asset_library(report: InstallationReport) -> CapabilityResult:
    if report.asset_library_indication:
        return CapabilityResult(
            name="asset_library",
            available=True,
            detail="Asset Library indicated by installation metadata.",
            severity="none",
        )
    return CapabilityResult(
        name="asset_library",
        available=False,
        detail="Asset Library not indicated.",
        severity="warning",
    )


def _check_grpc_proto_files(report: InstallationReport) -> CapabilityResult:
    if report.grpc_proto_files:
        return CapabilityResult(
            name="grpc_proto_files",
            available=True,
            detail=f"Found {len(report.grpc_proto_files)} .proto file(s).",
            severity="none",
        )
    return CapabilityResult(
        name="grpc_proto_files",
        available=False,
        detail="No gRPC .proto files found.",
        severity="error",
    )


def _check_cmd_roadrunner_api(report: InstallationReport) -> CapabilityResult:
    if report.cmd_roadrunner_api:
        return CapabilityResult(
            name="cmd_roadrunner_api",
            available=True,
            detail="CmdRoadRunnerApi detected.",
            severity="none",
        )
    return CapabilityResult(
        name="cmd_roadrunner_api",
        available=False,
        detail="CmdRoadRunnerApi not detected.",
        severity="error",
    )


def _check_supported_imports(report: InstallationReport) -> CapabilityResult:
    return CapabilityResult(
        name="supported_imports",
        available=True,
        detail=f"Supported formats: {', '.join(report.supported_imports)}",
        severity="none",
    )


def _check_supported_exports(report: InstallationReport) -> CapabilityResult:
    return CapabilityResult(
        name="supported_exports",
        available=True,
        detail=f"Supported formats: {', '.join(report.supported_exports)}",
        severity="none",
    )


def _check_authoring_functions(report: InstallationReport) -> CapabilityResult:
    if report.authoring_functions:
        return CapabilityResult(
            name="authoring_functions",
            available=True,
            detail=f"Detected: {', '.join(report.authoring_functions)}",
            severity="none",
        )
    return CapabilityResult(
        name="authoring_functions",
        available=False,
        detail="No authoring functions detected in installation metadata.",
        severity="warning",
    )


_CHECKS = (
    (_check_roadrunner_executable, "required"),
    (_check_roadrunner_release, "optional"),
    (_check_matlab_executable, "required"),
    (_check_matlab_release, "optional"),
    (_check_roadrunner_api, "required"),
    (_check_automated_driving_toolbox, "required"),
    (_check_scene_builder, "required"),
    (_check_roadrunner_scenario, "required"),
    (_check_asset_library, "optional"),
    (_check_grpc_proto_files, "required"),
    (_check_cmd_roadrunner_api, "required"),
    (_check_supported_imports, "optional"),
    (_check_supported_exports, "optional"),
    (_check_authoring_functions, "optional"),
)


def run_capability_probe() -> CapabilityReport:
    """Run all capability probes and return a consolidated report."""

    installation = probe_installation()
    results: list[CapabilityResult] = []

    for check_fn, severity_label in _CHECKS:
        result = check_fn(installation)
        if severity_label == "required" and not result.available:
            logger.warning("Required capability missing: %s — %s", result.name, result.detail)
        results.append(result)

    errors = [r for r in results if r.severity == "error"]
    if errors:
        overall = "blocked"
    elif any(not r.available for r in results):
        overall = "degraded"
    else:
        overall = "available"

    return CapabilityReport(
        results=tuple(results),
        overall_status=overall,
        installation=installation,
    )