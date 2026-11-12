"""Interactive local settings staging, validation and explicit profile persistence."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ultimate_pipeline.gui.config.controls import ConfiguratorModel
from ultimate_pipeline.gui.config.profiles import Profile, ProfileStore
from ultimate_pipeline.gui.config.validation import coerce_for_declared_type, validate_profile

from .widgets import action, section, text_label


class SettingsPanel(QWidget):
    def __init__(self, registry, parent=None):
        super().__init__(parent)
        existing = registry.resolve("configurator")
        self.model = existing if isinstance(existing, ConfiguratorModel) else ConfiguratorModel()
        self.entries = self.model.controls()
        self._visible = []
        root, outer = section("Settings & configuration profiles", "Search the source-backed catalogue, stage validated values and save named local profiles.")
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search 318 declared settings…")
        self.search.textChanged.connect(self.update_list)
        self.filter = QComboBox()
        self.filter.addItems(["All", "Editable", "Deferred / unbound", "Secret-classified"])
        self.filter.currentIndexChanged.connect(self.update_list)
        toolbar.addWidget(self.search, 3)
        toolbar.addWidget(self.filter, 1)
        outer.addLayout(toolbar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Setting", "Category", "Declared type", "Binding"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.select_setting)
        outer.addWidget(self.table, stretch=3)
        self.provenance = text_label("Select a setting to view its source and permitted operations.")
        outer.addWidget(self.provenance)
        row = QHBoxLayout()
        self.value = QLineEdit()
        self.value.setPlaceholderText("Value (typed from source declaration)")
        row.addWidget(self.value, stretch=1)
        row.addWidget(action("Stage value", self.stage, True))
        row.addWidget(action("Undo", self.undo))
        outer.addLayout(row)
        self.profile_name = QLineEdit("operator_profile")
        self.profile_name.setMaximumWidth(220)
        ops = QHBoxLayout()
        ops.addWidget(text_label("Profile name:"))
        ops.addWidget(self.profile_name)
        ops.addWidget(action("Validate staging", self.validate))
        ops.addWidget(action("Save local profile", self.save_profile))
        ops.addWidget(action("Load local profile", self.load_profile))
        outer.addLayout(ops)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(105)
        outer.addWidget(self.log)
        outer.addWidget(text_label("STAGING ONLY · Profile files do not apply settings to a CARLA server. "
                                   "Unknown ranges remain UNVERIFIED; secrets are never exported."))
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(root)
        self.update_list()

    def update_list(self, *_):
        needle = self.search.text().lower().strip()
        mode = self.filter.currentText()
        self._visible = [e for e in self.entries if
                         (not needle or needle in e.setting_id.lower() or needle in e.kind.lower())
                         and (mode == "All" or mode == "Editable" and e.enabled
                              or mode == "Deferred / unbound" and not e.enabled
                              or mode == "Secret-classified" and e.safety_class == "SECRET")]
        self.table.setRowCount(len(self._visible))
        for r, meta in enumerate(self._visible):
            for c, val in enumerate((meta.setting_id, meta.kind,
                                     meta.python_type or "UNKNOWN",
                                     "EDITABLE STAGING" if meta.enabled else "UNBOUND")):
                item = QTableWidgetItem(val)
                item.setToolTip(meta.provenance)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def selected(self):
        r = self.table.currentRow()
        return self._visible[r] if 0 <= r < len(self._visible) else None

    def select_setting(self):
        meta = self.selected()
        if meta is None:
            return
        self.provenance.setText(f"{meta.setting_id} · {meta.provenance}\n"
                                f"Safety: {meta.safety_class} · {meta.disabled_reason or 'staging permitted'}")
        self.value.setEnabled(meta.enabled and meta.safety_class != "SECRET")

    def stage(self):
        meta = self.selected()
        if meta is None or meta.safety_class == "SECRET":
            self.log.setPlainText("Select a non-secret, editable setting")
            return
        raw = self.value.text()
        value, typed = coerce_for_declared_type(raw, meta.python_type)
        if not typed:
            self.log.setPlainText("UNVERIFIED TYPE · select a setting with a known declared type")
            return
        try:
            self.model.stage(meta.setting_id, value)
            self.log.setPlainText(f"STAGED ONLY · {meta.setting_id} = {value!r}\nNo simulator change.")
        except (PermissionError, KeyError, ValueError) as exc:
            self.log.setPlainText(f"REFUSED: {exc}")

    def undo(self):
        self.log.setPlainText("Undid staged edit: " + repr(self.model.undo()))

    def validate(self):
        report = validate_profile(self.model.staged_values(), self.model.registry)
        self.log.setPlainText(f"Validation: {'NO ERRORS' if report.ok else 'ERROR'}; "
                              f"{len(report.unverified)} UNVERIFIED\n" +
                              "\n".join(f"{i.setting_id}: {i.severity}: {i.message}"
                                        for i in report.issues[:5]))
        return report

    def _store(self):
        base = Path.home() / "CARLA_Ops_Studio" / "profiles"
        return ProfileStore(base, self.model.registry)

    def save_profile(self):
        if not self.validate().ok:
            return
        try:
            store = self._store()
            record = store.export(Profile(self.profile_name.text(), self.model.staged_values()))
            self.log.setPlainText(f"SAVED STAGED PROFILE · {record['path']}\nNot applied to CARLA")
        except Exception as exc:
            self.log.setPlainText(f"SAVE FAILED: {exc}")

    def load_profile(self):
        try:
            loaded = self._store().load(self.profile_name.text())
            self.model.staged.clear()
            for setting_id, val in loaded.values.items():
                self.model.stage(setting_id, val)
            self.log.setPlainText(f"LOADED STAGED PROFILE · {len(loaded.values)} settings\nNot applied")
        except Exception as exc:
            self.log.setPlainText(f"LOAD FAILED: {exc}")
