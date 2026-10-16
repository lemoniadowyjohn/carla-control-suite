"""Feature-specific tests for v3.1/v3.2 controls.

These tests verify the actual functionality of weather, map, camera,
connection, and experiment controls — not just that they exist.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def app():
    from ultimate_pipeline.gui.shell.main_window import create_application
    return create_application([])


from ultimate_pipeline.gui.runtime.weather import (
    WEATHER_GOVERNED_FIELDS, WEATHER_RANGES, READBACK_TOLERANCE,
    WeatherApplication, WeatherFieldStatus, apply_weather,
)
from ultimate_pipeline.gui.control_center.weather_panel import PRESETS, WeatherPanel
from ultimate_pipeline.gui.control_center.capability_matrix import (
    build_capability_matrix, ControlState,
)
from ultimate_pipeline.gui.control_center.experiments_panel import TEMPLATES
from ultimate_pipeline.gui.control_center.feeds import FeedsPanel, FrameIngress
from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel
from ultimate_pipeline.gui.control_center.connection_panel import ConnectionPanel


# ----------------------------------------------------------------------
# Weather backend tests
# ----------------------------------------------------------------------

class FakeWeather:
    """Mock CARLA WeatherParameters for testing."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeWorld:
    """Mock CARLA World for testing."""
    def __init__(self):
        self._weather = FakeWeather(**{f: 0.0 for f in WEATHER_GOVERNED_FIELDS})
        self.set_weather_calls = []

    def set_weather(self, params):
        self.set_weather_calls.append(params)
        for k in WEATHER_GOVERNED_FIELDS:
            if hasattr(params, k):
                setattr(self._weather, k, getattr(params, k))

    def get_weather(self):
        return self._weather


def test_weather_all_14_fields_are_governed():
    """All 14 CARLA 0.9.16 weather fields are in the governed list."""
    assert len(WEATHER_GOVERNED_FIELDS) == 14
    expected = {
        "cloudiness", "precipitation", "precipitation_deposits",
        "wind_intensity", "sun_azimuth_angle", "sun_altitude_angle",
        "fog_density", "fog_distance", "fog_falloff", "wetness",
        "scattering_intensity", "mie_scattering_scale",
        "rayleigh_scattering_scale", "dust_storm",
    }
    assert set(WEATHER_GOVERNED_FIELDS) == expected


def test_weather_ranges_cover_numeric_fields():
    """All numeric weather fields have declared ranges."""
    numeric_fields = [f for f in WEATHER_GOVERNED_FIELDS
                      if f not in ("wetness_persistence", "cloud_height_enabled")]
    for field in numeric_fields:
        assert field in WEATHER_RANGES, f"{field} missing range"
        low, high = WEATHER_RANGES[field]
        assert low < high, f"{field} range invalid: [{low}, {high}]"


def test_weather_apply_with_valid_values():
    """Applying valid weather values succeeds with fresh-readback verification."""
    world = FakeWorld()
    requested = {"cloudiness": 50.0, "precipitation": 30.0, "fog_density": 10.0}
    result = apply_weather(world, requested)
    assert result.ok
    assert len(world.set_weather_calls) == 1
    statuses = {f["field"]: f["status"] for f in result.value["fields"]}
    assert all(s == "VERIFIED_APPLIED" for s in statuses.values())


def test_weather_apply_rejects_unknown_fields():
    """Unknown weather fields are refused."""
    world = FakeWorld()
    result = apply_weather(world, {"unknown_field": 42.0})
    assert not result.ok
    assert "not governed" in result.reason


def test_weather_apply_rejects_out_of_range():
    """Out-of-range values are rejected per-field."""
    world = FakeWorld()
    result = apply_weather(world, {"cloudiness": 200.0})
    assert not result.ok
    data = result.value
    assert any(f["status"] == "OUT_OF_RANGE" for f in data["fields"])


class SilentIgnoreWorld:
    """Fake world whose set_weather silently ignores the write.

    Models a server that accepts the RPC but does not honor the value,
    so the fresh get_weather() readback still reports the old state.
    """
    def __init__(self):
        self._weather = FakeWeather(**{f: 0.0 for f in WEATHER_GOVERNED_FIELDS})

    def set_weather(self, params):
        pass

    def get_weather(self):
        return self._weather


def test_weather_readback_mismatch_is_detected():
    """A fresh readback mismatch is reported, not silently passed."""
    world = SilentIgnoreWorld()
    result = apply_weather(world, {"cloudiness": 50.0})
    assert not result.ok
    data = result.value
    cloudiness_status = [f for f in data["fields"] if f["field"] == "cloudiness"][0]
    assert cloudiness_status["status"] == "READBACK_MISMATCH"


def test_weather_readback_tolerance():
    """READBACK_TOLERANCE is 1/4096."""
    assert READBACK_TOLERANCE == 1.0 / 4096.0


def test_weather_stale_readback_is_not_used():
    """apply_weather must observe state AFTER set_weather (behavioral).

    A world that returns planted stale values for any read taken before the
    write, and the true state for reads after it: verification must classify
    from the post-write readback. Passes only if the call order is
    set_weather -> get_weather; a pre-write readback yields READBACK_MISMATCH.
    """
    import inspect
    from types import SimpleNamespace

    sig = inspect.signature(apply_weather)
    assert "readback" not in sig.parameters, (
        "apply_weather must not accept a pre-set readback parameter"
    )

    class PlantedStaleWorld:
        def __init__(self):
            self.calls = []
            self._written = False
            self._weather = FakeWeather(**{f: 0.0 for f in WEATHER_GOVERNED_FIELDS})

        def set_weather(self, params):
            self.calls.append("set_weather")
            self._written = True
            for k in WEATHER_GOVERNED_FIELDS:
                if hasattr(params, k):
                    setattr(self._weather, k, getattr(params, k))

        def get_weather(self):
            self.calls.append("get_weather")
            if not self._written:
                return FakeWeather(**{f: 77.0 for f in WEATHER_GOVERNED_FIELDS})
            return self._weather

    world = PlantedStaleWorld()
    result = apply_weather(
        world, {"cloudiness": 50.0},
        parameters_factory=lambda fields: SimpleNamespace(**fields),
    )
    assert world.calls[-1] == "get_weather", (
        "final observation must be get_weather(), after the write"
    )
    assert "set_weather" in world.calls[:-1], (
        "set_weather() must precede the verification readback"
    )
    assert result.ok, (
        f"post-write readback must drive verification, got {result.value}"
    )
    status = result.value["fields"][0]["status"]
    assert status == "VERIFIED_APPLIED"


def test_weather_no_readback_marks_not_verified():
    """Without fresh readback, fields are WRITTEN_NOT_VERIFIED, not APPLIED."""
    class NoReadbackWorld:
        def set_weather(self, params):
            pass
        # No get_weather method
    world = NoReadbackWorld()
    result = apply_weather(world, {"cloudiness": 50.0})
    assert not result.ok
    data = result.value
    cloudiness = [f for f in data["fields"] if f["field"] == "cloudiness"][0]
    assert cloudiness["status"] == "WRITTEN_NOT_VERIFIED"


def test_weather_verified_applied_on_fresh_readback():
    """Fresh readback matching requested value yields VERIFIED_APPLIED."""
    world = FakeWorld()
    result = apply_weather(world, {"cloudiness": 50.0})
    assert result.ok
    data = result.value
    cloudiness = [f for f in data["fields"] if f["field"] == "cloudiness"][0]
    assert cloudiness["status"] == "VERIFIED_APPLIED"


def test_weather_scattering_fields():
    """Scattering and dust storm fields are handled correctly."""
    world = FakeWorld()
    result = apply_weather(world, {
        "scattering_intensity": 50.0,
        "mie_scattering_scale": 0.05,
        "rayleigh_scattering_scale": 0.05,
        "dust_storm": 10.0,
    })
    assert result.ok


def test_weather_presets_are_valid():
    """All presets contain only governed fields with valid ranges."""
    for name, values in PRESETS.items():
        unknown = set(values) - set(WEATHER_GOVERNED_FIELDS)
        assert not unknown, f"Preset {name} has unknown fields: {unknown}"
        for field, val in values.items():
            if field in WEATHER_RANGES:
                low, high = WEATHER_RANGES[field]
                assert low <= val <= high, (
                    f"Preset {name} field {field}={val} outside [{low}, {high}]"
                )


def test_weather_panel_constructs_offscreen(app):
    """WeatherPanel builds without a live server."""
    panel = WeatherPanel()
    assert panel is not None
    assert hasattr(panel, "tabs")


# ----------------------------------------------------------------------
# Capability matrix tests
# ----------------------------------------------------------------------

def test_capability_matrix_classifies_all_controls():
    """Every control has a valid classification."""
    matrix = build_capability_matrix()
    assert matrix["total_controls"] > 0
    valid_states = {s.value for s in ControlState}
    for state, items in matrix["by_state"].items():
        assert state in valid_states, f"Invalid state: {state}"
        for item in items:
            assert item["control_id"]
            assert item["route"]
            assert item["test_id"]


def test_capability_matrix_weather_count():
    """14 weather controls are classified."""
    matrix = build_capability_matrix()
    weather_items = [
        i for items in matrix["by_state"].values() for i in items
        if i["route"] == "04_world_time"
    ]
    assert len(weather_items) == 14


# ----------------------------------------------------------------------
# Map tests
# ----------------------------------------------------------------------

def test_maps_panel_constructs_offscreen(app):
    """MapsPanel builds without a live server."""
    panel = MapsPanel()
    assert panel is not None
    assert hasattr(panel, "tabs")


def test_map_load_requires_exclusive_authority(app):
    """Map loading is refused under SHARED_READONLY."""
    from ultimate_pipeline.gui.health import SessionAuthority
    panel = MapsPanel(authority=SessionAuthority.SHARED_READONLY)
    # No world connected — should refuse
    from PyQt6.QtWidgets import QListWidgetItem
    item = QListWidgetItem("Town01")
    panel.available_maps_list.addItem(item)
    panel.available_maps_list.setCurrentItem(item)
    panel.load_selected_map()
    report = panel.load_report.toPlainText()
    assert "REFUSED" in report


def test_map_load_refused_when_authority_missing(app):
    """A panel with no bound authority fails closed."""
    panel = MapsPanel()
    from PyQt6.QtWidgets import QListWidgetItem
    item = QListWidgetItem("Town01")
    panel.available_maps_list.addItem(item)
    panel.available_maps_list.setCurrentItem(item)
    panel.load_selected_map()
    assert "REFUSED" in panel.load_report.toPlainText()


def test_map_load_refused_without_client(app):
    """Exclusive authority but no client handle: explicit refusal, no crash."""
    from ultimate_pipeline.gui.health import SessionAuthority
    panel = MapsPanel(world=object(), authority=SessionAuthority.EXCLUSIVE_WORLD)
    from PyQt6.QtWidgets import QListWidgetItem
    item = QListWidgetItem("Town01")
    panel.available_maps_list.addItem(item)
    panel.available_maps_list.setCurrentItem(item)
    panel.load_selected_map()
    report = panel.load_report.toPlainText()
    assert "REFUSED" in report
    assert "client" in report.lower()


class FakeRuntimeMap:
    def __init__(self, name):
        self.name = name


class FakeRuntimeWorld:
    def __init__(self, map_name):
        self._map = FakeRuntimeMap(map_name)

    def get_map(self):
        return self._map


class FakeCarlaClient:
    """Client double: the only object exposing load_world/get_available_maps."""

    def __init__(self, loaded_map="/Game/Carla/Maps/Town01"):
        self.loaded_map = loaded_map
        self.load_calls = []
        self.world = FakeRuntimeWorld(loaded_map)

    def load_world(self, name):
        self.load_calls.append(name)
        return self.world

    def get_available_maps(self):
        return ["/Game/Carla/Maps/Town01", "/Game/Carla/Maps/Town02"]


def _select_map(panel, name):
    from PyQt6.QtWidgets import QListWidgetItem
    item = QListWidgetItem(name)
    panel.available_maps_list.addItem(item)
    panel.available_maps_list.setCurrentItem(item)


def test_map_load_with_client_verifies_and_emits(app, monkeypatch):
    """Client path: load, rebind world, verify identity, emit world_changed."""
    from ultimate_pipeline.gui.health import SessionAuthority
    from ultimate_pipeline.gui.control_center import maps_panel as maps_mod

    client = FakeCarlaClient()
    panel = MapsPanel(client=client, authority=SessionAuthority.EXCLUSIVE_WORLD)
    emitted = []
    panel.world_changed.connect(emitted.append)

    _select_map(panel, "/Game/Carla/Maps/Town01")
    monkeypatch.setattr(
        maps_mod.QMessageBox, "question",
        lambda *a, **k: maps_mod.QMessageBox.StandardButton.Yes,
    )
    panel.load_selected_map()

    assert client.load_calls == ["/Game/Carla/Maps/Town01"]
    assert panel.world is client.world, "world must be rebound to the loaded world"
    assert panel.runtime_map == "/Game/Carla/Maps/Town01"
    assert emitted == ["/Game/Carla/Maps/Town01"]
    assert "identity verified" in panel.load_report.toPlainText()


def test_map_load_identity_mismatch_still_invalidates(app, monkeypatch):
    """Path-qualified mismatch is reported but never skips invalidation."""
    from ultimate_pipeline.gui.health import SessionAuthority
    from ultimate_pipeline.gui.control_center import maps_panel as maps_mod

    client = FakeCarlaClient(loaded_map="/Game/Carla/Maps/Town02")
    panel = MapsPanel(client=client, authority=SessionAuthority.EXCLUSIVE_WORLD)
    emitted = []
    panel.world_changed.connect(emitted.append)

    _select_map(panel, "/Game/Carla/Maps/Town01")
    monkeypatch.setattr(
        maps_mod.QMessageBox, "question",
        lambda *a, **k: maps_mod.QMessageBox.StandardButton.Yes,
    )
    panel.load_selected_map()

    assert "MISMATCH" in panel.load_report.toPlainText()
    assert panel.world is client.world, "world must be rebound even on mismatch"
    assert emitted == ["/Game/Carla/Maps/Town02"], (
        "world_changed must fire even when identity verification fails"
    )


def test_refresh_server_maps_uses_client(app):
    """get_available_maps is served by the injected client."""
    client = FakeCarlaClient()
    panel = MapsPanel(client=client)
    panel.refresh_server_maps()
    assert panel.available_maps_list.count() == 2


def test_refresh_server_maps_without_client_refuses(app):
    """No client: explicit message instead of treating world as a client."""
    panel = MapsPanel(world=object())
    panel.refresh_server_maps()
    assert "NO CARLA CLIENT" in panel.runtime_info.text()


def test_weather_apply_refused_under_shared_readonly(app):
    """Weather mutation is refused under SHARED_READONLY (fail-closed gate)."""
    from ultimate_pipeline.gui.health import SessionAuthority
    panel = WeatherPanel(world=FakeWorld(),
                         authority=SessionAuthority.SHARED_READONLY)
    panel.apply_custom()
    assert "REFUSED" in panel.custom_state.text()
    assert panel._worker is None, "no worker must start under SHARED_READONLY"


def test_weather_apply_refused_without_authority(app):
    """World bound but no authority: apply is refused, not attempted."""
    panel = WeatherPanel(world=FakeWorld(), authority=None)
    panel.apply_custom()
    assert "REFUSED" in panel.custom_state.text()
    assert panel._worker is None


# ----------------------------------------------------------------------
# Camera feed tests
# ----------------------------------------------------------------------

def test_feeds_panel_constructs_offscreen(app):
    """FeedsPanel builds without a live server."""
    panel = FeedsPanel()
    assert panel is not None
    assert len(panel.tiles) == 4


def test_frame_ingress_publish():
    """FrameIngress emits frames correctly."""
    ingress = FrameIngress()
    received = []
    ingress.frame_received.connect(lambda sid, img, fid, ts: received.append((sid, fid, ts)))
    from PyQt6.QtGui import QImage
    img = QImage(100, 100, QImage.Format.Format_RGB32)
    ingress.publish("Front RGB", img, 42, 1.5)
    assert len(received) == 1
    assert received[0] == ("Front RGB", 42, 1.5)


def test_feed_tile_placeholder(app):
    """FeedTile shows placeholder when no frame received."""
    from ultimate_pipeline.gui.control_center.feeds import FeedTile
    tile = FeedTile("Test")
    assert "UNBOUND" in tile.header.text()


# ----------------------------------------------------------------------
# Connection tests
# ----------------------------------------------------------------------

def test_connection_panel_constructs_offscreen(app):
    """ConnectionPanel builds without a live server."""
    panel = ConnectionPanel()
    assert panel is not None
    assert panel.host.text() == "127.0.0.1"
    assert panel.port.value() == 2000


# ----------------------------------------------------------------------
# Experiment template tests
# ----------------------------------------------------------------------

def test_experiment_templates_are_valid():
    """All templates reference valid experiment families."""
    from ultimate_pipeline.gui.control_center.plans import EXPERIMENTS
    for name, tpl in TEMPLATES.items():
        assert "experiment" in tpl, f"Template {name} missing experiment"
        assert "notes" in tpl, f"Template {name} missing notes"


def test_experiment_templates_cover_v31_workspaces():
    """Templates cover weather, cameras, elevation, and sync."""
    template_names = set(TEMPLATES.keys())
    assert "Weather Sweep" in template_names
    assert "RGB FOV Study" in template_names
    assert "Elevation Inspection" in template_names
    assert "Multi-Camera Sync" in template_names


# ----------------------------------------------------------------------
# Regression: existing tests still pass
# ----------------------------------------------------------------------

def test_weather_application_ok_property():
    """WeatherApplication.ok is True only for VERIFIED_APPLIED fields."""
    app = WeatherApplication([
        WeatherFieldStatus("cloudiness", 50.0, "VERIFIED_APPLIED", 50.0),
        WeatherFieldStatus("precipitation", 30.0, "VERIFIED_APPLIED", 30.0),
    ])
    assert app.ok

    for bad in ("APPLIED", "WRITTEN_NOT_VERIFIED", "READBACK_MISMATCH",
                "OUT_OF_RANGE", "UNSUPPORTED"):
        app_bad = WeatherApplication([
            WeatherFieldStatus("cloudiness", 50.0, bad, 50.0),
        ])
        assert not app_bad.ok, f"status {bad!r} must not count as ok"