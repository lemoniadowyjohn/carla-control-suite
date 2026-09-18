# -*- coding: utf-8 -*-
"""P08 SIG-ENR-001 tests: provenance-backed idempotent signal enrichment."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.signals.signal_enrichment import (
    SignalEnrichment,
    build_controller,
    detect_duplicate_signals,
    enrich_signals_idempotent,
    validate_placement,
)


def _road(rid: str, length: float = 100.0):
    return ET.Element("road", id=str(rid), length=f"{length:.3f}")


def _root(roads):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    return root


def _signal_ids(root):
    out = []
    for road in root.findall("road"):
        for sig in road.findall("./signals/signal"):
            out.append(sig.get("id"))
    return out


class TestPlacementValidation:
    def test_valid_placement(self):
        root = _root([_road("1")])
        rec = SignalEnrichment(source_entity="osm:node/1", confidence="grounded",
                               road_id="1", s=10.0, t=2.0)
        assert validate_placement(root, rec) is None

    def test_s_out_of_range_rejected(self):
        root = _root([_road("1", 100.0)])
        rec = SignalEnrichment(source_entity="osm:node/1", confidence="grounded",
                               road_id="1", s=150.0, t=0.0)
        problem = validate_placement(root, rec)
        assert problem is not None and "outside" in problem

    def test_missing_road_rejected(self):
        root = _root([_road("1")])
        rec = SignalEnrichment(source_entity="osm:node/1", confidence="grounded",
                               road_id="99", s=0.0, t=0.0)
        assert validate_placement(root, rec) is not None

    def test_nonfinite_rejected(self):
        root = _root([_road("1")])
        rec = SignalEnrichment(source_entity="osm:node/1", confidence="grounded",
                               road_id="1", s=float("nan"), t=0.0)
        assert validate_placement(root, rec) is not None


class TestEnrichment:
    def test_insert_and_idempotent_rerun(self):
        root = _root([_road("1")])
        recs = [SignalEnrichment(source_entity="osm:node/10", confidence="grounded",
                                 road_id="1", s=10.0, t=2.0)]
        first = enrich_signals_idempotent(root, recs)
        assert first["counts"]["grounded"]["inserted"] == 1
        assert len(_signal_ids(root)) == 1
        second = enrich_signals_idempotent(root, recs)
        assert second["counts"]["grounded"]["matched"] == 1
        assert second["counts"]["grounded"]["inserted"] == 0
        assert len(_signal_ids(root)) == 1

    def test_provenance_attached(self):
        root = _root([_road("1")])
        recs = [SignalEnrichment(source_entity="osm:node/10", confidence="grounded",
                                 road_id="1", s=10.0, t=2.0)]
        enrich_signals_idempotent(root, recs)
        sig = root.find("./road/signals/signal")
        prov = sig.find("./userData/provenance")
        assert prov is not None
        assert prov.get("source_entity") == "osm:node/10"
        assert prov.get("confidence") == "grounded"

    def test_invalid_placement_rejected_not_clamped(self):
        root = _root([_road("1", 100.0)])
        recs = [SignalEnrichment(source_entity="osm:node/10", confidence="grounded",
                                 road_id="1", s=500.0, t=0.0)]
        res = enrich_signals_idempotent(root, recs)
        assert res["counts"]["grounded"]["rejected"] == 1
        assert len(_signal_ids(root)) == 0

    def test_ambiguous_source_rejected(self):
        root = _root([_road("1")])
        recs = [SignalEnrichment(source_entity="?unknown", confidence="grounded",
                                 road_id="1", s=10.0, t=0.0)]
        res = enrich_signals_idempotent(root, recs)
        assert res["counts"]["grounded"]["ambiguous"] == 1
        assert res["total_ambiguous"] == 1

    def test_synthetic_debug_needs_opt_in(self):
        root = _root([_road("1")])
        recs = [SignalEnrichment(source_entity="dbg:1", confidence="synthetic_debug",
                                 road_id="1", s=5.0, t=0.0)]
        res = enrich_signals_idempotent(root, recs)
        assert res["counts"]["synthetic_debug"]["rejected"] == 1
        res2 = enrich_signals_idempotent(root, recs, allow_synthetic_debug=True)
        assert res2["counts"]["synthetic_debug"]["inserted"] == 1

    def test_mode_separated_counts(self):
        root = _root([_road("1")])
        recs = [
            SignalEnrichment(source_entity="osm:node/1", confidence="grounded",
                             road_id="1", s=5.0, t=0.0),
            SignalEnrichment(source_entity="osm:node/2", confidence="inferred",
                             road_id="1", s=6.0, t=0.0),
        ]
        res = enrich_signals_idempotent(root, recs)
        assert res["counts"]["grounded"]["inserted"] == 1
        assert res["counts"]["inferred"]["inserted"] == 1

    def test_bad_confidence_rejected(self):
        with pytest.raises(ValueError):
            SignalEnrichment(source_entity="osm:node/1", confidence="guessed",
                             road_id="1", s=0.0, t=0.0)


class TestDuplicates:
    def test_source_id_duplicate_detected(self):
        root = _root([_road("1")])
        recs = [SignalEnrichment(source_entity="osm:node/10", confidence="grounded",
                                 road_id="1", s=10.0, t=2.0)]
        enrich_signals_idempotent(root, recs)
        sig = root.find("./road/signals/signal")
        sig2 = ET.SubElement(root.find("./road/signals"), "signal",
                             id="dup", s="10.0", t="2.0")
        prov = ET.SubElement(sig2, "userData")
        ET.SubElement(prov, "provenance", source_entity="osm:node/10", confidence="grounded")
        res = detect_duplicate_signals(root)
        assert any(g["kind"] == "source_id" and g["count"] == 2 for g in res["duplicate_groups"])

    def test_spatial_grouping_detected(self):
        root = _root([_road("1")])
        recs = [
            SignalEnrichment(source_entity="osm:node/1", confidence="grounded",
                             road_id="1", s=10.0, t=0.0),
            SignalEnrichment(source_entity="osm:node/2", confidence="grounded",
                             road_id="1", s=10.5, t=0.0),
        ]
        enrich_signals_idempotent(root, recs)
        res = detect_duplicate_signals(root)
        assert any(g["kind"] == "spatial_grouping" for g in res["duplicate_groups"])


class TestController:
    def test_build_controller_native(self):
        root = _root([_road("1")])
        res = build_controller(root, controller_id="ctl_1", name="junction_1",
                               signals=["1_1", "1_2"])
        assert res["inserted"] is True
        ctl = root.find("./controller/controller")
        assert ctl.get("id") == "ctl_1"
        assert len(ctl.findall("control")) == 2

    def test_controller_idempotent(self):
        root = _root([_road("1")])
        build_controller(root, controller_id="ctl_1", name="junction_1", signals=["1_1"])
        res = build_controller(root, controller_id="ctl_1", name="junction_1", signals=["1_1"])
        assert res["inserted"] is False
        assert res["reason"] == "already_present"
