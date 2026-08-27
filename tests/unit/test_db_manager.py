"""ultimate_pipeline/database/db_manager.py -- SQLite-backed experiment & dataset registry
used by main_pipeline.py, run_archiver.py, and dataset_generator.py. Existing coverage
(test_db_manager_get_connection_removed.py) only guards against a specific past regression
(a removed get_connection stub); the actual database logic (table creation, additive-only
schema migration, fail-loud schema validation, and the log_* insert methods) had zero
coverage. Found via an expanded orphaned-.pyc sweep of the top-level tests/ directory (the
original tests/test_db_manager.py no longer exists on this branch).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ultimate_pipeline.database.db_manager import Database


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Database:
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "DB_FILE", str(tmp_path / "test.db"))
    return Database()


# ---------------------------------------------------------------------------
# Table creation / schema validation on init
# ---------------------------------------------------------------------------

def test_init_creates_all_expected_tables(db: Database):
    conn = sqlite3.connect(db.db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    conn.close()
    assert set(Database.EXPECTED_SCHEMA.keys()) <= tables


def test_init_creates_db_file_parent_dir(tmp_path: Path, monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    nested = tmp_path / "nested" / "dir" / "test.db"
    monkeypatch.setattr(SETTINGS, "DB_FILE", str(nested))
    Database()
    assert nested.parent.is_dir()


def test_reopening_existing_db_does_not_raise(tmp_path: Path, monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "DB_FILE", str(tmp_path / "test.db"))
    Database()
    Database()  # second open against the same file must not raise


# ---------------------------------------------------------------------------
# _get_table_schema
# ---------------------------------------------------------------------------

def test_get_table_schema_returns_column_name_to_type_map(db: Database):
    schema = db._get_table_schema("experiments")
    assert schema["id"] == "INTEGER"
    assert schema["config_json"] == "TEXT"


def test_get_table_schema_nonexistent_table_returns_empty(db: Database):
    assert db._get_table_schema("does_not_exist") == {}


# ---------------------------------------------------------------------------
# _migrate_add_missing_columns (additive-only)
# ---------------------------------------------------------------------------

def test_migrate_adds_missing_column_to_existing_table(tmp_path: Path, monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(SETTINGS, "DB_FILE", str(db_path))

    # Pre-create an "experiments" table missing the "results_json" column.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE experiments (id INTEGER PRIMARY KEY, timestamp TEXT, "
        "experiment_type TEXT, config_json TEXT)"
    )
    conn.commit()
    conn.close()

    database = Database()

    schema = database._get_table_schema("experiments")
    assert "results_json" in schema  # migration added it


def test_migrate_never_drops_extra_columns(tmp_path: Path, monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(SETTINGS, "DB_FILE", str(db_path))

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE experiments (id INTEGER PRIMARY KEY, timestamp TEXT, "
        "experiment_type TEXT, config_json TEXT, results_json TEXT, "
        "extra_legacy_column TEXT)"
    )
    conn.commit()
    conn.close()

    database = Database()  # must not raise despite the extra column, and must not drop it

    schema = database._get_table_schema("experiments")
    assert "extra_legacy_column" in schema


# ---------------------------------------------------------------------------
# _validate_schema (fail loud)
# ---------------------------------------------------------------------------

def test_validate_schema_type_mismatch_raises(tmp_path: Path, monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(SETTINGS, "DB_FILE", str(db_path))

    # Pre-create with "metric_value" as TEXT instead of the expected REAL.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE domain_gap_metrics (id INTEGER PRIMARY KEY, timestamp TEXT, "
        "tile_id TEXT, metric_name TEXT, metric_value TEXT, metadata_json TEXT)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="schema mismatch"):
        Database()


# ---------------------------------------------------------------------------
# log_* insert methods
# ---------------------------------------------------------------------------

def test_log_dataset_entry_inserts_a_row(db: Database):
    db.log_dataset_entry(
        timestamp="2026-08-27T00:00:00Z", dataset_name="ds1", image_path="/a.png",
        label_path="/a.json", map_type="auto", augmentation=0, metadata_json="{}",
    )
    conn = sqlite3.connect(db.db_path)
    row = conn.execute("SELECT dataset_name FROM dataset_entries").fetchone()
    conn.close()
    assert row[0] == "ds1"


def test_log_experiment_inserts_a_row(db: Database):
    db.log_experiment(
        timestamp="2026-08-27T00:00:00Z", experiment_type="rq1",
        config_json="{}", results_json="{}",
    )
    conn = sqlite3.connect(db.db_path)
    row = conn.execute("SELECT experiment_type FROM experiments").fetchone()
    conn.close()
    assert row[0] == "rq1"


def test_log_domain_gap_metric_inserts_a_row(db: Database):
    db.log_domain_gap_metric(
        timestamp="2026-08-27T00:00:00Z", tile_id="tile_0_0",
        metric_name="frechet", metric_value=42.5, metadata_json="{}",
    )
    conn = sqlite3.connect(db.db_path)
    row = conn.execute("SELECT metric_value FROM domain_gap_metrics").fetchone()
    conn.close()
    assert row[0] == 42.5


def test_log_pipeline_run_inserts_a_row(db: Database):
    db.log_pipeline_run(
        run_id="run_1", timestamp="2026-08-27T00:00:00Z",
        output_dir="/out", archive_dir="/archive", status="ok", metadata_json="{}",
    )
    conn = sqlite3.connect(db.db_path)
    row = conn.execute("SELECT run_id, status FROM pipeline_runs").fetchone()
    conn.close()
    assert row == ("run_1", "ok")


def test_multiple_log_calls_accumulate_rows(db: Database):
    for i in range(3):
        db.log_experiment(
            timestamp="2026-08-27T00:00:00Z", experiment_type=f"exp_{i}",
            config_json="{}", results_json="{}",
        )
    conn = sqlite3.connect(db.db_path)
    count = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    conn.close()
    assert count == 3
