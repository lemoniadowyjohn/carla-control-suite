from __future__ import annotations

import pytest

from ultimate_pipeline.core.opendrive_gen_diagnostic import (
    MIN_SUCCESSFUL_LOADS,
    classify_failure,
    detect_stall,
    determinism_verdict,
    load_diagnostic_release,
    summarize_loads_jsonl,
)


def _attempt(outcome, **kw):
    a = {
        "attempt": 1,
        "started_at": 0.0,
        "outcome": outcome,
        "duration_s": 600.0,
        "marker": "",
        "map_name": "OpenDriveMap",
        "vram_used_mb": -1,
        "cpu_pct": -1.0,
        "rss_mb": -1.0,
        "window_s": 7200.0,
        "diagnostics": {},
    }
    a.update(kw)
    return a


def test_classify_length_assert_dominant():
    assert classify_failure("LowLevelFatalError [Line:136] Exception thrown: s <= road->GetLength()") == "LENGTH_ASSERT"


def test_classify_oom():
    assert classify_failure("Fatal error: out of memory during mesh generation") == "OOM"
    assert classify_failure("LowLevelFatalError: Not enough memory to allocate") == "OOM"


def test_classify_rpc_timeout():
    assert classify_failure("RPC timed out after 300 seconds") == "RPC_TIMEOUT"


def test_classify_generic_fatal():
    assert classify_failure("LowLevelFatalError [Line:99] something unknown") == "GENERIC_FATAL"


def test_classify_empty_unknown():
    assert classify_failure("") == "UNKNOWN"
    assert classify_failure(None) == "UNKNOWN"


def test_determinism_requires_two_successes():
    one = [_attempt("SUCCESS", attempt=1)]
    dv = determinism_verdict(one)
    assert dv["verdict"] == "LOADS_INSUFFICIENT"
    assert len(one) < MIN_SUCCESSFUL_LOADS or dv["verdict"] == "LOADS_DETERMINISTIC"


def test_determinism_two_successes_pass():
    two = [_attempt("SUCCESS", attempt=1), _attempt("SUCCESS", attempt=2)]
    dv = determinism_verdict(two)
    assert dv["verdict"] == "LOADS_DETERMINISTIC"
    assert dv["successes"] == 2
    assert dv["map_names_uniform"]


def test_length_assert_blocks_even_with_successes():
    mixed = [
        _attempt("SUCCESS", attempt=1),
        _attempt("LENGTH_ASSERT", attempt=2, marker="s <= road->GetLength()"),
        _attempt("SUCCESS", attempt=3),
    ]
    dv = determinism_verdict(mixed)
    assert dv["verdict"] == "LOADS_LENGTH_ASSERT_FAILED"


def test_oom_recorded_in_memory_pattern():
    two = [_attempt("SUCCESS", attempt=1), _attempt("OOM", attempt=2)]
    dv = determinism_verdict(two)
    assert dv["memory_pattern"] == "OOM_PRESENT"


def test_crashed_after_two_successes_is_not_deterministic():
    two = [_attempt("SUCCESS", attempt=1), _attempt("SUCCESS", attempt=2), _attempt("GENERIC_FATAL", attempt=3)]
    dv = determinism_verdict(two)
    assert dv["verdict"] == "LOADS_CRASHED"


def test_stall_detection():
    flat = [{"t_s": 0.0, "rss_mb": 100.0}, {"t_s": 10.0, "rss_mb": 100.1}, {"t_s": 400.0, "rss_mb": 100.2}]
    assert detect_stall(flat, stall_s=300.0)
    growing = [{"t_s": 0.0, "rss_mb": 100.0}, {"t_s": 120.0, "rss_mb": 500.0}, {"t_s": 240.0, "rss_mb": 900.0}]
    assert not detect_stall(growing, stall_s=300.0)


def test_release_gate_blocks_insufficient_evidence():
    ev = {
        "loads": [_attempt("SUCCESS", attempt=1)],
        "candidate_sha256": "6bac3570",
        "runtime_sha256": "newruntime",
        "attempted_at_utc": "2026-08-13T00:00:00Z",
    }
    out = load_diagnostic_release(ev)
    assert not out["pass"]
    assert out["determinism"]["verdict"] == "LOADS_INSUFFICIENT"


def test_release_gate_blocks_length_assert_candidate():
    ev = {
        "loads": [
            _attempt("SUCCESS", attempt=1),
            _attempt("LENGTH_ASSERT", attempt=2, marker="s <= road->GetLength()"),
        ],
        "candidate_sha256": "80ebb00",
        "runtime_sha256": "x",
        "attempted_at_utc": "2026-08-13T00:00:00Z",
    }
    out = load_diagnostic_release(ev)
    assert not out["pass"]
    assert out["determinism"]["verdict"] == "LOADS_LENGTH_ASSERT_FAILED"


def test_release_gate_pass_two_successes(tmp_path):
    p = tmp_path / "loads.jsonl"
    p.write_text(
        "\n".join(
            [
                '{"attempt": 1, "outcome": "SUCCESS", "map_name": "OpenDriveMap"}',
                '{"attempt": 2, "outcome": "SUCCESS", "map_name": "OpenDriveMap"}',
                "",
            ]
        ),
        encoding="utf-8",
    )
    summ = summarize_loads_jsonl(str(p))
    assert summ["verdict"]["verdict"] == "LOADS_DETERMINISTIC"
    ev = {
        "loads": summ["attempts"],
        "candidate_sha256": "6bac3570",
        "runtime_sha256": "newruntime",
        "attempted_at_utc": "2026-08-13T00:00:00Z",
    }
    out = load_diagnostic_release(ev)
    assert out["pass"]
