"""The 17-screen route registry and the control->backend binding matrix.

Navigation is data, not a hand-written ``if`` chain, so a route cannot drift
from its declared backend.

A control with no truthful backend is bound to ``available=False`` and carries
a ``file:line``-style source reason. It is rendered disabled with that reason --
never as an inert button, and never with fabricated live telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "ScreenRoute", "SCREEN_ROUTES", "SCREEN_COUNT", "route_for",
    "ControlBinding", "CONTROL_MATRIX_SOURCE", "bind_control",
    "Accessibility", "KEYBOARD_ORDER",
]


class ScreenRoute(str, Enum):
    """The 17 documented screens."""

    HOME = "01_home"
    PROFILES = "02_environment_profiles"
    CONNECTION = "03_connection_diagnostics"
    WORLD_TIME = "04_world_time"
    MAPS_GIS = "05_maps_gis_cooking"
    TRAFFIC_MANAGER = "06_traffic_manager"
    ACTORS_ROUTES = "07_actors_routes"
    SENSORS = "08_sensors_streams"
    CALIBRATION = "09_calibration_workbench"
    PERCEPTION = "10_perception_localization"
    SCENARIO_TEST = "11_scenario_test_studio"
    FUZZER = "12_operational_fuzzer"
    QA_GATES = "13_qa_gates"
    EXPERIMENTS = "14_experiments_runs"
    JOB_CONTROL = "15_job_control"
    DIAGNOSTICS = "16_diagnostics_logs"
    SETTINGS = "17_settings_safety_help"


#: The documented control catalogue the bindings must reconcile against.
CONTROL_MATRIX_SOURCE = "07_GUI_SPEC/CONTROL_CATALOG.csv"


@dataclass(frozen=True)
class ScreenRoute:
    """One navigation route. ``implemented`` distinguishes Task 13 screens."""

    route: str
    title: str
    backend_service: str
    implemented: bool = False
    read_only: bool = True
    order: int = 0

    def as_dict(self) -> dict:
        return {"route": self.route, "title": self.title,
                "backend_service": self.backend_service,
                "implemented": self.implemented, "read_only": self.read_only,
                "order": self.order}


_ROUTE_DATA: tuple[tuple[str, str, str, bool], ...] = (
    ("01_home", "Home", "status", True),
    ("02_environment_profiles", "Environment Profiles", "configurator", True),
    ("03_connection_diagnostics", "Connection and Diagnostics", "carla_backend", True),
    ("04_world_time", "World and Time", "carla_backend", True),
    ("05_maps_gis_cooking", "Maps, GIS and Cooking", "map_registry", True),
    ("06_traffic_manager", "Traffic Manager", "traffic_manager", True),
    ("07_actors_routes", "Actors and Routes", "carla_backend", True),
    ("08_sensors_streams", "Sensors and Streams", "calibration", True),
    ("09_calibration_workbench", "Calibration Workbench", "calibration", True),
    ("10_perception_localization", "Perception and Localization", "model_inference", False),
    ("11_scenario_test_studio", "Scenario Test Studio", "experiments", True),
    ("12_operational_fuzzer", "Operational Fuzzer", "mutators", True),
    ("13_qa_gates", "QA Gates", "quality", True),
    ("14_experiments_runs", "Experiments and Runs", "experiments", True),
    ("15_job_control", "Job Control", "experiments", True),
    ("16_diagnostics_logs", "Diagnostics and Logs", "audit_journal", True),
    ("17_settings_safety_help", "Settings, Safety and Help", "settings_registry", True),
)

SCREEN_ROUTES: dict[str, ScreenRoute] = {
    key: ScreenRoute(route=key, title=title, backend_service=service,
                    implemented=implemented, read_only=True, order=index + 1)
    for index, (key, title, service, implemented) in enumerate(_ROUTE_DATA)
}

SCREEN_COUNT = len(SCREEN_ROUTES)


def route_for(key: str) -> ScreenRoute:
    if key not in SCREEN_ROUTES:
        raise KeyError(f"no such screen route: {key!r}")
    return SCREEN_ROUTES[key]


# --------------------------------------------------------------- controls
@dataclass(frozen=True)
class ControlBinding:
    """One documented control bound to a backend action.

    ``available`` means the backend service exists. ``mutation_allowed`` means
    the session authority permits it *right now*. A mutating control that is
    available but not permitted is DISABLED, not silently live.
    """

    control_id: str
    label: str
    screen: str
    backend_service: str
    action: str
    test_id: str
    available: bool
    disabled_reason: str = ""
    source: str = ""
    mutating: bool = False
    mutation_allowed: bool = True
    authority_reason: str = ""

    @property
    def accessible_name(self) -> str:
        return f"{self.label} ({self.screen})"

    def as_dict(self) -> dict:
        return {"control_id": self.control_id, "label": self.label,
                "screen": self.screen, "backend_service": self.backend_service,
                "action": self.action, "test_id": self.test_id,
                "available": self.available, "disabled_reason": self.disabled_reason,
                "source": self.source, "mutating": self.mutating,
                "mutation_allowed": self.mutation_allowed,
                "authority_reason": self.authority_reason,
                "accessible_name": self.accessible_name}


def bind_control(control_id: str, label: str, screen: str, backend_service: str,
                 action: str, test_id: str, *, registry: Any = None,
                 mutating: bool = False, source: str = "") -> ControlBinding:
    """Bind a control to a real backend, or disable it with a stated reason.

    Mutating controls are additionally gated by the session authority via the
    Task 06 gate, so no mutating control is ever live under SHARED_READONLY.
    """
    if registry is None:
        available, reason = False, "no service registry supplied"
        resolved_source = source or "unbound: no registry"
    elif registry.available(backend_service):
        available, reason = True, ""
        resolved_source = source or registry.source_of(backend_service)
    else:
        available = False
        reason = registry.reason_unavailable(backend_service) or \
            f"{backend_service} is not registered"
        resolved_source = source or registry.source_of(backend_service)
        reason = f"{reason} [{resolved_source}]"

    mutation_allowed, authority_reason = True, ""
    if mutating and available:
        mutation_allowed, authority_reason = _authority_gate(registry)
    return ControlBinding(control_id, label, screen, backend_service, action,
                          test_id, available, reason, resolved_source, mutating,
                          mutation_allowed, authority_reason)


def _authority_gate(registry: Any) -> tuple[bool, str]:
    """Consult the Task 06 gate so SHARED_READONLY disables all mutation."""
    authority = getattr(getattr(registry, "badges", None),
                        "session_authority", "SHARED_READONLY")
    state = getattr(getattr(registry, "badges", None), "connection_state", None)
    try:
        from ultimate_pipeline.gui.health import (
            ConnectionState, mutating_controls_enabled)
        allowed = mutating_controls_enabled(
            state or ConnectionState.OFFLINE, authority)
    except Exception as exc:  # a gate failure must never enable mutation
        return False, f"authority gate unavailable ({type(exc).__name__})"
    if allowed:
        return True, ""
    return False, (
        f"session authority is {authority}; every simulator-mutating control "
        "stays disabled until exclusive authority is claimed")


@dataclass(frozen=True)
class Accessibility:
    """Keyboard focus order for the shell chrome."""

    order: tuple[str, ...]
    shortcuts: dict[str, str]

    def as_dict(self) -> dict:
        return {"focus_order": list(self.order), "shortcuts": dict(self.shortcuts)}


KEYBOARD_ORDER = Accessibility(
    order=("mode_badge", "command_palette", "nav_list", "page_title",
           "content_area", "status_bar"),
    shortcuts={"command_palette": "Ctrl+K", "search": "Ctrl+F",
               "next_route": "Ctrl+Right", "previous_route": "Ctrl+Left",
               "refresh": "F5", "help": "F1"},
)