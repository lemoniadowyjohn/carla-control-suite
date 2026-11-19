"""F16 RL fuzzer/map perturbation quality invariants (V135, test-only).

Deterministic, bounded tests of exposed RL fuzzer behavior. Does not alter
thresholds/mandatory gates/training policies and makes no real-world RL claims.
"""
from __future__ import annotations

import hashlib
import json
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


def _make_map(tmp_path: Path, n_arcs: int = 2, n_objects: int = 6) -> Path:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", {"id": "0", "length": "100.0", "junction": "-1"})
    pv = ET.SubElement(road, "planView")
    for i in range(n_arcs):
        g = ET.SubElement(
            pv,
            "geometry",
            {"s": str(i * 50.0), "x": "0.0", "y": "0.0", "hdg": "0.0", "length": "50.0"},
        )
        ET.SubElement(g, "arc", {"curvature": "0.01"})
    lanes = ET.SubElement(road, "lanes")
    sec = ET.SubElement(lanes, "laneSection", {"s": "0.0"})
    for side_tag, lane_id, lane_type in (("left", "1", "sidewalk"), ("right", "-1", "driving")):
        side = ET.SubElement(sec, side_tag)
        lane = ET.SubElement(side, "lane", {"id": lane_id, "type": lane_type})
        # Polynomial width profile: a + b*ds + c*ds^2 + d*ds^3
        ET.SubElement(lane, "width", {"sOffset": "0.0", "a": "3.5", "b": "0.1", "c": "-0.001", "d": "0.0"})
    objs = ET.SubElement(root, "objects")
    for j in range(n_objects):
        ET.SubElement(objs, "object", {"id": str(j), "type": "tree", "s": str(j), "t": "4.0"})
    p = tmp_path / "base.xodr"
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)
    return p


def _width_value(width_el, ds: float) -> float:
    return sum(
        float(width_el.get(k, "0")) * (ds ** p)
        for p, k in enumerate(("a", "b", "c", "d"))
    )


def test_seed_reproducibility_multi_episode_byte_identical(tmp_path):
    src = _make_map(tmp_path)
    f1 = RLFuzzer(seed=123)
    f2 = RLFuzzer(seed=123)
    outs1 = [f1.run_episode(str(src), out_dir=str(tmp_path / "a")) for _ in range(3)]
    outs2 = [f2.run_episode(str(src), out_dir=str(tmp_path / "b")) for _ in range(3)]
    hashes1 = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in outs1]
    hashes2 = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in outs2]
    assert hashes1 == hashes2


def test_different_seeds_can_produce_different_actions():
    a = RLFuzzer(seed=1).sample_action()
    b = RLFuzzer(seed=2).sample_action()
    assert a != b


@pytest.mark.parametrize("scale", [0.7, 1.0, 1.3])
def test_driving_lane_width_polynomial_scaled_uniformly_and_nonnegative(tmp_path, scale):
    src = _make_map(tmp_path)
    fuzzer = RLFuzzer(seed=0)
    action = {"lane_width_scale": scale, "curvature_noise": 0.0, "object_density_scale": 1.0}
    out = fuzzer.apply_to_map(str(src), action, out_dir=str(tmp_path / "out"))
    root = ET.parse(out).getroot()
    # Only driving lane scaled; sidewalk unchanged.
    driving = root.find(".//lane[@type='driving']/width")
    sidewalk = root.find(".//lane[@type='sidewalk']/width")
    assert driving is not None and sidewalk is not None
    for ds in (0.0, 1.0, 5.0, 10.0):
        assert _width_value(driving, ds) == pytest.approx((3.5 + 0.1 * ds - 0.001 * ds * ds) * scale, abs=1e-4)
        assert _width_value(sidewalk, ds) == pytest.approx(3.5 + 0.1 * ds - 0.001 * ds * ds, abs=1e-9)
        assert _width_value(driving, ds) > 0.0


def test_bounds_enforced_reject_impossible_or_out_of_range_actions():
    fuzzer = RLFuzzer(seed=0)
    bad = [
        {"lane_width_scale": LANE_WIDTH_SCALE_MIN - 0.01, "curvature_noise": 0.0, "object_density_scale": 1.0},
        {"lane_width_scale": LANE_WIDTH_SCALE_MAX + 0.01, "curvature_noise": 0.0, "object_density_scale": 1.0},
        {"lane_width_scale": 1.0, "curvature_noise": -1e-9, "object_density_scale": 1.0},
        {"lane_width_scale": 1.0, "curvature_noise": CURVATURE_NOISE_MAX + 1e-6, "object_density_scale": 1.0},
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": OBJECT_DENSITY_MIN - 0.01},
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": OBJECT_DENSITY_MAX + 0.01},
        {"lane_width_scale": float("nan"), "curvature_noise": 0.0, "object_density_scale": 1.0},
    ]
    for action in bad:
        with pytest.raises(ValueError):
            fuzzer.validate_action(action)


def test_curvature_always_clamped_to_physical_cap(tmp_path):
    # High base curvature + max noise must remain within cap.
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", {"id": "0", "length": "10.0", "junction": "-1"})
    pv = ET.SubElement(road, "planView")
    g = ET.SubElement(pv, "geometry", {"s": "0.0", "x": "0.0", "y": "0.0", "hdg": "0.0", "length": "10.0"})
    ET.SubElement(g, "arc", {"curvature": "0.24"})
    p = tmp_path / "arc.xodr"
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)
    out = RLFuzzer(seed=123).apply_to_map(
        str(p),
        {"lane_width_scale": 1.0, "curvature_noise": CURVATURE_NOISE_MAX, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "out"),
    )
    curv = float(ET.parse(out).getroot().find(".//arc").get("curvature"))
    assert abs(curv) <= MAX_ABS_CURVATURE
    assert math.isfinite(curv)


def test_missing_elevation_and_topology_context_do_not_produce_fake_quality_claim(tmp_path):
    # Map with no elevationProfile/junction detail: fuzzer must still produce a
    # deterministic perturbed copy and a report, but must not emit any pass/accept
    # quality verdict fields.
    src = _make_map(tmp_path)
    fuzzer = RLFuzzer(seed=7)
    out = fuzzer.apply_to_map(
        str(src),
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "out"),
    )
    report = json.loads(Path(out + ".json").read_text(encoding="utf-8"))
    forbidden = {"quality_pass", "map_accepted", "valid_for_release", "valid_for_experiments", "gate_pass"}
    assert forbidden.isdisjoint(report.keys())
    # Output is a well-formed OpenDRIVE root copy.
    assert ET.parse(out).getroot().tag == "OpenDRIVE"
    assert ET.parse(out).getroot().find(".//elevationProfile") is None


def test_input_file_never_mutated(tmp_path):
    src = _make_map(tmp_path)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    RLFuzzer(seed=99).run_episode(str(src), out_dir=str(tmp_path / "out"))
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
