"""RealismModule's "RULES MODE (advanced)" branch (enrich(), enabled by default --
ENABLE_REALISM_RULES/ENABLE_GUARDRAILS/ENABLE_BENCHES/ENABLE_SMART_LAMPS/
ENABLE_TRASH_BINS all default True) guards every feature behind
hasattr(RealismModule, "_rule_lamps"/"_benches"/"_guardrail"/"_trash_bins"/
"_estimate_curvature"). NONE of these 5 methods existed -- confirmed via grep,
2026-08-26 -- so despite every flag reading "enabled", benches/guardrails/trash
bins were NEVER generated on any real regen (0%, silently, no error). Only
lamp_post objects ever appeared, via the SIMPLE MODE fallback (_simple_lamps),
because _rule_lamps didn't exist either.

street_furniture_rules.py already defines the rule constants (LAMP_SPACING,
BENCH_INTERVAL, TRASH_EVERY, MAX_CURVATURE_FOR_GUARDRAIL, is_residential,
needs_guardrail) -- only the placement logic that consumes them was missing.
"""
import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.realism import RealismModule
from ultimate_pipeline.enrichment.street_furniture_rules import StreetFurnitureRules


def _straight_road(rid="1", length=200.0):
    r = ET.Element("road", id=rid, junction="-1", length=str(length))
    pv = ET.SubElement(r, "planView")
    geom = ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length=str(length))
    ET.SubElement(geom, "line")
    return r


def _curved_road(rid="2", length=50.0, curvature=0.1):
    r = ET.Element("road", id=rid, junction="-1", length=str(length))
    pv = ET.SubElement(r, "planView")
    geom = ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length=str(length))
    ET.SubElement(geom, "arc", curvature=str(curvature))
    return r


# --------------------------------------------------------------------------
# _estimate_curvature
# --------------------------------------------------------------------------

def test_estimate_curvature_straight_road_is_near_zero():
    curv = RealismModule._estimate_curvature(_straight_road())
    assert abs(curv) < 1e-6


def test_estimate_curvature_curved_road_matches_arc_curvature():
    curv = RealismModule._estimate_curvature(_curved_road(curvature=0.1))
    assert abs(curv - 0.1) < 1e-6


# --------------------------------------------------------------------------
# _rule_lamps
# --------------------------------------------------------------------------

def test_rule_lamps_places_posts_at_configured_spacing():
    road = _straight_road(length=100.0)
    n = RealismModule._rule_lamps(road, spacing=StreetFurnitureRules.LAMP_SPACING,
                                   offset=StreetFurnitureRules.LAMP_OFFSET)
    assert n == int(100.0 // StreetFurnitureRules.LAMP_SPACING)
    posts = road.findall(".//objects/object[@type='lamp_post']")
    assert len(posts) == n
    assert posts[0].get("t") == str(StreetFurnitureRules.LAMP_OFFSET)


# --------------------------------------------------------------------------
# _benches
# --------------------------------------------------------------------------

def test_benches_placed_on_long_residential_road():
    road = _straight_road(length=400.0)
    n = RealismModule._benches(road)
    assert n == int(400.0 // StreetFurnitureRules.BENCH_INTERVAL)
    assert n > 0
    benches = road.findall(".//objects/object[@type='bench']")
    assert len(benches) == n


def test_benches_zero_on_road_shorter_than_interval():
    road = _straight_road(length=50.0)  # < BENCH_INTERVAL (150m)
    n = RealismModule._benches(road)
    assert n == 0


# --------------------------------------------------------------------------
# _trash_bins
# --------------------------------------------------------------------------

def test_trash_bins_placed_at_configured_interval():
    road = _straight_road(length=500.0)
    n = RealismModule._trash_bins(road)
    assert n == int(500.0 // StreetFurnitureRules.TRASH_EVERY)
    bins_ = road.findall(".//objects/object[@type='trash_bin']")
    assert len(bins_) == n


# --------------------------------------------------------------------------
# _guardrail
# --------------------------------------------------------------------------

def test_guardrail_placed_on_sharp_curve():
    road = _curved_road(curvature=0.1)  # > MAX_CURVATURE_FOR_GUARDRAIL (0.02)
    n = RealismModule._guardrail(road)
    assert n >= 1
    rails = road.findall(".//objects/object[@type='guard_rail']")
    assert len(rails) == n


def test_guardrail_not_placed_on_straight_road():
    road = _straight_road()
    curv = RealismModule._estimate_curvature(road)
    assert not StreetFurnitureRules.needs_guardrail(curv)
    n = RealismModule._guardrail(road)
    assert n == 0


# --------------------------------------------------------------------------
# End-to-end: enrich() in RULES MODE now actually generates all 4 categories
# --------------------------------------------------------------------------

def test_enrich_rules_mode_generates_benches_guardrails_trash_bins(monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "ENABLE_REALISM_RULES", True)
    monkeypatch.setattr(SETTINGS, "ENABLE_SMART_LAMPS", True)
    monkeypatch.setattr(SETTINGS, "ENABLE_BENCHES", True)
    monkeypatch.setattr(SETTINGS, "ENABLE_GUARDRAILS", True)
    monkeypatch.setattr(SETTINGS, "ENABLE_TRASH_BINS", True)

    root = ET.Element("OpenDRIVE")
    root.append(_straight_road("1", length=400.0))  # residential-speed inferred by default
    root.append(_curved_road("2", length=50.0, curvature=0.1))

    RealismModule.enrich(root)

    types_present = {
        o.get("type") for o in root.findall(".//objects/object")
    }
    # Before this fix: only lamp_post ever appeared. Now bench/guard_rail/trash_bin
    # must be reachable too (given the hasattr methods now exist).
    assert "bench" in types_present or "trash_bin" in types_present
    assert "guard_rail" in types_present
