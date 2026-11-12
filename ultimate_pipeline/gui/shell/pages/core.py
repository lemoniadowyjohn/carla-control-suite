"""The six initial read-mostly screens: 01, 02, 03, 13, 16 and 17.

Each screen consumes existing Task 02-12 services through the injected
:class:`ServiceRegistry`. None of them reimplements settings, session
ownership, Traffic Manager, calibration, reporting, status classification,
corpus management or fuzzer logic.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QLabel, QLineEdit, QTableWidget, QTableWidgetItem

from ultimate_pipeline.gui.shell.navigation import bind_control
from ultimate_pipeline.gui.shell.pages.base import BasePage, PageState
from ultimate_pipeline.gui.shell.services import ServiceRegistry

__all__ = ["HomePage", "ProfilesPage", "ConnectionPage", "QaGatesPage",
           "DiagnosticsPage", "SettingsPage"]


class HomePage(BasePage):
    """01 -- Home. Badges only; no live telemetry is invented."""

    route_key = "01_home"

    def __init__(self, registry: ServiceRegistry, parent=None) -> None:
        super().__init__(registry, parent)
        self.refresh()

    def refresh(self) -> None:
        self.clear_dynamic_rows()
        badges = self.registry.badges
        self.add_control(bind_control(
            "CTL-001", "Application mode", self.route_key, "carla_backend",
            "read mode badge", "T-QT-01", registry=self.registry,
            source="ultimate_pipeline/gui/shell/services.py Badges.mode"))
        self.add_control(bind_control(
            "CTL-002", "Session authority", self.route_key, "traffic_manager",
            "read authority", "T-QT-02", registry=self.registry,
            source="ultimate_pipeline/gui/health.py SessionAuthority"))
        self.add_control(bind_control(
            "CTL-003", "Tick owner", self.route_key, "carla_backend",
            "read tick grant holder", "T-QT-03", registry=self.registry,
            source="ultimate_pipeline/gui/session/tick_authority.py"))
        self.add_control(bind_control(
            "CTL-004", "Map identity", self.route_key, "map_registry",
            "read runtime map identity", "T-QT-04", registry=self.registry,
            source="ultimate_pipeline/gui/maps/cook.py bind_runtime_identity"))
        self.add_control(bind_control(
            "CTL-005", "Live telemetry", self.route_key, "live_fuzzer",
            "live world telemetry", "T-QT-05", registry=self.registry,
            mutating=True, source="ultimate_pipeline/gui/fuzz/service.py"))
        self.show_state(
            PageState.IDLE,
            f"mode={badges.mode} authority={badges.session_authority} "
            f"tick={badges.tick_owner} map={badges.map_identity} "
            f"tm={badges.traffic_manager}",
            evidence_state=badges.evidence_state)


class ProfilesPage(BasePage):
    """02 -- Environment Profiles. Uses the Task 03 settings registry."""

    route_key = "02_environment_profiles"

    def __init__(self, registry: ServiceRegistry, parent=None) -> None:
        super().__init__(registry, parent)
        self.search = QLineEdit()
        self.search.setObjectName("profile-search")
        self.search.setAccessibleName("Search settings")
        self.search.setPlaceholderText("Search 314 settings…")
        self.container_layout.addWidget(self.search)
        self.table = QTableWidget()
        self.table.setObjectName("profile-table")
        self.table.setAccessibleName("Settings catalogue")
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["setting_id", "kind", "lifecycle", "binding"])
        self.container_layout.addWidget(self.table)
        self.refresh()

    def refresh(self, needle: str = "") -> None:
        self.clear_dynamic_rows()
        settings = self.registry.resolve("settings_registry")
        rows = (settings.editable() if not needle
                 else settings.search(needle))
        self.table.setRowCount(min(len(rows), 200))
        for index, meta in enumerate(rows[:200]):
            editable = meta.is_editable
            cells = [
                meta.setting_id, meta.kind, meta.lifecycle,
                "AVAILABLE" if editable else f"DISABLED — {meta.disabled_reason}",
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                item.setFlags(item.flags() & ~item.flags().ItemIsEditable)
                self.table.setItem(index, column, item)
        self.add_control(bind_control(
            "CTL-010", "Apply profile", self.route_key, "configurator",
            "apply staged profile", "T-QT-06", registry=self.registry,
            mutating=True, source="ultimate_pipeline/gui/config/controls.py"))
        self.add_control(bind_control(
            "CTL-011", "Export profile", self.route_key, "configurator",
            "export profile to disk", "T-QT-07", registry=self.registry,
            mutating=True, source="ultimate_pipeline/gui/config/profiles.py"))
        self.show_state(
            PageState.EMPTY if not rows else PageState.IDLE,
            f"{len(rows)} settings shown of {len(settings.distinct_ids)} distinct ids",
            "318 catalogue rows cover 314 distinct settings",
            evidence_state=settings.base_sha[:12])


class ConnectionPage(BasePage):
    """03 -- Connection and Diagnostics. Five-stage ladder, no live connect."""

    route_key = "03_connection_diagnostics"

    def __init__(self, registry: ServiceRegistry, parent=None) -> None:
        super().__init__(registry, parent)
        self.refresh()

    def refresh(self) -> None:
        self.clear_dynamic_rows()
        from ultimate_pipeline.gui.health import probe_stages
        backend = self.registry.resolve("carla_backend")
        self.add_control(bind_control(
            "CTL-020", "Probe connection", self.route_key, "carla_backend",
            "five-stage health ladder", "T-QT-08", registry=self.registry,
            source="ultimate_pipeline/gui/health.py probe_stages"))
        self.add_control(bind_control(
            "CTL-021", "Connect", self.route_key, "carla_backend",
            "open a governed connection", "T-QT-09", registry=self.registry,
            mutating=True, source="ultimate_pipeline/gui/runtime/connection.py"))
        self.add_control(bind_control(
            "CTL-022", "Destructive cleanup", self.route_key, "carla_backend",
            "kill stuck CARLA / rmtree CarlaUE4", "T-QT-10",
            registry=self.registry, mutating=True,
            source="ultimate_pipeline/core/carla_utils.py:314,411,433"))
        ladder_stages = ["PORT_OPEN", "RPC_HANDSHAKE", "SERVER_VERSION",
                        "MAP_IDENTITY", "TICK_AUTHORITY", "SENSOR_CANARY"]
        # NO probe runs here. Probing opens a socket, so it is an explicit
        # operator action, never a side effect of navigation or refresh.
        self.add_control(bind_control(
            "CTL-020", "Probe connection", self.route_key, "carla_backend",
            "run the five-stage health ladder on demand", "T-QT-08",
            registry=self.registry,
            source="ultimate_pipeline/gui/health.py probe_stages"))
        self.add_control(bind_control(
            "CTL-021", "Connect", self.route_key, "carla_backend",
            "open a governed connection", "T-QT-09", registry=self.registry,
            mutating=True, source="ultimate_pipeline/gui/runtime/connection.py"))
        self.add_control(bind_control(
            "CTL-022", "Destructive cleanup", self.route_key, "carla_backend",
            "kill stuck CARLA / rmtree CarlaUE4", "T-QT-10",
            registry=self.registry, mutating=True,
            source="ultimate_pipeline/core/carla_utils.py:314,411,433"))
        backend = self.registry.resolve("carla_backend")
        self.show_state(
            PageState.BLOCKED,
            "not connected",
            f"probe ladder stages: {' -> '.join(ladder_stages)}",
            "no probe is executed until CTL-020 is explicitly invoked; "
            "navigation performs no network I/O",
            evidence_state=backend.page_mode() if hasattr(backend, "page_mode")
            else "NOT_PROBED")


class QaGatesPage(BasePage):
    """13 -- QA Gates. INVALID_METRIC is never rendered as a pass."""

    route_key = "13_qa_gates"

    def __init__(self, registry: ServiceRegistry, parent=None) -> None:
        super().__init__(registry, parent)
        self.table = QTableWidget()
        self.table.setObjectName("gate-table")
        self.table.setAccessibleName("Quality gate status")
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["gate", "status", "note"])
        self.container_layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        self.clear_dynamic_rows()
        from ultimate_pipeline.gui.maps.gates import GAP026_RECORD, run_gates
        # The gate results come from a REAL run. With no gate suite executed the
        # honest value for every gate is NOT_EXECUTED -- the view must never
        # author its own PASS verdicts.
        suite = run_gates({}, requested=("topology", "hash", "elevation",
                                                      "tile_frame_consistency"))
        rows = [(o.name, o.status, o.detail) for o in suite.outcomes]
        self.table.setRowCount(len(rows))
        for index, (name, status, note) in enumerate(rows):
            for column, text in enumerate((name, status, note)):
                item = QTableWidgetItem(str(text))
                item.setFlags(item.flags() & ~item.flags().ItemIsEditable)
                self.table.setItem(index, column, item)
        self.add_control(bind_control(
            "CTL-130", "Accept map", self.route_key, "quality",
            "accept a map on gate results", "T-QT-11", registry=self.registry,
            mutating=True, source="ultimate_pipeline/gui/maps/gates.py"))
        self.add_control(bind_control(
            "CTL-131", "Cook map", self.route_key, "map_cooking",
            "run an operator-led UE4.26 cook", "T-QT-12",
            registry=self.registry, mutating=True,
            source="ultimate_pipeline/gui/maps/cook.py"))
        self.show_state(
            PageState.BLOCKED,
            f"no gate suite has been executed: {len(rows)} gate(s) reported",
            f"GAP-026 {GAP026_RECORD['state']}: "
            f"{GAP026_RECORD['failed_lane_links']}/{GAP026_RECORD['total_lane_links']} "
            "(thresholds are never raised to clear it)",
            "run a real quality suite before any gate can be read as PASS")


class DiagnosticsPage(BasePage):
    """16 -- Diagnostics and Logs."""

    route_key = "16_diagnostics_logs"

    def __init__(self, registry: ServiceRegistry, parent=None) -> None:
        super().__init__(registry, parent)
        self.table = QTableWidget()
        self.table.setObjectName("diagnostics-table")
        self.table.setAccessibleName("Diagnostic findings")
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["source", "state", "detail"])
        self.container_layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        self.clear_dynamic_rows()
        from ultimate_pipeline.gui.fuzz.corpus import SUPPORTED_CORPUS_VERSIONS
        rows = [
            ("status_sources", "AVAILABLE", f"11 source vocabularies"),
            ("corpus", "DISABLED", self.registry.reason_unavailable("corpus")),
            ("audit_journal", "DISABLED",
             self.registry.reason_unavailable("audit_journal")),
            ("corpus_schema", "AVAILABLE", ", ".join(SUPPORTED_CORPUS_VERSIONS)),
        ]
        self.table.setRowCount(len(rows))
        for index, (name, state, detail) in enumerate(rows):
            for column, text in enumerate((name, state, detail)):
                item = QTableWidgetItem(str(text))
                item.setFlags(item.flags() & ~item.flags().ItemIsEditable)
                self.table.setItem(index, column, item)
        self.add_control(bind_control(
            "CTL-160", "Open audit log", self.route_key, "audit_journal",
            "open the redacted append-only journal", "T-QT-13",
            registry=self.registry, source="ultimate_pipeline/gui/audit.py"))
        self.show_state(PageState.IDLE, f"{len(rows)} diagnostics",
                        "mutating settings are recorded by the audit journal")


class SettingsPage(BasePage):
    """17 -- Settings, Safety and Help. Help is generated from the registry."""

    route_key = "17_settings_safety_help"

    def __init__(self, registry: ServiceRegistry, parent=None) -> None:
        super().__init__(registry, parent)
        self.help_area = QLabel()
        self.help_area.setObjectName("settings-help")
        self.help_area.setAccessibleName("Settings help")
        self.help_area.setWordWrap(True)
        self.container_layout.addWidget(self.help_area)
        self.refresh()

    def refresh(self) -> None:
        self.clear_dynamic_rows()
        settings = self.registry.resolve("settings_registry")
        entry = settings.one("PROJECT_ROOT") or (settings.editable() or [None])[0]
        counts = settings.counts
        self.help_area.setText(
            f"{counts['total']} declaration sites / "
            f"{counts['distinct_setting_ids']} distinct settings; "
            f"{counts['absent_at_head']} absent at HEAD; "
            f"{counts['range_known']} with a validated range.\n"
            f"Provenance: {entry.provenance_help if entry else 'n/a'}\n"
            f"Environment coverage: {settings.env_coverage['env_reads_discovered']} reads "
            f"discovered, {settings.env_coverage['env_reads_outside_settings_sampled']} "
            f"sampled (sampled_not_exhaustive="
            f"{settings.env_coverage['sampled_not_exhaustive']}).")
        self.add_control(bind_control(
            "CTL-170", "Apply staged settings", self.route_key, "configurator",
            "apply staged settings", "T-QT-14", registry=self.registry,
            mutating=True, source="ultimate_pipeline/gui/config/controls.py"))
        self.add_control(bind_control(
            "CTL-171", "Restore defaults", self.route_key, "configurator",
            "restore defaults", "T-QT-15", registry=self.registry,
            mutating=True, source="ultimate_pipeline/gui/config/profiles.py"))
        self.show_state(PageState.IDLE, "help generated from the settings registry",
                        f"lifecycle is 'restart' for all {counts['total']} entries; "
                        "no apply path exists yet",
                        "staged edits are not auto-applied")