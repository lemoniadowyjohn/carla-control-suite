"""Interactive Weather control panel using the governed weather backend.

Provides tabs for Current Weather, Custom Weather, Presets, Time & Simulation,
and Verification with actual CARLA 0.9.16 weather control.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from ultimate_pipeline.gui.runtime.weather import (
    WEATHER_GOVERNED_FIELDS, WEATHER_RANGES, READBACK_TOLERANCE,
    apply_weather, WeatherApplication,
)
from ultimate_pipeline.gui.results import Result

from .widgets import action, section, text_label


# Preset weather configurations matching CARLA 0.9.16 WeatherParameters
PRESETS = {
    "Clear": {
        "cloudiness": 0.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 10.0, "sun_azimuth_angle": 180.0, "sun_altitude_angle": 45.0,
        "fog_density": 0.0, "fog_distance": 0.0, "fog_falloff": 0.0,
        "wetness": 0.0, "scattering_intensity": 0.0, "mie_scattering_scale": 0.033,
        "rayleigh_scattering_scale": 0.033, "dust_storm": 0.0,
    },
    "Cloudy": {
        "cloudiness": 80.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 20.0, "sun_azimuth_angle": 180.0, "sun_altitude_angle": 30.0,
        "fog_density": 0.0, "fog_distance": 0.0, "fog_falloff": 0.0,
        "wetness": 0.0, "scattering_intensity": 20.0, "mie_scattering_scale": 0.05,
        "rayleigh_scattering_scale": 0.05, "dust_storm": 0.0,
    },
    "Rain": {
        "cloudiness": 90.0, "precipitation": 80.0, "precipitation_deposits": 60.0,
        "wind_intensity": 30.0, "sun_azimuth_angle": 180.0, "sun_altitude_angle": 15.0,
        "fog_density": 20.0, "fog_distance": 10.0, "fog_falloff": 0.5,
        "wetness": 80.0, "scattering_intensity": 40.0, "mie_scattering_scale": 0.08,
        "rayleigh_scattering_scale": 0.08, "dust_storm": 0.0,
    },
    "Fog": {
        "cloudiness": 100.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 5.0, "sun_azimuth_angle": 180.0, "sun_altitude_angle": 10.0,
        "fog_density": 80.0, "fog_distance": 5.0, "fog_falloff": 0.8,
        "wetness": 20.0, "scattering_intensity": 30.0, "mie_scattering_scale": 0.06,
        "rayleigh_scattering_scale": 0.06, "dust_storm": 0.0,
    },
    "Sunset": {
        "cloudiness": 40.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 15.0, "sun_azimuth_angle": 270.0, "sun_altitude_angle": -5.0,
        "fog_density": 10.0, "fog_distance": 20.0, "fog_falloff": 0.3,
        "wetness": 0.0, "scattering_intensity": 15.0, "mie_scattering_scale": 0.04,
        "rayleigh_scattering_scale": 0.04, "dust_storm": 0.0,
    },
}


class WeatherApplyWorker(QThread):
    """Background worker for applying weather to avoid blocking the UI."""

    finished = pyqtSignal(object)

    def __init__(self, world, requested: dict, parameters_factory=None, parent=None):
        super().__init__(parent)
        self.world = world
        self.requested = requested
        self.parameters_factory = parameters_factory

    def run(self):
        try:
            result = apply_weather(
                self.world,
                self.requested,
                parameters_factory=self.parameters_factory,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.finished.emit(Result.failure(f"Weather worker error: {exc}"))


class WeatherPanel(QWidget):
    """Interactive Weather control panel with full CARLA 0.9.16 support."""

    def __init__(self, world=None, authority=None, parent=None,
                 runtime_session=None):
        super().__init__(parent)
        self.world = world
        self.authority = authority
        self._worker = None
        self.current_weather = None
        self.runtime_session = runtime_session
        self._build_ui()
        if runtime_session is not None:
            # No destroyed-hook: Python callbacks during C++ teardown can
            # fail fast (0xC0000409); RuntimeSession isolates dead-widget
            # subscribers at publish time instead.
            self._unsubscribe_runtime = runtime_session.subscribe(
                self._on_runtime_world_changed)

    def _on_runtime_world_changed(self, event):
        """Invalidation subscriber: rebind or drop the cached world reference.

        The shared session is authoritative: on MAP_LOAD the panel adopts
        the new world, on LOAD_FAILURE/BINDING_FAILURE/DISCONNECT it drops
        to None so no apply can target a dead reference.
        """
        session = self.runtime_session
        if session is None:
            return
        self.world = session.world
        if self.world is None:
            self.current_state.setText(
                f"WORLD UNBOUND · generation {event.generation} · "
                f"{event.reason} · apply disabled")
        else:
            self.current_state.setText(
                f"WORLD BOUND · generation {event.generation} · {event.reason}")

    def _has_exclusive_authority(self) -> bool:
        """Fail-closed: only an explicitly exclusive authority may mutate."""
        if self.authority is None:
            return False
        from ultimate_pipeline.gui.session.session import exclusive_claimed
        try:
            return exclusive_claimed(self.authority)
        except Exception:
            return False

    def _build_ui(self):
        root, outer = section(
            "Weather Control",
            "Full CARLA 0.9.16 weather control with readback verification. "
            "Mutating controls require exclusive authority."
        )

        self.tabs = QTabWidget()
        self.tabs.setObjectName("weather-tabs")
        outer.addWidget(self.tabs)

        # Build all tabs
        self._build_current_tab()
        self._build_custom_tab()
        self._build_presets_tab()
        self._build_time_sim_tab()
        self._build_verification_tab()

        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(root)

    def _build_current_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.current_state = text_label("NOT CONNECTED", "warning-pill")
        layout.addWidget(self.current_state)

        # Current weather display
        self.current_fields = {}
        form = QFormLayout()
        for field in WEATHER_GOVERNED_FIELDS:
            lbl = QLabel("0.0")
            lbl.setStyleSheet("font-family: monospace; color: #c9d6e6;")
            self.current_fields[field] = lbl
            form.addRow(field.replace("_", " "), lbl)
        layout.addLayout(form)

        # Refresh button
        layout.addWidget(action("Refresh from Server", self.refresh_current))

        self.tabs.addTab(tab, "Current Weather")

    def _build_custom_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.custom_inputs = {}
        form = QFormLayout()

        for field in WEATHER_GOVERNED_FIELDS:
            bounds = WEATHER_RANGES.get(field, None)
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setSingleStep(0.5)
            if field in WEATHER_RANGES:
                spin.setRange(*WEATHER_RANGES[field])
            else:
                spin.setRange(-1e6, 1e6)
            spin.setAccessibleName(field)
            spin.setToolTip("Validated against CARLA 0.9.16 ranges")
            self.custom_inputs[field] = spin
            form.addRow(field.replace("_", " "), spin)

        layout.addLayout(form)

        # Preset loader
        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Select preset..."] + sorted(PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self._load_preset)
        preset_row.addWidget(QLabel("Load preset:"))
        preset_row.addWidget(self.preset_combo)
        layout.addLayout(preset_row)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addWidget(action("Stage & Preview", self.stage_custom, True))
        btn_row.addWidget(action("Apply Weather (requires authority)", self.apply_custom))
        btn_row.addWidget(action("Save as Custom Preset", self.save_preset))
        layout.addLayout(btn_row)

        self.custom_state = text_label("STAGED: NOT APPLIED", "warning-pill")
        layout.addWidget(self.custom_state)

        layout.addStretch(1)
        self.tabs.addTab(tab, "Custom Weather")

    def _build_presets_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(text_label(
            "Built-in CARLA 0.9.16 weather presets. "
            "Select a preset to stage it in the Custom Weather tab.",
            "muted"
        ))

        grid = QGridLayout()
        for i, (name, values) in enumerate(PRESETS.items()):
            btn = QPushButton(name)
            btn.setMinimumHeight(80)
            btn.setStyleSheet("font-size: 14px;")
            btn.clicked.connect(lambda _, n=name: self._load_preset(n))
            btn.setToolTip("Click to stage this preset in Custom Weather")
            grid.addWidget(btn, i // 3, i % 3)

        layout.addLayout(grid)
        layout.addStretch(1)
        self.tabs.addTab(tab, "Presets")

    def _build_time_sim_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(text_label(
            "Time & Simulation parameters (requested, not applied without authority).",
            "muted"
        ))

        form = QFormLayout()
        self.time_inputs = {}
        params = [
            ("fixed_delta_seconds", 0.005, 0.2, 0.05, 3),
            ("synchronous_mode", 0, 1, 0, 0),
            ("substepping", 0, 10, 0, 0),
            ("max_substep_delta_time", 0.001, 0.1, 0.01, 3),
            ("max_substeps", 1, 20, 10, 0),
        ]
        for name, minv, maxv, default, decimals in params:
            spin = QDoubleSpinBox()
            spin.setRange(minv, maxv)
            spin.setDecimals(decimals)
            spin.setValue(default)
            spin.setAccessibleName(name)
            self.time_inputs[name] = spin
            form.addRow(name.replace("_", " "), spin)

        layout.addLayout(form)
        layout.addWidget(action("Export time config", self.save_time_config))
        layout.addStretch(1)
        self.tabs.addTab(tab, "Time & Simulation")

    def _build_verification_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(text_label(
            "Weather application verification. Shows requested vs applied vs measured.",
            "muted"
        ))

        self.verify_report = QPlainTextEdit()
        self.verify_report.setReadOnly(True)
        self.verify_report.setPlainText("No weather application attempted yet.")
        self.verify_report.setStyleSheet("font-family: monospace;")
        layout.addWidget(self.verify_report)

        btn_row = QHBoxLayout()
        btn_row.addWidget(action("Export Verification Report", self.export_verification))
        layout.addLayout(btn_row)

        self.tabs.addTab(tab, "Verification")

    # --- Tab event handlers ---

    def _load_preset(self, name: str):
        if name not in PRESETS:
            return
        values = PRESETS[name]
        for field, widget in self.custom_inputs.items():
            if field in values:
                if isinstance(widget, QDoubleSpinBox):
                    widget.setValue(values[field])
                elif hasattr(widget, "setChecked"):
                    widget.setChecked(values[field])
        self.custom_state.setText(f"PRESET STAGED: {name} · NOT APPLIED")
        self.tabs.setCurrentIndex(1)  # Switch to Custom tab

    def stage_custom(self):
        """Validate and stage custom weather values."""
        requested = {}
        errors = []
        for field, widget in self.custom_inputs.items():
            val = widget.value()
            bounds = WEATHER_RANGES.get(field)
            if bounds and not (bounds[0] <= val <= bounds[1]):
                errors.append(f"{field}: {val} outside range {bounds}")
            requested[field] = val

        if errors:
            self.custom_state.setText("VALIDATION ERRORS")
            QMessageBox.warning(self, "Validation Failed", "\n".join(errors))
            return

        self.custom_state.setText("STAGED · READY TO APPLY · REQUIRES AUTHORITY")
        self.custom_state.setStyleSheet("color: #e6c35a; font-weight: bold;")

    def apply_custom(self):
        """Apply staged weather to connected CARLA world."""
        if not self.world:
            self.custom_state.setText("NO WORLD CONNECTED")
            return
        if not self._has_exclusive_authority():
            self.custom_state.setText("REFUSED · REQUIRES EXCLUSIVE AUTHORITY")
            self.custom_state.setStyleSheet("color: #e65a5a; font-weight: bold;")
            return

        requested = {f: w.value() for f, w in self.custom_inputs.items()}

        # Disable apply button during operation
        self.custom_state.setText("APPLYING...")

        self._worker = WeatherApplyWorker(self.world, requested)
        self._worker.finished.connect(self._on_apply_finished)
        self._worker.start()

    def _on_apply_finished(self, result: Result):
        if result.ok:
            self.custom_state.setText("APPLIED · VERIFIED")
            self.custom_state.setStyleSheet("color: #65c4e7; font-weight: bold;")
            if self.current_weather:
                self._update_current_display(result.value)
        else:
            self.custom_state.setText("APPLY FAILED · READBACK MISMATCH OR ERROR")
            self.custom_state.setStyleSheet("color: #e65a5a; font-weight: bold;")

        # Show detailed report in Verification tab
        self.verify_report.setPlainText(
            f"OK: {result.ok}\n"
            f"Reason: {getattr(result, 'reason', 'N/A')}\n"
            f"Detail: {getattr(result, 'value', 'N/A')}\n"
        )
        self.tabs.setCurrentIndex(4)  # Switch to Verification tab

    def refresh_current(self):
        """Read current weather from connected server."""
        if not self.world or not hasattr(self.world, "get_weather"):
            self.current_state.setText("NO WORLD / NO get_weather")
            return
        try:
            weather = self.world.get_weather()
            self.current_weather = weather
            self._update_current_display(weather)
            self.current_state.setText("LIVE READBACK RECEIVED")
            self.current_state.setStyleSheet("color: #65c4e7;")
        except Exception as exc:
            self.current_state.setText(f"READBACK FAILED: {exc}")

    def _update_current_display(self, weather_or_app):
        """Update current weather display from WeatherParameters, WeatherApplication, or result dict."""
        if isinstance(weather_or_app, dict):
            # Result.value shape from apply_weather: {"ok": ..., "fields": [...]}
            data = {}
            for entry in weather_or_app.get("fields", []):
                value = entry.get("readback")
                if value is not None:
                    data[entry.get("field")] = value
        elif isinstance(weather_or_app, WeatherApplication):
            data = {f.field: f.readback for f in weather_or_app.fields}
        else:
            data = {}
            for field in WEATHER_GOVERNED_FIELDS:
                if hasattr(weather_or_app, field):
                    data[field] = getattr(weather_or_app, field)

        for field, lbl in self.current_fields.items():
            val = data.get(field, "N/A")
            lbl.setText(str(val) if val != "N/A" else "N/A")

    def save_preset(self):
        """Save custom preset to JSON file."""
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save Weather Preset", "custom_weather_preset.json", "JSON (*.json)")
        if not destination:
            return
        import json
        values = {f: w.value() for f, w in self.custom_inputs.items()}
        record = {
            "schema": "carla-ops-weather-preset/v1",
            "name": "Custom Preset",
            "values": values,
        }
        Path(destination).write_text(json.dumps(record, indent=2), encoding="utf-8")
        self.custom_state.setText(f"PRESET SAVED: {destination}")

    def save_time_config(self):
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save Time Config", "time_config.json", "JSON (*.json)")
        if not destination:
            return
        import json
        values = {n: w.value() for n, w in self.time_inputs.items()}
        record = {"schema": "carla-ops-time-config/v1", "values": values}
        Path(destination).write_text(json.dumps(record, indent=2), encoding="utf-8")

    def export_verification(self):
        destination, _ = QFileDialog.getSaveFileName(
            self, "Export Verification", "weather_verification.json", "JSON (*.json)")
        if not destination:
            return
        import json
        Path(destination).write_text(self.verify_report.toPlainText(), encoding="utf-8")