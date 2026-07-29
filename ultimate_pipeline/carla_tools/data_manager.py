from __future__ import annotations
import json
from pathlib import Path
from typing import Any


class DataManager:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        self._captured: list[dict[str, Any]] = []

    def store(self, key: str, value: Any) -> None:
        self._data[key] = value

    def retrieve(self, key: str) -> Any:
        return self._data.get(key)

    def record(self, frame: int, sensor_id: str, data: Any) -> None:
        self._captured.append({
            "frame": frame,
            "sensor_id": sensor_id,
            "timestamp": __import__("time").time(),
            "data": data,
        })

    def save_capture_log(self, filename: str = "capture_log.json") -> Path:
        path = self.output_dir / filename
        path.write_text(json.dumps(self._captured, indent=2, default=str))
        return path

    def save_data(self, filename: str = "session_data.json") -> Path:
        path = self.output_dir / filename
        path.write_text(json.dumps(self._data, indent=2, default=str))
        return path

    @property
    def output_path(self) -> Path:
        return self.output_dir

    @property
    def capture_count(self) -> int:
        return len(self._captured)

    def clear(self) -> None:
        self._data.clear()
        self._captured.clear()
