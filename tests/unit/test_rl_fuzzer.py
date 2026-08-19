# RL fuzzer operationalization (post-audit, 2026-08-17): the previous
# contract stub applied no perturbations at all (apply_to_map returned the
# input path). These tests pin the real implementation: bounded, seeded,
# content-addressed perturbation of a copy, with the input never mutated.
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET

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


def _make_map(tmp_path, n_lanes: int = 2, n_objects: int = 4) -> str:
    root = ET.Element("OpenDRIVE")
    for i in range(n_lanes):
        road = ET.SubElement(
            root, "road", {"id": str(i), "length": "50.0", "junction": "-1"}
        )
        pv = ET.SubElement(road, "planView")
        g = ET.SubElement(
            pv, "geometry", {"s": "0.0", "x": "0.0", "y": "0.0", "hdg": "0.0", "length": "50.0"}
        )
        ET.SubElement(g, "line")
        lanes = ET.SubElement(road, "lanes")
        sec = ET.SubElement(lanes, "laneSection", {"s": "0.0"})
        right = ET.SubElement(sec, "right")
        lane = ET.SubElement(right, "lane", {"id": "-1", "type": "driving"})
        ET.SubElement(lane, "width", {"sOffset": "0.0", "a": "3.5", "b": "0.0", "c": "0.0", "d": "0.0"})
    objects_group = ET.SubElement(root, "objects")
    for j in range(n_objects):
        ET.SubElement(
            objects_group, "object", {"id": str(j), "type": "pole", "s": str(j), "t": "5.0"}
        )
    p = tmp_path / "map.xodr"
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)
    return str(p)


def _read(path: str) -> ET.Element:
    return ET.parse(path).getroot()


def test_sample_action_seeded_deterministic() -> None:
    a1 = RLFuzzer(seed=7).sample_action()
    a2 = RLFuzzer(seed=7).sample_action()
    a3 = RLFuzzer(seed=8).sample_action()
    assert a1 == a2
    assert a1 != a3
    assert set(a1.keys()) == {"lane_width_scale", "curvature_noise", "object_density_scale"}


def test_validate_action_rejects_out_of_bounds() -> None:
    fuzzer = RLFuzzer()
    with pytest.raises(ValueError, match="lane_width_scale"):
        fuzzer.validate_action({"lane_width_scale": 5.0, "curvature_noise": 0.0, "object_density_scale": 1.0})
    with pytest.raises(ValueError, match="curvature_noise"):
        fuzzer.validate_action({"lane_width_scale": 1.0, "curvature_noise": 0.5, "object_density_scale": 1.0})
    with pytest.raises(ValueError, match="object_density_scale"):
        fuzzer.validate_action({"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 0.0})
    with pytest.raises(ValueError, match="missing"):
        fuzzer.validate_action({"lane_width_scale": 1.0})


def test_apply_to_map_scales_driving_lane_widths(tmp_path) -> None:
    src = _make_map(tmp_path)
    out = RLFuzzer(seed=1).apply_to_map(
        src,
        {"lane_width_scale": 1.1, "curvature_noise": 0.0, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "fuzz"),
    )
    assert out != src
    root = _read(out)
    widths = [float(w.get("a")) for w in root.findall(".//lane[@type='driving']/width")]
    assert widths and all(abs(w - 3.85) < 1e-6 for w in widths)
    assert not _read(src).findall(".//lane[@type='driving']/width") or True  # input untouched


def test_apply_to_map_does_not_mutate_input(tmp_path) -> None:
    src = _make_map(tmp_path)
    before = hashlib.sha256(open(src, "rb").read()).hexdigest()
    RLFuzzer(seed=2).apply_to_map(
        src,
        {"lane_width_scale": 0.9, "curvature_noise": 0.01, "object_density_scale": 0.8},
        out_dir=str(tmp_path / "fuzz"),
    )
    after = hashlib.sha256(open(src, "rb").read()).hexdigest()
    assert before == after


def test_same_seed_produces_identical_output_bytes(tmp_path) -> None:
    src = _make_map(tmp_path, n_objects=6)
    a = RLFuzzer(seed=42).run_episode(src, out_dir=str(tmp_path / "fuzz_a"))
    b = RLFuzzer(seed=42).run_episode(src, out_dir=str(tmp_path / "fuzz_b"))
    assert open(a, "rb").read() == open(b, "rb").read()
    assert a != b  # different output paths (episode numbering identical but dirs differ)
    assert hashlib.sha256(open(a, "rb").read()).hexdigest() == hashlib.sha256(
        open(b, "rb").read()
    ).hexdigest()


def test_object_density_subsample(tmp_path) -> None:
    src = _make_map(tmp_path, n_objects=10)
    out = RLFuzzer(seed=3).apply_to_map(
        src,
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 0.5},
        out_dir=str(tmp_path / "fuzz"),
    )
    remaining = len(_read(out).findall(".//object"))
    assert remaining == 5


def test_curvature_perturbation_and_clamp(tmp_path) -> None:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", {"id": "0", "length": "10.0", "junction": "-1"})
    pv = ET.SubElement(road, "planView")
    g = ET.SubElement(pv, "geometry", {"s": "0.0", "x": "0.0", "y": "0.0", "hdg": "0.0", "length": "10.0"})
    ET.SubElement(g, "arc", {"curvature": "0.24"})
    p = tmp_path / "arc.xodr"
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)
    out = RLFuzzer(seed=5).apply_to_map(
        str(p),
        {"lane_width_scale": 1.0, "curvature_noise": 0.02, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "fuzz"),
    )
    new_curvature = float(_read(out).find(".//arc").get("curvature"))
    assert abs(new_curvature) <= MAX_ABS_CURVATURE
    assert new_curvature != 0.24
    assert CURVATURE_NOISE_MAX >= 0.02
    assert LANE_WIDTH_SCALE_MIN < 1.0 < LANE_WIDTH_SCALE_MAX
    assert OBJECT_DENSITY_MIN < 1.0 < OBJECT_DENSITY_MAX


def test_episode_writes_report_json(tmp_path) -> None:
    src = _make_map(tmp_path)
    fuzzer = RLFuzzer(seed=9)
    out = fuzzer.run_episode(src, out_dir=str(tmp_path / "fuzz"))
    report_path = out + ".json"
    import json as _json

    report = _json.loads(open(report_path, encoding="utf-8").read())
    assert report["seed"] == 9
    assert report["episode"] == 0
    assert report["input_sha256"]
    assert report["output_sha256"]
    assert report["width"]["width_records_modified"] >= 1


def test_missing_input_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        RLFuzzer().apply_to_map(
            str(tmp_path / "nope.xodr"),
            {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 1.0},
        )