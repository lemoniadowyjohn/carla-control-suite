from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict

from ultimate_pipeline.config.settings import SETTINGS


class Database:
    """
    SQLite-backed experiment & dataset registry.

    Guarantees:
    - Tables always exist
    - Schema is validated on startup
    - Missing columns are added automatically (forward-compatible)
    - Type mismatches fail hard (research safety)
    """

    # ==========================================================
    # AUTHORITATIVE SCHEMA (single source of truth)
    # ==========================================================
    EXPECTED_SCHEMA: Dict[str, Dict[str, str]] = {
        "dataset_entries": {
            "id": "INTEGER",
            "timestamp": "TEXT",
            "dataset_name": "TEXT",
            "image_path": "TEXT",
            "label_path": "TEXT",
            "map_type": "TEXT",
            "augmentation": "INTEGER",
            "metadata_json": "TEXT",
        },
        "experiments": {
            "id": "INTEGER",
            "timestamp": "TEXT",
            "experiment_type": "TEXT",
            "config_json": "TEXT",
            "results_json": "TEXT",
        },
        "domain_gap_metrics": {
            "id": "INTEGER",
            "timestamp": "TEXT",
            "tile_id": "TEXT",
            "metric_name": "TEXT",
            "metric_value": "REAL",
            "metadata_json": "TEXT",
        },
        "pipeline_runs": {
            "id": "INTEGER",
            "run_id": "TEXT",
            "timestamp": "TEXT",
            "output_dir": "TEXT",
            "archive_dir": "TEXT",
            "status": "TEXT",
            "metadata_json": "TEXT",
        },
    }

    # ==========================================================
    # INIT
    # ==========================================================
    def __init__(self):
        self.db_path = Path(SETTINGS.DB_FILE)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._ensure_tables()
        self._migrate_add_missing_columns()
        self._validate_schema()

    # ==========================================================
    # CONNECTION
    # ==========================================================
    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30)

    # ==========================================================
    # SCHEMA INTROSPECTION
    # ==========================================================
    def _get_table_schema(self, table: str) -> Dict[str, str]:
        """
        Returns {column_name: column_type}
        """
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        rows = cur.fetchall()
        conn.close()

        # row = (cid, name, type, notnull, dflt_value, pk)
        return {r[1]: r[2].upper() for r in rows}

    # ==========================================================
    # MIGRATION (SAFE, ADDITIVE ONLY)
    # ==========================================================
    def _migrate_add_missing_columns(self) -> None:
        """
        Adds missing columns if schema evolved.
        NEVER removes or renames columns.
        """
        conn = self._connect()
        cur = conn.cursor()

        for table, expected in self.EXPECTED_SCHEMA.items():
            actual = self._get_table_schema(table)

            if not actual:
                continue

            for col, col_type in expected.items():
                if col not in actual:
                    print(f"🛠 DB migration: adding column {table}.{col} ({col_type})")
                    cur.execute(
                        f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                    )

        conn.commit()
        conn.close()

    # ==========================================================
    # HARD VALIDATION (FAIL LOUD)
    # ==========================================================
    def _validate_schema(self) -> None:
        """
        Ensures DB schema matches EXPECTED_SCHEMA exactly.
        Fails on missing columns or type mismatches.
        """
        for table, expected_cols in self.EXPECTED_SCHEMA.items():
            actual = self._get_table_schema(table)

            if not actual:
                raise RuntimeError(f"DB schema error: table '{table}' missing")

            missing = set(expected_cols) - set(actual)
            extra = set(actual) - set(expected_cols)

            type_mismatch = {
                col: (actual[col], expected_cols[col])
                for col in expected_cols
                if col in actual and actual[col] != expected_cols[col]
            }

            if missing or type_mismatch:
                raise RuntimeError(
                    f"DB schema mismatch in table '{table}'\n"
                    f"Missing columns: {sorted(missing)}\n"
                    f"Type mismatches: {type_mismatch}\n"
                    f"Actual schema: {actual}"
                )

            if extra:
                print(
                    f"⚠ DB schema note: extra columns in '{table}': {sorted(extra)}"
                )

    # ==========================================================
    # TABLE CREATION
    # ==========================================================
    def _ensure_tables(self) -> None:
        conn = self._connect()
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_entries
            (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     TEXT,
                dataset_name  TEXT,
                image_path    TEXT,
                label_path    TEXT,
                map_type      TEXT,
                augmentation  INTEGER,
                metadata_json TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments
            (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT,
                experiment_type TEXT,
                config_json     TEXT,
                results_json    TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS domain_gap_metrics
            (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     TEXT,
                tile_id       TEXT,
                metric_name   TEXT,
                metric_value  REAL,
                metadata_json TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs
            (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id        TEXT,
                timestamp     TEXT,
                output_dir    TEXT,
                archive_dir   TEXT,
                status        TEXT,
                metadata_json TEXT
            )
            """
        )

        conn.commit()
        conn.close()

    # ==========================================================
    # PUBLIC API
    # ==========================================================
    def log_dataset_entry(self, **kwargs) -> None:
        conn = self._connect()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO dataset_entries
                (timestamp, dataset_name, image_path, label_path,
                 map_type, augmentation, metadata_json)
            VALUES
                (:timestamp, :dataset_name, :image_path, :label_path,
                 :map_type, :augmentation, :metadata_json)
            """,
            kwargs,
        )

        conn.commit()
        conn.close()

    def log_experiment(self, **kwargs) -> None:
        conn = self._connect()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO experiments
                (timestamp, experiment_type, config_json, results_json)
            VALUES
                (:timestamp, :experiment_type, :config_json, :results_json)
            """,
            kwargs,
        )

        conn.commit()
        conn.close()

    def log_domain_gap_metric(self, **kwargs) -> None:
        conn = self._connect()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO domain_gap_metrics
                (timestamp, tile_id, metric_name, metric_value, metadata_json)
            VALUES
                (:timestamp, :tile_id, :metric_name, :metric_value, :metadata_json)
            """,
            kwargs,
        )

        conn.commit()
        conn.close()

    def log_pipeline_run(self, **kwargs) -> None:
        """
        Records archived pipeline runs.
        Used by RunArchiver.
        """
        conn = self._connect()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO pipeline_runs
                (run_id, timestamp, output_dir, archive_dir, status, metadata_json)
            VALUES
                (:run_id, :timestamp, :output_dir, :archive_dir, :status, :metadata_json)
            """,
            kwargs,
        )

        conn.commit()
        conn.close()
