from __future__ import annotations

import pytest

from run_n_certify import _length_invariant_evidence
from ultimate_pipeline.core.opendrive_gen_diagnostic import (
    MIN_SUCCESSFUL_LOADS,
    classify_failure,
    detect_stall,
    determinism_verdict,
    load_diagnostic_release,
    sample_vram_mb,
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


def test_summarize_loads_jsonl_fields(tmp_path):
    p = tmp_path / "loads.jsonl"
    p.write_text(
        "\n".join(
            [
                '{"attempt": 1, "outcome": "SUCCESS", "map_name": "OpenDriveMap", "started_at": 0.0}',
                '{"attempt": 2, "outcome": "SUCCESS", "map_name": "OpenDriveMap", "started_at": 10.0}',
                '{"attempt": 3, "outcome": "OOM", "map_name": "OpenDriveMap", "started_at": 20.0}',
                "",
            ]
        ),
        encoding="utf-8",
    )
    summ = summarize_loads_jsonl(str(p))
    assert [a["attempt"] for a in summ["attempts"]] == [1, 2, 3]
    assert [a["outcome"] for a in summ["attempts"]] == ["SUCCESS", "SUCCESS", "OOM"]
    dv = summ["verdict"]
    assert dv["verdict"] == "LOADS_CRASHED"
    assert dv["successes"] == 2
    assert dv["memory_pattern"] == "OOM_PRESENT"


def test_sample_vram_mb_returns_int():
    vram = sample_vram_mb()
    assert isinstance(vram, int)
    assert vram == -1 or vram >= 0


def _minimal_xodr(roads):
    """roads: iterable of (length, [(s, length), ...]) -> minimal XODR text."""
    body = []
    for rlen, geoms in roads:
        plan = "".join(
            f'<geometry s="{s}" length="{glen}" x="0" y="0" hdg="0"/>' for s, glen in geoms
        )
        body.append(f'<road id="r" length="{rlen}"><planView>{plan}</planView></road>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<OpenDRIVE>" + "".join(body) + "</OpenDRIVE>"
    )


def test_length_invariant_exceeding_geometry_violates(tmp_path):
    p = tmp_path / "violating.xodr"
    p.write_text(_minimal_xodr([("100.0", [("0.0", "150.0")])]), encoding="utf-8")
    out = _length_invariant_evidence(str(p))
    assert out["violations"] >= 1
    assert out["roads_checked"] == 1


def test_length_invariant_compliant_road_clean(tmp_path):
    p = tmp_path / "compliant.xodr"
    p.write_text(
        _minimal_xodr([("100.0", [("0.0", "100.0"), ("100.0", "0.0")])]),
        encoding="utf-8",
    )
    out = _length_invariant_evidence(str(p))
    assert out["violations"] == 0
    assert out["roads_checked"] == 1


def test_length_invariant_zero_length_zero_geometry_no_violation(tmp_path):
    # Degenerate: a zero-length road whose geometry also has zero extent does
    # not exceed the length (0 > 1e-9 is false), so no violation. It is still
    # counted in roads_checked. This is the ONLY non-positive case that is clean.
    p = tmp_path / "zero_length.xodr"
    p.write_text(_minimal_xodr([("0.0", [("0.0", "0.0")])]), encoding="utf-8")
    out = _length_invariant_evidence(str(p))
    assert out["violations"] == 0
    assert out["roads_checked"] == 1


def test_length_invariant_non_positive_length_with_geometry_violates(tmp_path):
    # Crash-safe intent: a road with length <= 0 that carries real geometry WILL
    # trip CARLA's `s <= GetLength()` assert, so it MUST register a violation
    # (not be exempted). Locks the corrected G19 semantics against regression.
    p = tmp_path / "nonpos.xodr"
    p.write_text(_minimal_xodr([("0.0", [("0.0", "10.0")])]), encoding="utf-8")
    out = _length_invariant_evidence(str(p))
    assert out["violations"] >= 1
    assert out["roads_checked"] == 1


def test_length_invariant_negative_length_with_geometry_violates(tmp_path):
    p = tmp_path / "neg.xodr"
    p.write_text(_minimal_xodr([("-5.0", [("0.0", "1.0")])]), encoding="utf-8")
    out = _length_invariant_evidence(str(p))
    assert out["violations"] >= 1
    assert out["roads_checked"] == 1


def test_length_invariant_missing_length_skipped(tmp_path):
    # A road with no parseable length attribute cannot be evaluated: it is
    # skipped entirely and NOT counted in roads_checked.
    p = tmp_path / "missing.xodr"
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><OpenDRIVE>'
        '<road id="r"><planView><geometry s="0.0" length="10.0" x="0" y="0" hdg="0"/>'
        "</planView></road></OpenDRIVE>",
        encoding="utf-8",
    )
    out = _length_invariant_evidence(str(p))
    assert out["roads_checked"] == 0
    assert out["violations"] == 0
