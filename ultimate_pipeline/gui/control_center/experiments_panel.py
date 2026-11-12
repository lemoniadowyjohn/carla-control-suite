"""Operator experiment designer with reusable templates for v3.1 workspaces."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPlainTextEdit, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .plans import EXPERIMENTS, ExperimentPlan, read_plan, save_plan
from .widgets import action, section, text_label


# Reusable experiment templates for v3.1 workspaces
TEMPLATES = {
    "Weather Sweep": {
        "experiment": "weather_sweep",
        "notes": "Sweep cloudiness, precipitation, fog density across ranges. "
                 "Record readback for each step. Requires EXCLUSIVE_WORLD authority.",
    },
    "Day/Night Visibility": {
        "experiment": "visibility_comparison",
        "notes": "Compare sensor visibility at different sun altitudes. "
                 "Capture RGB frames at dawn, noon, dusk, night.",
    },
    "RGB FOV Study": {
        "experiment": "camera_fov_study",
        "notes": "Capture RGB images at multiple FOV settings (30, 60, 90, 120). "
                 "Measure resolution and distortion trade-offs.",
    },
    "Depth Camera Capture": {
        "experiment": "depth_capture",
        "notes": "Capture depth camera frames at various distances. "
                 "Verify depth accuracy against known references.",
    },
    "Semantic Segmentation": {
        "experiment": "semantic_capture",
        "notes": "Capture semantic segmentation output. "
                 "Verify class labels and color mapping.",
    },
    "Multi-Camera Sync": {
        "experiment": "camera_sync",
        "notes": "Synchronize multiple cameras on same actor. "
                 "Measure frame timestamp alignment.",
    },
    "Elevation Inspection": {
        "experiment": "elevation_terrain",
        "notes": "Inspect terrain elevation profiles from OpenDRIVE and GeoTIFF. "
                 "Compare road z(s) with DEM data.",
    },
    "Sensor Mounting": {
        "experiment": "sensor_mounting",
        "notes": "Compare sensor mounting positions and rotations. "
                 "Measure coverage and occlusion.",
    },
}


class ExperimentsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root, outer = section("Experiment design & run library",
                              "Create reproducible offline experiment specifications. No run is started or claimed.")
        self.name = QLineEdit("new_experiment")
        self.family = QComboBox()
        self.family.addItems(EXPERIMENTS)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2**31 - 1)
        self.seed.setValue(42)
        self.local_map = QLineEdit()
        self.local_map.setPlaceholderText("Optional local .xodr / .osm / DEM path")
        self.profile = QLineEdit()
        self.profile.setPlaceholderText("Optional configuration profile identifier")
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Hypothesis, expected evidence, oracle, acceptance criteria…")
        self.notes.setMaximumHeight(130)
        form = QFormLayout()
        for label, widget in (("Name", self.name), ("Experiment", self.family),
                              ("Random seed", self.seed), ("Local map path", self.local_map),
                              ("Configuration profile", self.profile), ("Notes", self.notes)):
            form.addRow(label, widget)
        outer.addLayout(form)

        # Template loader
        template_row = QHBoxLayout()
        self.template_combo = QComboBox()
        self.template_combo.addItems(["Select template..."] + sorted(TEMPLATES.keys()))
        self.template_combo.currentTextChanged.connect(self._load_template)
        template_row.addWidget(QLabel("Template:"))
        template_row.addWidget(self.template_combo)
        outer.addLayout(template_row)

        actions = QHBoxLayout()
        actions.addWidget(action("Save plan JSON…", self.save, True))
        actions.addWidget(action("Load plan JSON…", self.load))
        actions.addStretch(1)
        outer.addLayout(actions)
        self.state = text_label("PLAN_ONLY_NOT_EXECUTED · live experiments require a separately granted runtime lease", "warning-pill")
        outer.addWidget(self.state)
        self.plans = QTableWidget(0, 4)
        self.plans.setHorizontalHeaderLabels(["Name", "Family", "Seed", "Status"])
        self.plans.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.plans.setAccessibleName("Loaded experiment plans")
        outer.addWidget(self.plans, stretch=1)
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addWidget(root)

    def _load_template(self, name: str):
        if name not in TEMPLATES:
            return
        tpl = TEMPLATES[name]
        self.family.setCurrentText(tpl["experiment"])
        self.notes.setPlainText(tpl["notes"])
        self.state.setText(f"TEMPLATE LOADED: {name} · NOT EXECUTED")

    def current_plan(self) -> ExperimentPlan:
        return ExperimentPlan(name=self.name.text(), experiment=self.family.currentText(),
                              seed=self.seed.value(), local_map=self.local_map.text(),
                              profile=self.profile.text(), notes=self.notes.toPlainText())

    def save(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save offline experiment plan",
                          self.name.text().strip() + ".json", "JSON (*.json)")
        if not filename:
            return
        try:
            plan = self.current_plan()
            save_plan(plan, filename)
            self.state.setText(f"SAVED PLAN · {Path(filename).name} · NOT EXECUTED")
            self.add_to_table(plan)
        except Exception as exc:
            QMessageBox.warning(self, "Plan could not be saved", str(exc))

    def load(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open experiment plan", "", "JSON (*.json)")
        if not filename:
            return
        try:
            plan = read_plan(filename)
            self.name.setText(plan.name)
            self.family.setCurrentText(plan.experiment)
            self.seed.setValue(plan.seed)
            self.local_map.setText(plan.local_map)
            self.profile.setText(plan.profile)
            self.notes.setPlainText(plan.notes)
            self.state.setText(f"LOADED LOCAL PLAN · {Path(filename).name} · NOT EXECUTED")
            self.add_to_table(plan)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid plan", str(exc))

    def add_to_table(self, plan: ExperimentPlan):
        idx = self.plans.rowCount()
        self.plans.insertRow(idx)
        for col, val in enumerate((plan.name, plan.experiment, str(plan.seed), "PLAN_ONLY")):
            self.plans.setItem(idx, col, QTableWidgetItem(val))
