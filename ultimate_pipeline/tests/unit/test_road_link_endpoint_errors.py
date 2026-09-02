# ultimate_pipeline/quality/road_link_endpoint_errors.py -- zero prior
# test coverage. Live: stage_09_tiling.py calls write_road_link_endpoint_errors()
# unconditionally (RQ1-adjacent map-quality diagnostic, always runs before
# tiling) and repair_road_link_targets() conditionally behind
# UP_ENABLE_ROAD_LINK_TARGET_REPAIR.
#
# The core per-link geometry semantics (_from_endpoint_for_link,
# _endpoint_s, _expected_heading_delta_rad, _normalize_contact_point) were
# cross-checked against the already-established, independently-written
# equivalents in quality/check_geometric_continuity.py
# (_source_endpoint_for_link, _endpoint_s, _expected_heading_delta_rad,
# _normalize_contact_point) and found to match exactly -- strong evidence
# this file's road-link-endpoint math is correct. repair_road_link_targets()
# is newer/unique logic (contactPoint flipping, nearby-endpoint search,
# self-link prevention); reviewed carefully for the "wrong end/wrong
# entity" bug class found elsewhere this session -- no bug found on
# inspection, confirmed by these tests via direct reproduction.
from __future__ import annotations

import json
import math
from pathlib import Path

from ultimate_pipeline.quality.road_link_endpoint_errors import (
    build_road_link_endpoint_errors,
    repair_road_link_targets,
    write_road_link_endpoint_errors,
)


def _road(rid: str, x0: float, y0: float, hdg0: float, length: float, *,
          succ: tuple[str, str] | None = None,
          pred: tuple[str, str] | None = None) -> str:
    """succ/pred: (elementId, contactPoint) or None."""
    link_inner = ""
    if pred is not None:
        eid, cp = pred
        link_inner += f'<predecessor elementType="road" elementId="{eid}" contactPoint="{cp}"/>'
    if succ is not None:
        eid, cp = succ
        link_inner += f'<successor elementType="road" elementId="{eid}" contactPoint="{cp}"/>'
    link_xml = f"<link>{link_inner}</link>" if link_inner else ""
    return (
        f'<road name="R{rid}" length="{length}" id="{rid}" junction="-1">'
        f'{link_xml}'
        f'<planView><geometry s="0" x="{x0}" y="{y0}" hdg="{hdg0}" length="{length}"><line/></geometry></planView>'
        f'</road>'
    )


def _write_xodr(path: Path, roads_xml: str) -> None:
    path.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><OpenDRIVE>{roads_xml}</OpenDRIVE>',
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# build_road_link_endpoint_errors / write_road_link_endpoint_errors
# ---------------------------------------------------------------------------

def test_well_aligned_successor_link_has_zero_dxy_and_dhdg(tmp_path: Path):
    # A (0,0)->(10,0) heading 0; A's successor is B, contactPoint=start;
    # B starts exactly at (10,0) heading 0 -- perfectly continuous.
    roads = (
        _road("1", 0, 0, 0, 10, succ=("2", "start"))
        + _road("2", 10, 0, 0, 10, pred=("1", "end"))
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)

    report = build_road_link_endpoint_errors(str(xodr))

    assert report["num_road_links"] == 2  # A's successor + B's predecessor
    link = next(l for l in report["links"] if l["from_road_id"] == "1")
    assert link["status"] == "ok"
    assert link["dxy_m"] == 0.0
    assert link["dhdg_rad"] == 0.0


def test_misaligned_successor_link_reports_nonzero_dxy(tmp_path: Path):
    # B is displaced 5m from where A's successor link says it should be.
    roads = (
        _road("1", 0, 0, 0, 10, succ=("2", "start"))
        + _road("2", 15, 0, 0, 10)
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)

    report = build_road_link_endpoint_errors(str(xodr))

    link = next(l for l in report["links"] if l["from_road_id"] == "1")
    assert link["status"] == "ok"
    assert link["dxy_m"] == 5.0
    assert report["summary"]["dxy_m"]["max"] == 5.0


def test_missing_target_road_counted_and_reported(tmp_path: Path):
    roads = _road("1", 0, 0, 0, 10, succ=("999", "start"))
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)

    report = build_road_link_endpoint_errors(str(xodr))

    assert report["num_missing_targets"] == 1
    link = report["links"][0]
    assert link["status"] == "missing_target_road"
    assert link["dxy_m"] is None


def test_invalid_contact_point_counted_and_defaults_to_start(tmp_path: Path):
    roads = (
        _road("1", 0, 0, 0, 10, succ=("2", "sideways"))
        + _road("2", 10, 0, 0, 10)
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)

    report = build_road_link_endpoint_errors(str(xodr))

    assert report["num_invalid_contact_point"] == 1
    link = next(l for l in report["links"] if l["from_road_id"] == "1")
    assert link["contact_point"] is None
    assert link["contact_point_defaulted"] is True
    assert link["to_endpoint"] == "start"


def test_opposite_direction_heading_expected_for_end_end_join(tmp_path: Path):
    # A's successor is B with contactPoint="end": B's END touches A's end,
    # meaning B runs "backward" relative to A -- a 180 deg heading delta
    # is geometrically correct, not an error, at that shared point.
    # B: heading pi (pointing back toward A) with length 10 starting at
    # (20,0) so that B's END (s=length, walking "backward" along heading
    # pi for 10m from (20,0)) lands at (10,0) == A's end. hdg is radians.
    roads = (
        _road("1", 0, 0, 0, 10, succ=("2", "end"))
        + _road("2", 20, 0, math.pi, 10)
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)

    report = build_road_link_endpoint_errors(str(xodr))

    link = next(l for l in report["links"] if l["from_road_id"] == "1")
    assert link["status"] == "ok"
    assert link["dxy_m"] < 1e-6
    # dhdg_rad is the residual AFTER subtracting the expected pi delta --
    # near zero here confirms the expected-delta formula is being applied,
    # not ignored (a naive same-heading check would report ~pi error).
    assert link["dhdg_rad"] < 1e-6


def test_top_offenders_sorted_worst_first(tmp_path: Path):
    roads = (
        _road("1", 0, 0, 0, 10, succ=("2", "start"))
        + _road("2", 12, 0, 0, 10)  # 2m gap
        + _road("3", 0, 100, 0, 10, succ=("4", "start"))
        + _road("4", 20, 100, 0, 10)  # 10m gap
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)

    report = build_road_link_endpoint_errors(str(xodr), top_k=1)

    assert len(report["top_offenders"]) == 1
    assert report["top_offenders"][0]["from_road_id"] == "3"
    assert report["top_offenders"][0]["dxy_m"] == 10.0


def test_write_road_link_endpoint_errors_creates_output_dir_and_file(tmp_path: Path):
    roads = _road("1", 0, 0, 0, 10)
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)
    out_json = tmp_path / "nested" / "dir" / "report.json"

    result = write_road_link_endpoint_errors(xodr_path=str(xodr), out_json=str(out_json))

    assert out_json.is_file()
    on_disk = json.loads(out_json.read_text(encoding="utf-8"))
    assert on_disk["num_roads"] == 1
    assert result["num_roads"] == 1


# ---------------------------------------------------------------------------
# repair_road_link_targets
# ---------------------------------------------------------------------------

def test_repair_flips_contact_point_when_that_fixes_alignment(tmp_path: Path):
    # A's successor points to B with contactPoint="start", but B's START
    # is far away while B's END happens to sit exactly where A's successor
    # should connect -- a contactPoint flip (not a retarget) is the
    # correct, minimal fix.
    # B's END (not start) sits exactly where A's successor should connect:
    # B heading pi (radians), length 10, x0=20 -> B's end (walking 10m
    # along heading pi from (20,0)) lands at (10,0) == A's end.
    roads = (
        _road("1", 0, 0, 0, 10, succ=("2", "start"))
        + _road("2", 20, 0, math.pi, 10)
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)
    out = tmp_path / "out.xodr"

    result = repair_road_link_targets(xodr_path=str(xodr), output_path=str(out), bad_dxy_threshold_m=1.0)

    assert result["applied"] is True
    assert result["num_repaired"] == 1

    report_after = build_road_link_endpoint_errors(str(out))
    link = next(l for l in report_after["links"] if l["from_road_id"] == "1")
    assert link["dxy_m"] < 1e-6
    assert link["contact_point"] == "end"


def test_repair_leaves_already_good_links_untouched(tmp_path: Path):
    roads = (
        _road("1", 0, 0, 0, 10, succ=("2", "start"))
        + _road("2", 10, 0, 0, 10)
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)
    out = tmp_path / "out.xodr"

    result = repair_road_link_targets(xodr_path=str(xodr), output_path=str(out), bad_dxy_threshold_m=1.0)

    assert result["applied"] is False
    assert result["num_repaired"] == 0


def test_repair_finds_nearby_endpoint_when_target_is_missing(tmp_path: Path):
    # A's successor points to a road that doesn't exist; a real road C
    # happens to start exactly where A ends.
    roads = (
        _road("1", 0, 0, 0, 10, succ=("999", "start"))
        + _road("3", 10, 0, 0, 10)
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)
    out = tmp_path / "out.xodr"

    result = repair_road_link_targets(
        xodr_path=str(xodr),
        output_path=str(out),
        bad_dxy_threshold_m=1.0,
        search_radius_start_m=1.0,
        search_radius_cap_m=5.0,
        search_radius_step_m=1.0,
    )

    assert result["applied"] is True
    report_after = build_road_link_endpoint_errors(str(out))
    link = next(l for l in report_after["links"] if l["from_road_id"] == "1")
    assert link["to_road_id"] == "3"
    assert link["status"] == "ok"


def test_repair_never_creates_a_new_self_link(tmp_path: Path):
    # A's successor points to a missing road; A's OWN endpoints happen to
    # be the only ones within search radius of A's own end (a contrived
    # single-road scenario) -- must not rewrite the link to point at
    # itself.
    roads = _road("1", 0, 0, 0, 10, succ=("999", "start"))
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)
    out = tmp_path / "out.xodr"

    result = repair_road_link_targets(
        xodr_path=str(xodr),
        output_path=str(out),
        bad_dxy_threshold_m=1.0,
        search_radius_start_m=1.0,
        search_radius_cap_m=50.0,
        search_radius_step_m=1.0,
    )

    assert result["num_repaired"] == 0
    report_after = build_road_link_endpoint_errors(str(out))
    link = report_after["links"][0]
    assert link["to_road_id"] == "999"  # untouched, still broken but not self-linked


def test_repair_respects_threshold_does_not_repair_if_no_candidate_within_radius(tmp_path: Path):
    roads = (
        _road("1", 0, 0, 0, 10, succ=("2", "start"))
        + _road("2", 1000, 1000, 0, 10)  # far outside any reasonable search radius
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)
    out = tmp_path / "out.xodr"

    result = repair_road_link_targets(
        xodr_path=str(xodr),
        output_path=str(out),
        bad_dxy_threshold_m=1.0,
        search_radius_start_m=1.0,
        search_radius_cap_m=5.0,
        search_radius_step_m=1.0,
    )

    assert result["num_repaired"] == 0


def test_repair_writes_jsonl_log_of_changes(tmp_path: Path):
    roads = (
        _road("1", 0, 0, 0, 10, succ=("999", "start"))
        + _road("3", 10, 0, 0, 10)
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)
    out = tmp_path / "out.xodr"
    log_path = tmp_path / "repair_log.jsonl"

    repair_road_link_targets(
        xodr_path=str(xodr),
        output_path=str(out),
        repair_log_jsonl=str(log_path),
        bad_dxy_threshold_m=1.0,
        search_radius_start_m=1.0,
        search_radius_cap_m=5.0,
        search_radius_step_m=1.0,
    )

    assert log_path.is_file()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["before"]["to_road_id"] == "999"
    assert entry["after"]["to_road_id"] == "3"


def test_repair_malformed_xodr_returns_error_dict_not_crash(tmp_path: Path):
    xodr = tmp_path / "bad.xodr"
    xodr.write_text("not valid xml <<<", encoding="utf-8")

    result = repair_road_link_targets(xodr_path=str(xodr))

    assert result["applied"] is False
    assert "error" in result
