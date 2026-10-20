# -*- coding: utf-8 -*-
"""Regression test: RunArchiver must tolerate a missing output root.

The first RQ1B five-run campaign at the research branch exposed this:
every child run crashed with FileNotFoundError on the never-yet-created
``ultimate_pipeline_out`` directory at stage "archive old runs".
"""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.database import run_archiver as ra_mod


class TestRunArchiverMissingOutputRoot:
    def test_list_runs_missing_root_is_empty(self, tmp_path, monkeypatch):
        archiver = object.__new__(ra_mod.RunArchiver)
        archiver.output_root = Path(tmp_path) / "definitely_missing"
        archiver.keep_last_n = 10
        assert archiver._list_runs() == []

        archiver.archive_old_runs()  # also must not raise
        assert not archiver.output_root.exists()

    def test_list_runs_existing_root_still_filters_run_dirs(self, tmp_path, monkeypatch):
        (tmp_path / "20260101_101010").mkdir()
        (tmp_path / "not_a_run").mkdir()
        (tmp_path / "20260102_020202").mkdir()

        archiver = object.__new__(ra_mod.RunArchiver)
        archiver.output_root = tmp_path
        runs = archiver._list_runs()
        assert [p.name for p in runs] == ["20260102_020202", "20260101_101010"]
