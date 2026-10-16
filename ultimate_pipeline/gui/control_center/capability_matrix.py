"""Capability matrix for v3.2 live integration audit.

Classifies every control by its real operational state:
- OFFLINE_FUNCTIONAL: Works without a simulator
- LIVE_READ_ONLY_VERIFIED: Verified against a live server (read-only)
- LIVE_MUTATION_VERIFIED: Verified against a live server (mutation)
- CONFIGURATION_ONLY: Stages values but cannot apply
- UNSUPPORTED: No backend capability exists
- BLOCKED: Requires external gate (G5-G8, Q22, etc.)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ControlState(str, Enum):
    OFFLINE_FUNCTIONAL = "OFFLINE_FUNCTIONAL"
    LIVE_READ_ONLY_VERIFIED = "LIVE_READ_ONLY_VERIFIED"
    LIVE_MUTATION_VERIFIED = "LIVE_MUTATION_VERIFIED"
    CONFIGURATION_ONLY = "CONFIGURATION_ONLY"
    UNSUPPORTED = "UNSUPPORTED"
    BLOCKED = "BLOCKED"


@dataclass
class ControlClassification:
    control_id: str
    route: str
    state: ControlState
    backend_contract: str
    widget: str
    runtime_method: str
    test_id: str
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "control_id": self.control_id,
            "route": self.route,
            "state": self.state.value,
            "backend_contract": self.backend_contract,
            "widget": self.widget,
            "runtime_method": self.runtime_method,
            "test_id": self.test_id,
            "notes": self.notes,
        }


# Weather controls (14 CARLA 0.9.16 fields)
WEATHER_CONTROLS = [
    ControlClassification("cloudiness", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-01"),
    ControlClassification("precipitation", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-02"),
    ControlClassification("precipitation_deposits", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-03"),
    ControlClassification("wind_intensity", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-04"),
    ControlClassification("sun_azimuth_angle", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-05"),
    ControlClassification("sun_altitude_angle", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-06"),
    ControlClassification("fog_density", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-07"),
    ControlClassification("fog_distance", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-08"),
    ControlClassification("fog_falloff", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-09"),
    ControlClassification("wetness", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-10"),
    ControlClassification("wetness_persistence", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QCheckBox", "world.set_weather", "T-WX-11"),
    ControlClassification("cloud_height", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-12"),
    ControlClassification("cloud_height_enabled", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QCheckBox", "world.set_weather", "T-WX-13"),
    ControlClassification("radius", "04_world_time", ControlState.CONFIGURATION_ONLY,
                          "carla.WeatherParameters", "QDoubleSpinBox", "world.set_weather", "T-WX-14"),
]

# Map controls
MAP_CONTROLS = [
    ControlClassification("available_maps_list", "05_maps_gis_cooking", ControlState.OFFLINE_FUNCTIONAL,
                          "carla.Client.get_available_maps", "QListWidget", "client.get_available_maps", "T-MAP-01"),
    ControlClassification("load_selected_map", "05_maps_gis_cooking", ControlState.BLOCKED,
                          "carla.World.load_world", "QPushButton", "world.load_world", "T-MAP-02",
                          "Requires exclusive authority + confirmation"),
    ControlClassification("local_inspector", "05_maps_gis_cooking", ControlState.OFFLINE_FUNCTIONAL,
                          "map_analysis.inspect_xml_map", "QTextEdit", "local file inspection", "T-MAP-03"),
    ControlClassification("elevation_panel", "05_maps_gis_cooking", ControlState.OFFLINE_FUNCTIONAL,
                          "map_analysis.evaluate_elevation", "ElevationPanel", "local file inspection", "T-MAP-04"),
]

# Camera controls
CAMERA_CONTROLS = [
    ControlClassification("front_rgb_feed", "08_sensors_streams", ControlState.OFFLINE_FUNCTIONAL,
                          "FrameIngress.publish", "FeedTile", "external frame producer", "T-CAM-01"),
    ControlClassification("rear_rgb_feed", "08_sensors_streams", ControlState.OFFLINE_FUNCTIONAL,
                          "FrameIngress.publish", "FeedTile", "external frame producer", "T-CAM-02"),
    ControlClassification("depth_feed", "08_sensors_streams", ControlState.OFFLINE_FUNCTIONAL,
                          "FrameIngress.publish", "FeedTile", "external frame producer", "T-CAM-03"),
    ControlClassification("semantic_feed", "08_sensors_streams", ControlState.OFFLINE_FUNCTIONAL,
                          "FrameIngress.publish", "FeedTile", "external frame producer", "T-CAM-04"),
    ControlClassification("camera_width", "08_sensors_streams", ControlState.CONFIGURATION_ONLY,
                          "carla.Blueprint.set_attribute", "QDoubleSpinBox", "sensor config", "T-CAM-05"),
    ControlClassification("camera_height", "08_sensors_streams", ControlState.CONFIGURATION_ONLY,
                          "carla.Blueprint.set_attribute", "QDoubleSpinBox", "sensor config", "T-CAM-06"),
    ControlClassification("camera_fov", "08_sensors_streams", ControlState.CONFIGURATION_ONLY,
                          "carla.Blueprint.set_attribute", "QDoubleSpinBox", "sensor config", "T-CAM-07"),
    ControlClassification("camera_tick", "08_sensors_streams", ControlState.CONFIGURATION_ONLY,
                          "carla.Blueprint.set_attribute", "QDoubleSpinBox", "sensor config", "T-CAM-08"),
    ControlClassification("mjpeg_attach", "08_sensors_streams", ControlState.OFFLINE_FUNCTIONAL,
                          "MjpegSource", "QPushButton", "external MJPEG stream", "T-CAM-09"),
    ControlClassification("local_playback", "08_sensors_streams", ControlState.OFFLINE_FUNCTIONAL,
                          "QImage", "QPushButton", "local file playback", "T-CAM-10"),
]

# Connection controls
CONNECTION_CONTROLS = [
    ControlClassification("host_input", "03_connection_diagnostics", ControlState.OFFLINE_FUNCTIONAL,
                          "carla.Client", "QLineEdit", "client connection", "T-CONN-01"),
    ControlClassification("port_input", "03_connection_diagnostics", ControlState.OFFLINE_FUNCTIONAL,
                          "carla.Client", "QSpinBox", "client connection", "T-CONN-02"),
    ControlClassification("timeout_input", "03_connection_diagnostics", ControlState.OFFLINE_FUNCTIONAL,
                          "carla.Client.set_timeout", "QDoubleSpinBox", "client connection", "T-CONN-03"),
    ControlClassification("rpc_probe", "03_connection_diagnostics", ControlState.BLOCKED,
                          "carla.Client.get_server_version", "QPushButton", "RPC probe", "T-CONN-04",
                          "Requires live CARLA server"),
]

# Experiment controls
EXPERIMENT_CONTROLS = [
    ControlClassification("experiment_designer", "14_experiments_runs", ControlState.OFFLINE_FUNCTIONAL,
                          "plans.save_plan", "QLineEdit+QComboBox", "local plan save", "T-EXP-01"),
    ControlClassification("template_loader", "14_experiments_runs", ControlState.OFFLINE_FUNCTIONAL,
                          "TEMPLATES dict", "QComboBox", "template selection", "T-EXP-02"),
    ControlClassification("plan_browser", "14_experiments_runs", ControlState.OFFLINE_FUNCTIONAL,
                          "plans.read_plan", "QTableWidget", "local plan load", "T-EXP-03"),
]


def build_capability_matrix() -> dict:
    """Build the complete capability matrix."""
    all_controls = (
        WEATHER_CONTROLS + MAP_CONTROLS + CAMERA_CONTROLS
        + CONNECTION_CONTROLS + EXPERIMENT_CONTROLS
    )
    by_state: dict[str, list[dict]] = {}
    for ctrl in all_controls:
        state = ctrl.state.value
        by_state.setdefault(state, []).append(ctrl.as_dict())
    return {
        "schema": "carla-ops-capability-matrix/v3.2",
        "total_controls": len(all_controls),
        "by_state": by_state,
        "summary": {state: len(items) for state, items in by_state.items()},
    }


def save_matrix(path: str | Path) -> Path:
    matrix = build_capability_matrix()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    return target


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "capability_matrix_v3.2.json"
    p = save_matrix(out)
    print(f"Capability matrix saved: {p}")
    m = build_capability_matrix()
    print(f"Total controls: {m['total_controls']}")
    for state, count in m["summary"].items():
        print(f"  {state}: {count}")