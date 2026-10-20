"""Stage B1 acceptance: shared runtime session and invalidation wiring.

Covers the RuntimeSession service itself (generation IDs, event structure,
reason validation, subscriber isolation) and its production wiring:
MapsPanel records every load outcome and adopts external invalidations,
WeatherPanel rebinds/drops its world, FeedsPanel drops frame caches, and
every route resolves the single session instance from the registry.

Offline: no CARLA server is contacted; worlds/clients are local doubles.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.gui.health import SessionAuthority
from ultimate_pipeline.gui.session.runtime_session import (
    BINDING_FAILURE,
    DISCONNECT,
    INITIAL,
    LOAD_FAILURE,
    MAP_LOAD,
    MAP_MISMATCH,
    REASONS,
    RuntimeSession,
    WorldChangedEvent,
)

# ------------------------------------------------------------------ doubles
class DummyWorld:
    def __init__(self, name="dummy"):
        self.name = name


class DummyClient:
    def __init__(self):
        self.load_calls = []

    def load_world(self, name):
        self.load_calls.append(name)
        return DummyWorld(name)


class RaisingClient:
    def load_world(self, name):
        raise RuntimeError("RPC timeout")

    def get_available_maps(self):
        return ["/Game/Carla/Maps/Town01"]


class FakeRuntimeMap:
    def __init__(self, name):
        self.name = name


class FakeRuntimeWorld:
    def __init__(self, map_name):
        self._map = FakeRuntimeMap(map_name)

    def get_map(self):
        return self._map


class FakeCarlaClient:
    def __init__(self, loaded_map="/Game/Carla/Maps/Town01"):
        self.loaded_map = loaded_map
        self.load_calls = []
        self.world = FakeRuntimeWorld(loaded_map)

    def load_world(self, name):
        self.load_calls.append(name)
        return self.world

    def get_available_maps(self):
        return ["/Game/Carla/Maps/Town01", "/Game/Carla/Maps/Town02"]


@pytest.fixture
def app():
    from ultimate_pipeline.gui.shell.main_window import create_application
    return create_application([])


def _select_map(panel, name):
    from PyQt6.QtWidgets import QListWidgetItem
    item = QListWidgetItem(name)
    panel.available_maps_list.addItem(item)
    panel.available_maps_list.setCurrentItem(item)


# ============================================================ service core
def test_initial_state_is_unbound_and_unpublished():
    session = RuntimeSession()
    assert session.generation == 0
    assert session.map_identity == "UNBOUND"
    assert session.has_world is False and session.has_client is False
    assert session.last_event is None
    assert session.authority is SessionAuthority.SHARED_READONLY
    assert session.snapshot()["last_event"] is None


def test_bind_world_publishes_generation_and_state():
    session = RuntimeSession()
    world, client = DummyWorld(), DummyClient()
    event = session.bind_world(world, map_identity="Town02",
                               reason=MAP_LOAD, source="test", client=client)
    assert isinstance(event, WorldChangedEvent)
    assert event.generation == 1
    assert event.reason == MAP_LOAD and event.source == "test"
    assert event.map_identity == "Town02"
    assert event.world_bound is True and event.client_bound is True
    assert session.world is world and session.client is client
    assert session.map_identity == "Town02"
    assert session.last_event == event


def test_generations_increase_monotonically():
    session = RuntimeSession()
    g1 = session.bind_world(DummyWorld(), map_identity="Town01",
                            reason=INITIAL, source="t").generation
    g2 = session.clear_binding(reason=LOAD_FAILURE, source="t",
                               map_identity="UNKNOWN").generation
    g3 = session.disconnect(source="t").generation
    assert (g1, g2, g3) == (1, 2, 3)
    assert session.generation == 3


def test_clear_binding_keeps_client_but_drops_world():
    session = RuntimeSession()
    session.bind_world(DummyWorld(), map_identity="Town01",
                       reason=MAP_LOAD, client="client-1")
    event = session.clear_binding(reason=LOAD_FAILURE, source="t",
                                  map_identity="UNKNOWN")
    assert event.world_bound is False
    assert session.world is None
    assert session.client == "client-1", "a failed load must not drop the client"
    assert session.map_identity == "UNKNOWN"
    assert event.client_bound is True


def test_disconnect_drops_client_world_and_identity():
    session = RuntimeSession()
    session.bind_world(DummyWorld(), map_identity="Town01",
                       reason=MAP_LOAD, client="client-1")
    event = session.disconnect(source="connection_panel")
    assert event.reason == DISCONNECT
    assert session.world is None and session.client is None
    assert session.map_identity == "UNBOUND"
    assert event.world_bound is False and event.client_bound is False


def test_binding_failure_convenience_publishes_unknown_identity():
    session = RuntimeSession()
    session.bind_world(DummyWorld(), map_identity="Town01",
                       reason=MAP_LOAD, client="client-1")
    event = session.binding_failure(source="maps_panel")
    assert event.reason == BINDING_FAILURE
    assert session.world is None
    assert session.map_identity == "UNKNOWN"
    assert session.client == "client-1"


def test_bind_world_rejects_none_world():
    session = RuntimeSession()
    with pytest.raises(ValueError):
        session.bind_world(None, map_identity="Town01", reason=MAP_LOAD)


def test_unknown_reason_rejected_on_both_paths():
    session = RuntimeSession()
    with pytest.raises(ValueError):
        session.bind_world(DummyWorld(), map_identity="Town01", reason="WHATEVER")
    with pytest.raises(ValueError):
        session.clear_binding(reason="WHATEVER", source="t")


def test_reason_boundness_is_enforced():
    session = RuntimeSession()
    with pytest.raises(ValueError):
        session.bind_world(DummyWorld(), map_identity="Town01", reason=DISCONNECT)
    with pytest.raises(ValueError):
        session.clear_binding(reason=MAP_LOAD, source="t")
    with pytest.raises(ValueError):
        session.clear_binding(reason=MAP_MISMATCH, source="t")


def test_map_identity_must_be_a_non_empty_string():
    session = RuntimeSession()
    with pytest.raises(ValueError):
        session.bind_world(DummyWorld(), map_identity="", reason=MAP_LOAD)
    with pytest.raises(ValueError):
        session.bind_world(DummyWorld(), map_identity=None, reason=MAP_LOAD)
    with pytest.raises(ValueError):
        session.clear_binding(reason=DISCONNECT, source="t", map_identity="  ")


def test_reason_set_is_exactly_the_documented_vocabulary():
    assert REASONS == frozenset({INITIAL, MAP_LOAD, MAP_MISMATCH,
                                 LOAD_FAILURE, BINDING_FAILURE, DISCONNECT})


# ------------------------------------------------------------ subscribers
def test_subscribers_receive_events_and_unsubscribe_stops_delivery():
    session = RuntimeSession()
    seen_a, seen_b = [], []
    unsub_a = session.subscribe(seen_a.append)
    session.subscribe(seen_b.append)
    session.bind_world(DummyWorld(), map_identity="Town01", reason=MAP_LOAD)
    assert [e.generation for e in seen_a] == [1]
    assert len(seen_b) == 1
    unsub_a()
    unsub_a()  # idempotent
    session.bind_world(DummyWorld(), map_identity="Town02", reason=MAP_LOAD)
    assert len(seen_a) == 1, "unsubscribed callback must not be called again"
    assert [e.generation for e in seen_b] == [1, 2]
    assert session.snapshot()["subscriber_count"] == 1


def test_subscribe_rejects_non_callable():
    session = RuntimeSession()
    with pytest.raises(TypeError):
        session.subscribe("not-callable")


def test_raising_subscriber_is_isolated_and_recorded():
    session = RuntimeSession()
    delivered = []

    def bad(event):
        raise RuntimeError("subscriber exploded")

    session.subscribe(bad)
    session.subscribe(delivered.append)
    # Publication itself must never raise because a subscriber did.
    event = session.bind_world(DummyWorld(), map_identity="Town01",
                               reason=MAP_LOAD, source="test")
    assert event.generation == 1
    assert session.last_event == event
    assert len(delivered) == 1, "later subscribers still receive the event"
    assert len(session.subscriber_errors) == 1
    assert "subscriber exploded" in session.subscriber_errors[0]
    assert session.snapshot()["subscriber_errors"]


def test_reentrant_subscriber_call_does_not_deadlock():
    session = RuntimeSession()
    captured = {}

    def reentrant(event):
        captured["snapshot"] = session.snapshot()
        captured["generation"] = session.generation

    session.subscribe(reentrant)
    session.bind_world(DummyWorld(), map_identity="Town01", reason=MAP_LOAD)
    assert captured["snapshot"]["generation"] == 1
    assert captured["generation"] == 1


def test_explicit_client_argument_replaces_and_none_clears():
    session = RuntimeSession()
    session.bind_world(DummyWorld(), map_identity="Town01",
                       reason=MAP_LOAD, client="c1")
    session.bind_world(DummyWorld(), map_identity="Town01", reason=MAP_LOAD)
    assert session.client == "c1", "omitted client keeps the previous handle"
    session.bind_world(DummyWorld(), map_identity="Town01",
                       reason=MAP_LOAD, client=None)
    assert session.client is None, "explicit None replaces (is not the keep sentinel)"


def test_snapshot_reports_identity_authority_and_counts():
    session = RuntimeSession()
    session.subscribe(lambda event: None)
    session.bind_world(DummyWorld(), map_identity="Town01",
                       reason=MAP_LOAD, client="c1", source="test")
    snap = session.snapshot()
    assert snap["generation"] == 1
    assert snap["map_identity"] == "Town01"
    assert snap["world_bound"] is True and snap["client_bound"] is True
    assert snap["authority"] == "SHARED_READONLY"
    assert snap["subscriber_count"] == 1
    assert snap["last_event"]["reason"] == MAP_LOAD


# =================================================== maps panel integration
def test_maps_panel_records_bind_into_session_and_emits(app):
    from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel

    session = RuntimeSession()
    panel = MapsPanel(world=DummyWorld(), runtime_session=session)
    emitted = []
    panel.world_changed.connect(emitted.append)
    panel.runtime_map = "Town02"

    panel._invalidate_stale_references("Town02", MAP_LOAD)

    assert emitted == ["Town02"]
    event = session.last_event
    assert event.reason == MAP_LOAD and event.generation == 1
    assert event.world_bound is True and event.source == "maps_panel"
    assert session.map_identity == "Town02"
    assert session.world is panel.world


def test_maps_panel_records_unbound_outcome_as_clear(app):
    from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel

    session = RuntimeSession()
    panel = MapsPanel(runtime_session=session)
    emitted = []
    panel.world_changed.connect(emitted.append)

    panel._invalidate_stale_references("UNKNOWN", LOAD_FAILURE)

    assert emitted == ["UNKNOWN"]
    event = session.last_event
    assert event.reason == LOAD_FAILURE and event.world_bound is False
    assert session.map_identity == "UNKNOWN"


def test_maps_panel_successful_load_binds_session(app, monkeypatch):
    from ultimate_pipeline.gui.control_center import maps_panel as maps_mod
    from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel

    session = RuntimeSession()
    client = FakeCarlaClient()
    panel = MapsPanel(client=client, authority=SessionAuthority.EXCLUSIVE_WORLD,
                      runtime_session=session)
    emitted = []
    panel.world_changed.connect(emitted.append)

    _select_map(panel, "/Game/Carla/Maps/Town01")
    monkeypatch.setattr(
        maps_mod.QMessageBox, "question",
        lambda *a, **k: maps_mod.QMessageBox.StandardButton.Yes,
    )
    panel.load_selected_map()

    assert emitted == ["/Game/Carla/Maps/Town01"]
    event = session.last_event
    assert event.reason == MAP_LOAD and event.generation == 1
    assert event.world_bound is True and event.client_bound is True
    assert session.world is client.world
    assert session.client is client
    assert session.map_identity == "/Game/Carla/Maps/Town01"


def test_maps_panel_failed_load_clears_session_and_panel_world(app, monkeypatch):
    from ultimate_pipeline.gui.control_center import maps_panel as maps_mod
    from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel

    session = RuntimeSession()
    panel = MapsPanel(client=RaisingClient(),
                      authority=SessionAuthority.EXCLUSIVE_WORLD,
                      runtime_session=session)
    emitted = []
    panel.world_changed.connect(emitted.append)

    _select_map(panel, "/Game/Carla/Maps/Town01")
    monkeypatch.setattr(
        maps_mod.QMessageBox, "question",
        lambda *a, **k: maps_mod.QMessageBox.StandardButton.Yes,
    )
    panel.load_selected_map()

    assert emitted == ["UNKNOWN"]
    assert panel.world is None, "failed attempt must not retain a stale world"
    assert panel.runtime_map == "UNKNOWN"
    event = session.last_event
    assert event.reason == LOAD_FAILURE and event.world_bound is False
    assert session.map_identity == "UNKNOWN"
    assert session.world is None


def test_maps_panel_mismatch_records_bound_mismatch(app, monkeypatch):
    from ultimate_pipeline.gui.control_center import maps_panel as maps_mod
    from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel

    session = RuntimeSession()
    client = FakeCarlaClient(loaded_map="/Game/Carla/Maps/Town02")
    panel = MapsPanel(client=client, authority=SessionAuthority.EXCLUSIVE_WORLD,
                      runtime_session=session)

    _select_map(panel, "/Game/Carla/Maps/Town01")
    monkeypatch.setattr(
        maps_mod.QMessageBox, "question",
        lambda *a, **k: maps_mod.QMessageBox.StandardButton.Yes,
    )
    panel.load_selected_map()

    event = session.last_event
    assert event.reason == MAP_MISMATCH and event.world_bound is True
    assert session.map_identity == "/Game/Carla/Maps/Town02"


def test_maps_panel_adopts_external_disconnect(app):
    from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel

    session = RuntimeSession()
    world, client = DummyWorld(), DummyClient()
    panel = MapsPanel(world=world, client=client, runtime_session=session)
    panel.runtime_map = "Town01"

    session.disconnect(source="connection_panel")

    assert panel.world is None, "external disconnect must drop the local world"
    assert panel.client is None
    assert panel.runtime_map == "UNBOUND"
    assert "UNBOUND" in panel.runtime_info.text()


def test_maps_panel_ignores_its_own_events(app):
    from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel

    session = RuntimeSession()
    world = DummyWorld()
    panel = MapsPanel(world=world, runtime_session=session)
    emitted = []
    panel.world_changed.connect(emitted.append)

    panel._invalidate_stale_references("Town01", MAP_LOAD)

    # The subscriber ran but adopted identical state (source == maps_panel
    # is skipped): the panel keeps its own references and does not clobber.
    assert panel.world is world
    assert emitted == ["Town01"]
    assert session.generation == 1


def test_maps_panel_resolve_client_prefers_session_client(app):
    from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel

    session = RuntimeSession()
    session_local_client = DummyClient()
    panel = MapsPanel(client=None, runtime_session=session)
    assert panel._resolve_client() is None

    session.bind_world(DummyWorld(), map_identity="Town01",
                       reason=MAP_LOAD, client=session_local_client)
    assert panel._resolve_client() is session_local_client


# =================================================== weather panel wiring
def test_weather_panel_rebinds_and_drops_world_on_events(app):
    from ultimate_pipeline.gui.control_center.weather_panel import WeatherPanel

    session = RuntimeSession()
    old_world = DummyWorld("old")
    panel = WeatherPanel(world=old_world, runtime_session=session)
    emitted_bound = []
    session.subscribe(lambda e: emitted_bound.append(e.world_bound))

    new_world = DummyWorld("new")
    session.bind_world(new_world, map_identity="Town02", reason=MAP_LOAD)
    assert panel.world is new_world, "map load must rebind the weather world"
    assert "WORLD BOUND" in panel.current_state.text()

    session.disconnect(source="connection_panel")
    assert panel.world is None, "disconnect must drop the weather world"
    assert "WORLD UNBOUND" in panel.current_state.text()
    assert emitted_bound == [True, False]


# ====================================================== feeds panel wiring
def test_feeds_panel_invalidates_frame_cache_on_event(app):
    from ultimate_pipeline.gui.control_center.feeds import FeedsPanel

    session = RuntimeSession()
    panel = FeedsPanel(runtime_session=session)
    panel._files = [Path("frame_001.png")]
    panel._frame_index = 7
    panel._timer.start()
    assert panel._timer.isActive()

    session.bind_world(DummyWorld(), map_identity="Town01", reason=MAP_LOAD)

    assert panel._files == [], "frame cache must be dropped"
    assert panel._frame_index == 0
    assert not panel._timer.isActive(), "playback timer must stop"
    assert "frame caches invalidated" in panel.state.text()
    assert panel.tiles["Front RGB"].caption.text() == "No camera callback received"


def test_feeds_panel_survives_construction_without_session(app):
    from ultimate_pipeline.gui.control_center.feeds import FeedsPanel

    panel = FeedsPanel()
    panel._files = [Path("keep.png")]
    session = RuntimeSession()
    session.bind_world(DummyWorld(), map_identity="Town01", reason=MAP_LOAD)
    assert panel._files, "a panel without a session is not wired to events"


# ======================================================== registry & shell
def test_build_registry_registers_one_runtime_session():
    from ultimate_pipeline.gui.shell.services import build_registry

    registry = build_registry()
    assert registry.available("runtime_session")
    session = registry.resolve("runtime_session")
    assert isinstance(session, RuntimeSession)
    assert registry.source_of("runtime_session") == \
        "ultimate_pipeline/gui/session/runtime_session.py"


def test_every_wired_route_resolves_the_same_session_instance(app):
    from ultimate_pipeline.gui.control_center.workspaces import (
        create_operator_workspace,
    )
    from ultimate_pipeline.gui.shell.services import build_registry

    registry = build_registry()
    shared = registry.resolve("runtime_session")
    navigate = lambda route: None  # noqa: E731

    weather = create_operator_workspace("04_world_time", registry, navigate)
    assert weather.runtime_session is shared

    maps_tab = create_operator_workspace("05_maps_gis_cooking", registry, navigate)
    assert maps_tab.widget(0).runtime_session is shared

    feeds_tab = create_operator_workspace("08_sensors_streams", registry, navigate)
    assert feeds_tab.widget(0).runtime_session is shared

    # Unwired routes still work and do not create duplicate sessions.
    create_operator_workspace("01_home", registry, navigate)
    assert registry.available("runtime_session")
    assert registry.resolve("runtime_session") is shared


def test_event_after_widget_deletion_is_isolated(app):
    """A dead-widget subscriber must not kill publication (no destroyed-hook).

    Panels deliberately do NOT hook QObject.destroyed -- running Python
    during the C++ destructor cascade can fail fast (observed as exit
    0xC0000409 when a MainWindow was garbage-collected). Instead
    RuntimeSession isolates the RuntimeError raised by calls into the
    deleted widget and records it in subscriber_errors.
    """
    from ultimate_pipeline.gui.control_center.weather_panel import WeatherPanel
    from PyQt6.QtCore import QCoreApplication, QEvent

    session = RuntimeSession()
    panel = WeatherPanel(runtime_session=session)
    assert session.snapshot()["subscriber_count"] == 1

    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, int(QEvent.Type.DeferredDelete))
    QCoreApplication.processEvents()

    # The widget is gone; publication must still succeed ...
    event = session.bind_world(DummyWorld(), map_identity="Town01",
                               reason=MAP_LOAD, source="test")
    assert event.generation == 1
    assert session.generation == 1
    # ... and the dead-widget call must be recorded, not raised.
    assert session.subscriber_errors, "call into deleted widget must be isolated"
    assert "RuntimeError" in session.subscriber_errors[0]


def test_service_recorded_events_flow_to_all_wired_panels(app):
    """One publication reaches weather, feeds and maps subscribers."""
    from ultimate_pipeline.gui.control_center.workspaces import (
        create_operator_workspace,
    )
    from ultimate_pipeline.gui.shell.services import build_registry

    registry = build_registry()
    session = registry.resolve("runtime_session")
    navigate = lambda route: None  # noqa: E731

    weather = create_operator_workspace("04_world_time", registry, navigate)
    feeds_tab = create_operator_workspace("08_sensors_streams", registry, navigate)
    feeds = feeds_tab.widget(0)

    session.bind_world(DummyWorld(), map_identity="Town01", reason=MAP_LOAD)

    assert "WORLD BOUND" in weather.current_state.text()
    assert "frame caches invalidated" in feeds.state.text()
    assert session.generation == 1
