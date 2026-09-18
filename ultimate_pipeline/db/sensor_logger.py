from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


class SensorLogger:
    """Tiny SQLite logger used by stress/perception tooling.

    This is intentionally minimal: it provides just enough structure to store
    experiment outputs without requiring an external DB dependency.
    """

    def __init__(self, db_path: str = "logs/ultimate_pipeline.sqlite3") -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self._init_schema()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_uuid TEXT PRIMARY KEY,
                created_utc INTEGER,
                model_checkpoint TEXT,
                dataset_uuid TEXT,
                notes TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experiment_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_uuid TEXT,
                created_utc INTEGER,
                tile_x INTEGER,
                tile_y INTEGER,
                map_name TEXT,
                metric_name TEXT,
                metric_value REAL,
                extra_json TEXT,
                FOREIGN KEY(experiment_uuid) REFERENCES experiments(experiment_uuid)
            )
            """
        )
        self.conn.commit()

    def register_experiment(
        self,
        *,
        model_checkpoint: str,
        dataset_uuid: str,
        notes: str = "",
    ) -> str:
        exp_uuid = str(uuid.uuid4())
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO experiments (experiment_uuid, created_utc, model_checkpoint, dataset_uuid, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (exp_uuid, int(time.time()), model_checkpoint, dataset_uuid, notes),
        )
        self.conn.commit()
        return exp_uuid

    def log_experiment_result(
        self,
        *,
        experiment_uuid: str,
        tile_x: int,
        tile_y: int,
        map_name: str,
        metric_name: str,
        metric_value: float,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO experiment_results
            (experiment_uuid, created_utc, tile_x, tile_y, map_name, metric_name, metric_value, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_uuid,
                int(time.time()),
                int(tile_x),
                int(tile_y),
                str(map_name),
                str(metric_name),
                float(metric_value),
                json.dumps(extra or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()
