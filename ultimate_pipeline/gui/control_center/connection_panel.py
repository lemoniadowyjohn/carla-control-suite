"""Explicit, read-only CARLA RPC connection probe; never runs on navigation."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit,
    QSpinBox, QDoubleSpinBox, QVBoxLayout, QWidget,
)

from .widgets import action, section, text_label


class ReadOnlyProbe(QThread):
    report = pyqtSignal(object)

    def __init__(self, host: str, port: int, timeout: float, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.timeout = timeout

    def run(self):
        try:
            # CARLA SDK is optional and imported only after explicit click.
            import carla
            client = carla.Client(self.host, self.port)
            client.set_timeout(self.timeout)
            version = client.get_server_version()  # real CARLA RPC, not TCP handshake
            world = client.get_world()
            result = {"rpc": "RESPONDED", "server_version": version,
                      "map_name": world.get_map().name,
                      "sync_mode": world.get_settings().synchronous_mode,
                      "identity": "RPC_OBSERVED_MAP_NOT_COOK_VERIFIED",
                      "authority": "SHARED_READONLY; no tick, actor, or world mutation"}
            self.report.emit((True, result))
        except Exception as exc:
            self.report.emit((False, f"{type(exc).__name__}: {exc}"))


class ConnectionPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        root, outer = section("Server connection & identity", "An explicit CARLA RPC query is permitted; no world loads, ticks or actor mutations.")
        self.host = QLineEdit("127.0.0.1")
        self.host.setAccessibleName("CARLA server host")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(2000)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(1.0, 8.0)
        self.timeout.setValue(3.0)
        self.timeout.setSuffix(" s")
        form = QFormLayout()
        form.addRow("Server host", self.host)
        form.addRow("RPC port", self.port)
        form.addRow("Timeout", self.timeout)
        outer.addLayout(form)
        outer.addWidget(action("Probe CARLA RPC (read-only)", self.probe, True))
        self.state = text_label("NOT_PROBED · no network request made", "warning-pill")
        outer.addWidget(self.state)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlainText("G5: BLOCKED_COOK_REQUIRED\nG6: UNBOUND\nG7: NOT_CLAIMED\nG8: TICK_AUTHORITY_MISSING\n\n"
                                 "RPC readback cannot by itself verify cooked-content provenance or lease ownership.")
        outer.addWidget(self.report, stretch=1)
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(root)

    def probe(self):
        if self._worker and self._worker.isRunning():
            return
        import ipaddress
        import re
        host = self.host.text().strip()
        if not host or len(host) > 255 or not re.fullmatch(r"[A-Za-z0-9.\-:]+", host):
            self.state.setText("INVALID HOST · use an IP address or DNS name")
            return
        self.state.setText("PROBING · an explicit read-only RPC query is running")
        self._worker = ReadOnlyProbe(host, self.port.value(), self.timeout.value(), self)
        self._worker.report.connect(self._receive)
        self._worker.start()

    def _receive(self, packet):
        import json
        ok, data = packet
        if ok:
            self.state.setText("RPC RESPONDED · LIVE READ-ONLY OBSERVATION · NO AUTHORITY CLAIMED")
            self.report.setPlainText(json.dumps(data, indent=2) +
                  "\n\nG5/G7 content verification and G8 exclusive tick authority remain UNVERIFIED")
        else:
            self.state.setText("UNAVAILABLE · RPC probe failed; simulator not controlled")
            self.report.setPlainText(str(data))
