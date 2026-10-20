"""Explicit, bounded external MJPEG input. No CARLA sensor creation or tick control."""
from __future__ import annotations

import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

MAX_FRAME_BYTES = 3 * 1024 * 1024
MAX_BUFFER_BYTES = 6 * 1024 * 1024


def validate_feed_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("stream URL must be HTTP(S) with a host")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("credentials and fragments are not accepted in stream URLs")
    if len(url) > 2048:
        raise ValueError("stream URL is too long")
    return url.strip()


class MjpegSource(QThread):
    """One operator-started HTTP stream; frame boundaries are bounded by JPEG markers."""
    image_received = pyqtSignal(QImage)
    stream_error = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = validate_feed_url(url)

    def run(self):
        try:
            req = Request(self.url, headers={"User-Agent": "CarlaOpsStudio/preview",
                                             "Accept": "multipart/x-mixed-replace,image/jpeg"})
            buffer = bytearray()
            previous = 0.0
            with urlopen(req, timeout=2.5) as response:
                while not self.isInterruptionRequested():
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    if len(buffer) > MAX_BUFFER_BYTES:
                        self.stream_error.emit("MJPEG buffer exceeded 6 MiB; stream stopped")
                        return
                    while True:
                        start = buffer.find(b"\xff\xd8")
                        if start < 0:
                            # Keep at most a marker fragment, not an unlimited header.
                            buffer = buffer[-1:]
                            break
                        end = buffer.find(b"\xff\xd9", start + 2)
                        if end < 0:
                            if start:
                                del buffer[:start]
                            break
                        frame = bytes(buffer[start:end + 2])
                        del buffer[:end + 2]
                        if len(frame) > MAX_FRAME_BYTES:
                            self.stream_error.emit("MJPEG frame exceeded 3 MiB; dropped")
                            continue
                        now = time.monotonic()
                        if now - previous < 0.1:
                            continue
                        image = QImage.fromData(frame, "JPEG")
                        if not image.isNull():
                            previous = now
                            self.image_received.emit(image)
        except Exception as exc:
            self.stream_error.emit(f"Stream unavailable: {type(exc).__name__}: {exc}")
