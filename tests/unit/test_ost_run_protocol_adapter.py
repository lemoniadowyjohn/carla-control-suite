"""ultimate_pipeline/tools/ost_run_protocol_adapter.py -- post-run thesis protocol adapter
that synthesizes determinism_fingerprint.json/pipeline_health_summary.json/
map_content_fingerprint.json from a run directory's existing pipeline outputs, referenced by
this session's LIVE_RUN_PROTOCOL_MAP.md. This pass covers the pure helper functions
(read_json/write_json/find_canonical_xodr/summarize_gate_from_debug/merge_gate_summaries/
collect_up_env); main()'s full CLI orchestration and the subprocess-based safe_git_commit are
out of scope, matching this sweep's established pattern. Found untested via the orphaned-.pyc
sweep.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ultimate_pipeline.tools.ost_run_protocol_adapter import (
    collect_up_env,
    find_canonical_xodr,
    merge_gate_summaries,
    read_json,
    summarize_gate_from_debug,
    write_json,
)


# ---------------------------------------------------------------------------
# read_json / write_json
# ---------------------------------------------------------------------------

def test_read_json_missing_file_returns_none(tmp_path: Path):
    assert read_json(tmp_path / "nope.json") is None


def test_read_json_malformed_content_returns_none_not_raise(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert read_json(p) is None


def test_read_json_valid_content_parses(tmp_path: Path):
    p = tmp_path / "ok.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    assert read_json(p) == {"a": 1}


def test_write_json_then_read_json_round_trips(tmp_path: Path):
    p = tmp_path / "out.json"
    write_json(p, {"b": 2, "a": 1})
    assert read_json(p) == {"a": 1, "b": 2}


def test_write_json_output_is_sorted_and_indented(tmp_path: Path):
    p = tmp_path / "out.json"
    write_json(p, {"z": 1, "a": 2})
    text = p.read_text(encoding="utf-8")
    assert text.index('"a"') < text.index('"z"')
    assert "\n" in text  # indented, not a single line


# ---------------------------------------------------------------------------
# find_canonical_xodr
# ---------------------------------------------------------------------------

def test_find_canonical_xodr_prefers_tile_0_0(tmp_path: Path):
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir()
    (tiles_dir / "tile_0_0.xodr").write_text("<OpenDRIVE/>", encoding="utf-8")
    (tiles_dir / "tile_1_1.xodr").write_text("<OpenDRIVE/>", encoding="utf-8")

    path, reason = find_canonical_xodr(tmp_path)

    assert path == tiles_dir / "tile_0_0.xodr"
    assert reason == "tiles/tile_0_0.xodr"


def test_find_canonical_xodr_falls_back_to_newest_xodr(tmp_path: Path):
    older = tmp_path / "old.xodr"
    newer = tmp_path / "new.xodr"
    older.write_text("<OpenDRIVE/>", encoding="utf-8")
    os.utime(older, (1000, 1000))
    newer.write_text("<OpenDRIVE/>", encoding="utf-8")
    os.utime(newer, (2000, 2000))

    path, reason = find_canonical_xodr(tmp_path)

    assert path == newer
    assert reason == "newest *.xodr"


def test_find_canonical_xodr_none_found(tmp_path: Path):
    path, reason = find_canonical_xodr(tmp_path)
    assert path is None
    assert reason == "none found"


# ---------------------------------------------------------------------------
# summarize_gate_from_debug
# ---------------------------------------------------------------------------

def test_summarize_gate_none_debug_returns_all_none():
    result = summarize_gate_from_debug(None, "some_file.json")
    assert result == {"ok": None, "issues": None, "source": None}


def test_summarize_gate_reads_ok_key():
    result = summarize_gate_from_debug({"ok": True}, "f.json")
    assert result["ok"] is True
    assert result["source"] == "f.json"


def test_summarize_gate_reads_passed_key_when_ok_absent():
    result = summarize_gate_from_debug({"passed": False}, "f.json")
    assert result["ok"] is False


def test_summarize_gate_non_bool_ok_key_is_ignored():
    # "ok": 1 is truthy but not a bool -- the source's isinstance check must reject it.
    result = summarize_gate_from_debug({"ok": 1}, "f.json")
    assert result["ok"] is None


def test_summarize_gate_issues_from_list_length():
    result = summarize_gate_from_debug({"issues": [1, 2, 3]}, "f.json")
    assert result["issues"] == 3


def test_summarize_gate_issues_from_int_count():
    result = summarize_gate_from_debug({"errors": 5}, "f.json")
    assert result["issues"] == 5


def test_summarize_gate_issues_heuristic_discontinuity_key_fallback():
    result = summarize_gate_from_debug({"heading_discontinuities": [1, 2]}, "f.json")
    assert result["issues"] == 2


def test_summarize_gate_no_recognizable_keys_returns_none_issues():
    result = summarize_gate_from_debug({"unrelated_key": "value"}, "f.json")
    assert result["issues"] is None
    assert result["ok"] is None


# ---------------------------------------------------------------------------
# merge_gate_summaries
# ---------------------------------------------------------------------------

def test_merge_gate_summaries_both_none_returns_none_sources():
    result = merge_gate_summaries(None, "primary.json", None, "secondary.json")
    assert result == {"ok": None, "issues": None, "sources": None}


def test_merge_gate_summaries_primary_takes_precedence():
    primary = {"ok": True, "issues": 0}
    secondary = {"ok": False, "issues": 5}
    result = merge_gate_summaries(primary, "primary.json", secondary, "secondary.json")
    assert result["ok"] is True
    assert result["issues"] == 0
    assert result["sources"] == ["primary.json", "secondary.json"]


def test_merge_gate_summaries_falls_back_to_secondary_when_primary_lacks_ok():
    primary = {"unrelated": 1}  # summarize_gate_from_debug -> ok=None, issues=None
    secondary = {"ok": True, "issues": 2}
    result = merge_gate_summaries(primary, "primary.json", secondary, "secondary.json")
    assert result["ok"] is True
    assert result["issues"] == 2


def test_merge_gate_summaries_only_primary_present():
    result = merge_gate_summaries({"ok": True}, "primary.json", None, "secondary.json")
    assert result["ok"] is True
    assert result["sources"] == ["primary.json"]


# ---------------------------------------------------------------------------
# collect_up_env
# ---------------------------------------------------------------------------

def test_collect_up_env_filters_to_up_prefixed_vars(monkeypatch):
    monkeypatch.setenv("UP_THESIS_STRICT", "1")
    monkeypatch.setenv("UP_RELEASE_PROFILE", "DEVELOPMENT")
    monkeypatch.setenv("NOT_UP_PREFIXED", "should_not_appear")

    result = collect_up_env()

    assert result["UP_THESIS_STRICT"] == "1"
    assert result["UP_RELEASE_PROFILE"] == "DEVELOPMENT"
    assert "NOT_UP_PREFIXED" not in result


def test_collect_up_env_sorted_by_key(monkeypatch):
    monkeypatch.setenv("UP_ZEBRA", "1")
    monkeypatch.setenv("UP_ALPHA", "2")

    result = collect_up_env()

    keys = [k for k in result.keys() if k in ("UP_ZEBRA", "UP_ALPHA")]
    assert keys == ["UP_ALPHA", "UP_ZEBRA"]
