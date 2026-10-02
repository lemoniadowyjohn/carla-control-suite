"""Batch-10 RQ2 lane: authority validation, negative controls, smoke tests.

Every rejection path of ultimate_pipeline.domain_gap.rq2_metric_authority is
exercised against small synthetic XODR fixtures (no pinned maps, no CARLA).
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.domain_gap import rq2_metric_authority as auth


def _road(rid, x0, y0, length, hdg=0.0, width=3.5, junction="-1"):
    road = ET.Element("road", id=rid, length=str(length), junction=junction)
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(
        plan, "geometry", s="0", x=str(x0), y=str(y0), hdg=str(hdg), length=str(length)
    )
    ET.SubElement(geom, "line")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    for lid, side in (("1", "right"), ("-1", "left")):
        lane = ET.SubElement(section, side, id=lid, type="driving", level="false")
        ET.SubElement(lane, "width", sOffset="0", a=str(width), b="0", c="0", d="0")
    return road


def _xodr(*roads, georef="+proj=tmerc +datum=WGS84 +units=m +no_defs", junctions=()):
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header")
    ET.SubElement(header, "offset", x="0.0", y="0.0", z="0.0", hdg="0.0")
    if georef is not None:
        geo = ET.SubElement(header, "geoReference")
        geo.text = georef
    for road in roads:
        root.append(road)
    for jid in junctions:
        ET.SubElement(root, "junction", id=str(jid), name=f"j{jid}")
    return root


def _write(tmp_path, name, root):
    p = tmp_path / name
    ET.ElementTree(root).write(str(p), encoding="utf-8", xml_declaration=True)
    return str(p)


@pytest.fixture()
def pair(tmp_path):
    manual = _write(
        tmp_path, "manual.xodr",
        _xodr(_road("1", 0.0, 0.0, 20.0, junction="10"),
              _road("2", 0.0, 100.0, 20.0), junctions=("10",)),
    )
    auto = _write(
        tmp_path, "auto.xodr",
        _xodr(_road("101", 0.0, 3.0, 20.0, junction="20"),
              _road("102", 0.0, 103.0, 20.0), junctions=("20",)),
    )
    return auto, manual


def test_smoke_manual_hull_reports_all_thesis_metrics(pair):
    auto, manual = pair
    res = auth.run_rq2_comparison(auto, manual, "manual_hull", {})
    assert res.scope == "manual_hull"
    for m in auth.THESIS_PRIMARY_METRICS:
        assert m in res.primary, f"missing required metric {m}"
    assert res.provenance["auto_sha256"] and res.provenance["manual_sha256"]
    assert res.provenance["authority_impl_sha256"]
    d = res.to_dict()
    assert set(d["primary"]) == set(res.primary)  # no duplicate keys


def test_smoke_whole_map_frechet_not_run(pair):
    auto, manual = pair
    res = auth.run_rq2_comparison(auto, manual, "whole_map", {})
    assert res.primary["frechet_distance"]["status"] == "NOT_RUN"
    assert math.isfinite(res.primary["road_length_ratio"])


def test_rejects_wrong_auto_sha(pair):
    auto, manual = pair
    with pytest.raises(ValueError, match="wrong auto SHA"):
        auth.run_rq2_comparison(
            auto, manual, "manual_hull",
            {"verify_shas": True, "expected_auto_sha256": "0" * 64},
        )


def test_rejects_wrong_manual_sha(pair):
    auto, manual = pair
    import hashlib
    real = hashlib.sha256(open(auto, "rb").read()).hexdigest()
    with pytest.raises(ValueError, match="wrong manual source SHA"):
        auth.run_rq2_comparison(
            auto, manual, "manual_hull",
            {"verify_shas": True, "expected_auto_sha256": real,
             "expected_manual_sha256": "f" * 64},
        )


def test_rejects_lfs_pointer(tmp_path, pair):
    _, manual = pair
    p = tmp_path / "lfs.xodr"
    p.write_text("version https://git-lfs/spec blah\noid sha256:abc\n", encoding="utf-8")
    with pytest.raises(ValueError, match="LFS"):
        auth.run_rq2_comparison(str(p), manual, "manual_hull", {})


def test_rejects_invalid_xodr(tmp_path, pair):
    _, manual = pair
    p = tmp_path / "bad.xodr"
    p.write_text("<OpenDRIVE><unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid XML/XODR"):
        auth.run_rq2_comparison(str(p), manual, "manual_hull", {})


def test_rejects_non_opendrive_root(tmp_path, pair):
    _, manual = pair
    p = tmp_path / "other.xml"
    ET.ElementTree(ET.Element("NotDrive")).write(str(p))
    with pytest.raises(ValueError, match="invalid XODR"):
        auth.run_rq2_comparison(str(p), manual, "manual_hull", {})


def test_rejects_frame_mismatch(tmp_path):
    auto = _write(tmp_path, "a.xodr", _xodr(_road("1", 0, 0, 10), georef=None))
    manual = _write(tmp_path, "m.xodr", _xodr(_road("1", 0, 0, 10)))
    with pytest.raises(ValueError, match="[Ff]rame mismatch|geoReference"):
        auth.run_rq2_comparison(auto, manual, "manual_hull", {})


def test_rejects_unsupported_scope(pair):
    auto, manual = pair
    with pytest.raises(ValueError, match="unsupported scope"):
        auth.run_rq2_comparison(auto, manual, "mixed_scope", {})


def test_rejects_empty_road_network(tmp_path):
    auto = _write(tmp_path, "a.xodr", _xodr())
    manual = _write(
        tmp_path, "m.xodr", _xodr(_road("1", 0, 0, 10), _road("2", 0, 50, 10))
    )
    with pytest.raises(ValueError, match="empty road network"):
        auth.run_rq2_comparison(auto, manual, "manual_hull", {})
    empty_manual = _write(tmp_path, "m0.xodr", _xodr())
    with pytest.raises(ValueError, match="empty road network"):
        auth.run_rq2_comparison(manual, empty_manual, "whole_map", {})


def test_rejects_missing_required_metric():
    with pytest.raises(ValueError, match="missing required"):
        auth._check_required_metrics({"lane_width_gap": 0.0})


def test_rejects_nan_inf_metric():
    with pytest.raises(ValueError, match="NaN/inf"):
        auth._require_finite("x", float("nan"))
    with pytest.raises(ValueError, match="NaN/inf"):
        auth._require_finite("x", float("inf"))


def test_rejects_unknown_config_key(pair):
    auto, manual = pair
    with pytest.raises(ValueError, match="unknown config"):
        auth.run_rq2_comparison(auto, manual, "manual_hull", {"bogus": 1})


def test_results_deterministic(pair):
    auto, manual = pair
    a = auth.run_rq2_comparison(auto, manual, "manual_hull", {}).to_dict()
    b = auth.run_rq2_comparison(auto, manual, "manual_hull", {}).to_dict()
    assert a["primary"] == b["primary"]
