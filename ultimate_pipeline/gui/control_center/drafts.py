"""User-configurable proposal forms that do not mutate CARLA or claim readback."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PyQt6.QtWidgets import (
    QDoubleSpinBox, QFileDialog, QFormLayout, QLineEdit,
    QPlainTextEdit, QVBoxLayout, QWidget,
)

from .widgets import action, section, text_label

# Bounds are only local proposal-editor constraints; NOT CARLA-server verification.
FIELDS = {
    "04_world_time": (
        ("cloudiness_percent", 0, 100, 0), ("precipitation_percent", 0, 100, 0),
        ("sun_altitude_deg", -90, 90, 45), ("fog_density_percent", 0, 100, 0),
        ("wetness_percent", 0, 100, 0), ("fixed_delta_seconds", 0.005, 0.2, 0.05),
    ),
    "06_traffic_manager": (
        ("following_distance_m", 0.1, 50, 2.5),
        ("global_speed_difference_percent", -50, 100, 0),
        ("hybrid_physics_radius_m", 5, 500, 70),
        ("random_seed", 0, 1000000, 42),
    ),
    "07_actors_routes": (
        ("proposed_vehicle_count", 0, 100, 10),
        ("proposed_pedestrian_count", 0, 100, 5),
        ("max_spawn_attempts", 1, 200, 20),
    ),
    "08_sensors_streams": (
        ("camera_width_px", 320, 3840, 1280),
        ("camera_height_px", 240, 2160, 720),
        ("camera_fov_deg", 10, 170, 90),
        ("camera_tick_seconds", 0.01, 1, 0.05),
        ("lidar_channels", 1, 128, 32),
        ("lidar_range_m", 1, 250, 80),
    ),
    "09_calibration_workbench": (
        ("focal_x_px", 1, 10000, 700), ("focal_y_px", 1, 10000, 700),
        ("principal_x_px", 0, 3840, 640), ("principal_y_px", 0, 2160, 360),
        ("mount_x_m", -20, 20, 1.5), ("mount_y_m", -20, 20, 0),
        ("mount_z_m", -10, 20, 2.2),
        ("mount_yaw_deg", -180, 180, 0),
        ("mount_pitch_deg", -90, 90, 0),
        ("mount_roll_deg", -180, 180, 0),
    ),
}


def export_draft(path: str | Path, route: str, values: dict) -> Path:
    """Persist an operator-requested proposal, never an observed runtime state."""
    if route not in FIELDS:
        raise ValueError("unknown form route")
    allowed = {name for name, *_ in FIELDS[route]}
    if set(values) != allowed:
        raise ValueError("draft keys do not match the route schema")
    target = Path(path)
    if target.suffix.lower() != ".json":
        raise ValueError("draft destination must be a JSON file")
    record = {"schema": "carla-ops-operator-draft/v1", "route": route,
              "state": "REQUESTED_NOT_APPLIED", "values": values}
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                         delete=False, prefix=".draft_") as stream:
            tmp_path = Path(stream.name)
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, target)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return target


class DraftControlsPanel(QWidget):
    def __init__(self, route: str, parent=None):
        super().__init__(parent)
        if route not in FIELDS:
            raise ValueError(f"unknown control draft route {route}")
        self.route = route
        self.inputs = {}
        title = {"04_world_time": "World, time & weather", "06_traffic_manager": "Traffic Manager",
                 "07_actors_routes": "Actors and traffic population",
                 "08_sensors_streams": "Sensor configuration proposals",
                 "09_calibration_workbench": "Calibration workspace"}[route]
        root, outer = section(title, "Edit local operator proposals with explicit bounds. Values are NOT APPLIED or MEASURED.")
        layout = QFormLayout()
        for field, minv, maxv, default in FIELDS[route]:
            spin = QDoubleSpinBox()
            spin.setRange(minv, maxv)
            spin.setDecimals(3 if isinstance(default, float) else 0)
            spin.setSingleStep(0.05 if "seconds" in field else 1)
            spin.setValue(default)
            spin.setAccessibleName(field.replace("_", " "))
            spin.setToolTip("Editor bounds only; actual server capability is not verified")
            layout.addRow(field.replace("_", " "), spin)
            self.inputs[field] = spin
        outer.addLayout(layout)
        outer.addWidget(action("Export proposal JSON…", self.save, True))
        self.state = text_label("REQUESTED_NOT_APPLIED · server state UNBOUND", "warning-pill")
        outer.addWidget(self.state)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        outer.addWidget(self.log, stretch=1)
        holder = QVBoxLayout(self)
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(root)

    def values(self) -> dict:
        return {name: widget.value() for name, widget in self.inputs.items()}

    def save(self):
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save unexecuted control proposal", self.route + "_draft.json", "JSON (*.json)")
        if not destination:
            return
        try:
            exported = export_draft(destination, self.route, self.values())
            self.state.setText("DRAFT SAVED · NOT APPLIED")
            self.log.setPlainText(str(exported) + "\nNo live CARLA method was called.")
        except Exception as exc:
            self.state.setText("EXPORT FAILED")
            self.log.setPlainText(f"{type(exc).__name__}: {exc}")
