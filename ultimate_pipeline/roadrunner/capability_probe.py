"""Dependency-free RoadRunner capability probing."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .models import (
    ArtifactRole,
    InstallationCapability,
    PathKind,
    PathRef,
    RoadRunnerMode,
)


ROADRUNNER_ENV = "ROADRUNNER_EXECUTABLE"
MATLAB_ENV = "MATLAB_EXECUTABLE"


@dataclass(frozen=True)
class CapabilityProbeResult:
    name: str
    available: bool
    detail: str
    severity: str = "required"


@dataclass(frozen=True)
class CapabilityProbeReport:
    overall_status: str
    results: tuple[CapabilityProbeResult, ...]
    capabilities: tuple[InstallationCapability, ...] = ()

    def to_dict(self) -> dict:
        return {
            "capabilities": [capability.to_dict() for capability in self.capabilities],
            "overall_status": self.overall_status,
            "results": [
                {
                    "available": result.available,
                    "detail": result.detail,
                    "name": result.name,
                    "severity": result.severity,
                }
                for result in self.results
            ],
        }


def _candidate_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.exists() else None


def _find_executable(env_var: str, names: Sequence[str]) -> tuple[Path | None, str]:
    env_path = _candidate_path(os.getenv(env_var))
    if env_path is not None:
        return env_path, f"found via {env_var}"
    if os.getenv(env_var):
        return None, f"{env_var} is set but does not exist: {os.getenv(env_var)}"

    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found), f"found on PATH as {name}"
    return None, "not found on PATH or environment"


def _roadrunner_capability(executable: Path) -> InstallationCapability:
    return InstallationCapability(
        capability_id="rr-local-authoring",
        adapter_name="roadrunner-local",
        supported_modes=(
            RoadRunnerMode.REFERENCE_ONLY,
            RoadRunnerMode.ROUNDTRIP_CANDIDATE,
            RoadRunnerMode.AUTHORITATIVE_SCENE,
            RoadRunnerMode.VISUAL_BUILD_ONLY,
        ),
        supported_imports=("xodr", "rrscene"),
        supported_exports=(
            ArtifactRole.RRSCENE,
            ArtifactRole.STRUCTURAL_XODR,
            ArtifactRole.VISUAL_MESH,
            ArtifactRole.CARLA_PACKAGE,
        ),
        executable_path=PathRef(path=executable.as_posix(), kind=PathKind.FILE, must_exist=True),
    )


def run_capability_probe() -> CapabilityProbeReport:
    rr_path, rr_detail = _find_executable(
        ROADRUNNER_ENV,
        ("RoadRunner", "RoadRunner.exe", "roadrunner", "roadrunner.exe"),
    )
    matlab_path, matlab_detail = _find_executable(
        MATLAB_ENV,
        ("matlab", "matlab.exe"),
    )

    results = [
        CapabilityProbeResult(
            name="roadrunner_executable",
            available=rr_path is not None,
            detail=rr_detail if rr_path is None else f"{rr_detail}: {rr_path}",
            severity="required",
        ),
        CapabilityProbeResult(
            name="matlab_executable",
            available=matlab_path is not None,
            detail=matlab_detail if matlab_path is None else f"{matlab_detail}: {matlab_path}",
            severity="optional",
        ),
    ]

    capabilities: tuple[InstallationCapability, ...] = ()
    if rr_path is not None:
        capabilities = (_roadrunner_capability(rr_path),)

    required_missing = any(not result.available and result.severity == "required" for result in results)
    overall = "blocked" if required_missing else "pass"
    if overall == "pass" and any(not result.available for result in results):
        overall = "partial"

    return CapabilityProbeReport(
        overall_status=overall,
        results=tuple(results),
        capabilities=capabilities,
    )


__all__ = [
    "CapabilityProbeReport",
    "CapabilityProbeResult",
    "MATLAB_ENV",
    "ROADRUNNER_ENV",
    "run_capability_probe",
]
