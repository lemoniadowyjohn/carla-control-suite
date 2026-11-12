"""Deterministic mocks for the remaining foundation protocols.

* ``MapRegistryBackend``  -- pins, verify (fail-closed), validate, resolve
* ``QualityGateBackend`` -- run, accept, topology, hash
* ``CalibrationBackend``  -- load, intrinsics, extrinsics, validate, export, lidar
* experiments / evidence / governance -- list (with discovery failures
  returned, never swallowed), run, resolve artifact

No ``carla`` import anywhere in this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ultimate_pipeline.gui.cancellation import CancellationToken
from ultimate_pipeline.gui.results import Result, Tri, TriState

__all__ = [
    "MockMapRegistryBackend", "MapPin", "MockQualityGateBackend",
    "MockCalibrationBackend", "MockExperimentBackend",
]


# --------------------------------------------------------------------------
# Map registry
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class MapPin:
    name: str
    path: str
    sha256: str
    bytes_: int = 0


class MockMapRegistryBackend:
    """Fail-closed map pin registry.

    ``verify`` reproduces the upstream failure modes exactly: unknown name,
    non-file, unreadable, LFS pointer, byte mismatch and sha256 drift all
    produce a refusal rather than a warning.
    """

    def __init__(self, pins: list[MapPin] | None = None) -> None:
        self._pins: dict[str, MapPin] = {}
        for pin in pins or [
            MapPin("Town01", "maps/Town01.xodr", "a" * 64),
            MapPin("Town07", "maps/Town07.xodr", "b" * 64),
        ]:
            self._pins[pin.name] = pin

    def list_pins(self) -> list[MapPin]:
        return list(self._pins.values())

    def verify(self, name: str) -> Result:
        pin = self._pins.get(name)
        if pin is None:
            return Result.failure(
                f"unknown map {name!r}", error_class="ValueError",
                error_source="ultimate_pipeline/carla_tools/map_registry.py",
                remediation="list_pins() to see registered maps",
            )
        path = Path(pin.path)
        if not path.is_file():
            return Result.failure(
                f"{pin.path} is not a file", error_class="FileNotFoundError",
                error_source="ultimate_pipeline/carla_tools/map_registry.py",
            )
        try:
            blob = path.read_bytes()
        except OSError as exc:
            return Result.failure(f"unreadable: {exc}", error_class="PermissionError")
        if blob.startswith(b"version https://git-lfs"):
            return Result.failure(
                f"{pin.path} is an unresolved LFS pointer", error_class="ValueError",
                remediation="run git lfs pull",
            )
        digest = hashlib.sha256(blob).hexdigest()
        if digest != pin.sha256:
            return Result.failure(
                f"sha256 drift: expected {pin.sha256}, got {digest}",
                error_class="IntegrityError",
            )
        return Result.success({"name": pin.name, "sha256": digest})

    def validate(self) -> Result:
        return Result.success({"pins": len(self._pins), "status": "VALID"})

    def resolve_load_target(self, name: str) -> list[str]:
        return [self._pins[name].path] if name in self._pins else []


# --------------------------------------------------------------------------
# Quality gates
# --------------------------------------------------------------------------
class MockQualityGateBackend:
    """Offline quality-gate stand-in. Deterministic: no map is ever accepted
    unless the gate reports every requested gate green."""

    def __init__(self, passing_gates: tuple[str, ...] = ("topology", "hash", "elevation")) -> None:
        self._passing = set(passing_gates)

    def run(self, xodr_path: Path, gates: list[str], inputs: dict) -> Result:
        results = {gate: (gate in self._passing) for gate in gates}
        return Result.success({"gates": results, "all_green": all(results.values())})

    def accept(self, reports: dict, paths: dict, run_id: str, flags: dict) -> Result:
        failed = [name for name, ok in (reports.get("gates") or {}).items() if not ok]
        if failed:
            return Result.failure(f"gates failed: {sorted(failed)}",
                                  error_class="MapAcceptanceError")
        return Result.success({"accepted": True, "run_id": run_id})

    def topology(self, literal_rep: Any, comp_rep: Any) -> Result:
        if literal_rep == comp_rep:
            return Result.success({"equivalent": True})
        return Result.failure("topology mismatch", error_class="TopologyMismatch")

    def hash(self, path: Path) -> Result:
        if not Path(path).is_file():
            return Result.failure(f"{path} does not exist", error_class="FileNotFoundError")
        return Result.success({"sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()})


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------
class MockCalibrationBackend:
    """Offline calibration profile loader."""

    def __init__(self) -> None:
        self._profiles: dict[str, dict] = {}

    def load(self, path: Path) -> Result:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Result.failure(f"{path} does not exist", error_class="FileNotFoundError")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return Result.failure(f"corrupt profile: {exc}", error_class="ValueError")
        if not isinstance(payload, dict) or "sensors" not in payload:
            return Result.failure("profile is missing a 'sensors' section",
                                  error_class="SchemaError")
        profile_id = str(payload.get("profile_id", path.stem))
        self._profiles[profile_id] = payload
        return Result.success(payload)

    def intrinsics(self, profile: dict, sensor_id: str) -> Result:
        sensor = (profile.get("sensors") or {}).get(sensor_id)
        if sensor is None:
            return Result.failure(f"unknown sensor {sensor_id!r}", error_class="KeyError")
        if "K_undistortion" not in sensor:
            return Result.failure(
                f"sensor {sensor_id!r} has no K_undistortion block",
                error_class="SchemaError",
                remediation="re-export the profile with an explicit K_undistortion matrix",
            )
        return Result.success(sensor["K_undistortion"])

    def extrinsics(self, profile: dict, sensor_id: str) -> Result:
        sensor = (profile.get("sensors") or {}).get(sensor_id)
        if sensor is None:
            return Result.failure(f"unknown sensor {sensor_id!r}", error_class="KeyError")
        transform = sensor.get("extrinsics")
        if transform is None:
            return Result.failure(f"sensor {sensor_id!r} has no extrinsics",
                                  error_class="SchemaError")
        return Result.success({"transform": transform,
                               "convention": sensor.get("convention", "UNSPECIFIED")})

    def validate(self, profile: dict, vectors: list[str]) -> Result:
        return Result.success({"profile_id": profile.get("profile_id", ""),
                               "checked": len(vectors), "verdict": "DESIGN_ONLY"})

    def export(self, profile: dict, path: Path) -> Result:
        target = Path(path)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(profile, sort_keys=True, indent=2), encoding="utf-8")
        tmp.replace(target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return Result.success({"path": str(target), "sha256": digest})

    def lidar_attrs(self, profile: dict, sensor_id: str) -> Result:
        sensor = (profile.get("sensors") or {}).get(sensor_id)
        if sensor is None:
            return Result.failure(f"unknown sensor {sensor_id!r}", error_class="KeyError")
        return Result.success({"attrs": sensor.get("lidar", {}),
                               "effective_source": "ultimate_pipeline.sensors.canonical_lidar_spec"})


# --------------------------------------------------------------------------
# Experiments / evidence / governance
# --------------------------------------------------------------------------
@dataclass
class ExperimentDef:
    experiment_id: str
    description: str = ""


class MockExperimentBackend:
    """Experiment/evidence/governance stand-in.

    ``list_experiments`` returns discovery failures **alongside** the
    successful discoveries -- the upstream registry swallows them at
    ``registry.discover_experiments:432-442`` and the GUI must not.
    """

    def __init__(self, *, broken: tuple[str, ...] = ("exp_broken",)) -> None:
        self.experiments = [
            ExperimentDef("exp_baseline", "one-run baseline"),
            ExperimentDef("exp_matrix", "five-run determinism matrix"),
        ]
        self.discovery_failures = [
            {"experiment_id": name, "error_class": "ImportError",
             "detail": "module failed to import during discovery"}
            for name in broken
        ]
        self._runs: list[str] = []

    def list_experiments(self) -> Result:
        return Result.success(
            {"experiments": self.experiments, "discovery_failures": self.discovery_failures}
        )

    def run(self, experiment_id: str, config: dict, token: CancellationToken | None = None) -> Result:
        if token is not None:
            token.raise_if_cancelled()
        known = {e.experiment_id for e in self.experiments}
        if experiment_id not in known:
            return Result.failure(f"unknown experiment {experiment_id!r}",
                                  error_class="KeyError")
        run_id = f"{experiment_id}-run-{len(self._runs) + 1:03d}"
        self._runs.append(run_id)
        return Result.success({"run_id": run_id, "experiment_id": experiment_id})

    def resolve_final_artifact(self, run_dir: Path) -> Result:
        candidate = Path(run_dir) / "final_run_verdict.json"
        if not candidate.is_file():
            return Result.blocked(
                f"{candidate} does not exist",
                remediation="run the experiment to completion first",
            )
        try:
            return Result.success(json.loads(candidate.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            return Result.failure(f"corrupt verdict: {exc}", error_class="ValueError")


def build_mock_registry() -> dict[str, Any]:
    """One place that assembles every mock for offline GUI startup."""
    from ultimate_pipeline.gui.adapters.mock_backend import MockCarlaBackend
    from ultimate_pipeline.gui.adapters.mock_services import (
        MockCalibrationBackend,
        MockExperimentBackend,
        MockMapRegistryBackend,
        MockQualityGateBackend,
    )
    from ultimate_pipeline.gui.adapters.mock_traffic import MockTrafficManagerBackend

    return {
        "carla": MockCarlaBackend(),
        "traffic_manager": MockTrafficManagerBackend(),
        "map_registry": MockMapRegistryBackend(),
        "quality": MockQualityGateBackend(),
        "calibration": MockCalibrationBackend(),
        "experiments": MockExperimentBackend(),
    }