"""Multi-camera control center: RGB, Depth, Semantic with config and diagnostics.

Supports local file playback, external MJPEG, and CARLA-native sensor streams
via FrameIngress. Never claims mock images are live CARLA feeds.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from .widgets import action, section, text_label
from .mjpeg import MjpegSource


class FrameIngress(QObject):
    """Thread-safe Qt signal for frames supplied by an externally owned adapter."""
    frame_received = pyqtSignal(str, QImage, int, float)

    def publish(self, sensor_id: str, image: QImage, frame_id: int, timestamp: float):
        self.frame_received.emit(sensor_id, image.copy(), int(frame_id), float(timestamp))


class FeedTile(QWidget):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self._original = QPixmap()
        self.header = text_label(f"{name.upper()}  ·  UNBOUND", "status-pill")
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumSize(200, 140)
        self.picture.setStyleSheet(
            "background:#101b2b; border:1px solid #31445c; border-radius:6px;"
        )
        self.picture.setAccessibleName(f"{name} camera preview")
        self.caption = text_label("No camera callback received", "muted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.addWidget(self.header)
        layout.addWidget(self.picture, stretch=1)
        layout.addWidget(self.caption)
        self.set_placeholder()

    def set_placeholder(self):
        self._original = QPixmap(420, 240)
        self._original.fill(QColor("#17263b"))
        painter = QPainter(self._original)
        painter.setPen(QPen(QColor("#2a4562"), 2))
        for x in range(0, 420, 35):
            painter.drawLine(x, 0, x, 240)
        for y in range(0, 240, 35):
            painter.drawLine(0, y, 420, y)
        painter.setPen(QColor("#70add2"))
        painter.drawText(
            self._original.rect(), Qt.AlignmentFlag.AlignCenter,
            "NO LIVE STREAM\nMOCK PLACEHOLDER"
        )
        painter.end()
        self._resize_image()

    def _resize_image(self):
        if not self._original.isNull():
            self.picture.setPixmap(self._original.scaled(
                max(self.picture.width(), 200),
                max(self.picture.height(), 140),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._resize_image()

    def update_frame(self, image: QImage, source: str,
                     frame_id: int | None, timestamp: float | None):
        self._original = QPixmap.fromImage(image.copy())
        self.header.setText(f"{self.name.upper()}  ·  {source}")
        identity = (
            f"Frame ID {frame_id}" if frame_id is not None else "Frame ID NOT_SUPPLIED"
        )
        ts = (
            f"source timestamp {timestamp:.3f} s" if timestamp is not None
            else "source timestamp NOT_SUPPLIED"
        )
        if source == "LOCAL REPLAY":
            identity = f"Local file index {frame_id}"
        self.caption.setText(f"{identity} · {ts}")
        self._resize_image()


class FeedsPanel(QWidget):
    """Multi-camera control center with RGB, Depth, Semantic, and Other Sensors."""

    CHANNELS = ("Front RGB", "Rear RGB", "Depth", "Semantic")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ingress = FrameIngress(self)
        self.ingress.frame_received.connect(self.on_frame)
        self.tiles = {name: FeedTile(name) for name in self.CHANNELS}
        self._files: list[Path] = []
        self._frame_index = 0
        self._streams = {}
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.next_frame)
        self._build_ui()

    def _build_ui(self):
        root, outer = section(
            "Camera & sensor monitor",
            "Four independent preview channels. Playback is LOCAL FILE data; "
            "no fake live feeds. CARLA-native streams require authorized adapter."
        )

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)

        self._build_live_feeds_tab()
        self._build_camera_config_tab()
        self._build_diagnostics_tab()
        self._build_other_sensors_tab()

        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(root)

    def _build_live_feeds_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        commands = QHBoxLayout()
        for btn in (
            action("Open image sequence…", self.open_sequence, True),
            action("Pause / resume", self.toggle),
            action("Next frame", self.next_frame),
            action("Stop / clear", self.stop),
        ):
            commands.addWidget(btn)
        commands.addStretch(1)
        layout.addLayout(commands)

        external = QHBoxLayout()
        self.channel = QComboBox()
        self.channel.addItems(self.CHANNELS)
        self.url = QLineEdit("http://127.0.0.1:8080/stream")
        self.url.setPlaceholderText("External CARLA camera bridge: HTTP(S) MJPEG URL")
        external.addWidget(self.channel)
        external.addWidget(self.url, stretch=1)
        external.addWidget(action("Attach MJPEG", self.attach_stream))
        external.addWidget(action("Stop streams", self.stop_streams))
        layout.addLayout(external)

        self.state = text_label(
            "UNBOUND · No CARLA sensor frames. Attach a governed frame producer to FrameIngress.",
            "warning-pill",
        )
        layout.addWidget(self.state)

        grid = QGridLayout()
        grid.setSpacing(8)
        for i, name in enumerate(self.CHANNELS):
            grid.addWidget(self.tiles[name], i // 2, i % 2)
        layout.addLayout(grid, stretch=1)

        layout.addWidget(text_label(
            "LiDAR / radar / GNSS / IMU: metadata channels not bound in mock mode. "
            "Sensor lifecycle and frame identity require an approved producer."
        ))
        self.tabs.addTab(tab, "Live Feeds")

    def _build_camera_config_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(text_label("Camera Configuration", "workspace-heading"))
        layout.addWidget(text_label(
            "Configure camera parameters. Values are REQUESTED, not applied without authority.",
            "muted"
        ))

        form = QFormLayout()
        self.config_inputs = {}
        params = [
            ("Image Width (px)", 320, 3840, 1280, 0),
            ("Image Height (px)", 240, 2160, 720, 0),
            ("FOV (degrees)", 10, 170, 90, 1),
            ("Sensor Tick (s)", 0.01, 1.0, 0.05, 3),
            ("Gamma", 1.0, 5.0, 2.2, 2),
            ("ISO", 100, 3200, 800, 0),
            ("Shutter Speed (ms)", 0.1, 100, 10, 1),
            ("Aperture", 1.0, 22.0, 5.6, 1),
        ]
        for name, minv, maxv, default, decimals in params:
            spin = QDoubleSpinBox()
            spin.setRange(minv, maxv)
            spin.setDecimals(decimals)
            spin.setValue(default)
            spin.setAccessibleName(name)
            self.config_inputs[name] = spin
            form.addRow(name, spin)
        layout.addLayout(form)

        # Mounting
        layout.addWidget(text_label("Mounting Position", "card-caption"))
        mount_form = QFormLayout()
        self.mount_inputs = {}
        for axis, minv, maxv, default in [
            ("X (m)", -20, 20, 1.5), ("Y (m)", -20, 20, 0.0),
            ("Z (m)", -10, 20, 2.2), ("Yaw (deg)", -180, 180, 0),
            ("Pitch (deg)", -90, 90, 0), ("Roll (deg)", -180, 180, 0),
        ]:
            spin = QDoubleSpinBox()
            spin.setRange(minv, maxv)
            spin.setDecimals(2)
            spin.setValue(default)
            self.mount_inputs[axis] = spin
            mount_form.addRow(axis, spin)
        layout.addLayout(mount_form)

        layout.addWidget(action("Export Camera Config", self.export_camera_config))
        layout.addStretch(1)
        self.tabs.addTab(tab, "Camera Config")

    def _build_diagnostics_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(text_label("Stream Diagnostics", "workspace-heading"))

        self.diag_report = QPlainTextEdit()
        self.diag_report.setReadOnly(True)
        self.diag_report.setPlainText(
            "No active streams.\n"
            "Frame IDs, timestamps, and drop counters will appear here when streams are active."
        )
        layout.addWidget(self.diag_report)

        self.fps_label = text_label("Measured FPS: N/A", "muted")
        layout.addWidget(self.fps_label)
        self.frame_age_label = text_label("Frame Age: N/A", "muted")
        layout.addWidget(self.frame_age_label)

        self.tabs.addTab(tab, "Diagnostics")

    def _build_other_sensors_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(text_label("Other Sensors", "workspace-heading"))
        layout.addWidget(text_label(
            "LiDAR, Radar, GNSS, IMU configuration. "
            "These sensors require CARLA actor spawning authority.",
            "muted"
        ))

        form = QFormLayout()
        self.sensor_inputs = {}
        sensor_params = [
            ("LiDAR Channels", 1, 128, 32, 0),
            ("LiDAR Range (m)", 1, 250, 80, 1),
            ("LiDAR Points/Sec", 1000, 1000000, 200000, 0),
            ("Radar Range (m)", 1, 500, 100, 1),
            ("GNSS Update Rate (Hz)", 1, 100, 20, 0),
            ("IMU Update Rate (Hz)", 10, 1000, 100, 0),
        ]
        for name, minv, maxv, default, decimals in sensor_params:
            spin = QDoubleSpinBox()
            spin.setRange(minv, maxv)
            spin.setDecimals(decimals)
            spin.setValue(default)
            self.sensor_inputs[name] = spin
            form.addRow(name, spin)
        layout.addLayout(form)

        layout.addWidget(text_label(
            "SPAWN_REQUIRES_AUTHORITY: These sensors cannot be spawned in SHARED_READONLY mode.",
            "warning-pill"
        ))
        layout.addStretch(1)
        self.tabs.addTab(tab, "Other Sensors")

    # ------------------------------------------------------------- playback
    def open_sequence(self):
        directory = QFileDialog.getExistingDirectory(self, "Select local image frames")
        if not directory:
            return
        self._files = sorted(
            p for p in Path(directory).iterdir()
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}
        )[:2000]
        self._frame_index = 0
        if self._files:
            self.state.setText(f"LOCAL FILE PLAYBACK · {len(self._files)} images · NOT LIVE")
            self._timer.start()
            self.next_frame()
        else:
            self.state.setText("No supported local images found in selected folder")

    def on_frame(self, sensor_id: str, image: QImage, frame_id: int, timestamp: float):
        tile = self.tiles.get(sensor_id)
        if tile is None:
            return
        tile.update_frame(image, "EXTERNAL FRAME PRODUCER", frame_id, timestamp)
        self.state.setText("EXTERNAL FRAMES RECEIVED · source identity and authority not verified")

    def next_frame(self):
        if not self._files:
            return
        path = self._files[self._frame_index % len(self._files)]
        frame = QImage(str(path))
        if not frame.isNull():
            channel = self.CHANNELS[self._frame_index % len(self.CHANNELS)]
            self.tiles[channel].update_frame(frame, "LOCAL REPLAY", self._frame_index, None)
        self._frame_index += 1

    def toggle(self):
        if self._files:
            self._timer.stop() if self._timer.isActive() else self._timer.start()

    def stop(self):
        self._timer.stop()
        self._files = []
        for tile in self.tiles.values():
            tile.header.setText(f"{tile.name.upper()}  ·  UNBOUND")
            tile.caption.setText("No camera callback received")
            tile.set_placeholder()
        self.state.setText("UNBOUND · No CARLA sensor frames")

    def attach_stream(self):
        channel = self.channel.currentText()
        if channel in self._streams and self._streams[channel].isRunning():
            self.state.setText(f"STREAM {channel} already active. Stop it before reattaching.")
            return
        try:
            worker = MjpegSource(self.url.text(), self)
        except ValueError as exc:
            self.state.setText(f"INVALID STREAM URL: {exc}")
            return
        worker.image_received.connect(lambda image, name=channel: self._external_image(name, image))
        worker.stream_error.connect(lambda message: self.state.setText(message))
        self._streams[channel] = worker
        worker.start()
        self.state.setText(f"CONNECTING EXTERNAL MJPEG · {channel} · CARLA ORIGIN UNVERIFIED")

    def _external_image(self, channel: str, image: QImage):
        self.tiles[channel].update_frame(image, "EXTERNAL MJPEG", None, None)
        self.state.setText("EXTERNAL MJPEG RECEIVED · frame IDs / CARLA origin NOT_VERIFIED")

    def stop_streams(self):
        for stream in self._streams.values():
            stream.requestInterruption()
        self.state.setText("External streams stopping · no CARLA actor mutation")

    def export_camera_config(self):
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save Camera Config", "camera_config.json", "JSON (*.json)"
        )
        if not destination:
            return
        import json
        values = {n: w.value() for n, w in self.config_inputs.items()}
        values.update({f"mount_{k}": v.value() for k, v in self.mount_inputs.items()})
        record = {
            "schema": "carla-ops-camera-config/v1",
            "state": "REQUESTED_NOT_APPLIED",
            "values": values,
        }
        Path(destination).write_text(json.dumps(record, indent=2), encoding="utf-8")
        self.state.setText(f"CONFIG SAVED: {destination}")

    def closeEvent(self, event):  # noqa: N802
        self._timer.stop()
        self.stop_streams()
        for stream in self._streams.values():
            if stream.isRunning():
                stream.wait(4000)
        super().closeEvent(event)