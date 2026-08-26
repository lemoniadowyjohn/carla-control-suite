from __future__ import annotations


def test_get_connection_stub_removed():
    """
    Database._get_connection was a dead `pass` stub with zero callers
    anywhere in the codebase (verified via grep before removal); the class's
    real, actively-used connection method is `_connect()` (used throughout,
    e.g. by `_get_table_schema`). `_get_connection` was a redundant duplicate
    stub and has been removed rather than implemented, since there was no
    caller or docstring to derive intended behavior from.
    """
    from ultimate_pipeline.database.db_manager import Database

    assert not hasattr(Database, "_get_connection")


def test_connect_remains_the_single_real_connection_method(monkeypatch, tmp_path):
    from ultimate_pipeline.config.settings import SETTINGS
    from ultimate_pipeline.database.db_manager import Database

    monkeypatch.setattr(SETTINGS, "DB_FILE", tmp_path / "test_pipeline.db", raising=False)

    db = Database()
    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert "dataset_entries" in tables
        assert "experiments" in tables
    finally:
        conn.close()
