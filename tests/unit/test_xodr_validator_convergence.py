"""OC-59 — strict OpenDRIVE validator convergence tests.

Locks: typed numeric parsing (no fail-open zeros), primitive profiles and
per-primitive coefficients, exactly-one-primitive, road-length policy,
s-continuity classification, laneSection/lane-ID rules, width-polynomial
evaluation, junction identity, XSD status honesty, the shared envelope and
the static facade's claim boundary. Deterministic, offline.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.quality.check_carla_opendrive_compat import (
    StrictCarlaOpendriveGate,
)
from ultimate_pipeline.quality.check_xodr_schema import (
    validate_xodr_schema,
    validate_xodr_schema_structured,
)
from ultimate_pipeline.quality.xodr_numeric import (
    MALFORMED,
    MISSING,
    NONFINITE,
    VALID,
    parse_required_float,
    parse_required_int,
)
from ultimate_pipeline.quality.xodr_strict_validator import (
    StrictXodrValidator,
)
from ultimate_pipeline.quality.xodr_validation_policy import (
    LEGACY_CONSERVATIVE,
    OPEN_DRIVE_STRUCTURAL,
    classify_s_step,
    road_length_check,
    width_extrema_over_interval,
)
from ultimate_pipeline.quality.xodr_validation_result import (
    ValidationResult,
    merge_results,
)
from ultimate_pipeline.tools.verify_final_xodr import (
    validate_final_xodr_static,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _geom(s="0", x="0", y="0", hdg="0", length="10", prim="<line/>"):
    return (f'<geometry s="{s}" x="{x}" y="{y}" hdg="{hdg}" '
            f'length="{length}">{prim}</geometry>')


def _lane_sec(s="0", lanes='<left><lane id="1" type="driving">'
              '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
              '</lane></left><center><lane id="0" type="none"/></center>'):
    return f"<laneSection s=\"{s}\">{lanes}</laneSection>"


def _road(rid="1", length="10", geoms=None, lanes=None, junction="-1"):
    geoms = geoms if geoms is not None else [_geom()]
    lanes = lanes if lanes is not None else _lane_sec()
    return (f'<road id="{rid}" length="{length}" junction="{junction}">'
            f"<planView>{''.join(geoms)}</planView>"
            f"<type s=\"0\" type=\"town\"/>"
            f"<lanes>{lanes}</lanes></road>")


def _doc(roads, header=('<header revMajor="1" revMinor="4">'
                       '<geoReference>+proj=tmerc +lon_0=9</geoReference>'
                       '<offset x="0" y="0" z="0" hdg="0"/>'
                       '</header>')):
    return ('<?xml version="1.0"?><OpenDRIVE>' + header + "".join(roads)
            + "</OpenDRIVE>")


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _codes(report):
    return {i["code"] for i in report["issues"]}


def _valid_road():
    return _road()


# ---------------------------------------------------------------------------
# §3 typed parsing
# ---------------------------------------------------------------------------

def test_parse_required_float_outcomes():
    assert parse_required_float(None).status == MISSING
    assert parse_required_float("banana").status == MALFORMED
    assert parse_required_float("").status == MALFORMED
    assert parse_required_float("   ").status == MALFORMED
    assert parse_required_float("nan").status == NONFINITE
    assert parse_required_float("inf").status == NONFINITE
    assert parse_required_float("-inf").status == NONFINITE
    good = parse_required_float("3.25")
    assert good.status == VALID and good.value == pytest.approx(3.25)
    # zero stays zero only when actually written
    assert parse_required_float("0").status == VALID


def test_parse_required_int_outcomes():
    assert parse_required_int(None).status == MISSING
    assert parse_required_int("banana").status == MALFORMED
    assert parse_required_int("").status == MALFORMED
    assert parse_required_int("1.5").status == MALFORMED
    assert parse_required_int("nan").status == NONFINITE
    assert parse_required_int("7").status == VALID


def test_no_zero_substitution_before_validity():
    # The whole point of §2: these must not become legitimate 0.0 anywhere.
    for raw in ("nan", "inf", "-inf", "banana", ""):
        assert parse_required_float(raw).value is None


# ---------------------------------------------------------------------------
# §4 adversarial numerics through the strict validator
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("attr,bad", [
    ("x", "nan"), ("y", "inf"), ("hdg", "-inf"), ("length", "banana"),
    ("s", ""),
])
def test_malformed_geometry_attr_is_deterministic_error(tmp_path, attr, bad):
    kwargs = {"s": "0", "x": "0", "y": "0", "hdg": "0", "length": "10"}
    kwargs[attr] = bad
    g = _geom(**kwargs)
    p = _write(tmp_path, "m.xodr", _doc([_road(geoms=[g])]))
    rep = StrictXodrValidator().validate_path(p)
    assert rep["ok"] is False
    assert any(c.startswith(f"geom_{attr}_") or c == "geom_length_nonpositive"
               or "malformed" in c or "missing" in c or "nonfinite" in c
               for c in _codes(rep)), _codes(rep)
    # twice => deterministic
    rep2 = StrictXodrValidator().validate_path(p)
    assert _codes(rep) == _codes(rep2)


def test_width_nan_and_elevation_inf_are_errors(tmp_path):
    lanes = _lane_sec(lanes='<left><lane id="1" type="driving">'
                      '<width sOffset="0" a="nan" b="0" c="0" d="0"/>'
                      '</lane></left><center><lane id="0" type="none"/></center>')
    road = (_road(lanes=lanes)
            .replace("</road>", '<elevationProfile><elevation s="0" a="0" b="inf" c="0" d="0"/>'
                     "</elevationProfile></road>"))
    p = _write(tmp_path, "m.xodr", _doc([road]))
    codes = _codes(StrictXodrValidator().validate_path(p))
    assert "width_a_nonfinite" in codes
    assert "elev_b_nonfinite" in codes


def test_malformed_lane_id_is_error(tmp_path):
    lanes = _lane_sec(lanes='<left><lane id="banana" type="driving">'
                      '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
                      '</lane></left><center><lane id="0" type="none"/></center>')
    p = _write(tmp_path, "m.xodr", _doc([_road(lanes=lanes)]))
    codes = _codes(StrictXodrValidator().validate_path(p))
    assert "lane_id_malformed" in codes


# ---------------------------------------------------------------------------
# §1/§21 basic structure
# ---------------------------------------------------------------------------

def test_empty_opendrive_and_no_roads(tmp_path):
    p = _write(tmp_path, "e.xodr", '<?xml version="1.0"?><OpenDRIVE/>')
    assert "no_roads" in _codes(StrictXodrValidator().validate_path(p))
    p2 = _write(tmp_path, "e2.xodr", '<?xml version="1.0"?><NotOpenDRIVE/>')
    assert "root_tag" in _codes(StrictXodrValidator().validate_path(p2))


def test_duplicate_roads_error(tmp_path):
    p = _write(tmp_path, "d.xodr", _doc([_valid_road(), _valid_road()]))
    assert "road_duplicate_id" in _codes(StrictXodrValidator().validate_path(p))


def test_valid_minimal_map_passes_strict_and_compat(tmp_path):
    p = _write(tmp_path, "ok.xodr", _doc([_valid_road()]))
    rep = StrictXodrValidator().validate_path(p)
    assert rep["ok"] is True, rep["issues"]
    root = ET.parse(str(p)).getroot()
    assert StrictCarlaOpendriveGate.validate(root) == []


# ---------------------------------------------------------------------------
# §5-§7 primitives
# ---------------------------------------------------------------------------

def test_spiral_valid_under_compat_profile_but_flagged_under_legacy(tmp_path):
    g = _geom(prim='<spiral curvStart="0.01" curvEnd="0.02"/>')
    p = _write(tmp_path, "s.xodr", _doc([_road(geoms=[g])]))
    assert StrictXodrValidator().validate_path(p)["ok"] is True
    assert StrictXodrValidator(
        profile=OPEN_DRIVE_STRUCTURAL).validate_path(p)["ok"] is True
    legacy = StrictXodrValidator(profile=LEGACY_CONSERVATIVE).validate_path(p)
    assert legacy["ok"] is False
    assert "geom_primitive_unsupported_by_profile" in _codes(legacy)


def test_spiral_malformed_curvstart_is_error(tmp_path):
    g = _geom(prim='<spiral curvEnd="0.02"/>')
    p = _write(tmp_path, "s.xodr", _doc([_road(geoms=[g])]))
    codes = _codes(StrictXodrValidator().validate_path(p))
    assert "spiral_curvStart_missing" in codes


def test_arc_malformed_curvature_is_error(tmp_path):
    g = _geom(prim='<arc curvature="banana"/>')
    p = _write(tmp_path, "a.xodr", _doc([_road(geoms=[g])]))
    codes = _codes(StrictXodrValidator().validate_path(p))
    assert "arc_curvature_malformed" in codes


def test_poly3_and_paramply3_coefficients_validated(tmp_path):
    g = _geom(prim='<poly3 a="0" b="0" c="oops" d="0"/>')
    p = _write(tmp_path, "p.xodr", _doc([_road(geoms=[g])]))
    assert "poly3_c_malformed" in _codes(StrictXodrValidator().validate_path(p))
    g2 = _geom(prim=('<paramPoly3 aU="0" bU="0" cU="0" dU="0" '
                     'aV="0" bV="nan" cV="0" dV="0" pRange="arcLength"/>'))
    p2 = _write(tmp_path, "pp.xodr", _doc([_road(geoms=[g2])]))
    assert "paramPoly3_bV_nonfinite" in _codes(
        StrictXodrValidator().validate_path(p2))
    g3 = _geom(prim=('<paramPoly3 aU="0" bU="0" cU="0" dU="0" '
                     'aV="0" bV="0" cV="0" dV="0" pRange="weird"/>'))
    p3 = _write(tmp_path, "pp3.xodr", _doc([_road(geoms=[g3])]))
    assert "paramPoly3_pRange_unsupported" in _codes(
        StrictXodrValidator().validate_path(p3))


def test_two_primitive_children_fail(tmp_path):
    g = _geom(prim='<line/><arc curvature="0.01"/>')
    p = _write(tmp_path, "t.xodr", _doc([_road(geoms=[g])]))
    codes = _codes(StrictXodrValidator().validate_path(p))
    assert "geom_type_ambiguous" in codes


def test_zero_and_unknown_primitive_children_fail(tmp_path):
    g = _geom(prim='')
    p = _write(tmp_path, "z.xodr", _doc([_road(geoms=[g])]))
    assert "geom_type_missing" in _codes(StrictXodrValidator().validate_path(p))
    g2 = _geom(prim='<clothoid curvStart="0" curvEnd="1"/>')
    p2 = _write(tmp_path, "u.xodr", _doc([_road(geoms=[g2])]))
    assert "geom_unknown_primitive" in _codes(
        StrictXodrValidator().validate_path(p2))


def test_compat_gate_rejects_double_primitive_and_validates_coeffs(tmp_path):
    g = _geom(prim='<line/><arc curvature="nan"/>')
    p = _write(tmp_path, "t.xodr", _doc([_road(geoms=[g])]))
    root = ET.parse(str(p)).getroot()
    codes = {i["code"] for i in StrictCarlaOpendriveGate.validate(root)}
    assert "geometry_primitive_count" in codes


# ---------------------------------------------------------------------------
# §8 road length policy
# ---------------------------------------------------------------------------

def test_road_length_policy_numbers():
    ok = road_length_check(100.0, 100.5)
    assert ok["status"] == "OK"
    bad = road_length_check(100.0, 50.0)
    assert bad["status"] == "MISMATCH"
    assert bad["absolute_error_m"] == pytest.approx(50.0)
    assert bad["relative_error"] == pytest.approx(0.5)
    # small absolute error on a short road: no warn (both floors required)
    assert road_length_check(2.0, 2.4)["status"] == "OK"


def test_road_length_mismatch_reports_fields(tmp_path):
    geoms = [_geom(s="0", length="10"), _geom(s="10", length="10")]
    p = _write(tmp_path, "l.xodr", _doc([_road(length="100", geoms=geoms)]))
    rep = StrictXodrValidator().validate_path(p)
    mism = [i for i in rep["issues"] if i["code"] == "road_length_mismatch"]
    assert mism
    ctx = mism[0]["context"]
    assert {"absolute_error_m", "relative_error", "abs_threshold_m",
            "rel_threshold"} <= set(ctx)


# ---------------------------------------------------------------------------
# §9 s continuity classification
# ---------------------------------------------------------------------------

def test_classify_s_step_table():
    assert classify_s_step(0.0, 10.0, 10.0) == "continuous"
    assert classify_s_step(0.0, 10.0, 12.0) == "gap"
    assert classify_s_step(0.0, 10.0, 8.0) == "overlap"
    assert classify_s_step(5.0, 5.0, 5.0) == "duplicate_s"
    assert classify_s_step(0.0, 10.0, -1.0) == "negative_s"


def test_geometry_gap_overlap_duplicate_codes(tmp_path):
    geoms = [_geom(s="0", length="10"), _geom(s="12", length="10")]
    p = _write(tmp_path, "g.xodr", _doc([_road(length="22", geoms=geoms)]))
    assert "geom_s_gap" in _codes(StrictXodrValidator().validate_path(p))
    geoms = [_geom(s="0", length="10"), _geom(s="8", length="10")]
    p = _write(tmp_path, "o.xodr", _doc([_road(length="18", geoms=geoms)]))
    assert "geom_s_overlap" in _codes(StrictXodrValidator().validate_path(p))
    geoms = [_geom(s="0", length="10"), _geom(s="0", length="10")]
    p = _write(tmp_path, "d.xodr", _doc([_road(length="10", geoms=geoms)]))
    assert "geom_s_duplicate" in _codes(StrictXodrValidator().validate_path(p))


# ---------------------------------------------------------------------------
# §10 laneSection, §11 lane IDs
# ---------------------------------------------------------------------------

def test_lanesection_bad_s_first_s_and_beyond_length(tmp_path):
    lanes = _lane_sec(s="banana") + _lane_sec(s="5")
    p = _write(tmp_path, "l.xodr", _doc([_road(length="10", lanes=lanes)]))
    codes = _codes(StrictXodrValidator().validate_path(p))
    assert "laneSection_s_malformed" in codes
    lanes = _lane_sec(s="2")
    p = _write(tmp_path, "f.xodr", _doc([_road(lanes=lanes)]))
    assert "laneSection_first_s_not_zero" in _codes(
        StrictXodrValidator().validate_path(p))
    lanes = _lane_sec(s="0") + _lane_sec(s="50")
    p = _write(tmp_path, "b.xodr", _doc([_road(length="10", lanes=lanes)]))
    assert "laneSection_s_gt_length" in _codes(
        StrictXodrValidator().validate_path(p))


def test_lane_id_rules(tmp_path):
    # duplicate within one side
    lanes = _lane_sec(lanes='<left><lane id="1" type="driving">'
                      '<width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane>'
                      '<lane id="1" type="driving">'
                      '<width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane>'
                      '</left><center><lane id="0" type="none"/></center>')
    p = _write(tmp_path, "d.xodr", _doc([_road(lanes=lanes)]))
    assert "duplicate_lane_id" in _codes(StrictXodrValidator().validate_path(p))
    # across sides
    lanes = _lane_sec(lanes='<left><lane id="1" type="driving">'
                      '<width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane>'
                      '</left><center><lane id="0" type="none"/></center>'
                      '<right><lane id="1" type="driving">'
                      '<width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane>'
                      '</right>')
    p = _write(tmp_path, "c.xodr", _doc([_road(lanes=lanes)]))
    assert "duplicate_lane_id_across_sides" in _codes(
        StrictXodrValidator().validate_path(p))
    # driving lane id 0
    lanes = _lane_sec(lanes='<left><lane id="0" type="driving">'
                      '<width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane>'
                      '</left><center><lane id="0" type="none"/></center>')
    p = _write(tmp_path, "z.xodr", _doc([_road(lanes=lanes)]))
    assert "driving_lane_id_zero" in _codes(
        StrictXodrValidator().validate_path(p))


# ---------------------------------------------------------------------------
# §12 width polynomial
# ---------------------------------------------------------------------------

def test_width_extrema_analytic():
    ok = width_extrema_over_interval(1.0, -6.0, 3.0, 0.0, 0.0, 4.0)
    assert ok["ok"] is True
    assert ok["min"] == pytest.approx(-2.0)  # vertex ds=1, ends positive
    assert ok["max"] == pytest.approx(25.0)
    bad = width_extrema_over_interval(float("nan"), 0, 0, 0, 0, 1)
    assert bad["ok"] is False


def test_width_negative_interior_detected(tmp_path):
    # a=1 > 0 at ds=0 and positive at ds=4, but -2 inside: endpoint-only
    # checks would pass; analytic evaluation must fail.
    lanes = _lane_sec(lanes='<left><lane id="1" type="driving">'
                      '<width sOffset="0" a="1.0" b="-6.0" c="3.0" d="0"/>'
                      '</lane></left><center><lane id="0" type="none"/></center>')
    p = _write(tmp_path, "w.xodr", _doc([_road(lanes=lanes)]))
    codes = _codes(StrictXodrValidator().validate_path(p))
    assert "lane_width_negative" in codes


# ---------------------------------------------------------------------------
# §13 junctions
# ---------------------------------------------------------------------------

def _road_ref(rid, junction="-1"):
    return (f'<road id="{rid}" length="10" junction="{junction}">'
            "<planView>" + _geom() + "</planView>"
            "<type s=\"0\" type=\"town\"/>"
            "<lanes>" + _lane_sec() + "</lanes></road>")


def test_junction_identity_rules(tmp_path):
    conn = ('<connection id="c1" incomingRoad="1" connectingRoad="2" '
            'contactPoint="start"/>')
    roads = [_road_ref("1"), _road_ref("2", junction="10")]
    p = _write(tmp_path, "j.xodr",
               _doc(roads).replace("</OpenDRIVE>",
                                   f'<junction id="10">{conn}</junction></OpenDRIVE>'))
    assert StrictXodrValidator().validate_path(p)["ok"] is True

    dup = _doc(roads).replace(
        "</OpenDRIVE>",
        f'<junction id="10">{conn}</junction><junction id="10">{conn}</junction></OpenDRIVE>')
    p = _write(tmp_path, "jd.xodr", dup)
    assert "junction_duplicate_id" in _codes(StrictXodrValidator().validate_path(p))

    bad_cp = _doc(roads).replace(
        "</OpenDRIVE>",
        '<junction id="10"><connection id="c1" incomingRoad="1" '
        'connectingRoad="2" contactPoint="middle"/></junction></OpenDRIVE>')
    p = _write(tmp_path, "jc.xodr", bad_cp)
    assert "junction_contactPoint_invalid" in _codes(
        StrictXodrValidator().validate_path(p))

    missing_cp = _doc(roads).replace(
        "</OpenDRIVE>",
        '<junction id="10"><connection id="c1" incomingRoad="1" '
        'connectingRoad="2"/></junction></OpenDRIVE>')
    p = _write(tmp_path, "jm.xodr", missing_cp)
    assert "junction_contactPoint_missing" in _codes(
        StrictXodrValidator().validate_path(p))

    ghost = _doc(roads).replace(
        "</OpenDRIVE>",
        '<junction id="10"><connection id="c1" incomingRoad="1" '
        'connectingRoad="999" contactPoint="start"/></junction></OpenDRIVE>')
    p = _write(tmp_path, "jg.xodr", ghost)
    assert "junction_connecting_missing" in _codes(
        StrictXodrValidator().validate_path(p))


# ---------------------------------------------------------------------------
# §14/§15 XSD honesty
# ---------------------------------------------------------------------------

def test_xsd_not_configured_is_not_pass(tmp_path):
    p = _write(tmp_path, "m.xodr", _doc([_valid_road()]))
    ok, err = validate_xodr_schema(str(p), None)
    assert ok is False and err
    structured = validate_xodr_schema_structured(str(p), None)
    assert structured["status"] == "NOT_CONFIGURED"
    assert structured["envelope_status"] == "NOT_RUN"
    assert structured["input_xodr_sha256"]


def test_xsd_missing_file_is_incomplete_not_pass(tmp_path):
    p = _write(tmp_path, "m.xodr", _doc([_valid_road()]))
    ok, err = validate_xodr_schema(str(p), str(tmp_path / "nope.xsd"))
    assert ok is False and err
    structured = validate_xodr_schema_structured(str(p), str(tmp_path / "nope.xsd"))
    assert structured["status"] == "INCOMPLETE_DEPENDENCY"
    assert structured["envelope_status"] == "INCOMPLETE"


def test_xsd_malformed_input_is_fail(tmp_path):
    pytest.importorskip("lxml")
    bad = _write(tmp_path, "bad.xodr", "<OpenDRIVE><unclosed>")
    xsd = _write(tmp_path, "s.xsd",
                 '<?xml version="1.0"?><xs:schema '
                 'xmlns:xs="http://www.w3.org/2001/XMLSchema"/>')
    structured = validate_xodr_schema_structured(str(bad), str(xsd))
    assert structured["status"] == "FAIL"
    assert structured["input_xodr_sha256"]


# ---------------------------------------------------------------------------
# §17 envelope + §18/§19 facade boundary
# ---------------------------------------------------------------------------

def test_envelope_merge_incomplete_is_not_pass():
    good = ValidationResult(validator="A", status="PASS")
    missing = ValidationResult(validator="B", status="INCOMPLETE")
    merged = merge_results("M", [good, missing])
    assert merged.status == "INCOMPLETE"
    assert merged.to_dict()["status"] == "INCOMPLETE"
    bad = ValidationResult(validator="C", status="FAIL")
    assert merge_results("M", [good, bad]).status == "FAIL"


def test_facade_pass_attests_offline_static_only(tmp_path):
    p = _write(tmp_path, "ok.xodr", _doc([_valid_road()]))
    env = validate_final_xodr_static(p)
    assert env["status"] == "PASS"
    assert env["attestation"] == "VERIFIED_OFFLINE_STATIC"
    assert "CARLA_LOAD_VERIFIED" not in env["attestation"]
    assert "CARLA_LOAD_VERIFIED" in env["claim_boundary"]
    assert set(env) >= {"validator", "schema_version", "input_xodr_sha256",
                        "status", "errors", "warnings", "statistics"}


def test_facade_fail_on_nan_geometry(tmp_path):
    g = _geom(x="nan")
    p = _write(tmp_path, "m.xodr", _doc([_road(geoms=[g])]))
    env = validate_final_xodr_static(p)
    assert env["status"] == "FAIL"
    assert env["attestation"] == "NOT_VERIFIED_OFFLINE_STATIC"
