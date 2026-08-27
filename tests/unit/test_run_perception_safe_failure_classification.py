"""ultimate_pipeline/tools/run_perception_safe.py -- supplemental coverage for
_classify_record_route_failure, _classify_map_probe_outcome, _known_capture_failure_reason,
and _extract_map_travel_risk_reason -- the pure diagnostic classifiers that determine WHY a
live-CARLA perception capture or map-loading probe failed. This session's history includes
extensive live-CARLA debugging where misdiagnosed failure causes wasted significant time -- a
priority-ordering bug in these classifiers (many overlapping string-match branches, evaluated
in a specific precedence order) could silently misattribute the wrong failure reason.
Supplemental to test_run_perception_safe_rig_contract.py (covers _rig_verification_contract_errors)
from earlier this session. run_perception_safe.py is 6,576 lines and mostly CARLA-dependent;
these four functions are pure string/dict/int classification logic with no CARLA calls. Found
via the orphaned-.pyc sweep.
"""
from __future__ import annotations

from ultimate_pipeline.tools.run_perception_safe import (
    _classify_map_probe_outcome,
    _classify_record_route_failure,
    _extract_map_travel_risk_reason,
    _known_capture_failure_reason,
)


def _record_route_kwargs(**overrides):
    base = dict(
        timed_out=False,
        proc_returncode=0,
        outputs_present=True,
        integrity_ok=True,
        integrity_reason="",
        first_measurement_ok=True,
        frames_recorded=10,
        stdout_text="",
        stderr_text="",
        skip_stream_check=False,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _classify_record_route_failure -- success and simple failure paths
# ---------------------------------------------------------------------------

def test_record_route_all_healthy_returns_empty_string():
    assert _classify_record_route_failure(**_record_route_kwargs()) == ""


def test_record_route_timeout_takes_priority_over_other_signals():
    result = _classify_record_route_failure(**_record_route_kwargs(timed_out=True))
    assert result == "record_route_timeout"


def test_record_route_nonzero_returncode_with_no_outputs():
    result = _classify_record_route_failure(
        **_record_route_kwargs(proc_returncode=1, outputs_present=False)
    )
    assert result == "record_route_nonzero"


def test_record_route_nonzero_returncode_but_outputs_present_falls_through():
    # outputs ARE present despite a nonzero code -- must not be classified as a hard failure
    # here; falls through to the integrity/frame checks below.
    result = _classify_record_route_failure(
        **_record_route_kwargs(proc_returncode=1, outputs_present=True)
    )
    assert result == ""


def test_record_route_integrity_failure_reports_the_given_reason():
    result = _classify_record_route_failure(
        **_record_route_kwargs(integrity_ok=False, integrity_reason="checksum_mismatch")
    )
    assert result == "checksum_mismatch"


def test_record_route_first_measurement_missing():
    result = _classify_record_route_failure(
        **_record_route_kwargs(first_measurement_ok=False)
    )
    assert result == "first_measurement_missing"


def test_record_route_zero_frames_recorded():
    result = _classify_record_route_failure(
        **_record_route_kwargs(frames_recorded=0)
    )
    assert result == "no_frames"


# ---------------------------------------------------------------------------
# _classify_record_route_failure -- stdout/stderr signal detection
# ---------------------------------------------------------------------------

def test_record_route_streaming_collapse_detected_in_stdout():
    result = _classify_record_route_failure(
        **_record_route_kwargs(stdout_text="ERROR: streaming_collapse_during_capture at frame 12")
    )
    assert result == "streaming_collapse_during_capture"


def test_record_route_streaming_collapse_detected_in_stderr():
    result = _classify_record_route_failure(
        **_record_route_kwargs(stderr_text="pre_spawn_stream_unavailable")
    )
    assert result == "streaming_collapse_during_capture"


def test_record_route_sensor_spawn_timeout_detected():
    result = _classify_record_route_failure(
        **_record_route_kwargs(stdout_text="thesis_rig_spawn_timeout after 30s")
    )
    assert result == "sensor_spawn_timeout"


def test_record_route_first_frame_timeout_detected():
    result = _classify_record_route_failure(
        **_record_route_kwargs(stderr_text="first_frame_timeout waiting for sensor callback")
    )
    assert result == "FIRST_FRAME_TIMEOUT"


def test_record_route_sensor_spawn_failed_missing_modalities():
    result = _classify_record_route_failure(
        **_record_route_kwargs(stdout_text="sensor_spawn_missing_required_modalities: lidar")
    )
    assert result == "sensor_spawn_failed"


def test_record_route_first_measurement_no_callbacks():
    result = _classify_record_route_failure(
        **_record_route_kwargs(stdout_text="first_measurement_no_callbacks after tick")
    )
    assert result == "no_callbacks"


def test_record_route_no_sensor_measurements_with_nonzero_code_skip_stream_check_true():
    result = _classify_record_route_failure(
        **_record_route_kwargs(
            stdout_text="no_sensor_measurements received", proc_returncode=1, skip_stream_check=True,
        )
    )
    assert result == "no_callbacks"


def test_record_route_no_sensor_measurements_with_nonzero_code_skip_stream_check_false():
    result = _classify_record_route_failure(
        **_record_route_kwargs(
            stdout_text="no_sensor_measurements received", proc_returncode=1, skip_stream_check=False,
        )
    )
    assert result == "streaming_unavailable"


def test_record_route_no_sensor_measurements_but_returncode_zero_does_not_trigger():
    # the no-callbacks signal only counts as a failure signal when paired with a nonzero code
    result = _classify_record_route_failure(
        **_record_route_kwargs(stdout_text="no_sensor_measurements received", proc_returncode=0)
    )
    assert result == ""


def test_record_route_streaming_refusal_with_nonzero_code_and_stream_check_enabled():
    result = _classify_record_route_failure(
        **_record_route_kwargs(
            stdout_text="streaming client: connection failed",
            proc_returncode=1,
            skip_stream_check=False,
        )
    )
    assert result == "streaming_unavailable"


def test_record_route_timeout_with_skip_stream_check_and_no_outputs_is_no_callbacks():
    result = _classify_record_route_failure(
        **_record_route_kwargs(timed_out=True, skip_stream_check=True, outputs_present=False)
    )
    assert result == "no_callbacks"


def test_record_route_case_insensitive_signal_matching():
    result = _classify_record_route_failure(
        **_record_route_kwargs(stdout_text="SENSOR_SPAWN_TIMEOUT DETECTED")
    )
    assert result == "sensor_spawn_timeout"


def test_record_route_streaming_collapse_takes_priority_over_sensor_spawn_timeout():
    # both signals present in the text -- streaming_collapse is checked first in the function.
    result = _classify_record_route_failure(
        **_record_route_kwargs(
            stdout_text="pre_spawn_stream_unavailable and also sensor_spawn_timeout"
        )
    )
    assert result == "streaming_collapse_during_capture"


# ---------------------------------------------------------------------------
# _classify_map_probe_outcome
# ---------------------------------------------------------------------------

def test_map_probe_timed_out_is_engine_fatal():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=True, returncode=0, probe_payload={}
    )
    assert verdict == "ENGINE_FATAL"
    assert detail == "map_probe_timeout"


def test_map_probe_empty_payload_is_engine_fatal():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False, returncode=0, probe_payload={}
    )
    assert verdict == "ENGINE_FATAL"
    assert detail == "map_probe_result_missing"


def test_map_probe_status_pass_is_success():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False, returncode=0, probe_payload={"status": "PASS"}
    )
    assert (verdict, detail) == ("", "")


def test_map_probe_ok_true_is_success_even_without_status():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False, returncode=0, probe_payload={"ok": True}
    )
    assert (verdict, detail) == ("", "")


def test_map_probe_mismatch_flag_reports_expected_vs_actual():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False,
        returncode=0,
        probe_payload={
            "mismatch": True,
            "expected_map_name": "Town10",
            "actual_map_name": "Town03",
        },
    )
    assert verdict == "WRONG_MAP_LOADED"
    assert "Town10" in detail and "Town03" in detail


def test_map_probe_mismatch_prefers_explicit_failure_detail_over_generated_message():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False,
        returncode=0,
        probe_payload={"mismatch": True, "failure_detail": "custom detail text"},
    )
    assert verdict == "WRONG_MAP_LOADED"
    assert detail == "custom detail text"


def test_map_probe_failure_reason_wrong_map_loaded():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False,
        returncode=0,
        probe_payload={"failure_reason": "WRONG_MAP_LOADED", "actual_map_name": "Town05"},
    )
    assert verdict == "WRONG_MAP_LOADED"
    assert detail == "Town05"


def test_map_probe_generic_failure_reason_is_engine_fatal_with_prefixed_detail():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False,
        returncode=0,
        probe_payload={"failure_reason": "some_other_reason", "failure_detail": "extra info"},
    )
    assert verdict == "ENGINE_FATAL"
    assert detail == "map_probe:some_other_reason:extra info"


def test_map_probe_crash_returncode_is_engine_fatal():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False, returncode=-1073741819, probe_payload={"status": "UNKNOWN"}
    )
    assert verdict == "ENGINE_FATAL"
    assert "map_probe_crash_returncode" in detail


def test_map_probe_generic_nonzero_returncode_is_engine_fatal():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False, returncode=1, probe_payload={"status": "UNKNOWN"}
    )
    assert verdict == "ENGINE_FATAL"
    assert "map_probe_nonzero_returncode:1" in detail


def test_map_probe_zero_returncode_unknown_status_is_success():
    # no explicit pass/fail signal and a clean returncode -- treated as success (empty verdict).
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False, returncode=0, probe_payload={"status": "UNKNOWN"}
    )
    assert (verdict, detail) == ("", "")


def test_map_probe_non_dict_payload_treated_as_missing():
    verdict, detail = _classify_map_probe_outcome(
        timed_out=False, returncode=0, probe_payload="not a dict"
    )
    assert verdict == "ENGINE_FATAL"
    assert detail == "map_probe_result_missing"


# ---------------------------------------------------------------------------
# _known_capture_failure_reason
# ---------------------------------------------------------------------------

def test_known_capture_failure_reason_non_dict_payload_returns_empty():
    assert _known_capture_failure_reason(None) == ""
    assert _known_capture_failure_reason("not a dict") == ""


def test_known_capture_failure_reason_status_ok_returns_empty_even_with_reason():
    payload = {"status": "OK", "failure_reason": "NO_FRAMES_RECEIVED"}
    assert _known_capture_failure_reason(payload) == ""


def test_known_capture_failure_reason_fail_status_known_reason_returned():
    payload = {"status": "FAIL", "failure_reason": "NO_FRAMES_RECEIVED"}
    assert _known_capture_failure_reason(payload) == "NO_FRAMES_RECEIVED"


def test_known_capture_failure_reason_skip_status_also_accepted():
    payload = {"status": "SKIP", "failure_reason": "LISTEN_FAILED"}
    assert _known_capture_failure_reason(payload) == "LISTEN_FAILED"


def test_known_capture_failure_reason_sensor_spawn_timeout_normalized_to_lowercase():
    payload = {"status": "FAIL", "failure_reason": "SENSOR_SPAWN_TIMEOUT"}
    assert _known_capture_failure_reason(payload) == "sensor_spawn_timeout"


def test_known_capture_failure_reason_map_travel_risk_prefix_passthrough():
    payload = {"status": "FAIL", "failure_reason": "MAP_TRAVEL_RISK_GRID0828"}
    assert _known_capture_failure_reason(payload) == "MAP_TRAVEL_RISK_GRID0828"


def test_known_capture_failure_reason_unrecognized_reason_returns_empty():
    payload = {"status": "FAIL", "failure_reason": "SOME_NOVEL_UNRECOGNIZED_REASON"}
    assert _known_capture_failure_reason(payload) == ""


def test_known_capture_failure_reason_case_insensitive_status_and_reason():
    payload = {"status": "fail", "failure_reason": "no_frames_received"}
    assert _known_capture_failure_reason(payload) == "NO_FRAMES_RECEIVED"


# ---------------------------------------------------------------------------
# _extract_map_travel_risk_reason
# ---------------------------------------------------------------------------

def test_extract_map_travel_risk_reason_finds_known_pattern():
    text = "capture aborted: MAP_TRAVEL_RISK_GRID0828 detected during spawn"
    assert _extract_map_travel_risk_reason(text) == "MAP_TRAVEL_RISK_GRID0828"


def test_extract_map_travel_risk_reason_no_match_returns_empty():
    assert _extract_map_travel_risk_reason("some unrelated error text") == ""


def test_extract_map_travel_risk_reason_handles_none_input():
    assert _extract_map_travel_risk_reason(None) == ""


def test_extract_map_travel_risk_reason_handles_non_string_input():
    assert _extract_map_travel_risk_reason(12345) == ""
