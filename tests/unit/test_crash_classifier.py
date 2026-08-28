"""ultimate_pipeline/core/crash_classifier.py -- priority-ordered regex classifier that
triages CARLA/SUMO crash log text into thesis-friendly failure categories. Used by
main_pipeline.py. Found while chasing an orphaned test named test_xodr_carla_fatal_patterns in
tests/quality/__pycache__ (no source module was ever found with a matching name); this module
is the closest genuine match by purpose (classifying crash-log text into categories including
ENGINE_FATAL) and had zero coverage anywhere on this branch regardless.
"""
from __future__ import annotations

from ultimate_pipeline.core.crash_classifier import CrashClassifier


# ---------------------------------------------------------------------------
# classify -- CARLA rules, in priority order
# ---------------------------------------------------------------------------

def test_classify_s_invariant_takes_top_priority():
    log = "Exception thrown: s >= 0.0 failed at road 42"
    assert CrashClassifier.classify(carla_log=log) == CrashClassifier.S_INVARIANT


def test_classify_lane_offset_error():
    log = "invalid lane offset detected"
    assert CrashClassifier.classify(carla_log=log) == CrashClassifier.LANE_OFFSET_ERROR


def test_classify_planview_error():
    log = "PlanView geometry invalid at s=120.5"
    assert CrashClassifier.classify(carla_log=log) == CrashClassifier.PLANVIEW_ERROR


def test_classify_float_error():
    log = "computed value is nan, aborting"
    assert CrashClassifier.classify(carla_log=log) == CrashClassifier.FLOAT_ERROR


def test_classify_physx_error():
    log = "PhysX heightfield collision failed"
    assert CrashClassifier.classify(carla_log=log) == CrashClassifier.PHYSX_ERROR


def test_classify_geometry_overflow():
    log = "triangulation failed: degenerate polygon"
    assert CrashClassifier.classify(carla_log=log) == CrashClassifier.GEOMETRY_OVERFLOW


def test_classify_file_io_error():
    log = "copy_opendrive_to_file: permission denied"
    assert CrashClassifier.classify(carla_log=log) == CrashClassifier.FILE_IO_ERROR


def test_classify_engine_fatal():
    log = "LowLevelFatalError [File:Unknown] [Line: 123]"
    assert CrashClassifier.classify(carla_log=log) == CrashClassifier.ENGINE_FATAL


def test_classify_case_insensitive():
    log = "EXCEPTION THROWN: S >= 0.0"
    assert CrashClassifier.classify(carla_log=log) == CrashClassifier.S_INVARIANT


def test_classify_priority_order_s_invariant_before_float_error():
    # log matches BOTH an S_INVARIANT pattern and a FLOAT_ERROR pattern (nan) --
    # S_INVARIANT is listed first in _CARLA_RULES and must win.
    log = "Exception thrown: s >= 0.0 (value was nan)"
    assert CrashClassifier.classify(carla_log=log) == CrashClassifier.S_INVARIANT


# ---------------------------------------------------------------------------
# classify -- SUMO rules
# ---------------------------------------------------------------------------

def test_classify_sumo_geometry_overflow():
    log = "Error: geometry of edge 42 is invalid"
    assert CrashClassifier.classify(sumo_log=log) == CrashClassifier.GEOMETRY_OVERFLOW


def test_classify_sumo_missing_link():
    log = "edge 17 has no successor"
    assert CrashClassifier.classify(sumo_log=log) == CrashClassifier.MISSING_LINK


def test_classify_sumo_junction_ref_error():
    log = "connectingRoad reference is invalid"
    assert CrashClassifier.classify(sumo_log=log) == CrashClassifier.JUNCTION_REF_ERROR


def test_classify_sumo_lane_width_error():
    log = "lane width is negative"
    assert CrashClassifier.classify(sumo_log=log) == CrashClassifier.LANE_WIDTH_ERROR


# ---------------------------------------------------------------------------
# classify -- CARLA takes priority over SUMO; empty/unknown handling
# ---------------------------------------------------------------------------

def test_classify_carla_log_checked_before_sumo_log():
    carla = "LowLevelFatalError"
    sumo = "edge 17 has no successor"
    # Both logs match a rule -- CARLA rules are checked first and must win.
    assert CrashClassifier.classify(carla_log=carla, sumo_log=sumo) == CrashClassifier.ENGINE_FATAL


def test_classify_falls_through_to_sumo_when_carla_log_has_no_match():
    carla = "everything looks fine here"
    sumo = "edge 17 has no successor"
    assert CrashClassifier.classify(carla_log=carla, sumo_log=sumo) == CrashClassifier.MISSING_LINK


def test_classify_no_logs_returns_unknown():
    assert CrashClassifier.classify() == CrashClassifier.UNKNOWN


def test_classify_empty_string_logs_returns_unknown():
    assert CrashClassifier.classify(carla_log="", sumo_log="") == CrashClassifier.UNKNOWN


def test_classify_unmatched_text_returns_unknown():
    assert CrashClassifier.classify(carla_log="the server started successfully") == CrashClassifier.UNKNOWN


# ---------------------------------------------------------------------------
# extract_recent_log
# ---------------------------------------------------------------------------

def test_extract_recent_log_missing_path_returns_empty():
    assert CrashClassifier.extract_recent_log("") == ""


def test_extract_recent_log_nonexistent_file_returns_empty():
    assert CrashClassifier.extract_recent_log("C:/definitely/not/a/real/path.log") == ""


def test_extract_recent_log_reads_full_file_under_tail_limit(tmp_path):
    log_file = tmp_path / "carla.log"
    log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
    text = CrashClassifier.extract_recent_log(str(log_file), tail=200)
    assert text == "line1\nline2\nline3\n"


def test_extract_recent_log_respects_tail_limit(tmp_path):
    log_file = tmp_path / "carla.log"
    lines = [f"line{i}\n" for i in range(10)]
    log_file.write_text("".join(lines), encoding="utf-8")
    text = CrashClassifier.extract_recent_log(str(log_file), tail=3)
    assert text == "line7\nline8\nline9\n"
