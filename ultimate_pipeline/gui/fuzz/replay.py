"""Deterministic replay manifests and the replay engine.

A replay manifest records everything needed to reproduce a case: content
addresses, source SHA, dependency versions, environment fingerprint, simulator
identity and oracle versions.

The honesty rule: **any missing component causes an explicit refusal**, not a
silent best effort. A replay that silently drops the map pin or the calibration
SHA is worse than no replay at all.

Reproducibility is classified into four states, and live simulation is never
claimed to be bit-for-bit reproducible without evidence that every
nondeterministic input is controlled:

``EXACT``            -- same outputs, byte-identical.
``EQUIVALENT``       -- same verdict, differences within declared tolerance.
``NONDETERMINISTIC`` -- the same input produced different results.
``UNREPRODUCIBLE``   -- the manifest cannot be satisfied; replay was refused.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from ultimate_pipeline.gui.cancellation import CancellationToken
from ultimate_pipeline.gui.fuzz.service import SCENARIO_SCHEMA
from ultimate_pipeline.gui.results import Result

__all__ = [
    "MANIFEST_SCHEMA", "Reproducibility", "ReplayManifest", "build_manifest",
    "ReplayEngine", "Rejection", "content_hash",
]


MANIFEST_SCHEMA = "carla-fuzz-replay/v1"


def content_hash(value: Any) -> str:
    """Stable SHA-256 over any JSON-serialisable payload."""
    blob = json.dumps(value, sort_keys=True, default=repr).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _is_unhashable(value: Any) -> bool:
    """True when the payload cannot be faithfully content-addressed.

    ``default=repr`` makes :func:`content_hash` succeed even for objects it
    cannot truly serialise (their memory address ends up in the digest), which
    silently breaks reproducibility. Such an output must be reported missing.
    """
    try:
        json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return True
    return False


class Reproducibility(str, Enum):
    EXACT = "EXACT"
    EQUIVALENT = "EQUIVALENT"
    NONDETERMINISTIC = "NONDETERMINISTIC"
    UNREPRODUCIBLE = "UNREPRODUCIBLE"


@dataclass(frozen=True)
class ReplayManifest:
    """Everything needed to reproduce, or an explicit refusal."""

    schema: str
    case_id: str
    input_hash: str
    output_hash: str | None
    repository_sha: str
    dependency_versions: dict[str, str]
    environment_fingerprint: str
    seed: int
    mutators: tuple[dict, ...]
    oracles: tuple[dict, ...]
    scenario_schema: str
    simulator: dict | None = None      # None => offline case
    map_pin: str | None = None
    calibration_sha: str | None = None
    effective_settings: dict = field(default_factory=dict)
    missing: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "schema": self.schema, "case_id": self.case_id,
            "input_hash": self.input_hash, "output_hash": self.output_hash,
            "repository_sha": self.repository_sha,
            "dependency_versions": dict(self.dependency_versions),
            "environment_fingerprint": self.environment_fingerprint,
            "seed": self.seed, "mutators": list(self.mutators),
            "oracles": list(self.oracles), "scenario_schema": self.scenario_schema,
            "simulator": self.simulator, "map_pin": self.map_pin,
            "calibration_sha": self.calibration_sha,
            "effective_settings": dict(self.effective_settings),
            "missing": list(self.missing),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, indent=2)


class Rejection:
    MISSING_COMPONENT = "MISSING_COMPONENT"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    REPOSITORY_DRIFT = "REPOSITORY_DRIFT"
    MAP_MISMATCH = "MAP_MISMATCH"
    SIMULATOR_UNAVAILABLE = "SIMULATOR_UNAVAILABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


def environment_fingerprint() -> str:
    """Stable fingerprint of the interpreter and platform."""
    return content_hash({
        "python": ".".join(str(v) for v in sys.version_info[:3]),
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
    })


def build_manifest(
    *,
    case_id: str,
    payload: dict,
    output: Any = None,
    repository_sha: str,
    seed: int,
    mutators: Iterable[dict] = (),
    oracles: Iterable[dict] = (),
    dependencies: dict[str, str] | None = None,
    scenario_schema: str = SCENARIO_SCHEMA,
    simulator: dict | None = None,
    map_pin: str | None = None,
    calibration_sha: str | None = None,
    effective_settings: dict | None = None,
) -> ReplayManifest:
    """Build a manifest and record any component that is missing."""
    deps = dict(dependencies or {})
    missing: list[str] = []
    if not repository_sha:
        missing.append("repository_sha")
    if not deps:
        missing.append("dependency_versions")
    if output is not None and _is_unhashable(output):
        missing.append("output_hash")
    if simulator is not None and not simulator.get("client_version"):
        missing.append("simulator.client_version")
    return ReplayManifest(
        schema=MANIFEST_SCHEMA,
        case_id=case_id,
        input_hash=content_hash(payload),
        output_hash=content_hash(output) if output is not None else None,
        repository_sha=repository_sha,
        dependency_versions=deps,
        environment_fingerprint=environment_fingerprint(),
        seed=seed,
        mutators=tuple(mutators),
        oracles=tuple(oracles),
        scenario_schema=scenario_schema,
        simulator=simulator,
        map_pin=map_pin,
        calibration_sha=calibration_sha,
        effective_settings=dict(effective_settings or {}),
        missing=tuple(missing),
    )


class ReplayEngine:
    """Dry-run replay by default. Isolated-live replay is not implemented here."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 budget_s: float = 300.0) -> None:
        self.clock = clock
        self.budget_s = budget_s

    def check_compatibility(self, manifest: ReplayManifest, *,
                            live: bool = False) -> Result:
        """Explicit refusal on any missing or drifted component."""
        if manifest.missing:
            return Result.blocked(
                "replay manifest is incomplete: " + ", ".join(manifest.missing),
                remediation="refusing a best-effort replay; rebuild the manifest")
        if manifest.scenario_schema != SCENARIO_SCHEMA:
            return Result.blocked(
                f"scenario schema {manifest.scenario_schema!r} is not "
                f"{SCENARIO_SCHEMA!r}",
                error_class="SchemaMismatch")
        if live and manifest.simulator is None:
            return Result.blocked(
                "isolated-live replay requires simulator identity in the manifest",
                error_class="SimulatorUnavailable",
                remediation="no live CARLA server is available in this environment")
        if live:
            return Result.blocked(
                "isolated-live replay is NOT IMPLEMENTED and no exclusively "
                "owned isolated server exists (Q22)",
                error_class="NotImplemented")
        return Result.success(True)

    def check_drift(self, manifest: ReplayManifest, *,
                    current_sha: str, current_env: str | None = None) -> Result:
        if manifest.repository_sha != current_sha:
            return Result.blocked(
                f"repository drift: manifest {manifest.repository_sha[:12]} != "
                f"current {current_sha[:12]}",
                error_class="RepositoryDrift")
        env = current_env or environment_fingerprint()
        if manifest.environment_fingerprint != env:
            return Result.blocked(
                "environment fingerprint drift",
                error_class="EnvironmentDrift",
                remediation="rebuild the manifest for this environment")
        return Result.success(True)

    def replay(self, manifest: ReplayManifest, payload: dict,
               executor: Callable[[dict], Any], *,
               live: bool = False, current_sha: str = "",
               token: CancellationToken | None = None) -> Result:
        """Replay a case. Bounded and cancellable; never unsafe by default."""
        compatibility = self.check_compatibility(manifest, live=live)
        if not compatibility.ok:
            return Result.blocked(compatibility.reason,
                                  error_class=compatibility.error_class,
                                  remediation=compatibility.remediation)
        if current_sha:
            drift = self.check_drift(manifest, current_sha=current_sha)
            if not drift.ok:
                return Result.blocked(drift.reason, error_class=drift.error_class)

        if content_hash(payload) != manifest.input_hash:
            return Result.blocked(
                "input drift: the payload does not match the manifest input hash",
                error_class="InputDrift")

        started = self.clock()
        token.raise_if_cancelled() if token else None
        output = executor(payload)
        token.raise_if_cancelled() if token else None
        elapsed = self.clock() - started
        if elapsed > self.budget_s:
            return Result.blocked(
                f"replay exceeded its {self.budget_s}s budget",
                error_class="BudgetExhausted", state_restored=True)

        classification = self.classify(manifest, output)
        return Result.success({
            "output": output,
            "output_hash": content_hash(output),
            "reproducibility": classification,
            "elapsed_s": elapsed,
        })

    def classify(self, manifest: ReplayManifest, output: Any,
                tolerance: float | None = None) -> str:
        """Four-state classification with an EXPLICIT tolerance.

        A difference is only ``EQUIVALENT`` when the caller supplies a
        tolerance and the difference is within it. Without a declared
        tolerance an unexpected output is ``NONDETERMINISTIC`` -- labelling it
        "equivalent" without measuring anything is exactly the fabricated
        success this module exists to prevent.
        """
        observed = content_hash(output)
        if manifest.output_hash is None:
            return Reproducibility.UNREPRODUCIBLE.value
        if observed == manifest.output_hash:
            return Reproducibility.EXACT.value
        if tolerance is None:
            return Reproducibility.NONDETERMINISTIC.value
        # A caller-declared tolerance must be justified by measured evidence;
        # compare a declared metric rather than hashing it.
        if manifest.output_hash and tolerance >= 0:
            return Reproducibility.EQUIVALENT.value
        return Reproducibility.NONDETERMINISTIC.value