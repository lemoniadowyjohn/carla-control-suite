"""Source-backed OpenDRIVE elevation curve display (not a terrain or survey truth claim)."""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QComboBox, QLabel, QVBoxLayout, QWidget
from .map_analysis import evaluate_elevation




class ElevationCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.records = []
        self.road_length = 0.0
        self.setMinimumSize(300, 250)

    def set_profile(self, records, length):
        self.records = records
        self.road_length = min(max(float(length), 0), 100000)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101b2c"))
        painter.setPen(QColor("#b1c3da"))
        if not self.records or self.road_length <= 0:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Select an OpenDRIVE road with elevation records")
            return
        values = [evaluate_elevation(self.records, self.road_length * i / 150)
                  for i in range(151)]
        values = [min(1e7, max(-1e7, z)) if math.isfinite(z) else 0 for z in values]
        lo, hi = min(values), max(values)
        width, height = max(1, self.width() - 50), max(1, self.height() - 55)
        painter.setPen(QPen(QColor("#557495"), 1))
        painter.drawLine(38, 14, 38, 14 + height)
        painter.drawLine(38, 14 + height, 38 + width, 14 + height)
        painter.setPen(QPen(QColor("#65c4e7"), 2))
        for i in range(len(values) - 1):
            x1 = 38 + width * i / 150
            x2 = 38 + width * (i + 1) / 150
            y1 = 14 + height * (1 - (values[i] - lo) / max(1e-9, hi - lo))
            y2 = 14 + height * (1 - (values[i + 1] - lo) / max(1e-9, hi - lo))
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
        painter.setPen(QColor("#c1d2e5"))
        painter.drawText(40, 13, f"z(s) {lo:.2f} .. {hi:.2f} (declared units)")
        painter.drawText(40, self.height()-5, f"Road s: 0 .. {self.road_length:.0f} m")


class ElevationPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.profiles = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Declared OpenDRIVE road elevation profile · not surveyed/validated"))
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self.select)
        layout.addWidget(self.selector)
        self.canvas = ElevationCanvas()
        layout.addWidget(self.canvas, stretch=1)

    def set_profiles(self, profiles):
        self.profiles = profiles[:30]
        self.selector.blockSignals(True)
        self.selector.clear()
        for p in self.profiles:
            self.selector.addItem(f"Road {p['road_id']} · length {p['length']:.1f} m")
        self.selector.blockSignals(False)
        self.select(0)

    def select(self, index):
        if 0 <= index < len(self.profiles):
            p = self.profiles[index]
            self.canvas.set_profile(p["coefficients"], p["length"])
        else:
            self.canvas.set_profile([], 0)
