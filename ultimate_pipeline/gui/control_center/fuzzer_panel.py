"""Offline mutator browser and deterministic case generator; no simulator runs."""
from __future__ import annotations

import json

from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QPlainTextEdit,
    QSpinBox, QVBoxLayout, QWidget,
)

from ultimate_pipeline.gui.fuzz.mutators import registry as mutators
from .widgets import action, section, text_label


class FuzzerPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root, outer = section("Operational Fuzzer · offline workbench", "15 registered families; simulator-guarded cases cannot execute without Q22.")
        self.family = QComboBox()
        self.family.addItems(mutators.names())
        self.seed = QSpinBox()
        self.seed.setRange(0, 2**31 - 1)
        self.seed.setValue(42)
        form = QFormLayout()
        form.addRow("Mutation family", self.family)
        form.addRow("Deterministic seed", self.seed)
        outer.addLayout(form)
        self.family.currentTextChanged.connect(self._update_info)
        self.info = text_label("")
        outer.addWidget(self.info)
        actions = QHBoxLayout()
        actions.addWidget(action("Generate bounded offline case", self.generate, True))
        actions.addStretch(1)
        outer.addLayout(actions)
        self.state = text_label("LIVE FUZZING: BLOCKED · no Q22 exclusive isolated-server lease", "warning-pill")
        outer.addWidget(self.state)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("No case generated")
        outer.addWidget(self.result, stretch=1)
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(root)
        self._update_info()

    def _update_info(self, *_):
        family = mutators.get(self.family.currentText())
        contract = family.contract
        self.info.setText(json.dumps(contract.as_dict(), indent=2, default=str))
        self.state.setText("SIMULATOR-GUARDED · GENERATION ONLY" if contract.requires_simulator
                           else "OFFLINE · Generation only, not an oracle execution")

    def generate(self):
        family = mutators.get(self.family.currentText())
        try:
            # Generation is allowed for all families; only evaluation is restricted.
            outcome = family.run(case_id="gui_preview", seed=self.seed.value(), base={})
            self.result.setPlainText(json.dumps(outcome.as_dict(), indent=2, default=str))
            self.state.setText("CASE GENERATED · NOT EXECUTED · NO PASS/FAIL VERDICT")
        except Exception as exc:
            self.state.setText("CASE GENERATION FAILED")
            self.result.setPlainText(f"{type(exc).__name__}: {exc}")
