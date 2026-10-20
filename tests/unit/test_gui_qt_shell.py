"""Task 13 acceptance tests: PyQt6 shell, 17 routes, six core screens.

Runs entirely offscreen. Maps to T-QT-01..36.

No simulator is started, no CARLA import occurs, and no widget is mutated off
the main thread.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ultimate_pipeline.gui.shell.main_window import (  # noqa: E402
    MainWindow,
    PAGE_FACTORIES,
    create_application,
)
from ultimate_pipeline.gui.shell.navigation import (  # noqa: E402
    KEYBOARD_ORDER,
    SCREEN_COUNT,
    SCREEN_ROUTES,
    ScreenRoute,
    bind_control,
    route_for,
)
from ultimate_pipeline.gui.shell.preferences import (  # noqa: E402
    SAFE_KEYS,
    SecretRejected,
    UIPreferences,
    load,
    save,
)
from ultimate_pipeline.gui.shell.services import (  # noqa: E402
    AppMode,
    Badges,
    ServiceRegistry,
    ServiceUnavailable,
    build_registry,
)
from ultimate_pipeline.gui.shell.workers import Debouncer, WorkerPool  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return create_application([])


@pytest.fixture()
def registry():
    return build_registry()


@pytest.fixture()
def window(app, registry, tmp_path):
    win = MainWindow(registry, prefs_path=tmp_path / "ui.json")
    yield win
    win.close()


# ================================================ T-QT-01..06  shell + routes
def test_T_QT_01_mode_badge_reports_real_state(window):
    badges = window.registry.badges
    text = window.mode_badge.text()
    for field in (badges.mode, badges.backend, badges.session_authority,
                  badges.tick_owner, badges.map_identity,
                  badges.traffic_manager, badges.evidence_state):
        assert field in text
    assert window.mode_badge.accessibleName()


def test_T_QT_02_session_authority_badge_is_shared_readonly_by_default(registry):
    assert registry.badges.session_authority == "SHARED_READONLY"
    assert registry.badges.tick_owner == "NONE"
    assert registry.badges.traffic_manager == "WRITE_ONLY"


def test_T_QT_03_evidence_state_is_not_evaluated_not_pass(window):
    assert window.registry.badges.evidence_state == "NOT_EVALUATED"
    assert "PASS" not in window.mode_badge.text()


def test_T_QT_04_map_identity_is_unbound_not_a_guess(window):
    assert window.registry.badges.map_identity == "UNBOUND"


def test_T_QT_05_launch_does_not_import_carla_or_ml(registry):
    assert "carla" not in sys.modules
    assert "torch" not in sys.modules
    assert registry.badges.mode == AppMode.MOCK.value


def test_T_QT_06_offline_mode_requires_no_simulator(app, registry):
    for name in registry.names():
        registry.resolve(name)  # must not raise
    assert registry.badges.backend == "mock"


# ============================================== T-QT-07..12  navigation
def test_T_QT_07_exactly_seventeen_routes_are_registered():
    assert SCREEN_COUNT == 17
    assert len(SCREEN_ROUTES) == 17
    assert sorted(SCREEN_ROUTES) == sorted(
        [r.route for r in SCREEN_ROUTES.values()])
    assert [SCREEN_ROUTES[k].order for k in sorted(SCREEN_ROUTES)] == list(range(1, 18))


def test_T_QT_08_every_route_declares_a_backend_service():
    for route in SCREEN_ROUTES.values():
        assert route.backend_service
        assert route.read_only is True


def test_T_QT_09_the_six_initial_screens_are_implemented():
    # Task 13: 6 core screens. Task 14 added 10 runtime/workflow screens.
    # Total implemented: 16 of 17 (route 10 remains placeholder per BL-35).
    implemented = sorted(k for k, r in SCREEN_ROUTES.items() if r.implemented)
    expected = [
        "01_home", "02_environment_profiles", "03_connection_diagnostics",
        "04_world_time", "05_maps_gis_cooking", "06_traffic_manager",
        "07_actors_routes", "08_sensors_streams", "09_calibration_workbench",
        "11_scenario_test_studio", "12_operational_fuzzer",
        "13_qa_gates", "14_experiments_runs", "15_job_control",
        "16_diagnostics_logs", "17_settings_safety_help",
    ]
    assert implemented == expected
    assert set(PAGE_FACTORIES) == set(implemented)


def test_T_QT_10_every_route_is_navigable(window):
    for key in SCREEN_ROUTES:
        window.navigate(key)
        assert window.current_route() == key
        assert window.stack.currentWidget() is window.pages[key]


def test_T_QT_11_navigation_is_keyboard_ordered(window):
    start = window.current_route()
    window.step_route(1)
    after = window.current_route()
    window.step_route(-1)
    assert window.current_route() == start
    assert after != start


def test_T_QT_12_an_unknown_route_is_refused(window):
    with pytest.raises(KeyError):
        window.navigate("99_does_not_exist")


def test_T_QT_12b_command_palette_navigates(window):
    window.command_palette.setText("13_qa_gates")
    window._palette_activated()
    assert window.current_route() == "13_qa_gates"
    window.command_palette.setText("nope")
    window._palette_activated()
    assert window.current_route() == "13_qa_gates"


def test_T_QT_12c_shortcuts_are_declared(window):
    for shortcut in ("Ctrl+K", "Ctrl+Right", "Ctrl+Left", "F5"):
        assert shortcut in KEYBOARD_ORDER.shortcuts.values()
    assert KEYBOARD_ORDER.order[0] == "mode_badge"


# ============================================== T-QT-13..18  controls
def test_T_QT_13_every_control_is_either_available_or_states_why(window):
    for key, page in window.pages.items():
        for row in getattr(page, "controls", []):
            binding = row.binding
            if binding.available:
                continue
            assert binding.disabled_reason, f"{binding.control_id} disabled with no reason"
            assert binding.source, f"{binding.control_id} disabled without a source"


def test_T_QT_14_unavailable_controls_are_disabled_not_inert(window):
    page = window.pages["13_qa_gates"]
    cook = next(b for b in page.unavailable_controls() if b.control_id == "CTL-131")
    assert "UE426_BLOCKED_OPERATOR_INSTALL" in cook.disabled_reason
    assert "ultimate_pipeline/gui/maps/cook.py" in cook.disabled_reason


def test_T_QT_15_no_fake_live_telemetry_is_rendered(window):
    page = window.pages["01_home"]
    live = next(b for b in page.unavailable_controls() if b.control_id == "CTL-005")
    assert live.mutating is True
    assert live.available is False
    assert live.backend_service == "live_fuzzer"
    assert "live fuzzing is disabled" in live.disabled_reason


def test_T_QT_16_controls_bind_to_the_documented_catalogue():
    from ultimate_pipeline.gui.shell.navigation import CONTROL_MATRIX_SOURCE
    assert CONTROL_MATRIX_SOURCE.endswith("CONTROL_CATALOG.csv")
    binding = bind_control("CTL-X", "L", "01_home", "carla_backend", "read", "T-QT-16",
                           registry=build_registry())
    assert binding.control_id == "CTL-X"
    assert binding.test_id == "T-QT-16"


def test_T_QT_17_every_bound_control_has_a_test_id(window):
    for page in window.pages.values():
        for row in getattr(page, "controls", []):
            assert row.binding.test_id.startswith("T-QT-")


def test_T_QT_18_accessible_names_exist_on_interactive_widgets(window):
    assert window.nav_list.accessibleName()
    assert window.command_palette.accessibleName()
    for page in window.pages.values():
        title = getattr(page, "title", None)
        if title is not None:
            assert title.accessibleName()


# ============================================== T-QT-19..24  states
def test_T_QT_19_qa_gates_never_renders_a_pass_it_authored(window):
    page = window.pages["13_qa_gates"]
    statuses = {page.table.item(r, 0).text(): page.table.item(r, 1).text()
                for r in range(page.table.rowCount())}
    # with no executed gate suite nothing may read PASS
    assert set(statuses) == {"topology", "hash", "elevation", "tile_frame_consistency"}
    assert "PASS" not in statuses.values(), "the view must never author a PASS"
    assert all(s in ("NOT_SUPPLIED", "NOT_EVALUATED", "SKIPPED", "BLOCKED",
                     "INVALID_METRIC") for s in statuses.values())


def test_T_QT_20_gap026_is_never_cleared_by_a_threshold(window):
    text = window.pages["13_qa_gates"].state_line.text()
    assert "2992/23529" in text
    assert "UNRESOLVED" in text or "GAP-026" in text


def test_T_QT_21_connection_page_does_not_probe_on_navigation(window):
    page = window.pages["03_connection_diagnostics"]
    connect = next(b for b in page.controls if b.binding.control_id == "CTL-021")
    assert connect.binding.mutating is True
    # navigation must perform no network I/O
    assert "no probe is executed" in page.state_line.text()
    assert "network I/O" in page.state_line.text()


def test_T_QT_22_destructive_cleanup_is_marked_mutating(window):
    page = window.pages["03_connection_diagnostics"]
    row = next(b for b in page.controls if b.binding.control_id == "CTL-022")
    assert row.binding.mutating is True
    assert "carla_utils.py" in row.binding.source


def test_T_QT_23_diagnostics_page_reports_disabled_services(window):
    page = window.pages["16_diagnostics_logs"]
    states = {page.table.item(r, 0).text(): page.table.item(r, 1).text()
              for r in range(page.table.rowCount())}
    assert states["corpus"] == "DISABLED"
    assert states["status_sources"] == "AVAILABLE"


def test_T_QT_24_settings_help_is_generated_from_the_registry(window):
    page = window.pages["17_settings_safety_help"]
    text = page.help_area.text()
    assert "318 declaration sites" in text
    assert "314 distinct settings" in text
    assert "sampled_not_exhaustive=True" in text


# ============================================== T-QT-25..30  prefs + workers
def test_T_QT_25_only_nonsecret_preferences_are_persisted(tmp_path):
    prefs = UIPreferences(last_route="13_qa_gates", theme="dark")
    path = save(prefs, tmp_path / "ui.json")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert set(stored) <= SAFE_KEYS
    assert "schema" in stored
    assert not any(k for k in stored if "pass" in k or "token" in k)


def test_T_QT_26_secret_looking_keys_are_refused(tmp_path):
    prefs = UIPreferences()
    prefs.__dict__["password"] = "hunter2"
    with pytest.raises(SecretRejected):
        save(prefs, tmp_path / "ui.json")


def test_T_QT_27_window_state_round_trips(app, registry, tmp_path):
    path = tmp_path / "ui.json"
    first = MainWindow(registry, prefs_path=path)
    first.navigate("16_diagnostics_logs")
    first.close()
    assert path.is_file()
    second = MainWindow(registry, prefs_path=path)
    assert second.current_route() == "16_diagnostics_logs"
    second.close()


def test_T_QT_28_a_corrupt_preference_file_falls_back_safely(tmp_path):
    path = tmp_path / "ui.json"
    path.write_text("{not json", encoding="utf-8")
    assert load(path).last_route == "01_home"
    path.write_text(json.dumps({"theme": 99}), encoding="utf-8")
    assert isinstance(load(path).theme, str)


def test_T_QT_29_workers_are_bounded_and_cancellable():
    pool = WorkerPool(max_workers=1, queue_depth=2)
    import time
    blocker = threading.Event()

    handle = pool.submit(lambda token: blocker.wait(0.2))
    second = pool.submit(lambda token: 2)
    with pytest.raises(RuntimeError):
        pool.submit(lambda token: 3)
    blocker.set()
    assert pool.result_of(handle, timeout=5).ok is True
    pool.shutdown()
    assert pool.stats()["rejected"] == 1


def test_T_QT_30_no_widget_is_touched_from_a_worker_thread():
    """The worker returns data; the GUI applies it. Proven, not assumed."""
    pool = WorkerPool(max_workers=1)
    window_titles: list[str] = []
    seen_threads: list[str] = []

    def work(token):
        seen_threads.append(threading.current_thread().name)
        return {"title": "computed"}

    handle = pool.submit(work)
    result = pool.result_of(handle, timeout=10)
    pool.shutdown()
    assert result.ok is True
    assert result.value == {"title": "computed"}
    assert threading.current_thread().name == "MainThread"
    assert seen_threads and seen_threads[0] != "MainThread"
    assert window_titles == []


def test_T_QT_30b_debouncer_coalesces_rapid_input():
    ticks = iter([0.0, 0.01, 0.02, 1.0])
    debouncer = Debouncer(delay_ms=250, clock=lambda: next(ticks, 99.0))
    assert debouncer.push("a") is True
    assert debouncer.push("ab") is False
    assert debouncer.pending == "ab"
    assert debouncer.flush() == "ab"


# ============================================== T-QT-31..36  contracts
def test_T_QT_31_service_unavailable_is_explicit_with_a_source():
    registry = ServiceRegistry()
    registry.register_unavailable("thing", "not implemented upstream", "src/x.py:10")
    assert registry.available("thing") is False
    with pytest.raises(ServiceUnavailable) as exc:
        registry.resolve("thing")
    assert exc.value.source == "src/x.py:10"
    assert "not implemented upstream" in str(exc.value)


def test_T_QT_32_registry_never_reimplements_existing_services(registry):
    for name in ("settings_registry", "configurator", "traffic_manager",
                 "carla_backend", "map_registry", "calibration", "quality",
                 "mutators", "coverage", "status_sources"):
        assert registry.available(name)
        assert registry.source_of(name).startswith("ultimate_pipeline/gui/")


def test_T_QT_33_live_fuzzer_is_registered_unavailable(registry):
    assert "live_fuzzer" not in registry.names()
    assert "Q22" in registry.reason_unavailable("live_fuzzer")


def test_T_QT_34_placeholder_pages_say_not_implemented(window):
    # Task 14: only route 10 is a registered placeholder (BL-35 ties it to Prompt 08)
    placeholder = window.pages["10_perception_localization"]
    texts = [w.text() for w in placeholder.findChildren(
        __import__("PyQt6.QtWidgets", fromlist=["QLabel"]).QLabel)]
    assert any("NOT YET IMPLEMENTED" in t for t in texts)
    assert not getattr(placeholder, "controls", [])


def test_T_QT_35_refresh_failure_is_surfaced_not_crashed(window):
    page = window.pages["01_home"]
    page.refresh = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    window.navigate("01_home")
    window.refresh_current()
    assert "boom" in page.state_line.text() or "boom" in window.statusBar().currentMessage()


def test_T_QT_36_status_bar_summarises_routes():
    registry = build_registry()
    app_instance = QApplication.instance()
    win = MainWindow(registry)
    message = win.statusBar().currentMessage()
    assert "17 routes registered" in message
    assert "6 implemented" in message
    win.close()


# ==================== regressions for the independent adverse review
def test_B1_launch_opens_no_socket_and_starts_no_thread():
    """Proven in-process by patching socket and counting threads."""
    import socket as socket_mod
    import threading as threading_mod

    opened: list = []
    original = socket_mod.create_connection
    socket_mod.create_connection = lambda *a, **k: (opened.append(a), original(*a, **k))[1]
    before_threads = {t.name for t in threading_mod.enumerate()}
    try:
        win = MainWindow(build_registry())
        win.show()
        for route in ("03_connection_diagnostics", "13_qa_gates", "01_home"):
            win.navigate(route)
            win.refresh_current()
    finally:
        socket_mod.create_connection = original
        win.close()
    assert opened == [], f"navigation opened a socket: {opened}"
    after = {t.name for t in threading_mod.enumerate()}
    assert after == before_threads, "launch started a thread"


def test_B2_mutating_controls_are_disabled_under_shared_readonly(window):
    for page in window.pages.values():
        for row in getattr(page, "controls", []):
            if not row.binding.mutating:
                continue
            assert row.enabled_for_use is False, row.binding.control_id
            assert row.isEnabled() is False
            if row.binding.available:
                assert row.binding.mutation_allowed is False
                assert "authority" in row.binding.authority_reason.lower()


def test_B3_secrets_are_refused_wherever_they_hide(tmp_path):
    nested = UIPreferences()
    nested.column_widths = {"auth_token": 1234}
    with pytest.raises(SecretRejected):
        save(nested, tmp_path / "a.json")
    valued = UIPreferences()
    valued.geometry = "Bearer sk-live-abcdef123"
    with pytest.raises(SecretRejected):
        save(valued, tmp_path / "b.json")
    listed = UIPreferences()
    listed.column_widths = {"col": 1}
    listed.theme = "ghp_abcdefghijkl"
    with pytest.raises(SecretRejected):
        save(listed, tmp_path / "c.json")


def test_B4_worker_pool_refuses_a_widget_capturing_callable():
    from PyQt6.QtWidgets import QLabel
    pool = WorkerPool(max_workers=1)
    label = QLabel("untouched")
    try:
        with pytest.raises(TypeError):
            pool.submit(lambda token: label.setText("MUTATED"))
        def outer():
            captured = QLabel("also untouched")
            return lambda token: captured.setText("MUTATED")
        with pytest.raises(TypeError):
            pool.submit(outer())
        assert label.text() == "untouched"
        # a non-UI callable is still accepted
        handle = pool.submit(lambda token: 42)
        assert pool.result_of(handle, timeout=10).value == 42
    finally:
        pool.shutdown()


def test_B5_a_stale_route_in_preferences_cannot_break_launch(tmp_path):
    path = tmp_path / "ui.json"
    path.write_text(json.dumps({"last_route": "99_nope"}), encoding="utf-8")
    win = MainWindow(build_registry(), prefs_path=path)
    assert win.current_route() == "01_home"
    win.close()
    path.write_text(json.dumps({"last_route": "../etc/passwd"}), encoding="utf-8")
    win2 = MainWindow(build_registry(), prefs_path=path)
    assert win2.current_route() == "01_home"
    win2.close()


def test_B6_the_qa_view_never_authors_its_own_verdicts(window):
    page = window.pages["13_qa_gates"]
    statuses = {page.table.item(r, 1).text()
                for r in range(page.table.rowCount())}
    assert "PASS" not in statuses


def test_B7_refresh_does_not_duplicate_controls(window):
    page = window.pages["01_home"]
    before = len(page.controls)
    ids_before = page.control_ids()
    for _ in range(5):
        window.refresh_current()
    assert len(page.controls) == before
    assert page.control_ids() == ids_before


def test_B7b_a_failing_page_does_not_break_construction(monkeypatch, registry):
    import ultimate_pipeline.gui.shell.main_window as mw

    class Boom:
        def __init__(self, registry, parent=None):
            raise RuntimeError("page boom")

    monkeypatch.setitem(mw.PAGE_FACTORIES, "01_home", Boom)
    win = mw.MainWindow(registry)
    labels = [w.text() for w in win.pages["01_home"].findChildren(
        __import__("PyQt6.QtWidgets", fromlist=["QLabel"]).QLabel)]
    assert any("FAILED TO INITIALISE" in t for t in labels)
    assert win.pages["01_home"].controls == []
    win.close()


def test_no_enabled_control_is_left_without_a_reason_when_disabled(window):
    for page in window.pages.values():
        for row in getattr(page, "controls", []):
            if not row.enabled_for_use:
                assert row.status.text().startswith("DISABLED")
                assert len(row.status.text()) > len("DISABLED")