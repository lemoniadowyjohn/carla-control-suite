"""Task 14 tests for the runtime and workflow screens.

These assert the *truthfulness* invariants rather than pixel output: an
unmeasured value must never render as measured, a blocked capability must
never look available, and mock mode must never import CARLA or torch.

Run with QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import pytest

from ultimate_pipeline.gui.run_status import RunStatus
from ultimate_pipeline.gui.shell.viewmodels import (
    UNAVAILABLE, ActorsRoutesModel, CalibrationModel, ExperimentRegistryPort,
    ExperimentsModel, FuzzerModel, JobsModel, MapsModel, ScenarioModel,
    SensorsModel, TrafficManagerModel, WorldTimeModel,
)


def _names(cells) -> set[str]:
    return {c.name for c in cells}


def _cell(cells, name):
    for c in cells:
        if c.name == name:
            return c
    raise AssertionError(f"{name!r} not in {_names(cells)}")


# --------------------------------------------------------------- fixtures
class _Config:
    def staged_values(self):
        return {"synchronous_mode": True, "fixed_delta_seconds": 0.05}


class _EmptyConfig:
    def staged_values(self):
        return {}


@dataclass
class _Obs:
    authority: str
    state: str = "FREE"
    detail: str = ""
    malformed: bool = False


class _Actors:
    def __init__(self, ids=("a", "b")):
        self._ids = tuple(ids)

    def actor_ids(self):
        return self._ids

    def cleanup_report(self):
        return "destroyed=0 preserved=2"


class _TM:
    claim_holder = "task14"
    declared_only = ("vehicle_percentage", "random_seed")


@pytest.fixture
def app():
    from ultimate_pipeline.gui.shell.main_window import create_application

    return create_application([])


# ------------------------------------------------------- NOT_EVALUATED
def test_unmeasured_values_are_never_reported_measured():
    cells = WorldTimeModel(_EmptyConfig()).rows()
    for cell in cells:
        assert cell.measured is False, cell
        assert cell.state == RunStatus.NOT_EVALUATED.value, cell


def test_measured_values_are_marked_measured():
    cells = WorldTimeModel(_Config()).rows()
    assert _cell(cells, "synchronous_mode").measured is True
    assert _cell(cells, "fixed_delta_seconds").value == 0.05


def test_loaded_map_is_never_claimed_measured():
    cells = WorldTimeModel(_Config()).rows()
    assert _cell(cells, "loaded_map").measured is False


# ------------------------------------------------------------------ maps
def test_map_layers_are_separated():
    rows = _names(MapsModel(None).rows())
    for layer in MapsModel(None).LAYERS:
        assert layer in rows, layer


def test_generated_cooked_and_runtime_are_never_confused():
    cells = MapsModel(None).rows()
    for layer in MapsModel(None).LAYERS[1:]:
        cell = _cell(cells, layer)
        assert cell.value == "NOT_BOUND"
        assert cell.measured is False


def test_cook_is_operator_only_blocked():
    cell = MapsModel(None).cook()
    assert cell.state == RunStatus.BLOCKED_EXTERNAL.value
    assert "UE4.26" in cell.note


# --------------------------------------------------- traffic manager
def test_traffic_manager_claims_zero_confirmed_settings():
    cell = _cell(TrafficManagerModel(_TM()).rows(), "confirmed settings")
    assert cell.value == 0
    assert cell.note


def test_traffic_manager_restore_is_unavailable():
    cell = _cell(TrafficManagerModel(_TM()).rows(), "restore TM defaults")
    assert cell.value == UNAVAILABLE
    assert cell.measured is False


def test_traffic_manager_declared_only_string_is_safe():
    class WeirdTM:
        claim_holder = None
        declared_only = object()
    assert "declared only" in _names(TrafficManagerModel(WeirdTM()).rows())


# -------------------------------------------------------------- actors
def test_actors_external_count_is_not_fabricated():
    cell = _cell(ActorsRoutesModel(_Actors()).rows(), "preserved external")
    assert cell.value == UNAVAILABLE
    assert cell.measured is False


def test_actors_owned_count_is_measured():
    assert _cell(ActorsRoutesModel(_Actors()).rows(), "owned actors").value == 2


# ------------------------------------------------------------- sensors
def test_sensors_show_nothing_before_any_callback():
    cell = _cell(SensorsModel().rows(), "callback metrics")
    assert cell.measured is False
    assert "no callback" in cell.note


def test_sensors_show_metrics_once_recorded():
    model = SensorsModel()
    model.record({"queue_depth": 3, "dropped": 0})
    cells = model.rows()
    assert _cell(cells, "queue_depth").measured is True
    assert _cell(cells, "dropped").measured is True


# --------------------------------------------------------- calibration
def test_calibration_has_no_unmeasured_reprojection_pass():
    cell = _cell(CalibrationModel().rows(), "reprojection")
    assert cell.measured is False
    assert cell.state == RunStatus.NOT_EVALUATED.value


def test_calibration_drift_needs_owner_approved_tolerance():
    cell = _cell(CalibrationModel().rows(), "drift")
    assert cell.measured is False
    assert "Q11" in cell.note


def test_calibration_sensors_are_unavailable():
    cell = _cell(CalibrationModel().rows(), "radar / GNSS / IMU")
    assert cell.value == UNAVAILABLE
    assert cell.measured is False


def test_calibration_records_partial_measurement():
    model = CalibrationModel()
    model.record({"reprojection": 0.9})
    cells = model.rows()
    assert _cell(cells, "reprojection").measured is True
    assert _cell(cells, "drift").measured is False


# ------------------------------------------------------- experiment port
def test_experiment_registry_default_is_unavailable_not_empty():
    port = ExperimentRegistryPort()
    assert port.available is False
    cells = ScenarioModel(port).rows()
    assert _cell(cells, "registered experiments").measured is False


def test_experiment_registry_never_imports_carla():
    """Importing the real registry pulls main_pipeline and therefore CARLA."""
    from ultimate_pipeline.gui.shell.pages import runtime

    model = ScenarioModel()
    model.rows()
    assert "carla" not in sys.modules
    assert runtime is not None


def test_injected_experiment_registry_is_reported():
    class Registry:
        EXPERIMENTS = {"a": 1, "b": 2}
        available = True
    cells = ScenarioModel(Registry()).rows()
    assert _cell(cells, "registered experiments").value == 2


def test_experiments_last_verdict_is_not_evaluated():
    cells = ExperimentsModel().rows()
    assert _cell(cells, "last verdict").state == RunStatus.NOT_EVALUATED.value


# --------------------------------------------------------------- fuzzer
def test_fuzzer_live_start_is_disabled_without_a_lease():
    from ultimate_pipeline.gui.fuzz.mutators import registry as mutators

    cell = _cell(FuzzerModel(mutators).rows(), "live Start")
    assert cell.value == "DISABLED"
    assert cell.state == RunStatus.BLOCKED_EXTERNAL.value


def test_fuzzer_separates_family_kinds():
    from ultimate_pipeline.gui.fuzz.mutators import registry as mutators

    cells = FuzzerModel(mutators).rows()
    offline = _cell(cells, "offline families").value
    simulator = _cell(cells, "simulator-guarded").value
    assert offline >= 1 and simulator >= 1
    assert offline + simulator == _cell(cells, "families").value


# ----------------------------------------------------------------- jobs
def test_jobs_shows_exactly_three_authorities():
    rows = _names(JobsModel().rows())
    assert rows == set(JobsModel.EXPECTED)


def test_jobs_marks_missing_observation_not_evaluated():
    cell = _cell(JobsModel().rows(), "REPO_WRITER")
    assert cell.measured is False
    assert cell.state == RunStatus.NOT_EVALUATED.value


def test_jobs_flags_malformed_lock():
    cell = _cell(JobsModel([_Obs("MACHINE_LEASE", malformed=True)]).rows(),
                 "MACHINE_LEASE")
    assert cell.value == "MALFORMED_LOCK"


def test_jobs_rejects_unknown_authority_loudly():
    rows = _names(JobsModel([_Obs("SOMETHING_ELSE")]).rows())
    assert "SOMETHING_ELSE" in rows
    assert rows != set(JobsModel.EXPECTED)


# -------------------------------------------------------- page wiring
def test_all_ten_runtime_pages_build(app):
    from ultimate_pipeline.gui.shell.main_window import PAGE_FACTORIES
    from ultimate_pipeline.gui.shell.pages.runtime import RUNTIME_ROUTES

    assert len(RUNTIME_ROUTES) == 10
    for route in RUNTIME_ROUTES:
        assert route in PAGE_FACTORIES, route


def test_runtime_page_renders_cells_and_blocked_list(app):
    from ultimate_pipeline.gui.shell.services import build_registry
    from ultimate_pipeline.gui.shell.pages.runtime import build_runtime_pages

    pages = build_runtime_pages(build_registry())
    assert len(pages) == 10
    for route, page in pages.items():
        page.refresh()
        assert page.table.rowCount() > 0, route
        assert page.blocked_label.text().startswith("Blocked"), route


def test_requested_values_are_visually_distinct(app):
    from ultimate_pipeline.gui.shell.services import build_registry
    from ultimate_pipeline.gui.shell.pages.runtime import build_runtime_pages

    page = build_runtime_pages(build_registry())["08_sensors_streams"]
    page.refresh()
    item = page.table.item(0, 2)
    assert item.text() == "requested"


def test_route_10_stays_a_placeholder(app):
    from ultimate_pipeline.gui.shell.main_window import PAGE_FACTORIES
    from ultimate_pipeline.gui.shell.navigation import SCREEN_ROUTES

    assert "10_perception_localization" in SCREEN_ROUTES
    assert "10_perception_localization" not in PAGE_FACTORIES


def test_mock_mode_imports_no_heavy_modules(app):
    from ultimate_pipeline.gui.shell.main_window import MainWindow
    from ultimate_pipeline.gui.shell.services import build_registry

    window = MainWindow(build_registry())
    window.show()
    try:
        for route in ("01_home", "04_world_time", "09_calibration_workbench",
                      "12_operational_fuzzer", "15_job_control"):
            window.navigate(route)
            window.refresh_current()
        assert "carla" not in sys.modules
        assert "torch" not in sys.modules
    finally:
        window.close()


def test_every_runtime_model_declares_something_blocked(app):
    from ultimate_pipeline.gui.shell.services import build_registry
    from ultimate_pipeline.gui.shell.pages.runtime import build_runtime_pages

    for route, page in build_runtime_pages(build_registry()).items():
        assert page.model.blocked(), route


def test_factory_cache_is_per_registry(app):
    from ultimate_pipeline.gui.shell.services import build_registry
    from ultimate_pipeline.gui.shell.pages.runtime import runtime_page_factory

    first = build_registry()
    second = build_registry()
    factory = runtime_page_factory("04_world_time")
    assert factory(first) is factory(first)
    assert factory(first) is not factory(second)


def test_unknown_runtime_route_raises(app):
    from ultimate_pipeline.gui.shell.services import build_registry
    from ultimate_pipeline.gui.shell.pages.runtime import runtime_page_factory

    with pytest.raises(KeyError):
        runtime_page_factory("99_not_a_route")(build_registry())


def test_main_window_navigates_all_routes(app):
    from ultimate_pipeline.gui.shell.main_window import MainWindow
    from ultimate_pipeline.gui.shell.navigation import SCREEN_ROUTES
    from ultimate_pipeline.gui.shell.services import build_registry

    window = MainWindow(build_registry())
    window.show()
    try:
        for route in SCREEN_ROUTES:
            window.navigate(route)
            window.refresh_current()
            assert window.current_route() == route
    finally:
        window.close()


def test_error_page_still_used_for_broken_runtime_model(app):
    """A failing view model must not take the whole shell down."""
    from ultimate_pipeline.gui.shell.main_window import (
        MainWindow, PAGE_FACTORIES, _ErrorPage,
    )
    from ultimate_pipeline.gui.shell.services import build_registry

    def boom(_registry):
        raise RuntimeError("model exploded")

    original = PAGE_FACTORIES["04_world_time"]
    PAGE_FACTORIES["04_world_time"] = boom
    try:
        window = MainWindow(build_registry())
        try:
            page = window.pages["04_world_time"]
            assert isinstance(page, _ErrorPage)
            assert "model exploded" in _error_text(page)
        finally:
            window.close()
    finally:
        PAGE_FACTORIES["04_world_time"] = original


def _error_text(page) -> str:
    from PyQt6.QtWidgets import QLabel

    return "\n".join(label.text() for label in page.findChildren(QLabel))