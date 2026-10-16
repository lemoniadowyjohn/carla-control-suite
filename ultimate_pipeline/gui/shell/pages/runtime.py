"""Qt pages for the runtime and workflow screens (Task 14).

Each page renders a Task 14 view model into a read-only table plus an explicit
list of blocked capabilities, so an operator can never mistake a deferred
capability for a working one.

Widgets are presentational only: no page calls a CARLA API, opens a socket, or
constructs a worker at construction time.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ultimate_pipeline.gui.shell.pages.base import BasePage
from ultimate_pipeline.gui.shell.viewmodels import (
    ActorsRoutesModel, CalibrationModel, ExperimentsModel, FuzzerModel,
    JobsModel, MapsModel, ScenarioModel, SensorsModel, TrafficManagerModel,
    WorldTimeModel,
)

__all__ = ["RuntimePage", "build_runtime_pages"]


class RuntimePage(BasePage):
    """Renders one view model's cells and its blocked-capability list."""

    def __init__(self, model: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            ["field", "value", "measured", "state"])
        self.table.setObjectName(f"{model.route}_cells")
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAccessibleName(f"{model.route} value table")
        self.blocked_label = QLabel("", self)
        self.blocked_label.setObjectName(f"{model.route}_blocked")
        self.blocked_label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(self.blocked_label)

    def refresh(self, _query: str = "") -> None:
        self.clear_dynamic_rows()
        cells = self.model.rows()
        self.table.setRowCount(len(cells))
        for row, cell in enumerate(cells):
            measured = "measured" if cell.measured else "requested"
            for col, text in enumerate((cell.name, str(cell.value), measured,
                                        cell.state or "-")):
                item = QTableWidgetItem(text)
                if cell.note:
                    item.setToolTip(cell.note)
                if not cell.measured:
                    item.setForeground(Qt.GlobalColor.darkYellow)
                self.table.setItem(row, col, item)
        blocked = self.model.blocked()
        self.blocked_label.setText(
            "Blocked / unavailable:\n  - " + "\n  - ".join(blocked)
            if blocked else "Blocked / unavailable: none")
        self.blocked_label.setAccessibleName(f"{self.model.route} blocked list")


def _experiment_registry(registry: Any) -> Any:
    # Deliberately never imports ultimate_pipeline.experiments.registry: that
    # module transitively imports main_pipeline and therefore the CARLA API,
    # which mock/offline mode forbids. The caller may inject a port instead.
    from ultimate_pipeline.gui.shell.viewmodels import ExperimentRegistryPort

    return _resolve(registry, "experiment_registry") or ExperimentRegistryPort()


def _actor_registry(registry: Any) -> Any:
    from ultimate_pipeline.gui.session import actor_registry

    return actor_registry.OwnedActorRegistry()


def _resolve(registry: Any, name: str, default: Any = None) -> Any:
    """ServiceRegistry exposes resolve(name); tolerate a missing service."""
    resolve = getattr(registry, "resolve", None)
    if resolve is None:
        return default
    try:
        return resolve(name)
    except Exception:
        return default


def build_runtime_pages(registry: Any) -> dict[str, RuntimePage]:
    """Construct the Task 14 pages from injected services only."""
    from ultimate_pipeline.gui.config.controls import ConfiguratorModel
    from ultimate_pipeline.gui.fuzz.mutators import registry as mutator_registry

    configurator = _resolve(registry, "configurator")
    if not isinstance(configurator, ConfiguratorModel):
        configurator = ConfiguratorModel()

    experiments = _experiment_registry(registry)
    job_observations = _resolve(registry, "job_observations", ())
    if not job_observations:
        job_observations = _observe_locks()

    models: dict[str, Any] = {
        "04_world_time": WorldTimeModel(configurator),
        "05_maps_gis_cooking": MapsModel(_resolve(registry, "map_registry")),
        "06_traffic_manager": TrafficManagerModel(
            _resolve(registry, "traffic_manager")),
        "07_actors_routes": ActorsRoutesModel(_actor_registry(registry)),
        "08_sensors_streams": SensorsModel(),
        "09_calibration_workbench": CalibrationModel(),
        "11_scenario_test_studio": ScenarioModel(experiments),
        "12_operational_fuzzer": FuzzerModel(mutator_registry),
        "14_experiments_runs": ExperimentsModel(experiments),
        "15_job_control": JobsModel(job_observations),
    }
    return {key: RuntimePage(model) for key, model in models.items()}


__all__ = ["RuntimePage", "build_runtime_pages", "runtime_page_factory",
           "RUNTIME_ROUTES"]

RUNTIME_ROUTES = (
    "04_world_time", "05_maps_gis_cooking", "06_traffic_manager",
    "07_actors_routes", "08_sensors_streams", "09_calibration_workbench",
    "11_scenario_test_studio", "12_operational_fuzzer",
    "14_experiments_runs", "15_job_control",
)

# Cached per registry instance so a test that injects a different registry
# never receives another test's already-built pages. The entry also holds the
# registry strongly (registries are unhashable dataclasses, so weak keys are
# impossible) which keeps id() stable, and every hit is liveness-validated: a
# page whose C++ object died with a previous window must never be re-parented
# into a new one.
_PAGE_CACHE: dict[int, tuple[Any, dict[str, RuntimePage]]] = {}


def _cached_pages(registry: Any) -> dict[str, RuntimePage] | None:
    key = id(registry)
    entry = _PAGE_CACHE.get(key)
    if entry is None:
        return None
    owner, pages = entry
    if owner is not registry:
        return None
    from PyQt6 import sip
    if any(sip.isdeleted(page) for page in pages.values()):
        del _PAGE_CACHE[key]
        return None
    return pages


def runtime_page_factory(route: str) -> Any:
    """Return a PAGE_FACTORIES-compatible factory for one runtime route."""

    def factory(registry: Any) -> RuntimePage:
        pages = _cached_pages(registry)
        if pages is None:
            pages = build_runtime_pages(registry)
            _PAGE_CACHE[id(registry)] = (registry, pages)
        if route not in pages:
            raise KeyError(f"{route} is not a Task 14 runtime route")
        return pages[route]

    factory.__name__ = f"runtime_page_{route}"
    return factory


def _observe_locks() -> tuple:
    """Observe the three lock authorities; never raises into the shell."""
    from ultimate_pipeline.gui.jobs.governance import observe_all_locks

    try:
        return tuple(observe_all_locks())
    except TypeError:
        return ()
    except Exception:
        return ()