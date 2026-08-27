"""ultimate_pipeline/determinism/stage_digest.py -- fingerprints a thesis stage directory's
well-known artifact files into a single stage_digest_sha256, used to compare determinism across
runs while deliberately excluding wall-clock generated_at_utc from the comparison. Found
untested via the orphaned-.pyc sweep.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ultimate_pipeline.determinism.stage_digest import (
    SOURCE_FILES,
    generate_stage_hashes,
)


def test_generate_stage_hashes_creates_stage_dir_if_missing(tmp_path: Path):
    stage_dir = tmp_path / "nested" / "stage"
    payload = generate_stage_hashes(stage_dir)
    assert stage_dir.is_dir()
    assert payload["files"] == []


def test_generate_stage_hashes_only_includes_known_source_files(tmp_path: Path):
    (tmp_path / "run_metadata.json").write_text("{}", encoding="utf-8")
    (tmp_path / "not_a_tracked_file.json").write_text("{}", encoding="utf-8")

    payload = generate_stage_hashes(tmp_path)

    relpaths = {f["relpath"] for f in payload["files"]}
    assert relpaths == {"run_metadata.json"}


def test_generate_stage_hashes_missing_files_silently_skipped(tmp_path: Path):
    # None of SOURCE_FILES exist -- must not raise, just produce an empty file list.
    payload = generate_stage_hashes(tmp_path)
    assert payload["files"] == []
    assert payload["stage_digest_sha256"] == hashlib.sha256(b"").hexdigest()


def test_generate_stage_hashes_records_correct_sha256_and_bytes(tmp_path: Path):
    content = b'{"key": "value"}'
    (tmp_path / "run_metadata.json").write_bytes(content)

    payload = generate_stage_hashes(tmp_path)

    entry = payload["files"][0]
    assert entry["sha256"] == hashlib.sha256(content).hexdigest()
    assert entry["bytes"] == len(content)


def test_generate_stage_hashes_files_sorted_by_relpath(tmp_path: Path):
    # SOURCE_FILES iteration order is `sorted(SOURCE_FILES)`, not declaration order.
    for name in ("carla_status.json", "full_report.json", "determinism_summary.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")

    payload = generate_stage_hashes(tmp_path)

    relpaths = [f["relpath"] for f in payload["files"]]
    assert relpaths == sorted(relpaths)


def test_generate_stage_hashes_writes_stage_hashes_json_to_disk(tmp_path: Path):
    (tmp_path / "run_metadata.json").write_text("{}", encoding="utf-8")

    payload = generate_stage_hashes(tmp_path)

    out_file = tmp_path / "stage_hashes.json"
    assert out_file.is_file()
    on_disk = json.loads(out_file.read_text(encoding="utf-8"))
    assert on_disk["stage_digest_sha256"] == payload["stage_digest_sha256"]


def test_generate_stage_hashes_digest_is_stable_across_repeated_calls_with_same_content(tmp_path: Path):
    (tmp_path / "run_metadata.json").write_text('{"a": 1}', encoding="utf-8")
    payload1 = generate_stage_hashes(tmp_path)
    payload2 = generate_stage_hashes(tmp_path)
    # generated_at_utc differs (wall clock) but stage_digest_sha256 is content-only and stable.
    assert payload1["stage_digest_sha256"] == payload2["stage_digest_sha256"]


def test_generate_stage_hashes_digest_changes_when_a_tracked_file_content_changes(tmp_path: Path):
    (tmp_path / "run_metadata.json").write_text('{"a": 1}', encoding="utf-8")
    payload1 = generate_stage_hashes(tmp_path)

    (tmp_path / "run_metadata.json").write_text('{"a": 2}', encoding="utf-8")
    payload2 = generate_stage_hashes(tmp_path)

    assert payload1["stage_digest_sha256"] != payload2["stage_digest_sha256"]


def test_generate_stage_hashes_digest_changes_when_a_new_tracked_file_appears(tmp_path: Path):
    (tmp_path / "run_metadata.json").write_text('{"a": 1}', encoding="utf-8")
    payload1 = generate_stage_hashes(tmp_path)

    (tmp_path / "full_report.json").write_text('{"b": 2}', encoding="utf-8")
    payload2 = generate_stage_hashes(tmp_path)

    assert payload1["stage_digest_sha256"] != payload2["stage_digest_sha256"]


def test_source_files_list_has_no_duplicates():
    assert len(SOURCE_FILES) == len(set(SOURCE_FILES))
