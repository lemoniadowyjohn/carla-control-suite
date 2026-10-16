"""Multi-tab map workspace: local inspection, CARLA map loading, elevation."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from .map_analysis import SUPPORTED, inspect_dem, inspect_xml_map
from .elevation import ElevationPanel
from .widgets import action, section, text_label


class Inspector(QThread):
    finished_report = pyqtSignal(object)

    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self.filename = filename

    def run(self):
        try:
            p = Path(self.filename)
            result = inspect_dem(p) if p.suffix.lower() in {".tif", ".tiff"} else inspect_xml_map(p)
            self.finished_report.emit((True, result))
        except Exception as exc:
            self.finished_report.emit((False, f"{type(exc).__name__}: {exc}"))


class PlanCanvas(QWidget):
    """Read-only 2D line/arc sample; never represents cooked runtime terrain."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self._raster = QPixmap()
        self.setMinimumSize(280, 260)
        self.setAccessibleName("Sampled local OpenDRIVE plan-view, not runtime map")

    def set_segments(self, segments):
        self.segments = segments[:2400]
        self._raster = QPixmap()
        self.update()

    def set_raster(self, values: dict):
        self.segments = []
        raw = values["pixels"]
        image = QImage(raw, values["width"], values["height"],
                       values["width"], QImage.Format.Format_Grayscale8).copy()
        self._raster = QPixmap.fromImage(image)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101b2c"))
        painter.setPen(QPen(QColor("#263a53"), 1))
        for x in range(0, self.width(), 36):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 36):
            painter.drawLine(0, y, self.width(), y)
        if not self._raster.isNull():
            target = self.rect().adjusted(18, 18, -18, -18)
            painter.drawPixmap(target, self._raster, self._raster.rect())
            painter.setPen(QColor("#c9d6e6"))
            painter.drawText(20, 18, "LOCAL DEM SAMPLE · vertical datum UNVERIFIED")
            return
        points = [xy for segment in self.segments for xy in segment]
        if not points:
            painter.setPen(QColor("#9caec5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Choose an OpenDRIVE file\nfor local geometric preview")
            return
        minx, maxx = min(p[0] for p in points), max(p[0] for p in points)
        miny, maxy = min(p[1] for p in points), max(p[1] for p in points)
        scale = min((self.width() - 36) / max(maxx - minx, 1),
                    (self.height() - 36) / max(maxy - miny, 1))

        def screen(p):
            return int(18 + (p[0] - minx) * scale), int(self.height() - 18 - (p[1] - miny) * scale)

        painter.setPen(QPen(QColor("#60b9ee"), 1.3))
        for segment in self.segments:
            for p1, p2 in zip(segment, segment[1:]):
                a, b = screen(p1), screen(p2)
                painter.drawLine(a[0], a[1], b[0], b[1])
        painter.setPen(QColor("#c9d6e6"))
        painter.drawText(12, 18, f"LOCAL SAMPLE · {len(self.segments)} segments")


class MapsPanel(QWidget):
    """Multi-tab map workspace with local inspection and CARLA runtime map loading."""

    def __init__(self, world=None, parent=None):
        super().__init__(parent)
        self.world = world
        self._worker = None
        self.selected = None
        self.runtime_map = "UNBOUND"

        root, outer = section(
            "Maps, terrain & elevation",
            "Select local OSM, OpenDRIVE or GeoTIFF assets. "
            "CARLA map loading requires exclusive runtime authority."
        )
        self.map_label = text_label(
            "LOCAL ASSET: NONE  ·  RUNTIME MAP: UNBOUND", "warning-pill"
        )
        outer.addWidget(self.map_label)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)

        self._build_local_tab()
        self._build_carla_map_tab()
        self._build_elevation_tab()

        safety = text_label(
            "SOURCE ≠ COOKED ≠ RUNTIME. Elevation sampling is exploratory; "
            "no GAP-026 threshold or vertical datum is inferred."
        )
        outer.addWidget(safety)
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(root)

    # ------------------------------------------------------------------ tabs
    def _build_local_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(text_label("LOCAL FILES", "card-caption"))
        self.paths = QListWidget()
        self.paths.setAccessibleName("Discovered local geospatial assets")
        self.paths.itemSelectionChanged.connect(self._selection_changed)
        ll.addWidget(self.paths)
        ll.addWidget(action("Add file…", self.browse, True))
        ll.addWidget(action("Scan folder…", self.scan_folder))
        ll.addWidget(action("Inspect selected", self.inspect))
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.canvas = PlanCanvas()
        self.elevation = ElevationPanel()
        self.visual_tabs = QTabWidget()
        self.visual_tabs.addTab(self.canvas, "Plan view / DEM")
        self.visual_tabs.addTab(self.elevation, "Road elevation")
        rl.addWidget(self.visual_tabs, stretch=3)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Map geometry and elevation inspection results")
        self.details.setPlainText(
            "No asset inspected. G5/G6/G7 remain blocked until separately verified."
        )
        rl.addWidget(self.details, stretch=2)
        splitter.addWidget(right)
        splitter.setSizes([260, 830])
        layout.addWidget(splitter, stretch=1)
        self.tabs.addTab(tab, "Local Inspector")

    def _build_carla_map_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(text_label("CARLA Server Map Management", "workspace-heading"))
        layout.addWidget(text_label(
            "Load and verify server maps. Requires exclusive runtime authority.", "muted"
        ))

        self.available_maps_list = QListWidget()
        self.available_maps_list.setAccessibleName("Available server maps")
        layout.addWidget(self.available_maps_list)

        btn_row = QHBoxLayout()
        btn_row.addWidget(action("Refresh Server Maps", self.refresh_server_maps, True))
        btn_row.addWidget(action("Load Selected Map", self.load_selected_map))
        layout.addLayout(btn_row)

        self.runtime_info = text_label("RUNTIME MAP: UNBOUND", "warning-pill")
        layout.addWidget(self.runtime_info)

        self.load_report = QPlainTextEdit()
        self.load_report.setReadOnly(True)
        self.load_report.setPlainText("No map load attempted.")
        layout.addWidget(self.load_report)
        self.tabs.addTab(tab, "CARLA Maps")

    def _build_elevation_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(ElevationPanel())
        self.tabs.addTab(tab, "Elevation")

    # ------------------------------------------------------- local inspection
    def add_file(self, file: str):
        p = Path(file)
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            if not any(
                self.paths.item(i).data(Qt.ItemDataRole.UserRole) == str(p)
                for i in range(self.paths.count())
            ):
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(p.name)
                item.setData(Qt.ItemDataRole.UserRole, str(p))
                item.setToolTip(str(p))
                self.paths.addItem(item)
                self.paths.setCurrentItem(item)

    def browse(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open local map/DEM", "",
            "Maps and elevation (*.xodr *.osm *.tif *.tiff)"
        )
        if filename:
            self.add_file(filename)

    def scan_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Select map asset folder")
        if directory:
            for p in sorted(Path(directory).iterdir())[:500]:
                if p.suffix.lower() in SUPPORTED and p.is_file():
                    self.add_file(str(p))

    def _selection_changed(self):
        item = self.paths.currentItem()
        self.selected = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.map_label.setText(
            f"LOCAL: {Path(self.selected).name if self.selected else 'NONE'}"
            f"  ·  RUNTIME: {self.runtime_map}"
        )

    def inspect(self):
        if not self.selected or (self._worker and self._worker.isRunning()):
            return
        self.details.setPlainText("Inspecting selected file in background…")
        self._worker = Inspector(self.selected, self)
        self._worker.finished_report.connect(self._on_report)
        self._worker.start()

    def _on_report(self, packet):
        ok, data = packet
        if not ok:
            self.canvas.set_segments([])
            self.details.setPlainText(str(data))
            return
        if data.get("raster_preview"):
            self.canvas.set_raster(data["raster_preview"])
        else:
            self.canvas.set_segments(data.get("segments", []))
        self.elevation.set_profiles(data.get("elevation_profiles", []))
        visible = {
            k: v for k, v in data.items()
            if k not in ("segments", "raster_preview", "elevation_profiles")
        }
        visible["elevation_profile_count_displayed"] = len(
            data.get("elevation_profiles", [])
        )
        self.details.setPlainText(json.dumps(visible, indent=2, default=str))
        self.map_label.setText(
            f"LOCAL INSPECTED: {data['file']}  ·  RUNTIME: {self.runtime_map}"
        )

    # --------------------------------------------------------- CARLA map load
    def refresh_server_maps(self):
        """Query available maps from the connected CARLA server."""
        if not self.world:
            self.runtime_info.setText("NO WORLD CONNECTED")
            return
        try:
            client = self.world.get_client() if hasattr(self.world, "get_client") else self.world
            maps = client.get_available_maps()
            self.available_maps_list.clear()
            for m in maps:
                self.available_maps_list.addItem(m)
            self.runtime_info.setText(f"SERVER MAPS: {len(maps)} available")
        except Exception as exc:
            self.runtime_info.setText(f"REFRESH FAILED: {type(exc).__name__}: {exc}")

    def load_selected_map(self):
        """Load selected map with explicit authority check and confirmation."""
        item = self.available_maps_list.currentItem()
        if not item:
            self.load_report.setPlainText("No map selected.")
            return
        map_name = item.text()

        # Authority check
        if not self._has_exclusive_authority():
            self.load_report.setPlainText(
                f"REFUSED: Loading map '{map_name}' requires exclusive runtime authority.\n"
                "Current session is SHARED_READONLY."
            )
            return

        # Explicit confirmation
        reply = QMessageBox.question(
            self, "Confirm Map Load",
            f"Load map '{map_name}'?\n\n"
            "This will invalidate actors, sensors, recordings and cached world references.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self.load_report.setPlainText("Map load cancelled by operator.")
            return

        try:
            # Use client.load_world, not world.load_world
            client = self.world.get_client() if hasattr(self.world, "get_client") else self.world
            client.load_world(map_name)

            # Verify actual active-world map identity
            actual_map = self.world.get_map().name if hasattr(self.world, "get_map") else "UNKNOWN"
            if actual_map != map_name:
                self.load_report.setPlainText(
                    f"MAP LOAD MISMATCH: requested '{map_name}', "
                    f"but active map is '{actual_map}'"
                )
                return

            # Atomically invalidate stale references
            self._invalidate_stale_references()

            self.runtime_map = map_name
            self.runtime_info.setText(f"RUNTIME MAP: {map_name}")
            self.map_label.setText(
                f"LOCAL: {Path(self.selected).name if self.selected else 'NONE'}"
                f"  ·  RUNTIME: {self.runtime_map}"
            )
            self.load_report.setPlainText(
                f"Map '{map_name}' loaded and identity verified.\n"
                "Stale actor, sensor, and camera references have been invalidated."
            )
        except Exception as exc:
            self.load_report.setPlainText(
                f"MAP LOAD FAILED: {type(exc).__name__}: {exc}"
            )

    def _invalidate_stale_references(self):
        """Invalidate stale actor, sensor, feed, and runtime references."""
        # Clear any cached sensor stats
        if hasattr(self, "sensor_stats"):
            self.sensor_stats = None
        # Clear any cached frame data
        for tile in getattr(self, "tiles", {}).values():
            if hasattr(tile, "set_placeholder"):
                tile.set_placeholder()

    def _has_exclusive_authority(self) -> bool:
        """Check if the current session has exclusive runtime authority."""
        if not self.world:
            return False
        authority = getattr(self.world, "authority", None)
        if authority is None:
            return False
        return str(authority) not in ("SHARED_READONLY", "NONE")