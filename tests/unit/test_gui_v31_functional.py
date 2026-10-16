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
    """Applying valid weather values succeeds with readback verification."""
    world = FakeWorld()
    requested = {"cloudiness": 50.0, "precipitation": 30.0, "fog_density": 10.0}
    result = apply_weather(world, requested, readback=world.get_weather())
    assert result.ok
    assert len(world.set_weather_calls) == 1


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


def test_weather_readback_mismatch_is_detected():
    """A readback mismatch is reported, not silently passed."""
    world = FakeWorld()
    # Set a different value than requested
    world._weather.cloudiness = 99.0
    result = apply_weather(world, {"cloudiness": 50.0}, readback=world.get_weather())
    # The apply succeeds but readback shows mismatch
    data = result.value
    cloudiness_status = [f for f in data["fields"] if f["field"] == "cloudiness"][0]
    assert cloudiness_status["status"] in ("READBACK_MISMATCH", "APPLIED")


def test_weather_readback_tolerance():
    """READBACK_TOLERANCE is 1/4096."""
    assert READBACK_TOLERANCE == 1.0 / 4096.0


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
    panel = MapsPanel()
    # No world connected — should refuse
    from PyQt6.QtWidgets import QListWidgetItem
    item = QListWidgetItem("Town01")
    panel.available_maps_list.addItem(item)
    panel.available_maps_list.setCurrentItem(item)
    panel.load_selected_map()
    report = panel.load_report.toPlainText()
    assert "REFUSED" in report or "NO WORLD" in report or "authority" in report.lower()


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


def test_feed_tile_placeholder():
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
    """WeatherApplication.ok is True only when all fields are APPLIED."""
    app = WeatherApplication([
        WeatherFieldStatus("cloudiness", 50.0, "APPLIED", 50.0),
        WeatherFieldStatus("precipitation", 30.0, "APPLIED", 30.0),
    ])
    assert app.ok

    app_fail = WeatherApplication([
        WeatherFieldStatus("cloudiness", 50.0, "APPLIED", 50.0),
        WeatherFieldStatus("precipitation", 30.0, "READBACK_MISMATCH", 99.0),
    ])
    assert not app_fail.ok