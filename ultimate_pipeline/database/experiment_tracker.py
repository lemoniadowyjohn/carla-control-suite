from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict

from ultimate_pipeline.database.db_manager import Database


@dataclass
class ExperimentHandle:
    id: int
    name: str
    version: int
    full_name: str  # e.g. "yolo_ingolstadt_v3"


class ExperimentTracker:
    """
    Simple experiment versioning built on top of Database.experiments.

    Each logical experiment has a base name, e.g.:
        "yolo_ingolstadt"
    and versions:
        v1, v2, v3...

    We store them as separate rows in experiments table, with
    config_json containing 'experiment_name' and 'version'.
    """

    def __init__(self, db: Database | None = None):
        self.db = db or Database()
        # force schema validation even if DB passed in
        self.db._validate_schema()

    def _next_version(self, base_name: str) -> int:
        conn = self.db._connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) 
            FROM experiments
            WHERE json_extract(config_json, '$.experiment_name') = ?
            """,
            (base_name,),
        )
        count = cur.fetchone()[0]
        conn.close()
        return count + 1

    def start_experiment(self, base_name: str, config: Dict[str, Any]) -> ExperimentHandle:
        """
        Create a new experiment row with an incremented version.
        Returns an ExperimentHandle with ID + version.
        """
        version = self._next_version(base_name)
        full_name = f"{base_name}_v{version}"

        full_config = dict(config)
        full_config["experiment_name"] = base_name
        full_config["version"] = version
        full_config["full_name"] = full_name

        timestamp = datetime.utcnow().isoformat()

        # Initially store empty results (will be updated later)
        self.db.log_experiment(
            timestamp=timestamp,
            experiment_type=base_name,
            config_json=json.dumps(full_config),
            results_json=json.dumps({"status": "running"}),
        )

        # Retrieve the last inserted id
        conn = self.db._connect()
        cur = conn.cursor()
        cur.execute("SELECT MAX(id) FROM experiments")
        exp_id = cur.fetchone()[0]
        conn.close()

        return ExperimentHandle(id=exp_id, name=base_name, version=version, full_name=full_name)

    def finish_experiment(self, handle: ExperimentHandle, results: Dict[str, Any]):
        """
        Update the experiment row with final results.
        """
        conn = self.db._connect()
        cur = conn.cursor()

        # Fetch existing config to keep it
        cur.execute("SELECT config_json FROM experiments WHERE id = ?", (handle.id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Experiment id {handle.id} not found")

        config_json = row[0]
        results_full = dict(results)
        results_full.setdefault("status", "finished")
        results_json = json.dumps(results_full)

        cur.execute(
            """
            UPDATE experiments
            SET results_json = ?
            WHERE id = ?
            """,
            (results_json, handle.id),
        )
        conn.commit()
        conn.close()
