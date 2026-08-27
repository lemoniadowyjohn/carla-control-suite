"""ultimate_pipeline/quality/xodr_junction_ref_cleanup.py -- conservative structural cleanup
that prunes <junction><connection> entries referencing road IDs that no longer exist (e.g.
after quarantine_bad_roads.py deletes roads), intended to keep the XODR loadable in CARLA.
Confirmed live via carla_utils.py. Found untested via the orphaned-.pyc sweep.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.xodr_junction_ref_cleanup import (
    JunctionRefCleanupStats,
    prune_invalid_junction_connections,
    prune_invalid_junction_connections_in_file,
)


def _road(rid):
    return ET.Element("road", id=rid, length="1.0", junction="-1")


def _junction(jid, connections):
    # connections: list of (incomingRoad, connectingRoad) tuples, None means attribute omitted
    j = ET.Element("junction", id=jid)
    for incoming, connecting in connections:
        attrs = {}
        if incoming is not None:
            attrs["incomingRoad"] = incoming
        if connecting is not None:
            attrs["connectingRoad"] = connecting
        ET.SubElement(j, "connection", **attrs)
    return j


def _xodr(roads, junctions):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    for j in junctions:
        root.append(j)
    return root


# ---------------------------------------------------------------------------
# prune_invalid_junction_connections
# ---------------------------------------------------------------------------

def test_valid_connections_are_untouched():
    root = _xodr(
        [_road("1"), _road("2"), _road("3")],
        [_junction("j1", [("1", "3"), ("2", "3")])],
    )
    stats = prune_invalid_junction_connections(root)
    assert stats == JunctionRefCleanupStats(removed_connections=0, removed_junctions=0)
    assert len(root.find("junction").findall("connection")) == 2


def test_connection_referencing_nonexistent_incoming_road_is_removed():
    root = _xodr(
        [_road("1"), _road("3")],
        [_junction("j1", [("99", "3"), ("1", "3")])],  # "99" does not exist as a <road>
    )
    stats = prune_invalid_junction_connections(root)
    assert stats.removed_connections == 1
    assert stats.removed_junctions == 0
    remaining = root.find("junction").findall("connection")
    assert len(remaining) == 1
    assert remaining[0].get("incomingRoad") == "1"


def test_connection_referencing_nonexistent_connecting_road_is_removed():
    root = _xodr(
        [_road("1")],
        [_junction("j1", [("1", "99")])],
    )
    stats = prune_invalid_junction_connections(root)
    assert stats.removed_connections == 1
    assert stats.removed_junctions == 1  # junction now has zero connections left


def test_connection_missing_incoming_attribute_is_removed_as_malformed():
    root = _xodr(
        [_road("1")],
        [_junction("j1", [(None, "1")])],
    )
    stats = prune_invalid_junction_connections(root)
    assert stats.removed_connections == 1


def test_connection_missing_connecting_attribute_is_removed_as_malformed():
    root = _xodr(
        [_road("1")],
        [_junction("j1", [("1", None)])],
    )
    stats = prune_invalid_junction_connections(root)
    assert stats.removed_connections == 1


def test_junction_with_all_connections_pruned_is_itself_removed():
    root = _xodr(
        [_road("1")],
        [_junction("j1", [("1", "99"), ("99", "1")])],  # both invalid
    )
    stats = prune_invalid_junction_connections(root)
    assert stats.removed_connections == 2
    assert stats.removed_junctions == 1
    assert root.findall("junction") == []


def test_junction_that_started_with_zero_connections_is_removed_too():
    root = _xodr([_road("1")], [_junction("j1", [])])
    stats = prune_invalid_junction_connections(root)
    assert stats.removed_connections == 0
    assert stats.removed_junctions == 1
    assert root.findall("junction") == []


def test_multiple_junctions_only_the_empty_one_is_removed():
    root = _xodr(
        [_road("1"), _road("2")],
        [
            _junction("j1", [("1", "99")]),  # will become empty
            _junction("j2", [("1", "2")]),   # stays valid
        ],
    )
    stats = prune_invalid_junction_connections(root)
    assert stats.removed_junctions == 1
    remaining_ids = {j.get("id") for j in root.findall("junction")}
    assert remaining_ids == {"j2"}


# ---------------------------------------------------------------------------
# prune_invalid_junction_connections_in_file
# ---------------------------------------------------------------------------

def test_file_variant_no_changes_returns_original_path(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    root = _xodr([_road("1"), _road("2")], [_junction("j1", [("1", "2")])])
    ET.ElementTree(root).write(str(xodr), encoding="utf-8", xml_declaration=True)

    out_path, stats = prune_invalid_junction_connections_in_file(xodr)

    assert out_path == xodr
    assert stats.removed_connections == 0


def test_file_variant_writes_sibling_file_when_pruned(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    root = _xodr([_road("1")], [_junction("j1", [("1", "99")])])
    ET.ElementTree(root).write(str(xodr), encoding="utf-8", xml_declaration=True)

    out_path, stats = prune_invalid_junction_connections_in_file(xodr)

    assert out_path != xodr
    assert out_path.name == "map__junction_refs_pruned.xodr"
    assert out_path.is_file()
    assert stats.removed_connections == 1
    out_root = ET.parse(str(out_path)).getroot()
    assert out_root.findall("junction") == []
