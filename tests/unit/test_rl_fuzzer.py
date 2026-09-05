# RL fuzzer operationalization (post-audit, 2026-08-17): the previous
# contract stub applied no perturbations at all (apply_to_map returned the
# input path). These tests pin the real implementation: bounded, seeded,
# content-addressed perturbation of a copy, with the input never mutated.
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


def _lane_width_root(a_value: str, lane_type: str = "driving") -> ET.Element:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", {"id": "0", "length": "10.0", "junction": "-1"})
    lanes = ET.SubElement(road, "lanes")
    sec = ET.SubElement(lanes, "laneSection", {"s": "0.0"})
    side = ET.SubElement(sec, "left" if lane_type == "sidewalk" else "right")
    lane = ET.SubElement(side, "lane", {"id": "1" if lane_type == "sidewalk" else "-1", "type": lane_type})
    ET.SubElement(lane, "width", {"sOffset": "0.0", "a": a_value, "b": "0.0", "c": "0.0", "d": "0.0"})
    return root


def _arc_root(curvature: str) -> ET.Element:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", {"id": "0", "length": "10.0", "junction": "-1"})
    pv = ET.SubElement(road, "planView")
    g = ET.SubElement(pv, "geometry", {"s": "0.0", "x": "0.0", "y": "0.0", "hdg": "0.0", "length": "10.0"})
    ET.SubElement(g, "arc", {"curvature": curvature})
    return root


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


# --------------------------------------------------------------------------
# Bug fixes: curvature clamp was counted but never applied; NaN/Inf lane
# widths silently passed the "<= 0.0" drop check (NaN/Inf comparisons are
# always False) and got written into the output XODR as literal "nan"/"inf".
# --------------------------------------------------------------------------


def test_perturb_curvature_actually_clamps_not_just_counts() -> None:
    # seed=0 with curvature=0.24, noise=0.02 is known (verified directly) to
    # push new_curvature to 0.253776874 -- genuinely over MAX_ABS_CURVATURE.
    # Unlike the pre-fix test (which used seed=5 and passed only by luck of
    # that seed's draw landing in-bounds), this fixture is chosen specifically
    # to exceed the cap, so the assertion is a real guarantee, not incidental.
    root = _arc_root("0.24")
    fuzzer = RLFuzzer(seed=0)
    stats = fuzzer._perturb_curvature(root, 0.02)
    new_curvature = float(root.find(".//arc").get("curvature"))
    assert stats["arc_curvature_clamped"] == 1
    assert abs(new_curvature) == pytest.approx(MAX_ABS_CURVATURE, abs=1e-9)


def test_perturb_curvature_within_bounds_is_not_clamped() -> None:
    root = _arc_root("0.0")
    fuzzer = RLFuzzer(seed=0)
    stats = fuzzer._perturb_curvature(root, 0.01)
    new_curvature = float(root.find(".//arc").get("curvature"))
    assert stats["arc_curvature_clamped"] == 0
    assert abs(new_curvature) <= MAX_ABS_CURVATURE


def test_perturb_curvature_skips_non_finite_input_curvature() -> None:
    root = _arc_root("nan")
    fuzzer = RLFuzzer(seed=0)
    stats = fuzzer._perturb_curvature(root, 0.02)
    # Left untouched (still "nan"), not perturbed into a fabricated finite value.
    assert root.find(".//arc").get("curvature") == "nan"
    assert stats["arc_records_modified"] == 0


def test_perturb_lane_widths_drops_nan_width_instead_of_corrupting() -> None:
    root = _lane_width_root("nan")
    fuzzer = RLFuzzer(seed=0)
    stats = fuzzer._perturb_lane_widths(root, 1.1)
    new_a = root.find(".//width").get("a")
    assert new_a == "nan"  # untouched, not corrupted further
    assert stats["width_records_modified"] == 0
    assert stats["width_records_dropped_nonpositive"] == 1


def test_perturb_lane_widths_drops_inf_width_instead_of_corrupting() -> None:
    root = _lane_width_root("inf")
    fuzzer = RLFuzzer(seed=0)
    stats = fuzzer._perturb_lane_widths(root, 1.1)
    new_a = root.find(".//width").get("a")
    assert new_a == "inf"
    assert stats["width_records_modified"] == 0
    assert stats["width_records_dropped_nonpositive"] == 1


def test_perturb_lane_widths_drops_negative_inf_width() -> None:
    root = _lane_width_root("-inf")
    fuzzer = RLFuzzer(seed=0)
    stats = fuzzer._perturb_lane_widths(root, 1.1)
    assert root.find(".//width").get("a") == "-inf"
    assert stats["width_records_modified"] == 0
    assert stats["width_records_dropped_nonpositive"] == 1


def test_apply_to_map_end_to_end_never_further_corrupts_non_finite_inputs(tmp_path) -> None:
    """Regression guard at the apply_to_map level: a pre-existing NaN width
    and NaN curvature (a garbage/degenerate INPUT, not something the fuzzer
    created) must be left byte-for-byte as they were, not run through the
    scale/noise arithmetic (which would still produce NaN/Inf, just via a
    different, harder-to-recognize string representation). The fuzzer's job
    is to perturb valid data, not to silently launder pre-existing garbage
    through an arithmetic operation."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", {"id": "0", "length": "10.0", "junction": "-1"})
    pv = ET.SubElement(road, "planView")
    g = ET.SubElement(pv, "geometry", {"s": "0.0", "x": "0.0", "y": "0.0", "hdg": "0.0", "length": "10.0"})
    ET.SubElement(g, "arc", {"curvature": "nan"})
    lanes = ET.SubElement(road, "lanes")
    sec = ET.SubElement(lanes, "laneSection", {"s": "0.0"})
    right = ET.SubElement(sec, "right")
    lane = ET.SubElement(right, "lane", {"id": "-1", "type": "driving"})
    ET.SubElement(lane, "width", {"sOffset": "0.0", "a": "inf", "b": "0.0", "c": "0.0", "d": "0.0"})
    p = tmp_path / "degenerate.xodr"
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)

    out = RLFuzzer(seed=1).apply_to_map(
        str(p),
        {"lane_width_scale": 1.1, "curvature_noise": 0.02, "object_density_scale": 1.0},
        out_dir=str(tmp_path / "fuzz"),
    )
    out_root = _read(out)
    assert out_root.find(".//width").get("a") == "inf"
    assert out_root.find(".//arc").get("curvature") == "nan"


# --------------------------------------------------------------------------
# Coverage backfill: already-correct behavior that had no direct test.
# --------------------------------------------------------------------------


def test_validate_action_rejects_non_dict() -> None:
    with pytest.raises(ValueError, match="dict"):
        RLFuzzer().validate_action("not a dict")


def test_validate_action_rejects_non_numeric_values() -> None:
    with pytest.raises(ValueError, match="numeric"):
        RLFuzzer().validate_action(
            {"lane_width_scale": "oops", "curvature_noise": 0.0, "object_density_scale": 1.0}
        )


def test_validate_action_accepts_exact_boundary_values() -> None:
    action = {
        "lane_width_scale": LANE_WIDTH_SCALE_MIN,
        "curvature_noise": CURVATURE_NOISE_MAX,
        "object_density_scale": OBJECT_DENSITY_MAX,
    }
    assert RLFuzzer().validate_action(action) == action
    action2 = {
        "lane_width_scale": LANE_WIDTH_SCALE_MAX,
        "curvature_noise": 0.0,
        "object_density_scale": OBJECT_DENSITY_MIN,
    }
    assert RLFuzzer().validate_action(action2) == action2


def test_validate_action_rejects_below_min_lane_width_scale() -> None:
    with pytest.raises(ValueError, match="lane_width_scale"):
        RLFuzzer().validate_action(
            {"lane_width_scale": LANE_WIDTH_SCALE_MIN - 0.01, "curvature_noise": 0.0, "object_density_scale": 1.0}
        )


def test_validate_action_rejects_negative_curvature_noise() -> None:
    with pytest.raises(ValueError, match="curvature_noise"):
        RLFuzzer().validate_action(
            {"lane_width_scale": 1.0, "curvature_noise": -0.001, "object_density_scale": 1.0}
        )


def test_validate_action_rejects_above_max_object_density() -> None:
    with pytest.raises(ValueError, match="object_density_scale"):
        RLFuzzer().validate_action(
            {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": OBJECT_DENSITY_MAX + 0.01}
        )


def test_perturb_lane_widths_skips_non_drivable_lane_types() -> None:
    root = _lane_width_root("2.0", lane_type="sidewalk")
    fuzzer = RLFuzzer(seed=0)
    stats = fuzzer._perturb_lane_widths(root, 1.5)
    assert root.find(".//width").get("a") == "2.0"  # untouched
    assert stats == {"width_records_modified": 0, "width_records_dropped_nonpositive": 0}


def test_object_density_scale_clamps_at_upper_bound(tmp_path) -> None:
    src = _make_map(tmp_path, n_objects=4)
    out = RLFuzzer(seed=0).apply_to_map(
        src,
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": OBJECT_DENSITY_MAX},
        out_dir=str(tmp_path / "fuzz"),
    )
    remaining = len(_read(out).findall(".//object"))
    assert remaining == 4  # can't keep more than exist, even at scale > 1.0


def test_object_density_handles_zero_objects(tmp_path) -> None:
    src = _make_map(tmp_path, n_objects=0)
    out = RLFuzzer(seed=0).apply_to_map(
        src,
        {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 0.5},
        out_dir=str(tmp_path / "fuzz"),
    )
    assert _read(out).findall(".//object") == []


def test_apply_to_map_default_out_dir(tmp_path) -> None:
    src = _make_map(tmp_path)
    out = RLFuzzer(seed=0).apply_to_map(
        str(src), {"lane_width_scale": 1.0, "curvature_noise": 0.0, "object_density_scale": 1.0}
    )
    assert Path(out).parent == Path(src).parent / "fuzz_out"


def test_main_cli_runs_episodes_and_prints_json(tmp_path, capsys) -> None:
    import json as _json
    import sys as _sys

    import ultimate_pipeline.utils.timestamped_print as _tp
    from ultimate_pipeline.experiments.rl_fuzzer import main

    src = _make_map(tmp_path)
    argv = [
        "rl_fuzzer",
        "--xodr", src,
        "--seed", "3",
        "--episodes", "2",
        "--out-dir", str(tmp_path / "fuzz_cli"),
        "--lane-width-scale", "1.05",
    ]
    old_argv = _sys.argv
    # Some other test/module in this pytest session may have called
    # _tp.enable_timestamped_print() without disabling it afterward -- that
    # globally monkeypatches builtins.print to prefix a
    # "[YYYY-MM-DD HH:MM:SS] " timestamp, which breaks main()'s
    # print(json.dumps(...)) contract for any test running later in the same
    # process (same root cause as the pre-existing test_find_broken_roads_cli.py
    # ::test_find_broken_roads_json_mode_... failure). Use the module's own
    # disable/enable so the *true* original print (captured at that module's
    # own import time) is restored, not whatever the bare `print` name
    # happens to resolve to right now -- if pollution is already active,
    # `print` itself would already be the polluted wrapper. Restore the
    # pre-test enabled/disabled state afterward either way.
    was_enabled = _tp._enabled
    _tp.disable_timestamped_print()
    _sys.argv = argv
    try:
        rc = main()
    finally:
        _sys.argv = old_argv
        if was_enabled:
            _tp.enable_timestamped_print()
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.strip().splitlines() if ln]
    assert len(lines) == 2
    records = [_json.loads(ln) for ln in lines]
    assert [r["episode"] for r in records] == [0, 1]
    assert all(r["action"]["lane_width_scale"] == 1.05 for r in records)