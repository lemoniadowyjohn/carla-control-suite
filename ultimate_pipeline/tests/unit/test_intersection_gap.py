# -*- coding: utf-8 -*-
"""Tests for IntersectionGap (ultimate_pipeline/domain_gap/intersection_gap.py).

Live: imported by run_full_domain_gap.py, pipeline_stages/stage_11_12_sim_domain.py,
stage_12_domain_gap.py -- feeds the RQ1 intersection-type domain-gap metric.
Zero prior test coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.domain_gap.intersection_gap import IntersectionGap


def _junction(n_roads: int, *, name: str = "", jid: str = "1") -> ET.Element:
    """A junction whose set of unique incoming roads has exactly n_roads
    members -- classify_junction() counts unique incomingRoad/connectingRoad
    values across all <connection> elements, so one incoming road per
    connection (no connectingRoad) gives precise control over that count."""
    j = ET.Element("junction", name=name, id=jid)
    for i in range(n_roads):
        ET.SubElement(j, "connection", incomingRoad=f"r{i}")
    return j


def test_dead_end_classified():
    assert IntersectionGap.classify_junction(_junction(1)) == "dead_end"


def test_three_way_classified():
    assert IntersectionGap.classify_junction(_junction(3)) == "three_way"


def test_four_way_classified():
    assert IntersectionGap.classify_junction(_junction(4)) == "four_way"


def test_complex_classified():
    assert IntersectionGap.classify_junction(_junction(5)) == "complex"


def test_roundabout_explicitly_named():
    j = _junction(4, name="Kreisverkehr Nord (roundabout)")
    assert IntersectionGap.classify_junction(j) == "roundabout"


def test_roundabout_rb_token():
    j = _junction(4, name="RB-12")
    assert IntersectionGap.classify_junction(j) == "roundabout"


def test_name_substring_not_falsely_classified_as_roundabout():
    # The "rb" roundabout marker used to be a raw substring match with no
    # word boundary, so any junction name/id containing "rb" anywhere --
    # e.g. a real German street name like "Silberburgstrasse" (contains
    # "...silbe-RB-urg...") -- would be silently misclassified as a
    # roundabout instead of by its real 4-way structure.
    j = _junction(4, name="Silberburgstrasse-Kreuzung")
    assert IntersectionGap.classify_junction(j) == "four_way"


def test_count_types_and_compute_gap():
    root_a = ET.Element("OpenDRIVE")
    root_a.append(_junction(1, jid="1"))
    root_a.append(_junction(4, jid="2"))
    root_b = ET.Element("OpenDRIVE")
    root_b.append(_junction(4, jid="1"))
    root_b.append(_junction(4, jid="2"))

    counts_a = IntersectionGap.count_types(root_a)
    counts_b = IntersectionGap.count_types(root_b)
    assert counts_a["dead_end"] == 1
    assert counts_a["four_way"] == 1
    assert counts_b["four_way"] == 2

    delta = {k: counts_b.get(k, 0) - counts_a.get(k, 0) for k in IntersectionGap.TYPES}
    assert delta["dead_end"] == -1
    assert delta["four_way"] == 1
