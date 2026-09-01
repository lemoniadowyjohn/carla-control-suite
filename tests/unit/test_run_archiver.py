# ultimate_pipeline/database/run_archiver.py -- live via main_pipeline.py
# (imported at line 1644). Zero prior test coverage despite performing a
# destructive shutil.move() on real pipeline run directories. No bug found
# after a careful read (keep-newest-N / archive-the-rest logic is correct,
# metadata collection is defensively wrapped, the archive target-exists
# check makes _archive_run idempotent) -- closing coverage on it anyway
# given the destructive-operation + zero-coverage combination this session
# has repeatedly found real bugs in.
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from ultimate_pipeline.database.run_archiver import RunArchiver


@pytest.fixture
def archiver(tmp_path: Path, monkeypatch) -> RunArchiver:
    from ultimate_pipeline.config.settings import SETTINGS

    output_root = tmp_path / "output"
    output_root.mkdir()
    db_root = tmp_path / "db_root"
    db_root.mkdir()

    monkeypatch.setattr(SETTINGS, "BASE_OUTPUT_DIR", str(output_root))
    monkeypatch.setattr(SETTINGS, "DB_ROOT", db_root)
    monkeypatch.setattr(SETTINGS, "DB_FILE", db_root / "test.db")

    return RunArchiver(keep_last_n=2)


def _make_run_dir(output_root: Path, name: str, *, mtime_offset_s: float = 0.0) -> Path:
    d = output_root / name
    d.mkdir()
    if mtime_offset_s:
        t = time.time() + mtime_offset_s
        import os

        os.utime(d, (t, t))
    return d


def test_list_runs_filters_non_run_directories(archiver: RunArchiver):
    output_root = Path(archiver.output_root)
    _make_run_dir(output_root, "20260101_120000_run")
    _make_run_dir(output_root, "not_a_run_dir")
    (output_root / "some_file.txt").write_text("x", encoding="utf-8")

    runs = archiver._list_runs()

    assert [r.name for r in runs] == ["20260101_120000_run"]


def test_list_runs_sorted_newest_first(archiver: RunArchiver):
    output_root = Path(archiver.output_root)
    _make_run_dir(output_root, "20260101_000001_old", mtime_offset_s=-100)
    _make_run_dir(output_root, "20260101_000002_new", mtime_offset_s=0)

    runs = archiver._list_runs()

    assert [r.name for r in runs] == ["20260101_000002_new", "20260101_000001_old"]


def test_archive_old_runs_noop_when_within_keep_limit(archiver: RunArchiver):
    output_root = Path(archiver.output_root)
    _make_run_dir(output_root, "20260101_000001_a")
    _make_run_dir(output_root, "20260101_000002_b")

    archiver.archive_old_runs()

    # keep_last_n=2, exactly 2 runs exist -> nothing archived
    assert sorted(p.name for p in output_root.iterdir()) == [
        "20260101_000001_a",
        "20260101_000002_b",
    ]
    assert not list(archiver.archive_root.iterdir())


def test_archive_old_runs_archives_the_oldest_beyond_keep_limit(archiver: RunArchiver):
    output_root = Path(archiver.output_root)
    _make_run_dir(output_root, "20260101_000001_oldest", mtime_offset_s=-200)
    _make_run_dir(output_root, "20260101_000002_middle", mtime_offset_s=-100)
    _make_run_dir(output_root, "20260101_000003_newest", mtime_offset_s=0)

    archiver.archive_old_runs()

    remaining = {p.name for p in output_root.iterdir()}
    archived = {p.name for p in archiver.archive_root.iterdir()}

    # keep_last_n=2 -> newest 2 stay, oldest 1 gets archived
    assert remaining == {"20260101_000002_middle", "20260101_000003_newest"}
    assert archived == {"20260101_000001_oldest"}


def test_archive_run_is_idempotent_when_target_already_exists(archiver: RunArchiver):
    output_root = Path(archiver.output_root)
    run_dir = _make_run_dir(output_root, "20260101_000001_run")
    marker = run_dir / "marker.txt"
    marker.write_text("original", encoding="utf-8")

    # Pre-create the archive target to simulate "already archived"
    target = archiver.archive_root / "20260101_000001_run"
    target.mkdir(parents=True)
    (target / "marker.txt").write_text("already archived", encoding="utf-8")

    archiver._archive_run(run_dir)

    # Original run_dir must be untouched (not moved into the existing target)
    assert run_dir.exists()
    assert marker.read_text(encoding="utf-8") == "original"


def test_archive_run_handles_missing_settings_snapshot_gracefully(archiver: RunArchiver):
    output_root = Path(archiver.output_root)
    run_dir = _make_run_dir(output_root, "20260101_000001_run")

    archiver._archive_run(run_dir)  # must not raise

    target = archiver.archive_root / "20260101_000001_run"
    assert target.exists()
    assert not run_dir.exists()


def test_archive_run_parses_valid_settings_snapshot_and_logs_to_db(archiver: RunArchiver):
    output_root = Path(archiver.output_root)
    run_dir = _make_run_dir(output_root, "20260101_000001_run")
    (run_dir / "settings_snapshot.json").write_text(
        json.dumps({"seed": 42}), encoding="utf-8"
    )

    archiver._archive_run(run_dir)

    conn = sqlite3.connect(archiver.db.db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT run_id, status, metadata_json FROM pipeline_runs WHERE run_id = ?",
        ("20260101_000001_run",),
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[1] == "archived"
    meta = json.loads(row[2])
    assert meta["settings_snapshot"] == {"seed": 42}


def test_archive_run_handles_malformed_json_snapshot_gracefully(archiver: RunArchiver):
    output_root = Path(archiver.output_root)
    run_dir = _make_run_dir(output_root, "20260101_000001_run")
    (run_dir / "settings_snapshot.json").write_text("{not valid json", encoding="utf-8")

    archiver._archive_run(run_dir)  # must not raise

    conn = sqlite3.connect(archiver.db.db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT metadata_json FROM pipeline_runs WHERE run_id = ?",
        ("20260101_000001_run",),
    )
    row = cur.fetchone()
    conn.close()

    meta = json.loads(row[0])
    assert "settings_snapshot_error" in meta
