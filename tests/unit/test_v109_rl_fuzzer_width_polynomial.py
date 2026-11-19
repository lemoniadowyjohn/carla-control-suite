"""V109 RL fuzzer: lane-width scaling preserves the OpenDRIVE cubic profile."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.experiments.rl_fuzzer import RLFuzzer


def _lane_width(**coefficients):
    root = ET.Element("OpenDRIVE")
    lane = ET.SubElement(root, "lane", {"type": "driving"})
    ET.SubElement(
        lane, "width", {k: str(v) for k, v in coefficients.items()}
    )
    return root, lane.find("width")


def _value(width, ds):
    return sum(
        float(width.get(key, "0")) * ds**power
        for power, key in enumerate(("a", "b", "c", "d"))
    )


@pytest.mark.parametrize("scale", [0.9, 1.25, 2.0])
def test_polynomial_width_is_scaled_uniformly_at_every_station(scale):
    root, width = _lane_width(a=3.5, b=0.25, c=-0.02, d=0.001)
    baseline = [_value(width, s) for s in (0, 1, 3, 5)]
    result = RLFuzzer._perturb_lane_widths(root, scale)
    assert result == {"width_records_modified": 1, "width_records_dropped_nonpositive": 0}
    observed = [_value(width, s) for s in (0, 1, 3, 5)]
    for actual, original in zip(observed, baseline):
        assert actual == pytest.approx(original * scale, abs=1e-4)


def test_malformed_cubic_coefficient_causes_no_partial_mutation():
    root, width = _lane_width(a=3.5, b="nan", c=0, d=0)
    before = dict(width.attrib)
    result = RLFuzzer._perturb_lane_widths(root, 1.2)
    assert dict(width.attrib) == before
    assert result["width_records_modified"] == 0
    assert result["width_records_dropped_nonpositive"] == 1


def test_sidewalk_not_rescaled():
    root, width = _lane_width(a=2.0, b=0.3, c=0, d=0)
    root.find(".//lane").set("type", "sidewalk")
    before = dict(width.attrib)
    assert RLFuzzer._perturb_lane_widths(root, 1.5)["width_records_modified"] == 0
    assert dict(width.attrib) == before
