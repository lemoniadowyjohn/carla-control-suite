"""Dependency-injected service container for the Phase 1 GUI.

The shell consumes the existing Task 02-12 services. It does **not** reimplement
settings, session ownership, Traffic Manager, calibration, reporting, status
classification, corpus management or fuzzer logic -- it wires them together.

Launching the GUI must not start CARLA, Unreal, a worker pool or a heavy ML
import. Everything is constructed lazily and offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

__all__ = [
    "AppMode", "ServiceRegistry", "Badges", "build_registry",
    "ServiceUnavailable", "resolve",
]


class AppMode(str, Enum):
    """The mode badge. ``MOCK`` is the default and needs no simulator."""

    MOCK = "MOCK"
    OFFLINE = "OFFLINE"
    LIVE = "LIVE"


class ServiceUnavailable(RuntimeError):
    """A service was requested but has no truthful implementation."""

    def __init__(self, service: str, reason: str, source: str = "") -> None:
        super().__init__(f"{service} unavailable: {reason}")
        self.service = service
        self.reason = reason
        self.source = source


@dataclass(frozen=True)
class Badges:
    """Every badge must represent real source data, never decoration."""

    mode: str = AppMode.MOCK.value
    session_authority: str = "SHARED_READONLY"
    tick_owner: str = "NONE"
    map_identity: str = "UNBOUND"
    evidence_as_of: str = ""
    evidence_state: str = "NOT_EVALUATED"
    traffic_manager: str = "WRITE_ONLY"
    backend: str = "mock"

    def as_dict(self) -> dict:
        return {
            "mode": self.mode, "session_authority": self.session_authority,
            "tick_owner": self.tick_owner, "map_identity": self.map_identity,
            "evidence_as_of": self.evidence_as_of, "evidence_state": self.evidence_state,
            "traffic_manager": self.traffic_manager, "backend": self.backend,
        }


@dataclass
class ServiceRegistry:
    """Lazy, injectable service locator.

    Services are supplied by the caller. Anything genuinely absent is reported
    as :class:`ServiceUnavailable` carrying the reason and its source, so a UI
    can disable the control with an explanation instead of showing an inert
    button.
    """

    _services: dict[str, Any] = field(default_factory=dict)
    _unavailable: dict[str, str] = field(default_factory=dict)
    _sources: dict[str, str] = field(default_factory=dict)
    badges: Badges = field(default_factory=Badges)

    def register(self, name: str, service: Any, source: str = "") -> None:
        self._services[name] = service
        self._sources[name] = source or name

    def register_unavailable(self, name: str, reason: str, source: str = "") -> None:
        self._unavailable[name] = reason
        self._sources[name] = source or name

    def available(self, name: str) -> bool:
        return name in self._services

    def reason_unavailable(self, name: str) -> str:
        return self._unavailable.get(name, "")

    def source_of(self, name: str) -> str:
        return self._sources.get(name, name)

    def resolve(self, name: str) -> Any:
        if name in self._services:
            return self._services[name]
        reason = self._unavailable.get(name)
        if reason:
            raise ServiceUnavailable(name, reason, self._sources.get(name, ""))
        raise ServiceUnavailable(name, "not registered", name)

    def names(self) -> list[str]:
        return sorted(self._services)

    def unavailable_names(self) -> list[str]:
        return sorted(self._unavailable)


def build_registry(*, mode: AppMode = AppMode.MOCK,
                   repository_sha: str = "") -> ServiceRegistry:
    """Assemble the real Task 02-12 services for offline/mock operation.

    Imports are local so that constructing the registry never pulls a heavy
    dependency into the process at import time.
    """
    from ultimate_pipeline.gui.adapters.mock_services import build_mock_registry
    from ultimate_pipeline.gui.audit import AuditJournal
    from ultimate_pipeline.gui.config.metadata import load_registry as load_settings
    from ultimate_pipeline.gui.config.controls import ConfiguratorModel
    from ultimate_pipeline.gui.fuzz.coverage import CoverageAnalyzer
    from ultimate_pipeline.gui.fuzz.corpus import CorpusStore
    from ultimate_pipeline.gui.fuzz.mutators import registry as mutator_registry
    from ultimate_pipeline.gui.freshness import EvidenceFreshnessService
    from ultimate_pipeline.gui.health import SessionAuthority
    from ultimate_pipeline.gui.jobs.governance import EvidenceBrowser
    from ultimate_pipeline.gui.run_status import SOURCE_VOCABULARIES
    from ultimate_pipeline.gui.session.runtime_session import RuntimeSession

    registry = ServiceRegistry()
    mocks = build_mock_registry()

    registry.register("runtime_session", RuntimeSession(),
                      "ultimate_pipeline/gui/session/runtime_session.py")
    registry.register("carla_backend", mocks["carla"],
                      "ultimate_pipeline/gui/adapters/mock_backend.py")
    registry.register("traffic_manager", mocks["traffic_manager"],
                      "ultimate_pipeline/gui/adapters/mock_traffic.py")
    registry.register("map_registry", mocks["map_registry"],
                      "ultimate_pipeline/gui/adapters/mock_services.py")
    registry.register("calibration", mocks["calibration"],
                      "ultimate_pipeline/gui/adapters/mock_services.py")
    registry.register("quality", mocks["quality"],
                      "ultimate_pipeline/gui/adapters/mock_services.py")
    registry.register("experiments", mocks["experiments"],
                      "ultimate_pipeline/gui/adapters/mock_services.py")

    registry.register("mutators", mutator_registry,
                      "ultimate_pipeline/gui/fuzz/mutators.py")
    registry.register("coverage", CoverageAnalyzer(),
                      "ultimate_pipeline/gui/fuzz/coverage.py")
    registry.register("status_sources", SOURCE_VOCABULARIES,
                      "ultimate_pipeline/gui/run_status.py")

    from pathlib import Path
    registry.register("settings_registry", load_settings(),
                      "ultimate_pipeline/gui/config/metadata.py")
    registry.register("configurator", ConfiguratorModel(),
                      "ultimate_pipeline/gui/config/controls.py")

    # Corpus needs a writable root; defer it so importing never creates dirs.
    registry.register_unavailable(
        "corpus", "corpus root is configured by the application, not at import",
        "ultimate_pipeline/gui/fuzz/corpus.py")
    registry.register_unavailable(
        "audit_journal", "audit journal root is configured by the application",
        "ultimate_pipeline/gui/audit.py")
    registry.register_unavailable(
        "live_fuzzer", "live fuzzing is disabled without an exclusively owned "
                       "isolated server lease (Q22)",
        "ultimate_pipeline/gui/fuzz/service.py")
    registry.register_unavailable(
        "map_cooking", "cooking is blocked: UE426_BLOCKED_OPERATOR_INSTALL",
        "ultimate_pipeline/gui/maps/cook.py")
    registry.register_unavailable(
        "model_inference", "no model weights exist in the repository",
        "ultimate_pipeline/gui/perception/service.py")

    registry.badges = Badges(
        mode=mode.value,
        session_authority=SessionAuthority.SHARED_READONLY.value,
        tick_owner="NONE",
        map_identity="UNBOUND",
        evidence_state="NOT_EVALUATED",
        traffic_manager="WRITE_ONLY",
        backend="mock",
    )
    return registry