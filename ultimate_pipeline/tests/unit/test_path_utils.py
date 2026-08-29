# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/tools/path_utils.py.

Live: all 5 functions imported by run_full_domain_gap.py. Zero prior test
coverage.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

from ultimate_pipeline.tools.path_utils import (
    ensure_dir,
    norm_path_str,
    repo_root,
    resolve_latest_run,
    timestamp_dirname,
)


def test_repo_root_finds_git_marker(tmp_path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert repo_root(nested) == tmp_path


def test_repo_root_finds_ultimate_pipeline_dir(tmp_path):
    (tmp_path / "ultimate_pipeline").mkdir()
    nested = tmp_path / "a"
    nested.mkdir()
    assert repo_root(nested) == tmp_path


def test_ensure_dir_creates_nested_directories(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    result = ensure_dir(target)
    assert result == target
    assert target.is_dir()


def test_ensure_dir_is_idempotent(tmp_path):
    target = tmp_path / "a"
    ensure_dir(target)
    ensure_dir(target)  # must not raise
    assert target.is_dir()


def test_norm_path_str_expands_and_resolves(tmp_path):
    result = norm_path_str(str(tmp_path) + "/./x/../y")
    assert result == str((tmp_path / "y").resolve())


def test_timestamp_dirname_matches_expected_pattern():
    name = timestamp_dirname("run_")
    assert name.startswith("run_")
    assert re.fullmatch(r"run_\d{8}_\d{6}", name)


def test_resolve_latest_run_picks_newest_valid_candidate(tmp_path):
    older = tmp_path / "run_a"
    newer = tmp_path / "run_b"
    now = time.time()
    # resolve_latest_run's timestamp is max(meta_mtime, tiles_dir_mtime,
    # run_dir_mtime) -- all three must be explicitly backdated per candidate,
    # or the comparison is dominated by real-clock creation-time noise
    # instead of the intended ordering.
    for d, ts in ((older, now - 100), (newer, now)):
        d.mkdir()
        meta = d / "tile_metadata.json"
        meta.write_text("{}")
        tiles = d / "tiles"
        tiles.mkdir()
        (tiles / "tile_0_0.xodr").write_text("<OpenDRIVE/>")
        os.utime(meta, (ts, ts))
        os.utime(tiles, (ts, ts))
        os.utime(d, (ts, ts))

    result = resolve_latest_run(tmp_path)
    assert result == newer


def test_resolve_latest_run_skips_named_directories(tmp_path):
    skip_me = tmp_path / "scratch"
    keep_me = tmp_path / "run_a"
    for d in (skip_me, keep_me):
        d.mkdir()
        (d / "tile_metadata.json").write_text("{}")
        tiles = d / "tiles"
        tiles.mkdir()
        (tiles / "tile_0_0.xodr").write_text("<OpenDRIVE/>")

    result = resolve_latest_run(tmp_path, skip_names=["scratch"])
    assert result == keep_me


def test_resolve_latest_run_raises_when_output_root_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_latest_run(tmp_path / "does_not_exist")


def test_resolve_latest_run_raises_when_no_valid_candidates(tmp_path):
    # A directory exists but has none of the required marker files.
    empty_run = tmp_path / "run_empty"
    empty_run.mkdir()
    with pytest.raises(RuntimeError):
        resolve_latest_run(tmp_path)
