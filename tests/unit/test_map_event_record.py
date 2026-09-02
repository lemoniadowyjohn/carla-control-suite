"""ultimate_pipeline/artifacts/map_event_record.py -- append-only JSONL audit log of
per-lane/road removal events during CARLA-safety pruning (carla_pruner.py) and quarantine
(quarantine_bad_roads.py, check_lane_connectivity.py), tagged with a cached map content hash.
Found untested via the orphaned-.pyc sweep.

NOTE on a real caching characteristic confirmed by test_get_map_hash_cache_is_never_invalidated_
by_content_change below: get_map_hash() caches map_hash.sha256 keyed only by out_dir (via its
basename), not by final_xodr_path content. If the same out_dir is ever reused across two prune()
calls with DIFFERENT xodr content (e.g. a retry, or a non-timestamped/reused output directory),
the second call silently returns the FIRST call's stale hash. In every real call site found
(carla_pruner.py, stage_08_integrity.py) out_dir is derived from a
per-run output path, so this is not exercised in practice today -- documenting the actual
behavior here rather than asserting it is correct, since fixing it would require confirming no
call site ever reuses an out_dir across content changes.
"""
from __future__ import annotations

import json
from pathlib import Path

from ultimate_pipeline.artifacts.map_event_record import (
    MapEventRecord,
    append_event,
    build_record,
    get_map_hash,
)


def _record(**overrides):
    base = dict(
        run_id="run1", map_hash="abc", stage_name="s", gate_name="g", event_type="removed",
        road_id="1", lane_section_id="0", lane_id="-1", junction_id=None,
        s_from=0.0, s_to=5.0, removed_length_m=5.0, removed_length_pct=1.0,
        tile_id=None, carla_failed_before_masking=None, carla_failed_after_masking=None,
        timestamp="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return MapEventRecord(**base)


# ---------------------------------------------------------------------------
# get_map_hash
# ---------------------------------------------------------------------------

def test_get_map_hash_computes_sha256_of_normalized_content(tmp_path: Path):
    out_dir = tmp_path / "run_abc"
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")

    digest = get_map_hash(str(out_dir), str(xodr))

    assert digest is not None
    assert len(digest) == 64


def test_get_map_hash_normalizes_crlf_before_hashing(tmp_path: Path):
    out_dir1 = tmp_path / "run_a"
    out_dir2 = tmp_path / "run_b"
    xodr_lf = tmp_path / "lf.xodr"
    xodr_crlf = tmp_path / "crlf.xodr"
    xodr_lf.write_bytes(b"line1\nline2\n")
    xodr_crlf.write_bytes(b"line1\r\nline2\r\n")

    digest_lf = get_map_hash(str(out_dir1), str(xodr_lf))
    digest_crlf = get_map_hash(str(out_dir2), str(xodr_crlf))

    assert digest_lf == digest_crlf


def test_get_map_hash_missing_file_returns_none(tmp_path: Path):
    out_dir = tmp_path / "run_abc"
    assert get_map_hash(str(out_dir), str(tmp_path / "does_not_exist.xodr")) is None


def test_get_map_hash_empty_out_dir_or_path_returns_none(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    assert get_map_hash("", str(xodr)) is None
    assert get_map_hash(str(tmp_path / "run"), "") is None


def test_get_map_hash_writes_a_cache_file(tmp_path: Path):
    out_dir = tmp_path / "run_abc"
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")

    digest = get_map_hash(str(out_dir), str(xodr))

    cache_path = out_dir / "artifacts" / "run_abc" / "map_hash.sha256"
    assert cache_path.is_file()
    assert cache_path.read_text(encoding="utf-8").strip() == digest


def test_get_map_hash_second_call_reuses_cache_without_rereading_file(tmp_path: Path):
    out_dir = tmp_path / "run_abc"
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>original", encoding="utf-8")
    first = get_map_hash(str(out_dir), str(xodr))

    xodr.unlink()  # if the cache weren't used, the second call would now return None

    second = get_map_hash(str(out_dir), str(xodr))
    assert second == first


def test_get_map_hash_cache_is_never_invalidated_by_content_change(tmp_path: Path):
    # Documents the caching characteristic described in this file's module docstring:
    # a stale cache in a reused out_dir silently masks a real content change.
    out_dir = tmp_path / "run_abc"
    xodr = tmp_path / "map.xodr"
    xodr.write_text("version one", encoding="utf-8")
    first = get_map_hash(str(out_dir), str(xodr))

    xodr.write_text("version two, totally different content", encoding="utf-8")
    second = get_map_hash(str(out_dir), str(xodr))

    assert second == first  # stale: still reports the ORIGINAL content's hash


# ---------------------------------------------------------------------------
# append_event
# ---------------------------------------------------------------------------

def test_append_event_writes_one_jsonl_line(tmp_path: Path):
    out_dir = tmp_path / "run_abc"
    append_event(str(out_dir), _record())

    events_path = out_dir / "artifacts" / "run_abc" / "map_events.jsonl"
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["road_id"] == "1"
    assert parsed["event_type"] == "removed"


def test_append_event_appends_across_multiple_calls(tmp_path: Path):
    out_dir = tmp_path / "run_abc"
    append_event(str(out_dir), _record(road_id="1"))
    append_event(str(out_dir), _record(road_id="2"))

    events_path = out_dir / "artifacts" / "run_abc" / "map_events.jsonl"
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["road_id"] == "1"
    assert json.loads(lines[1])["road_id"] == "2"


def test_append_event_never_raises_on_unwritable_dir(tmp_path: Path):
    # out_dir points through a file (not a directory) -- os.makedirs must fail internally,
    # but append_event swallows it (best-effort artifact logging, must not crash the pipeline).
    blocker = tmp_path / "blocker_file"
    blocker.write_text("x", encoding="utf-8")
    bad_out_dir = blocker / "nested"
    append_event(str(bad_out_dir), _record())  # must not raise


# ---------------------------------------------------------------------------
# build_record
# ---------------------------------------------------------------------------

def test_build_record_populates_run_id_from_out_dir_basename(tmp_path: Path):
    out_dir = tmp_path / "20260827T000000Z_run"
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")

    record = build_record(
        out_dir=str(out_dir), final_xodr_path=str(xodr),
        stage_name="carla_pruner", gate_name="carla_pruner", event_type="removed",
        road_id="1", lane_section_id="0", lane_id="-1", junction_id=None,
        s_from=0.0, s_to=5.0, removed_length_m=5.0, removed_length_pct=1.0,
    )

    assert record.run_id == "20260827T000000Z_run"
    assert record.map_hash is not None
    assert record.timestamp.endswith("Z")


def test_build_record_optional_fields_default_to_none(tmp_path: Path):
    out_dir = tmp_path / "run"
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")

    record = build_record(
        out_dir=str(out_dir), final_xodr_path=str(xodr),
        stage_name=None, gate_name=None, event_type="removed",
        road_id=None, lane_section_id=None, lane_id=None, junction_id=None,
        s_from=None, s_to=None, removed_length_m=None, removed_length_pct=None,
    )

    assert record.tile_id is None
    assert record.carla_failed_before_masking is None
    assert record.carla_failed_after_masking is None
