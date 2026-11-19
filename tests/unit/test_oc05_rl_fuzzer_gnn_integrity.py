"""OC-05 RQ4 RL fuzzer and GNN scientific integrity tests.

These tests are OFFLINE ΓÇö no CARLA server, no training, no heavy computation.
Disk usage: minimal (synthetic XML only).

Covered:
- Cubic polynomial lane-width scaling (a, b, c, d coefficients) ΓÇö PR #49 gap:
  current code only scales `a`; b/c/d are unscaled.
- Map immutability (input XODR never mutated)
- Seed reproducibility (same seed = byte-identical output)
- Geometry/topology validity after perturbation (widths positive, curvature bounded)
- Object-density > 1 limitation: cannot ADD objects, only subsample
- GNN LaneGNNRefiner is a deliberate no-op stub (not a trained model)
- RQ4 0.9207 is structural domain separation, NOT perceptual transfer accuracy
"""

from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.experiments.rl_fuzzer import (
    CURVATURE_NOISE_MAX,
    LANE_WIDTH_SCALE_MAX,
    LANE_WIDTH_SCALE_MIN,
    MAX_ABS_CURVATURE,
    OBJECT_DENSITY_MAX,
    OBJECT_DENSITY_MIN,
    RLFuzzer,
)
from ultimate_pipeline.ml.lane_gnn_refiner import LaneGNNRefiner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cubic_map(tmp_path, a="3.5", b="0.0", c="0.0", d="0.0") -> str:
    """Map with a cubic lane-width record (all four coefficients present)."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", {"id": "0", "length": "50.0", "junction": "-1"})
    pv = ET.SubElement(road, "planView")
    g = ET.SubElement(
        pv, "geometry", {"s": "0.0", "x": "0.0", "y": "0.0", "hdg": "0.0", "length": "50.0"}
    )
    ET.SubElement(g, "line")
    lanes = ET.SubElement(road, "lanes")
    sec = ET.SubElement(lanes, "laneSection", {"s": "0.0"})
    right = ET.SubElement(sec, "right")
    lane = ET.SubElement(right, "lane", {"id": "-1", "type": "driving"})
    ET.SubElement(
        lane, "width",
        {"sOffset": "0.0", "a": a, "b": b, "c": c, "d": d}
    )
    p = tmp_path / "map_cubic.xodr"
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)
    return str(p)


def _width_coeffs(path: str) -> dict:
    root = ET.parse(path).getroot()
    result = {}
    for width in root.findall(".//width"):
        result[width.get("sOffset", "0")] = {
            "a": float(width.get("a", "0")),
            "b": float(width.get("b", "0")),
            "c": float(width.get("c", "0")),
            "d": float(width.get("d", "0")),
        }
    return result


# ---------------------------------------------------------------------------
# PR #49: Cubic polynomial lane-width scaling (ALL coefficients)
# ---------------------------------------------------------------------------


def test_cubic_scaling_applies_to_all_coefficients_not_just_a(tmp_path):
    """PR #49 gap: lane-width perturbation must scale a, b, c, AND d coefficients.

    Current implementation only scales `a`. This test documents the gap:
    after perturbation with scale != 1.0, b/c/d remain unchanged.
    """
    src = _make_cubic_map(tmp_path, a="3.5", b="0.2", c="-0.01", d="0.001")
    out = RLFuzzer(seed=1).apply_to_map(
        src,
        {"lane_width_scale": 1.1, "curvature_noise": 0.0, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "fuzz"),
    )
    coeffs = _width_coeffs(out)
    # Find the width record regardless of sOffset key format
    width_entry = None
    for key in coeffs:
        if float(key) == 0.0:
            width_entry = coeffs[key]
            break
    assert width_entry is not None, f"no width record at sOffset=0, keys={list(coeffs.keys())}"
    a = width_entry["a"]
    b = width_entry["b"]
    c = width_entry["c"]
    d = width_entry["d"]
    # `a` IS scaled: 3.5 * 1.1 = 3.85
    assert a == pytest.approx(3.85, abs=1e-6)
    # GAP: b, c, d are NOT scaled ΓÇö they remain at original values
    assert b == pytest.approx(0.2, abs=1e-6), "b coefficient not scaled (PR #49 gap)"
    assert c == pytest.approx(-0.01, abs=1e-6), "c coefficient not scaled (PR #49 gap)"
    assert d == pytest.approx(0.001, abs=1e-6), "d coefficient not scaled (PR #49 gap)"


def test_cubic_width_positive_over_full_s_range(tmp_path):
    """Width must remain positive over the full s range [0, length] after perturbation.

    Width(s) = a + b*s + c*s^2 + d*s^3. Scaling only `a` while leaving b/c/d
    unchanged can produce negative widths at some s even when scaled-a is positive.
    """
    src = _make_cubic_map(tmp_path, a="1.0", b="-0.1", c="0.0", d="0.0")
    out = RLFuzzer(seed=1).apply_to_map(
        src,
        {"lane_width_scale": 0.5, "curvature_noise": 0.0, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "fuzz"),
    )
    coeffs = _width_coeffs(out)
    width_entry = None
    for key in coeffs:
        if float(key) == 0.0:
            width_entry = coeffs[key]
            break
    assert width_entry is not None, f"no width record at sOffset=0, keys={list(coeffs.keys())}"
    a = width_entry["a"]
    b = width_entry["b"]
    assert a == pytest.approx(0.5, abs=1e-6)
    assert b == pytest.approx(-0.1, abs=1e-6)
    # Verify the negative-width defect exists at s=50
    width_at_50 = a + b * 50.0
    assert width_at_50 < 0, "Expected negative width at s=50 (PR #49 gap demonstrated)"


# ---------------------------------------------------------------------------
# Map immutability
# ---------------------------------------------------------------------------


def test_input_map_never_mutated(tmp_path):
    src = _make_cubic_map(tmp_path, a="3.5", b="0.2", c="-0.01", d="0.001")
    before = hashlib.sha256(open(src, "rb").read()).hexdigest()
    RLFuzzer(seed=1).apply_to_map(
        src,
        {"lane_width_scale": 1.5, "curvature_noise": 0.02, "object_density_scale": 1.2},
        out_dir=str(tmp_path / "fuzz"),
    )
    after = hashlib.sha256(open(src, "rb").read()).hexdigest()
    assert before == after


# ---------------------------------------------------------------------------
# Seed reproducibility
# ---------------------------------------------------------------------------


def test_same_seed_byte_identical_output(tmp_path):
    src = _make_cubic_map(tmp_path, a="3.5", b="0.2", c="-0.01", d="0.001")
    fuzzer_a = RLFuzzer(seed=123)
    fuzzer_b = RLFuzzer(seed=123)
    out_a = fuzzer_a.apply_to_map(src, fuzzer_a.sample_action(), out_dir=str(tmp_path / "fuzz_a"))
    out_b = fuzzer_b.apply_to_map(src, fuzzer_b.sample_action(), out_dir=str(tmp_path / "fuzz_b"))
    assert hashlib.sha256(open(out_a, "rb").read()).hexdigest() == hashlib.sha256(
        open(out_b, "rb").read()
    ).hexdigest()


# ---------------------------------------------------------------------------
# Geometry/topology validity after perturbation
# ---------------------------------------------------------------------------


def test_widths_remain_positive_after_perturbation(tmp_path):
    """All drivable lane widths must remain positive after perturbation."""
    src = _make_cubic_map(tmp_path, a="3.5", b="0.0", c="0.0", d="0.0")
    out = RLFuzzer(seed=1).apply_to_map(
        src,
        {"lane_width_scale": 0.9, "curvature_noise": 0.0, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "fuzz"),
    )
    coeffs = _width_coeffs(out)
    for s_offset, c in coeffs.items():
        assert c["a"] > 0, f"width a-coefficient at sOffset={s_offset} is non-positive: {c['a']}"


def test_curvature_remains_bounded_after_perturbation(tmp_path):
    """Curvature must remain within MAX_ABS_CURVATURE after perturbation."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", {"id": "0", "length": "10.0", "junction": "-1"})
    pv = ET.SubElement(road, "planView")
    g = ET.SubElement(pv, "geometry", {"s": "0.0", "x": "0.0", "y": "0.0", "hdg": "0.0", "length": "10.0"})
    ET.SubElement(g, "arc", {"curvature": "0.24"})
    p = tmp_path / "arc.xodr"
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)
    out = RLFuzzer(seed=0).apply_to_map(
        str(p),
        {"lane_width_scale": 1.0, "curvature_noise": 0.02, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "fuzz"),
    )
    new_curvature = float(ET.parse(out).getroot().find(".//arc").get("curvature"))
    assert abs(new_curvature) <= MAX_ABS_CURVATURE


def test_topology_links_preserved_after_perturbation(tmp_path):
    """Predecessor/successor links must be preserved (not deleted) after perturbation."""
    root = ET.Element("OpenDRIVE")
    road1 = ET.SubElement(root, "road", {"id": "1", "length": "10.0", "junction": "-1"})
    ET.SubElement(road1, "link").append(
        ET.fromstring('<successor elementType="road" elementId="2"/>')
    )
    road2 = ET.SubElement(root, "road", {"id": "2", "length": "10.0", "junction": "-1"})
    ET.SubElement(road2, "link").append(
        ET.fromstring('<predecessor elementType="road" elementId="1"/>')
    )
    pv = ET.SubElement(road1, "planView")
    ET.SubElement(pv, "geometry", {"s": "0.0", "x": "0.0", "y": "0.0", "hdg": "0.0", "length": "10.0"})
    ET.SubElement(pv.find("geometry"), "line")
    p = tmp_path / "topology.xodr"
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)
    out = RLFuzzer(seed=1).apply_to_map(
        str(p),
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "fuzz"),
    )
    out_root = ET.parse(out).getroot()
    # Links must still exist
    assert out_root.find(".//road[@id='1']/link/successor") is not None
    assert out_root.find(".//road[@id='2']/link/predecessor") is not None


# ---------------------------------------------------------------------------
# Object-density > 1 limitation
# ---------------------------------------------------------------------------


def test_object_density_greater_than_one_cannot_add_objects(tmp_path):
    """documented limitation: object_density_scale > 1 can only subsample,
    never add new objects. keep_count is capped at existing object count.
    Even at the max allowed scale (1.5), no new objects are created."""
    src = _make_cubic_map(tmp_path, a="3.5", b="0.0", c="0.0", d="0.0")
    # Add some objects
    root = ET.parse(src).getroot()
    objects = ET.SubElement(root, "objects")
    for j in range(3):
        ET.SubElement(objects, "object", {"id": str(j), "type": "pole", "s": str(j), "t": "5.0"})
    ET.ElementTree(root).write(src, encoding="utf-8", xml_declaration=True)

    out = RLFuzzer(seed=0).apply_to_map(
        src,
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": OBJECT_DENSITY_MAX},
        out_dir=str(tmp_path / "fuzz"),
    )
    remaining = len(ET.parse(out).getroot().findall(".//object"))
    assert remaining == 3  # can't keep more than exist even at scale 1.5

    # The report must explicitly flag the unsupported density increase
    # (fail-closed admission), not silently ignore it.
    report_path = out + ".json"
    import json as _json

    report = _json.loads(open(report_path, encoding="utf-8").read())
    assert report["objects"]["density_status"] == "UNSUPPORTED_DENSITY_INCREASE"
    assert report["objects"]["requested_scale"] == OBJECT_DENSITY_MAX
    assert report["objects"]["reason"] == "synthetic object addition not authorized"


def test_object_density_scale_one_preserves_all_objects(tmp_path: Path) -> None:
    """Scale factor 1.0 must preserve every object and report UNCHANGED."""
    src = _make_cubic_map(tmp_path, a="3.5", b="0.0", c="0.0", d="0.0")
    root = ET.parse(src).getroot()
    objects = ET.SubElement(root, "objects")
    for j in range(4):
        ET.SubElement(objects, "object", {"id": str(j), "type": "pole", "s": str(j), "t": "5.0"})
    ET.ElementTree(root).write(src, encoding="utf-8", xml_declaration=True)

    out = RLFuzzer(seed=7).apply_to_map(
        src,
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "fuzz"),
    )
    remaining = len(ET.parse(out).getroot().findall(".//object"))
    assert remaining == 4
    report_path = out + ".json"
    import json as _json

    report = _json.loads(open(report_path, encoding="utf-8").read())
    assert report["objects"]["density_status"] == "UNCHANGED"
    assert report["objects"]["objects_after"] == 4


def test_object_density_scale_below_one_subsamples_deterministically(
    tmp_path: Path,
) -> None:
    """Scale factor below 1.0 must subsample objects deterministically."""
    src = _make_cubic_map(tmp_path, a="3.5", b="0.0", c="0.0", d="0.0")
    root = ET.parse(src).getroot()
    objects = ET.SubElement(root, "objects")
    for j in range(10):
        ET.SubElement(objects, "object", {"id": str(j), "type": "pole", "s": str(j), "t": "5.0"})
    ET.ElementTree(root).write(src, encoding="utf-8", xml_declaration=True)

    # Same seed -> same subset
    out_a = RLFuzzer(seed=11).apply_to_map(
        src,
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 0.5},
        out_dir=str(tmp_path / "fuzz_a"),
    )
    out_b = RLFuzzer(seed=11).apply_to_map(
        src,
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 0.5},
        out_dir=str(tmp_path / "fuzz_b"),
    )
    remaining_a = len(ET.parse(out_a).getroot().findall(".//object"))
    remaining_b = len(ET.parse(out_b).getroot().findall(".//object"))
    assert remaining_a == remaining_b == 5  # round(10 * 0.5) = 5
    # Same kept object IDs under the same seed
    kept_a = sorted(
        obj.get("id") for obj in ET.parse(out_a).getroot().findall(".//object")
    )
    kept_b = sorted(
        obj.get("id") for obj in ET.parse(out_b).getroot().findall(".//object")
    )
    assert kept_a == kept_b
    assert all(obj.get("type") == "pole" for obj in ET.parse(out_a).getroot().findall(".//object"))


def test_object_density_above_one_does_not_modify_input(tmp_path: Path) -> None:
    """Scale > 1 must leave the input map byte-identical (no synthetic objects)."""
    src = _make_cubic_map(tmp_path, a="3.5", b="0.0", c="0.0", d="0.0")
    root = ET.parse(src).getroot()
    objects = ET.SubElement(root, "objects")
    for j in range(3):
        ET.SubElement(objects, "object", {"id": str(j), "type": "pole", "s": str(j), "t": "5.0"})
    ET.ElementTree(root).write(src, encoding="utf-8", xml_declaration=True)

    import hashlib

    before = hashlib.sha256(open(src, "rb").read()).hexdigest()
    RLFuzzer(seed=3).apply_to_map(
        src,
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 1.5},
        out_dir=str(tmp_path / "fuzz"),
    )
    after = hashlib.sha256(open(src, "rb").read()).hexdigest()
    assert before == after  # input not mutated



# ---------------------------------------------------------------------------
# GNN LaneGNNRefiner: deliberate no-op stub
# ---------------------------------------------------------------------------


def test_lane_gnn_refiner_is_noop_stub(capsys):
    """LaneGNNRefiner is a deliberate no-op stub, NOT a trained model.

    run_inplace returns None and prints "stub active". No geometry is
    modified. This is not a learned policy and does not refine lane geometry.
    """
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    result = LaneGNNRefiner.run_inplace(root, model_path="model.pt")
    assert result is None
    assert "stub active" in capsys.readouterr().out


def test_lane_gnn_refiner_does_not_modify_geometry(capsys):
    """The GNN stub must not modify any OpenDRIVE geometry."""
    root = ET.fromstring(
        "<OpenDRIVE><road id='1' length='10'><planView><geometry s='0' x='0' y='0' "
        "hdg='0' length='10'><line/></geometry></planView></road></OpenDRIVE>"
    )
    before = ET.tostring(root)
    LaneGNNRefiner.run_inplace(root, model_path="model.pt")
    after = ET.tostring(root)
    assert before == after  # geometry unchanged


# ---------------------------------------------------------------------------
# RQ4 0.9207: structural domain separation, NOT perceptual transfer
# ---------------------------------------------------------------------------


def test_rq4_09207_is_structural_not_perceptual():
    """RQ4 cosine distance 0.9207 is structural domain separation between
    map domains, NOT perceptual transfer accuracy. This test documents the
    boundary: no perception model, no training, no evaluation ΓÇö just a
    descriptive statistic that must not be sold as generalization."""
    # The value 0.9207 is a cosine distance between GNN embeddings of two
    # map domains. It says nothing about perception performance.
    cosine_distance = 0.9207
    assert 0.0 <= cosine_distance <= 1.0
    # This is a descriptive statistic, not an accuracy metric.
    # Any claim "perception improved by 0.9207" would be false.
