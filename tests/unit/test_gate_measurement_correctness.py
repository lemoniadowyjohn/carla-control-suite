from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.diagnostics.elevation_summary import summarize_elevation
from ultimate_pipeline.quality.full_map_metrics import FullMapMetricsScanner
from ultimate_pipeline.quality.check_elevation_continuity import check_elevation_continuity
from ultimate_pipeline.debug.check_s_invariants import scan_s_invariants
from ultimate_pipeline.quality.map_acceptance import build_map_acceptance
from ultimate_pipeline.tools.crash_safe_length_repair import length_invariant_summary


def _write(tmp_path: Path, name: str, xml_text: str) -> str:
    path = tmp_path / name
    path.write_text(xml_text, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 1. summarize_elevation: real min/max/span from <elevation> records
# ---------------------------------------------------------------------------


def test_summarize_elevation_reports_true_min_max_span_on_sloped_fixture(tmp_path: Path) -> None:
    """A road climbing from 361.85 to 408.67 via a single sloped elevation
    record must report those as the true min/max, not just the 'a' coefficient
    at each record's local start (which misses the rise across b/c/d)."""
    xodr = _write(
        tmp_path,
        "sloped.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE><road id=\"1\" length=\"100.0\" junction=\"-1\">"
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="100.0"><line/></geometry></planView>'
        "<elevationProfile>"
        '<elevation s="0" a="361.85" b="0.4682" c="0.0" d="0.0"/>'
        "</elevationProfile>"
        "</road></OpenDRIVE>",
    )

    summary = summarize_elevation(xodr)

    assert summary["min"] == pytest.approx(361.85, abs=1e-6)
    assert summary["max"] == pytest.approx(408.67, abs=1e-6)
    assert summary["span"] == pytest.approx(408.67 - 361.85, abs=1e-6)
    assert summary["elevation_segment_count"] == 1


def test_summarize_elevation_flat_map_min_equals_max(tmp_path: Path) -> None:
    """Positive control: a flat map (constant a, zero b/c/d everywhere) must
    report min == max (span ~ 0), proving the gate isn't just always wide."""
    xodr = _write(
        tmp_path,
        "flat.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="50.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="50.0"><line/></geometry></planView>'
        "<elevationProfile>"
        '<elevation s="0" a="380.0" b="0.0" c="0.0" d="0.0"/>'
        "</elevationProfile>"
        "</road>"
        '<road id="2" length="30.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="30.0"><line/></geometry></planView>'
        "<elevationProfile>"
        '<elevation s="0" a="380.0" b="0.0" c="0.0" d="0.0"/>'
        "</elevationProfile>"
        "</road>"
        "</OpenDRIVE>",
    )

    summary = summarize_elevation(xodr)

    assert summary["min"] == pytest.approx(380.0, abs=1e-9)
    assert summary["max"] == pytest.approx(380.0, abs=1e-9)
    assert summary["span"] == pytest.approx(0.0, abs=1e-9)


def test_summarize_elevation_empty_map_is_null_control(tmp_path: Path) -> None:
    """Negative/empty control: a map with no <elevationProfile> records at all
    must genuinely report null, not a fabricated number."""
    xodr = _write(
        tmp_path,
        "empty.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE><road id=\"1\" length=\"20.0\" junction=\"-1\">"
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="20.0"><line/></geometry></planView>'
        "</road></OpenDRIVE>",
    )

    summary = summarize_elevation(xodr)

    assert summary["min"] is None
    assert summary["max"] is None
    assert summary["span"] is None
    assert summary["elevation_segment_count"] == 0


# ---------------------------------------------------------------------------
# 2. 08H full_map_metrics.elevation_continuity sub-metric
# ---------------------------------------------------------------------------


def test_full_map_metrics_elevation_continuity_detects_gradient_on_sloped_map(
    tmp_path: Path,
) -> None:
    """RED: the map has real elevation change across many single-record roads
    (the common encoding), but the old implementation only compared
    consecutive <elevation> records WITHIN the same road, so num_segments==0
    on a map where every road carries exactly one elevation record. The fixed
    metric must sample consecutive road-level elevation and report a nonzero
    gradient."""
    xodr = _write(
        tmp_path,
        "sloped_multi_road.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<link><successor elementType="road" elementId="2" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="361.85" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="368.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        "</OpenDRIVE>",
    )

    result = FullMapMetricsScanner.scan(xodr)
    elevation = result["elevation_continuity"]

    assert elevation["num_segments"] > 0
    assert elevation["max_gradient"] > 0.0


def test_full_map_metrics_elevation_continuity_flat_map_gradient_near_zero(
    tmp_path: Path,
) -> None:
    """Positive control: a flat map (all roads at the same elevation) must
    report gradient ~ 0, proving the metric isn't just always nonzero."""
    xodr = _write(
        tmp_path,
        "flat_multi_road.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<link><successor elementType="road" elementId="2" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="400.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="400.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        "</OpenDRIVE>",
    )

    result = FullMapMetricsScanner.scan(xodr)
    elevation = result["elevation_continuity"]

    assert elevation["num_segments"] > 0
    assert elevation["max_gradient"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 3. check_elevation_continuity: contactPoint / endpoint blind spot
# ---------------------------------------------------------------------------


def _linked_roads_xodr(
    *,
    contact_point: str,
    z_start_road2: float,
    z_end_road2: float = None,
) -> str:
    """Build two roads linked by successor/predecessor where road 2's usable
    join point depends on contactPoint. road 2 has DIFFERENT elevations at
    s=0 (start) vs s=length (end) so that picking the wrong endpoint silently
    hides (or fabricates) a z-seam."""
    if z_end_road2 is None:
        z_end_road2 = z_start_road2
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        f'<link><successor elementType="road" elementId="2" contactPoint="{contact_point}"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="400.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "<elevationProfile>"
        f'<elevation s="0" a="{z_start_road2}" b="0.0" c="0.0" d="0.0"/>'
        "</elevationProfile>"
        "</road>"
        "</OpenDRIVE>"
    )


def test_check_elevation_continuity_honors_contact_point_end(tmp_path: Path) -> None:
    """RED: road 1's successor link declares contactPoint="end", meaning the
    join is at road 2's END (s=length), not its start. road2 has a nonzero
    b-coefficient so its elevation at s=0 (100.0) genuinely differs from its
    elevation at s=length=10 (100 + 0.5*10 = 105.0). The checker must
    evaluate road2 at the contactPoint-selected endpoint (end -> 105.0), not
    hardcode s=0 (100.0) for every successor link regardless of contactPoint.
    """
    xodr = _write(
        tmp_path,
        "contact_end.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<link><successor elementType="road" elementId="2" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="405.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="100.0" b="0.5" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        "</OpenDRIVE>",
    )
    # road2 has NO link back to road1 here, so only road1's successor
    # direction is evaluated (single issue, unambiguous).
    # road2 elevation at s=10 (end, selected by contactPoint="end") = 105.0
    # road1 end z = 405.0 -> true dz = |405 - 105| = 300.
    # If the checker wrongly always uses road2 s=0 (start=100), dz would be
    # 305 instead -- a different, wrong number.
    report = check_elevation_continuity(xodr, eps_z=0.5)

    assert report["num_issues"] == 1
    issue = report["issues"][0]
    assert issue["contact_point"] == "end"
    assert issue["z_to_end"] == pytest.approx(105.0, abs=1e-6)
    assert issue["dz"] == pytest.approx(300.0, abs=1e-6)


def test_check_elevation_continuity_separates_junction_connector_links(
    tmp_path: Path,
) -> None:
    """RED/control: a junction-connector road joined to an ordinary road may
    have an expected lane-offset-driven z difference. These must be
    classified separately (not mixed into plain 'issues'), mirroring C6's
    junction_connector_issues split, so genuine road-to-road z-steps aren't
    diluted by expected junction artifacts.

    Both link directions (road1's successor -> road9, and road9's
    predecessor -> road1) are junction-connector links here since road9 has
    junction="1", so both surface under junction_connector_issues (the same
    both-directions pattern as ordinary road-to-road issues elsewhere in
    this checker and in check_geometric_continuity)."""
    xodr = _write(
        tmp_path,
        "junction_link.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<link><successor elementType="road" elementId="9" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="400.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        '<road id="9" length="5.0" junction="1">'
        '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="5.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="401.2" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        '<junction id="1"/>'
        "</OpenDRIVE>",
    )

    report = check_elevation_continuity(xodr, eps_z=0.5)

    assert report["num_issues"] == 0
    assert report.get("num_junction_connector_issues", 0) == 2
    assert len(report.get("junction_connector_issues", [])) == 2
    for issue in report["junction_connector_issues"]:
        assert issue["dz"] == pytest.approx(1.2, abs=1e-6)


def test_check_elevation_continuity_negative_control_flags_injected_z_step(
    tmp_path: Path,
) -> None:
    """Negative control: inject a genuine 1m z-step at an ordinary
    (non-junction) road-to-road boundary; the checker must flag it.

    Note: like check_geometric_continuity (C6), each physical joint is
    evaluated from both link directions (road1's successor AND road2's
    predecessor), so a single genuine seam surfaces as two issue records
    (one per direction) -- this mirrors the existing, intentional pattern
    and is not deduplicated here to keep the two checkers consistent.
    """
    xodr = _write(
        tmp_path,
        "z_step.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<link><successor elementType="road" elementId="2" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="400.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="401.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        "</OpenDRIVE>",
    )

    report = check_elevation_continuity(xodr, eps_z=0.5)

    assert report["ok"] is False
    assert report["num_issues"] == 2
    for issue in report["issues"]:
        assert issue["dz"] == pytest.approx(1.0, abs=1e-6)


def test_check_elevation_continuity_positive_control_clean_map_passes(
    tmp_path: Path,
) -> None:
    """Positive control: a clean map (matching z at every road-to-road join)
    must pass with zero issues."""
    xodr = _write(
        tmp_path,
        "clean.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<link><successor elementType="road" elementId="2" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="400.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="400.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        "</OpenDRIVE>",
    )

    report = check_elevation_continuity(xodr, eps_z=0.5)

    assert report["ok"] is True
    assert report["num_issues"] == 0


# ---------------------------------------------------------------------------
# 4. Length-invariant tolerance unification (certifier tol = 1e-9)
# ---------------------------------------------------------------------------


def _length_excess_fixture(tmp_path: Path, name: str, excess: float) -> str:
    declared = 10.0
    geom_len = declared + excess
    return _write(
        tmp_path,
        name,
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<OpenDRIVE><road id="1" length="{declared}" junction="-1">'
        f'<planView><geometry s="0" x="0" y="0" hdg="0" length="{geom_len}"><line/></geometry></planView>'
        "</road></OpenDRIVE>",
    )


def test_length_invariant_certifier_flags_sub_micron_excess(tmp_path: Path) -> None:
    """Certifier tolerance is 1e-9: a 1e-7 m excess must be reported."""
    xodr = _length_excess_fixture(tmp_path, "excess_1e7.xodr", 1e-7)
    root = ET.parse(xodr).getroot()

    summary = length_invariant_summary(root)

    assert summary["violations"] == 1


def test_check_s_invariants_uses_certifier_tolerance_and_end_s_measurement(
    tmp_path: Path,
) -> None:
    """RED: the ad-hoc C0 gate (check_s_invariants) must use the SAME
    tolerance (1e-9) and the SAME measurement (s + geometry.length, not just
    geometry.s) as the certifier's _length_invariant_evidence /
    length_invariant_summary, so a '0' can never hide a sub-1e-6 violation.

    Before the fix this gate used max(s_list) (geometry START s only) with a
    1e-6 tolerance, silently passing a road whose LAST geometry starts inside
    the declared length but whose length pushes its END past the declared
    length by far more than the certifier's tolerance.
    """
    # Road declares length=10. A single geometry starts at s=0 (well inside
    # the declared length) but has length=10.5, so its end (10.5) exceeds the
    # declared road length by 0.5m -- a large, real violation. The old
    # max(s_list) measurement only looks at geometry START s (0.0), which is
    # NOT > 10 + tol, so it was invisible to the old check.
    xodr = _write(
        tmp_path,
        "end_exceeds.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.5"><line/></geometry></planView>'
        "</road></OpenDRIVE>",
    )

    report = scan_s_invariants(xodr)

    kinds = [issue["kind"] for issue in report["issues"]]
    assert "geom_s_exceeds_road_length" in kinds

    # Sub-1e-6 excess (but > certifier's 1e-9 tol) must also be caught now.
    xodr_tiny = _write(
        tmp_path,
        "tiny_excess.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0000005"><line/></geometry></planView>'
        "</road></OpenDRIVE>",
    )
    tiny_report = scan_s_invariants(xodr_tiny)
    tiny_kinds = [issue["kind"] for issue in tiny_report["issues"]]
    assert "geom_s_exceeds_road_length" in tiny_kinds


def test_check_s_invariants_agrees_with_certifier_on_shared_fixture(tmp_path: Path) -> None:
    """Both the acceptance-path gate (check_s_invariants) and the certifier
    helper (length_invariant_summary, tol 1e-9) must agree on whether a
    1e-7 m excess is a violation -- no loose-tolerance escape hatch."""
    xodr = _length_excess_fixture(tmp_path, "shared_1e7.xodr", 1e-7)

    root = ET.parse(xodr).getroot()
    certifier_summary = length_invariant_summary(root)
    gate_report = scan_s_invariants(xodr)

    certifier_flags = certifier_summary["violations"] > 0
    gate_flags = any(
        issue["kind"] == "geom_s_exceeds_road_length" for issue in gate_report["issues"]
    )
    assert certifier_flags is True
    assert gate_flags == certifier_flags


def test_check_s_invariants_clean_map_reports_zero_length_issues(tmp_path: Path) -> None:
    """Positive control: a road whose geometry exactly matches its declared
    length must not be flagged."""
    xodr = _write(
        tmp_path,
        "exact.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road></OpenDRIVE>",
    )

    report = scan_s_invariants(xodr)
    kinds = [issue["kind"] for issue in report["issues"]]
    assert "geom_s_exceeds_road_length" not in kinds


def test_map_acceptance_flags_sub_micron_length_excess_matching_certifier(
    tmp_path: Path,
) -> None:
    """Per C9 spec item 4: a fixture with a 1e-7 m excess must be reported
    by BOTH the acceptance gate (build_map_acceptance, via final_xodr_path)
    AND the certifier (length_invariant_summary, tol 1e-9) -- no
    loose-tolerance escape. The acceptance gate must use the exact same
    helper/tolerance as the certifier so they can never disagree."""
    xodr = _length_excess_fixture(tmp_path, "map_acceptance_1e7.xodr", 1e-7)

    certifier_summary = length_invariant_summary(ET.parse(xodr).getroot())
    assert certifier_summary["violations"] == 1

    acceptance = build_map_acceptance({}, run_id="run", final_xodr_path=xodr)

    assert acceptance["valid_for_experiments"] is False
    assert "length_invariant" in acceptance["failed_gates"]
    assert acceptance["metrics"]["length_invariant_violations"] == 1
    assert acceptance["metrics"]["length_invariant_tol_m"] == pytest.approx(1e-9)


def test_map_acceptance_length_invariant_clean_map_passes(tmp_path: Path) -> None:
    """Positive control: a compliant candidate must not trip the
    length_invariant acceptance gate."""
    xodr = _write(
        tmp_path,
        "acceptance_clean.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road></OpenDRIVE>",
    )

    acceptance = build_map_acceptance({}, run_id="run", final_xodr_path=xodr)

    assert acceptance["valid_for_experiments"] is True
    assert "length_invariant" not in acceptance["failed_gates"]
    assert acceptance["metrics"]["length_invariant_violations"] == 0
