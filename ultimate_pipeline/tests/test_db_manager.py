from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime

import pytest

import ultimate_pipeline.config.settings as settings_module


@pytest.fixture
def tmp_settings_db(tmp_path, monkeypatch):
    """
    Patch SETTINGS.DB_FILE to point to a temporary DB.
    Returns the db_path to inspect.
    """
    db_path = tmp_path / "test_carla_pipeline.db"

    class DummySettings:
        DB_FILE = str(db_path)

    # Patch the SETTINGS object used by db_manager
    monkeypatch.setattr(settings_module, "SETTINGS", DummySettings(), raising=False)

    # Reload db_manager with patched SETTINGS
    from importlib import reload
    from ultimate_pipeline.database import db_manager as dbm

    reload(dbm)
    return db_path, dbm.Database


def test_db_initialization_creates_tables(tmp_settings_db):
    db_path, Database = tmp_settings_db
    db = Database()

    assert db_path.exists()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    conn.close()

    assert "dataset_entries" in tables
    assert "experiments" in tables
    assert "domain_gap_metrics" in tables


def test_log_dataset_entry(tmp_settings_db):
    db_path, Database = tmp_settings_db
    db = Database()

    ts = datetime.utcnow().isoformat()
    db.log_dataset_entry(
        timestamp=ts,
        dataset_name="test_dataset",
        image_path="/tmp/img.png",
        label_path="/tmp/lbl.txt",
        map_type="auto",
        augmentation=1,
        metadata_json=json.dumps({"foo": "bar"}),
    )

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT dataset_name, map_type, augmentation, metadata_json FROM dataset_entries")
    row = cur.fetchone()
    conn.close()

    assert row[0] == "test_dataset"
    assert row[1] == "auto"
    assert row[2] == 1
    meta = json.loads(row[3])
    assert meta["foo"] == "bar"


def test_log_experiment_and_versioning(tmp_settings_db):
    db_path, Database = tmp_settings_db
    db = Database()

    config = {"lr": 1e-3}
    results = {"mAP": 0.5}

    # we will call log_experiment manually here; versioning is handled by ExperimentTracker (see below)
    db.log_experiment(
        timestamp="2025-01-01T00:00:00Z",
        experiment_type="yolo_training",
        config_json=json.dumps(config),
        results_json=json.dumps(results),
    )

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT experiment_type, config_json, results_json FROM experiments")
    row = cur.fetchone()
    conn.close()

    assert row[0] == "yolo_training"
    assert json.loads(row[1])["lr"] == 1e-3
    assert json.loads(row[2])["mAP"] == 0.5


def test_log_domain_gap_metric(tmp_settings_db):
    db_path, Database = tmp_settings_db
    db = Database()

    db.log_domain_gap_metric(
        timestamp="2025-01-01T00:00:00Z",
        tile_id="tile_001",
        metric_name="curvature_diff",
        metric_value=0.42,
        metadata_json="{}",
    )

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT tile_id, metric_name, metric_value FROM domain_gap_metrics")
    row = cur.fetchone()
    conn.close()

    assert row[0] == "tile_001"
    assert row[1] == "curvature_diff"
    assert pytest.approx(row[2], 0.01) == 0.42
