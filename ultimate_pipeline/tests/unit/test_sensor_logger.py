# ultimate_pipeline/db/sensor_logger.py -- live via tile_validation/tile_stress_tester.py.
# Zero prior test coverage. No bugs found (parameterized queries, correct
# types, clean schema).
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ultimate_pipeline.db.sensor_logger import SensorLogger


def test_init_creates_db_file_and_schema(tmp_path):
    db_path = tmp_path / "nested" / "logs.sqlite3"
    logger = SensorLogger(db_path=str(db_path))
    try:
        assert db_path.exists()
        cur = logger.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert {"experiments", "experiment_results"} <= tables
    finally:
        logger.close()


def test_register_experiment_returns_uuid_and_persists_row(tmp_path):
    logger = SensorLogger(db_path=str(tmp_path / "db.sqlite3"))
    try:
        exp_uuid = logger.register_experiment(
            model_checkpoint="ckpt.pt", dataset_uuid="ds-1", notes="test run"
        )

        cur = logger.conn.cursor()
        cur.execute(
            "SELECT experiment_uuid, model_checkpoint, dataset_uuid, notes "
            "FROM experiments WHERE experiment_uuid = ?",
            (exp_uuid,),
        )
        row = cur.fetchone()
        assert row == (exp_uuid, "ckpt.pt", "ds-1", "test run")
    finally:
        logger.close()


def test_log_experiment_result_persists_row_with_correct_types(tmp_path):
    logger = SensorLogger(db_path=str(tmp_path / "db.sqlite3"))
    try:
        exp_uuid = logger.register_experiment(
            model_checkpoint="ckpt.pt", dataset_uuid="ds-1"
        )
        logger.log_experiment_result(
            experiment_uuid=exp_uuid,
            tile_x=3,
            tile_y=7,
            map_name="Ingolstadt",
            metric_name="mIoU",
            metric_value=0.812,
            extra={"note": "seed=42"},
        )

        cur = logger.conn.cursor()
        cur.execute(
            "SELECT tile_x, tile_y, map_name, metric_name, metric_value, extra_json "
            "FROM experiment_results WHERE experiment_uuid = ?",
            (exp_uuid,),
        )
        row = cur.fetchone()
        assert row[0] == 3
        assert row[1] == 7
        assert row[2] == "Ingolstadt"
        assert row[3] == "mIoU"
        assert row[4] == 0.812
        assert json.loads(row[5]) == {"note": "seed=42"}
    finally:
        logger.close()


def test_log_experiment_result_defaults_extra_to_empty_dict(tmp_path):
    logger = SensorLogger(db_path=str(tmp_path / "db.sqlite3"))
    try:
        exp_uuid = logger.register_experiment(
            model_checkpoint="ckpt.pt", dataset_uuid="ds-1"
        )
        logger.log_experiment_result(
            experiment_uuid=exp_uuid,
            tile_x=0,
            tile_y=0,
            map_name="m",
            metric_name="loss",
            metric_value=1.0,
        )

        cur = logger.conn.cursor()
        cur.execute(
            "SELECT extra_json FROM experiment_results WHERE experiment_uuid = ?",
            (exp_uuid,),
        )
        assert json.loads(cur.fetchone()[0]) == {}
    finally:
        logger.close()


def test_close_is_idempotent_and_swallows_errors(tmp_path):
    logger = SensorLogger(db_path=str(tmp_path / "db.sqlite3"))
    logger.close()
    logger.close()  # must not raise on double-close
