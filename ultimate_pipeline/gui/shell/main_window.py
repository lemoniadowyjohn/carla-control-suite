"""The application shell window.

Responsibilities kept deliberately small: chrome, navigation over the 17-route
registry, a command palette, keyboard navigation, and window-state persistence.

It never starts CARLA, Unreal, a worker pool on launch, or a heavy ML import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QGuiApplication, QKeySequence
from PyQt6.QtWidgets import (
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QHBoxLayout,
    QPushButton,
    QFrame,
    QTabWidget,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ultimate_pipeline.gui.shell import preferences as prefs_mod
from ultimate_pipeline.gui.shell.navigation import (
    KEYBOARD_ORDER,
    SCREEN_ROUTES,
    ScreenRoute,
)
from ultimate_pipeline.gui.shell.pages.base import PageState
from ultimate_pipeline.gui.shell.pages.core import (
    ConnectionPage,
    DiagnosticsPage,
    HomePage,
    ProfilesPage,
    QaGatesPage,
    SettingsPage,
)
from ultimate_pipeline.gui.shell.pages.runtime import (
    RUNTIME_ROUTES,
    runtime_page_factory,
)
from ultimate_pipeline.gui.shell.services import ServiceRegistry
from ultimate_pipeline.gui.control_center.styles import CONTROL_CENTRE_QSS
from ultimate_pipeline.gui.control_center.shutdown import stop_ui_workers
from ultimate_pipeline.gui.control_center.workspaces import create_operator_workspace

__all__ = ["MainWindow", "create_application", "PAGE_FACTORIES"]


PAGE_FACTORIES: dict[str, Any] = {
    "01_home": HomePage,
    "02_environment_profiles": ProfilesPage,
    "03_connection_diagnostics": ConnectionPage,
    "13_qa_gates": QaGatesPage,
    "16_diagnostics_logs": DiagnosticsPage,
    "17_settings_safety_help": SettingsPage,
}

# Task 14: runtime and workflow screens. Route 10 is deliberately absent: BL-35
# ties screen 10 to Prompt 08, so it stays a registered placeholder here.
for _route in RUNTIME_ROUTES:
    PAGE_FACTORIES[_route] = runtime_page_factory(_route)


class _PlaceholderPage(QWidget):
    """A route that is registered but not yet implemented.

    It says so explicitly rather than rendering an empty screen.
    """

    def __init__(self, route: ScreenRoute, registry: ServiceRegistry,
                 parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel(route.title)
        title.setObjectName("page-title")
        title.setAccessibleName(f"{route.route} page title")
        layout.addWidget(title)
        note = QLabel(
            f"This screen is registered but NOT YET IMPLEMENTED. "
            f"Planned backend: {route.backend_service}. No controls are bound, "
            f"so nothing here can mutate shared state.")
        note.setObjectName("page-placeholder")
        note.setAccessibleName(f"{route.route} not implemented")
        note.setWordWrap(True)
        layout.addWidget(note)


class _ErrorPage(QWidget):
    """A page that failed to construct. It says so and binds nothing."""

    def __init__(self, route: ScreenRoute, detail: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel(route.title)
        title.setObjectName("page-title")
        title.setAccessibleName(f"{route.route} page title")
        layout.addWidget(title)
        note = QLabel(
            f"This screen FAILED TO INITIALISE: {detail}. No controls are bound.")
        note.setObjectName("page-error")
        note.setAccessibleName(f"{route.route} failed to initialise")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.controls: list = []


class MainWindow(QMainWindow):
    """Shell chrome over the route registry."""

    def __init__(self, registry: ServiceRegistry,
                 prefs_path: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.prefs_path = Path(prefs_path) if prefs_path else None
        self.preferences = prefs_mod.load(self.prefs_path,
                                           valid_routes=tuple(SCREEN_ROUTES)) \
            if self.prefs_path else prefs_mod.UIPreferences()
        if self.preferences.last_route not in SCREEN_ROUTES:
            # Defensive: a stale route must never break construction.
            self.preferences.last_route = "01_home"
        self.pages: dict[str, QWidget] = {}
        self._current_route = self.preferences.last_route

        self.setObjectName("carla-gui-main-window")
        self.setAccessibleName("CARLA Ops Studio")
        self.setWindowTitle("CARLA Ops Studio | Operations Control Center — OFFLINE MOCK")

        # The technical views remain intact behind the evidence tab. New
        # operator workspaces must not rewrite the original 17 route contracts.
        central = QWidget()
        central.setObjectName("central")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        topbar = QWidget()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(18, 10, 15, 10)
        brand = QLabel("◈  CARLA OPS STUDIO")
        brand.setObjectName("app-brand")
        top.addWidget(brand)
        self.command_palette = QLineEdit()
        self.command_palette.setObjectName("command-palette")
        self.command_palette.setAccessibleName("Command palette")
        self.command_palette.setPlaceholderText("Find a workspace…  Ctrl+K")
        self.command_palette.setMaximumWidth(300)
        self.command_palette.returnPressed.connect(self._palette_activated)
        top.addStretch(1)
        top.addWidget(self.command_palette)
        for caption, key in (("Connection", "03_connection_diagnostics"),
                             ("Maps", "05_maps_gis_cooking"),
                             ("Cameras", "08_sensors_streams"),
                             ("Experiments", "14_experiments_runs")):
            button = QPushButton(caption)
            button.setAccessibleName(f"Open {caption}")
            button.clicked.connect(lambda _, route=key: self.navigate(route))
            top.addWidget(button)
        refresh = QPushButton("Refresh")
        refresh.setAccessibleName("Refresh the current technical evidence page")
        refresh.clicked.connect(self.refresh_current)
        top.addWidget(refresh)
        layout.addWidget(topbar)

        body = QWidget()
        main = QHBoxLayout(body)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(235)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 16, 8, 10)
        sidebar_title = QLabel("WORKSPACES")
        sidebar_title.setObjectName("card-caption")
        sidebar_layout.addWidget(sidebar_title)
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("nav-list")
        self.nav_list.setAccessibleName("Screen navigation")
        self.nav_list.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        for route in SCREEN_ROUTES.values():
            prefix = "○ " if not route.implemented else "▸ "
            item = QListWidgetItem(prefix + route.title)
            item.setData(Qt.ItemDataRole.UserRole, route.route)
            item.setToolTip(route.route + (" · backend deferred" if not route.implemented else ""))
            self.nav_list.addItem(item)
        self.nav_list.currentItemChanged.connect(self._nav_changed)
        sidebar_layout.addWidget(self.nav_list, stretch=1)
        self.mode_badge = QLabel(self._badge_text())
        self.mode_badge.setObjectName("mode-badge")
        self.mode_badge.setAccessibleName("Application mode badge")
        self.mode_badge.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.mode_badge.setWordWrap(True)
        sidebar_layout.addWidget(self.mode_badge)
        main.addWidget(sidebar)

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(16, 13, 16, 12)
        self.workspace_title = QLabel("Operations overview")
        self.workspace_title.setObjectName("workspace-heading")
        workspace_layout.addWidget(self.workspace_title)
        self.safety_line = QLabel("MOCK · SHARED_READONLY · NO TICK OWNERSHIP · LIVE MUTATION DISABLED")
        self.safety_line.setObjectName("warning-pill")
        workspace_layout.addWidget(self.safety_line)
        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setObjectName("workspace-tabs")
        self.workspace_tabs.setAccessibleName("Operator workspace and source-backed technical evidence")
        self.operator_stack = QStackedWidget()
        self.operator_stack.setObjectName("operator-page-stack")
        self.operator_pages = {}
        self.stack = QStackedWidget()
        self.stack.setObjectName("page-stack")
        self.stack.setAccessibleName("Screen content area")
        self.pages: dict[str, QWidget] = {}
        for route in SCREEN_ROUTES.values():
            factory = PAGE_FACTORIES.get(route.route)
            try:
                page = (factory(registry) if factory else _PlaceholderPage(route, registry))
            except Exception as exc:
                page = _ErrorPage(route, f"{type(exc).__name__}: {exc}")
            page.setObjectName(f"page-{route.route}")
            self.pages[route.route] = page
            self.stack.addWidget(page)
            panel = create_operator_workspace(route.route, registry, self.navigate)
            panel.setObjectName(f"operator-{route.route}")
            self.operator_pages[route.route] = panel
            self.operator_stack.addWidget(panel)
        self.workspace_tabs.addTab(self.operator_stack, "CONTROL CENTER")
        self.workspace_tabs.addTab(self.stack, "TECHNICAL EVIDENCE")
        workspace_layout.addWidget(self.workspace_tabs, stretch=1)
        main.addWidget(workspace, stretch=1)
        layout.addWidget(body, stretch=1)

        self.setCentralWidget(central)
        self.setStyleSheet(CONTROL_CENTRE_QSS)
        self.setMinimumSize(1000, 650)
        self.statusBar().setObjectName("status-bar")
        self.statusBar().showMessage(
            f"{len(SCREEN_ROUTES)} routes registered · "
            f"{sum(1 for r in SCREEN_ROUTES.values() if r.implemented)} implemented · "
            f"mode {self.registry.badges.mode} · no CARLA mutations")

        self._install_shortcuts()
        self.restore_window_state()
        if not self.preferences.geometry:
            self.resize(1450, 850)
        self.navigate(self._current_route, persist=False)

    # -- chrome ------------------------------------------------------------
    def _badge_text(self) -> str:
        badges = self.registry.badges
        return (f"MODE {badges.mode} · BACKEND {badges.backend} · "
                f"AUTHORITY {badges.session_authority} · TICK {badges.tick_owner} · "
                f"MAP {badges.map_identity} · TM {badges.traffic_manager} · "
                f"EVIDENCE {badges.evidence_state}")

    def _install_shortcuts(self) -> None:
        palette = QAction(self)
        palette.setShortcut(QKeySequence(KEYBOARD_ORDER.shortcuts["command_palette"]))
        palette.triggered.connect(self._focus_palette)
        self.addAction(palette)

        for name, shortcut in (("next_route", "Ctrl+Right"), ("previous_route", "Ctrl+Left")):
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(
                lambda _=False, step=1 if name == "next_route" else -1: self.step_route(step))
            self.addAction(action)

        refresh = QAction(self)
        refresh.setShortcut(QKeySequence(KEYBOARD_ORDER.shortcuts["refresh"]))
        refresh.triggered.connect(self.refresh_current)
        self.addAction(refresh)

    def _focus_palette(self) -> None:
        self.command_palette.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _palette_activated(self) -> None:
        target = self.command_palette.text().strip()
        if not target:
            return
        if target in SCREEN_ROUTES:
            self.navigate(target)
            self.command_palette.clear()
        else:
            matches = [key for key, route in SCREEN_ROUTES.items()
                       if target.lower() in route.title.lower()]
            if len(matches) == 1:
                self.navigate(matches[0])
                self.command_palette.clear()
            else:
                self.statusBar().showMessage(f"no unambiguous screen for {target!r}")

    # -- navigation --------------------------------------------------------
    def navigate(self, route_key: str, *, persist: bool = True) -> None:
        if route_key not in SCREEN_ROUTES:
            raise KeyError(route_key)
        self._current_route = route_key
        self.stack.setCurrentWidget(self.pages[route_key])
        self.operator_stack.setCurrentWidget(self.operator_pages[route_key])
        self.workspace_title.setText(SCREEN_ROUTES[route_key].title)
        for index in range(self.nav_list.count()):
            item = self.nav_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == route_key:
                self.nav_list.setCurrentRow(index)
                break
        if persist:
            self.preferences.last_route = route_key
            self.save_preferences()

    def step_route(self, step: int) -> None:
        keys = sorted(SCREEN_ROUTES, key=lambda k: SCREEN_ROUTES[k].order)
        index = (keys.index(self._current_route) + step) % len(keys)
        self.navigate(keys[index])

    def _nav_changed(self, current: QListWidgetItem, _previous=None) -> None:
        if current is None:
            return
        route_key = current.data(Qt.ItemDataRole.UserRole)
        if route_key and route_key != self._current_route:
            self.navigate(route_key)

    def current_route(self) -> str:
        return self._current_route

    def refresh_current(self) -> None:
        page = self.pages[self._current_route]
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception as exc:
                if hasattr(page, "show_state"):
                    page.show_state(PageState.ERROR,
                                    f"{type(exc).__name__}: {exc}")
                self.statusBar().showMessage(f"refresh failed: {exc}")

    # -- persistence -------------------------------------------------------
    def restore_window_state(self) -> None:
        if self.preferences.geometry:
            self.restoreGeometry(
                self.preferences.geometry.encode("utf-8", errors="ignore"))
        # HiDPI scaling is always on in Qt6: both AA_UseHighDpiPixmaps and
        # AA_EnableHighDpiScaling were removed there. The only supported knob
        # left is the rounding policy, applied on the QGuiApplication.
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    def save_preferences(self) -> None:
        self.preferences.geometry = bytes(
            self.saveGeometry().toBase64()).decode("ascii")
        if self.prefs_path is None:
            return
        try:
            prefs_mod.save(self.preferences, self.prefs_path)
        except Exception:
            # A preference failure must never take the window down.
            self.statusBar().showMessage("could not persist UI preferences")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if not stop_ui_workers(self.operator_pages):
            event.ignore()
            self.statusBar().showMessage(
                "Cannot close yet: background IO is still stopping. Retry shortly.")
            return
        self.save_preferences()
        super().closeEvent(event)


def create_application(argv: list[str] | None = None):
    """Build the QApplication. Qt and only Qt -- no simulator, no ML import."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(argv or [])
    app.setApplicationName("CARLA Ops Studio")
    app.setOrganizationName("carla-gui-phase1")
    app.setApplicationVersion("0.1.0-phase1")
    return app