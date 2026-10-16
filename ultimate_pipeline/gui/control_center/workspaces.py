"""The route -> operator workspace map, with 17 dedicated review contexts."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget,
)

from ultimate_pipeline.gui.shell.navigation import SCREEN_ROUTES
from ultimate_pipeline.gui.session.runtime_session import RuntimeSession
from .connection_panel import ConnectionPanel
from .drafts import DraftControlsPanel, FIELDS
from .experiments_panel import ExperimentsPanel
from .feeds import FeedsPanel
from .fuzzer_panel import FuzzerPanel
from .maps_panel import MapsPanel
from .settings_panel import SettingsPanel
from .weather_panel import WeatherPanel
from .widgets import action, card, section, text_label


class Dashboard(QWidget):
    def __init__(self, registry, navigate, parent=None):
        super().__init__(parent)
        root, outer = section("Operations overview", "CARLA Ops Studio  ·  Offline workbench and operator dashboard")
        badges = registry.badges
        grid = QGridLayout()
        summaries = [
            ("EXECUTION MODE", badges.mode, "Mock / offline; no simulator mutation"),
            ("SERVER", "NOT CONNECTED", "Use Connection to probe CARLA RPC"),
            ("WORLD / MAP", badges.map_identity, "Local map inspection is separate"),
            ("SIMULATOR AUTHORITY", badges.session_authority, "Tick owner: NONE"),
            ("TRAFFIC MANAGER", badges.traffic_manager, "Read-back not provided by CARLA"),
            ("SENSOR FRAMES", "UNBOUND", "Open camera monitoring for file replay"),
            ("EVIDENCE", badges.evidence_state, "No live validation claimed"),
            ("CONTROL COVERAGE", "44 / 116", "65 deferred · 7 disabled at v2 baseline"),
        ]
        for i, (title, value, sub) in enumerate(summaries):
            grid.addWidget(card(title, value, sub), i // 4, i % 4)
        outer.addLayout(grid)
        outer.addWidget(text_label("WORKSPACES", "workspace-heading"))
        buttons = QGridLayout()
        quick = [
            ("Server connection", "03_connection_diagnostics"),
            ("Maps & elevation", "05_maps_gis_cooking"),
            ("Sensor feeds", "08_sensors_streams"),
            ("Traffic Manager", "06_traffic_manager"),
            ("Calibration", "09_calibration_workbench"),
            ("Experiment studio", "14_experiments_runs"),
            ("Operational fuzzer", "12_operational_fuzzer"),
            ("Settings", "02_environment_profiles"),
        ]
        for index, (label, route) in enumerate(quick):
            buttons.addWidget(action(label + "  →", lambda _, r=route: navigate(r),
                                     index == 0), index // 4, index % 4)
        outer.addLayout(buttons)
        outer.addWidget(text_label("LIVE VALIDATION GATES", "workspace-heading"))
        gates = QHBoxLayout()
        for title, value in (("G5", "COOK REQUIRED"), ("G6", "RUNTIME IDENTITY UNBOUND"),
                             ("G7", "COOKED CONTENT UNVERIFIED"), ("G8", "TICK OWNER MISSING")):
            gates.addWidget(card(title, value))
        outer.addLayout(gates)
        outer.addStretch(1)
        hold = QVBoxLayout(self)
        hold.setContentsMargins(0, 0, 0, 0)
        hold.addWidget(root)


class StatusWorkspace(QWidget):
    """Honest informational workspace when a live integration is deferred."""
    def __init__(self, route: str, parent=None):
        super().__init__(parent)
        description = {
            "10_perception_localization": "No verified inference backend, detection model weights or localization service is bound.",
            "13_qa_gates": "Quality evidence is displayed in the Technical Evidence tab. Missing gates are not PASS.",
            "15_job_control": "Worktree, Git and simulator leases are independent. There is no live job queue adapter.",
            "16_diagnostics_logs": "Audit events and stage health reports are in Technical Evidence.",
            "17_settings_safety_help": "Use Environment Profiles to stage or save settings. Shared-readonly forbids mutation.",
        }.get(route, "No validated interactive runtime adapter is registered for this route.")
        root, outer = section(SCREEN_ROUTES[route].title, description)
        outer.addWidget(card("Capability", "DEFERRED / READ-ONLY", "No invented simulator state"))
        outer.addWidget(text_label("Use the Technical Evidence tab for source-backed status. "
                                   "Local proposals are deliberately separate from applied settings."))
        outer.addStretch(1)
        hold = QVBoxLayout(self)
        hold.setContentsMargins(0, 0, 0, 0)
        hold.addWidget(root)




def grouped(*tabs: tuple[str, QWidget]) -> QTabWidget:
    """Tabbed workflows; each tab owns a small, separately testable widget."""
    group = QTabWidget()
    group.setObjectName("operator-subtabs")
    for name, content in tabs:
        group.addTab(content, name)
    return group

def _runtime_session(registry):
    """The app-wide shared runtime session: exactly one per registry.

    Registered on first use so every route resolves the same instance;
    build_registry() registers it up front in production.
    """
    if not registry.available("runtime_session"):
        registry.register(
            "runtime_session", RuntimeSession(),
            "ultimate_pipeline/gui/session/runtime_session.py")
    return registry.resolve("runtime_session")


def create_operator_workspace(route: str, registry, navigate):
    """Instantiate a practical workspace while retaining original evidence pages."""
    try:
        if route == "01_home":
            return Dashboard(registry, navigate)
        if route == "02_environment_profiles":
            return SettingsPanel(registry)
        if route == "03_connection_diagnostics":
            return ConnectionPanel()
        if route == "04_world_time":
            return WeatherPanel(runtime_session=_runtime_session(registry))
        if route == "05_maps_gis_cooking":
            return grouped(("Map & elevation explorer",
                            MapsPanel(runtime_session=_runtime_session(registry))),
                           ("Cook / runtime provenance", StatusWorkspace(route)))
        if route == "06_traffic_manager":
            return grouped(("Global policy drafts", DraftControlsPanel(route)),
                           ("Per-vehicle / readback", StatusWorkspace(route)))
        if route == "07_actors_routes":
            return grouped(("Actor population", DraftControlsPanel(route)),
                           ("Ownership & routes", StatusWorkspace(route)))
        if route == "08_sensors_streams":
            return grouped(("Camera feeds",
                            FeedsPanel(runtime_session=_runtime_session(registry))),
                           ("Sensor configuration", DraftControlsPanel(route)),
                           ("Stream diagnostics", StatusWorkspace(route)))
        if route == "09_calibration_workbench":
            return grouped(("Intrinsics / extrinsics", DraftControlsPanel(route)),
                           ("Calibration QA", StatusWorkspace(route)))
        if route in ("11_scenario_test_studio", "14_experiments_runs"):
            return grouped(("Experiment designer", ExperimentsPanel()),
                           ("Run evidence", StatusWorkspace(route)))
        if route == "12_operational_fuzzer":
            return grouped(("Mutation cases", FuzzerPanel()),
                           ("Replay / corpus / oracles", StatusWorkspace(route)))
        return StatusWorkspace(route)
    except Exception as exc:
        # Do not hide construction errors behind a blank content pane.
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(text_label(f"WORKSPACE ERROR: {type(exc).__name__}: {exc}", "warning-pill"))
        return widget
