# -*- coding: utf-8 -*-
"""Frame synchronisation (NEW-261/262) and atomic phase journal (NEW-268).

The two invariants that matter scientifically:

* 6 cameras x 4 frames = 24 PNG files is **4** complete frames, never 24.
* Equal file counts with disjoint frame IDs is a FAIL, never a match.
* The phase journal must still contain the record you need after the engine
  dies, so every record is flushed + fsynced before returning.
"""
from __future__ import annotations

import json

import pytest

from ultimate_pipeline.perception.frame_sync import (
    assert_capture_complete,
    build_frame_correspondence,
    collect_frame_ids,
    common_frame_ids,
    evaluate_capture_completeness,
    extract_frame_id,
    scan_recording_directory,
    write_frame_correspondence,
)
from ultimate_pipeline.perception.phase_journal import (
    REQUIRED_PHASES,
    NullPhaseJournal,
    PhaseJournal,
    last_phase,
    read_journal,
)


# ---------------------------------------------------------------------------
# frame id extraction / collection
# ---------------------------------------------------------------------------


def test_extract_frame_id_takes_last_digit_run():
    assert extract_frame_id("rgb_front_left_camera/00000123.png") == 123
    assert extract_frame_id("cam_0007.ply") == 7


def test_extract_frame_id_falls_back_to_stem():
    assert extract_frame_id("0042.png") == 42
    assert extract_frame_id("no_digits.png") is None


def test_collect_frame_ids_scans_and_filters(tmp_path):
    cam = tmp_path / "cam"
    cam.mkdir()
    for i in range(3):
        (cam / f"{i:06d}.png").write_bytes(b"x")
    (cam / "notes.txt").write_bytes(b"x")

    ids, files = collect_frame_ids(cam)
    assert ids == {0, 1, 2}
    assert len(files) == 3  # .txt filtered out


def test_collect_frame_ids_on_missing_dir_is_empty_not_an_error(tmp_path):
    ids, files = collect_frame_ids(tmp_path / "nope")
    assert ids == set()
    assert files == []


# ---------------------------------------------------------------------------
# completeness verdict
# ---------------------------------------------------------------------------


def test_six_cameras_four_frames_is_four_complete_frames_not_twenty_four():
    sensor_frame_ids = {
        f"cam{i}": {0, 1, 2, 3} for i in range(6)
    }
    report = evaluate_capture_completeness(
        sensor_frame_ids, requested_frames=4, exact_set_required=True
    )
    assert report["verdict"] == "PASS"
    assert report["complete_frames"] == 4
    # The scientific count, not the file count.
    assert report["total_sensor_frames_sum"] == 24
    assert "file totals are never used as the scientific frame count" in report["counting_policy"]


def test_equal_counts_with_disjoint_frame_ids_fails():
    sensor_frame_ids = {
        "camA": {0, 1, 2, 3},
        "camB": {100, 101, 102, 103},  # same count, no overlap
    }
    report = evaluate_capture_completeness(sensor_frame_ids, requested_frames=4)
    assert report["verdict"] == "FAIL"
    assert report["complete_frames"] == 0
    assert any("complete_frames_below_requested" in r for r in report["reasons"])


def test_partial_overlap_reports_exact_missing_frames():
    report = evaluate_capture_completeness(
        {"camA": {1, 2, 3, 4}, "camB": {3, 4, 5, 6}},
        requested_frames=4,
        exact_set_required=True,
    )
    assert report["verdict"] == "FAIL"
    assert report["complete_frames"] == 2
    assert report["common_frame_ids"] == [3, 4]
    assert any(r.startswith("complete_frames_not_exact") for r in report["reasons"])


def test_governed_expected_set_must_match_exactly():
    report = evaluate_capture_completeness(
        {"camA": {1, 2, 3}},
        requested_frames=3,
        expected_frame_ids=[1, 2, 9],
    )
    assert report["verdict"] == "FAIL"
    assert "complete_frame_set_differs_from_governed_set" in report["reasons"]


def test_required_sensor_with_zero_frames_fails():
    report = evaluate_capture_completeness(
        {"camA": {1, 2, 3}, "camB": set()},
        required_sensors=["camA", "camB"],
        requested_frames=3,
    )
    assert report["verdict"] == "FAIL"
    assert report["empty_required_sensors"] == ["camB"]
    assert any("required_sensor_zero_frames" in r for r in report["reasons"])


def test_absent_required_sensor_fails():
    report = evaluate_capture_completeness(
        {"camA": {1, 2}},
        required_sensors=["camA", "cam_missing"],
        requested_frames=2,
    )
    assert report["verdict"] == "FAIL"
    assert report["missing_required_sensors"] == ["cam_missing"]


def test_common_frame_ids_intersection_is_order_and_key_independent():
    a = {"x": {1, 2, 3}, "y": {2, 3, 4}}
    assert common_frame_ids(a) == {2, 3}
    assert common_frame_ids({}) == set()


def test_assert_capture_complete_raises_with_reasons():
    report = evaluate_capture_completeness(
        {"camA": {1}}, requested_frames=5, exact_set_required=True
    )
    with pytest.raises(RuntimeError) as exc:
        assert_capture_complete(report)
    assert "capture_incomplete" in str(exc.value)
    assert "complete_frames=1" in str(exc.value)


def test_assert_capture_complete_passes_on_pass():
    report = evaluate_capture_completeness({"camA": {1, 2}}, requested_frames=2)
    assert_capture_complete(report)  # must not raise


# ---------------------------------------------------------------------------
# correspondence artifact
# ---------------------------------------------------------------------------


def test_build_frame_correspondence_marks_incomplete_rows():
    payload = build_frame_correspondence(
        {
            "camA": {0: "a/0.png", 1: "a/1.png", 2: "a/2.png"},
            "camB": {1: "b/1.png", 2: "b/2.png", 9: "b/9.png"},
        },
        required_sensors=["camA", "camB"],
        complete_only=False,
    )
    assert payload["complete_frames"] == 2
    assert [r["frame"] for r in payload["incomplete_rows"]] == [0, 9]
    assert payload["rejections"]["same_file_count_different_frame_ids"] is True


def test_build_frame_correspondence_complete_only_drops_incomplete(tmp_path):
    payload = build_frame_correspondence(
        {"camA": {0: "a/0.png", 1: "a/1.png"}, "camB": {1: "b/1.png"}},
        complete_only=True,
    )
    assert [r["frame"] for r in payload["rows"]] == [1]


def test_write_frame_correspondence_is_atomic(tmp_path):
    target = tmp_path / "sub" / "frame_correspondence.json"
    payload = {"schema": "FRAME_CORRESPONDENCE/v1", "complete_frames": 1}
    written = write_frame_correspondence(payload, target)
    assert written == target
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert not list(target.parent.glob("*.tmp"))  # temp file cleaned up


# ---------------------------------------------------------------------------
# directory scanning
# ---------------------------------------------------------------------------


def test_scan_recording_directory_two_level_layout(tmp_path):
    for kind in ("rgb", "semseg_raw"):
        for sensor in ("front_left_camera", "front_right_camera"):
            d = tmp_path / kind / sensor
            d.mkdir(parents=True)
            for i in range(3):
                (d / f"{i:06d}.png").write_bytes(b"x")

    result = scan_recording_directory(tmp_path)
    # Both kinds land under the same sensor key; the union is what matters.
    assert set(result) == {"front_left_camera", "front_right_camera"}
    assert set(result["front_left_camera"]) == {0, 1, 2}


def test_scan_recording_directory_explicit_sensor_dirs(tmp_path):
    d = tmp_path / "elsewhere"
    d.mkdir()
    for i in range(2):
        (d / f"{i:06d}.png").write_bytes(b"x")
    result = scan_recording_directory(
        tmp_path, sensor_dirs={"rgb_front": d}, required_sensors=["rgb_front"]
    )
    assert set(result["rgb_front"]) == {0, 1}


# ---------------------------------------------------------------------------
# phase journal (NEW-268)
# ---------------------------------------------------------------------------


def test_phase_journal_writes_one_line_per_record(tmp_path):
    path = tmp_path / "phase_journal.jsonl"
    with PhaseJournal(path) as journal:
        journal.record("MAP_LOAD_BEGIN", map="Grid0828")
        journal.record("CAPTURE_END", frames=4)
        assert journal.count == 2

    records = read_journal(path)
    assert [r["phase"] for r in records] == ["MAP_LOAD_BEGIN", "CAPTURE_END"]
    assert records[1]["frames"] == 4
    assert records[0]["seq"] == 0
    assert records[1]["seq"] == 1


def test_phase_journal_survives_a_kill_between_records(tmp_path):
    path = tmp_path / "phase_journal.jsonl"
    journal = PhaseJournal(path)
    journal.record("MAP_LOAD_BEGIN")
    journal.close()  # simulate the process going away

    # A later crash handler can still append; the earlier record is intact.
    resumed = PhaseJournal(path)
    resumed.record("MAP_LOAD_RETURN")
    resumed.close()

    records = read_journal(path)
    assert [r["phase"] for r in records] == ["MAP_LOAD_BEGIN", "MAP_LOAD_RETURN"]


def test_phase_journal_record_after_close_reopens_instead_of_dropping(tmp_path):
    path = tmp_path / "p.jsonl"
    journal = PhaseJournal(path)
    journal.close()
    journal.record("COMPLETE")
    journal.close()
    assert last_phase(path) == "COMPLETE"


def test_phase_journal_probe_and_pid_are_attached(tmp_path):
    path = tmp_path / "p.jsonl"
    with PhaseJournal(path, probe=lambda: {"vram_mb": 1000}, carla_pid=4242) as j:
        j.record("FIRST_SAMPLE")
    record = read_journal(path)[0]
    assert record["carla_pid"] == 4242
    assert record["vram_mb"] == 1000


def test_phase_journal_probe_failure_is_recorded_not_raised(tmp_path):
    def _boom():
        raise RuntimeError("probe dead")

    path = tmp_path / "p.jsonl"
    with PhaseJournal(path, probe=_boom) as j:
        j.record("FIRST_SAMPLE")
    record = read_journal(path)[0]
    assert record["probe_error"].startswith("RuntimeError:")


def test_phase_journal_truncates_after_max_records(tmp_path):
    path = tmp_path / "p.jsonl"
    journal = PhaseJournal(path, max_records=3)
    for i in range(5):
        journal.record(f"PHASE_{i}")
    journal.close()

    records = read_journal(path)
    phases = [r["phase"] for r in records]
    # The first max_records are kept verbatim; later writes collapse into a
    # JOURNAL_TRUNCATED marker instead of growing without bound.
    assert phases[:3] == ["PHASE_0", "PHASE_1", "PHASE_2"]
    assert phases.count("JOURNAL_TRUNCATED") == len(phases) - 3
    assert all(r.get("dropped") == 3 for r in records if r["phase"] == "JOURNAL_TRUNCATED")


def test_phase_journal_context_records_exception(tmp_path):
    path = tmp_path / "p.jsonl"
    with pytest.raises(ValueError):
        with PhaseJournal(path) as j:
            j.record("MAP_LOAD_BEGIN")
            raise ValueError("engine died")
    records = read_journal(path)
    assert [r["phase"] for r in records] == ["MAP_LOAD_BEGIN", "EXCEPTION"]
    assert "ValueError:engine died" in records[1]["error"]


def test_missing_required_phases_lists_every_absent_phase(tmp_path):
    path = tmp_path / "p.jsonl"
    journal = PhaseJournal(path)
    journal.record("MAP_LOAD_BEGIN")
    journal.record("COMPLETE")
    missing = journal.missing_required_phases()
    assert missing == [p for p in REQUIRED_PHASES if p not in ("MAP_LOAD_BEGIN", "COMPLETE")]
    assert len(missing) == len(REQUIRED_PHASES) - 2
    journal.close()


def test_read_journal_tolerates_unparseable_lines(tmp_path):
    path = tmp_path / "p.jsonl"
    path.write_text('{"phase":"A"}\nnot json at all\n{"phase":"B"}\n', encoding="utf-8")
    records = read_journal(path)
    assert [r.get("phase") for r in records] == ["A", "UNPARSEABLE", "B"]


def test_last_phase_ignores_records_without_a_phase(tmp_path):
    path = tmp_path / "p.jsonl"
    path.write_text('{"seq":1}\n{"phase":"COMPLETE"}\n', encoding="utf-8")
    assert last_phase(path) == "COMPLETE"
    assert last_phase(tmp_path / "missing.jsonl") is None


def test_null_phase_journal_is_a_drop_in_noop():
    journal = NullPhaseJournal()
    with journal as j:
        assert j.record("ANY") == {"phase": "ANY"}
    assert journal.count == 0
    assert journal.phases_seen() == []
    journal.flush()
    journal.close()
