#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Overpass-JSON -> OSM-XML converter (2026-09-15).

Why this exists
----------------
OSM2World only reads OSM XML (``.osm``/``.osm.xml``) or PBF -- it cannot
consume Overpass API's JSON "out geom" export directly. This codebase's
pinned building sources (e.g.
``campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_buildings_overpass.json``,
see ``ultimate_pipeline.config.settings.PINNED_BUILDINGS_SOURCE``) are exactly
that: Overpass JSON, not OSM XML. ``ultimate_pipeline.enrichment.osm_polygon_loader``
already parses this format for OpenDRIVE building-footprint insertion
(``OSMPolygonLoader.load_buildings_from_geojson``), but that path only
produces in-memory ``BuildingFootprint`` objects -- it never re-serializes to
OSM XML, so nothing upstream of it could hand the raw building data to
OSM2World. This module closes that gap.

Format read (Overpass "out geom" JSON)
---------------------------------------
Top level: ``{"version": ..., "generator": ..., "elements": [...]}``.
Each element is one of:

- ``way``: ``{"type": "way", "id": <int>, "tags": {...}, "geometry": [{"lat":
  ..., "lon": ...}, ...], "nodes": [<int>, ...]}``. ``geometry`` is the
  Overpass-embedded, already-ordered list of coordinates for every node in
  ``nodes`` -- no separate node table is provided, unlike OSM XML.
- ``relation``: ``{"type": "relation", "id": <int>, "tags": {...}, "members":
  [{"type": "way", "ref": <int>, "role": "outer"|"inner"|"", "geometry":
  [...]}]}``. Used for multipolygon buildings (courtyards, multi-part
  footprints); the ``building`` tag lives on the relation, not the member
  ways.

This mirrors exactly what ``OSMPolygonLoader.load_buildings_from_geojson``
already assumes about the format (see that module for the reference reading
of this same JSON shape).

What this module produces
--------------------------
A minimal, valid OSM XML document (``<osm version="0.6">``) containing:

- One ``<node>`` per *distinct* coordinate referenced by any way or relation
  member, deduplicated by coordinate (rounded to 1e-7 degrees, i.e. OSM's own
  precision -- about 1.1cm at the equator) so that ways/rings sharing an
  endpoint in the source data also share a node in the output. This matters
  for OSM2World's polygon/solid reconstruction: undeduplicated coincident
  nodes at shared building-wall corners can produce degenerate/duplicate-point
  polygons (see the ``IndoorModule$Elevator ... duplicate points`` failure
  mode documented in
  ``reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/README.md``).
  Node ids are synthetic and negative (``-1, -2, ...``), which is the
  standard OSM convention for "new, not yet assigned an id by the server"
  elements and guarantees no collision with real (always-positive) OSM ids
  from any roads file this output might later be merged with.
- One ``<way>`` per source way *and* per source relation's outer member way,
  each referencing its deduplicated node ids in order and carrying that
  way's/relation's original ``tags`` (``building``, ``height``,
  ``building:levels``, ``name``, etc.) unchanged. Way ids are synthetic and
  negative, offset from node ids so the two id spaces never collide either.
  A ring is closed (first node id == last) if the source coordinates were not
  already closed.

Multipolygon *relations* are intentionally flattened to their outer-ring
way(s): OSM2World (like ``OSMPolygonLoader``, see its C25/C28 notes) does not
require the inner/courtyard rings to render a recognizable building volume,
and preserving them would require reconstructing a full ``<relation
type="multipolygon">`` with correct member roles -- extra complexity for a
detail (courtyard holes) that is a documented, accepted minor over-fill
elsewhere in this codebase. If a use case needs true multipolygon relations,
``convert_overpass_json_to_osm_xml(..., emit_relations=True)`` also emits
``<relation type="multipolygon">`` elements referencing the same synthesized
outer ways, at negative ids past the way-id range.

Public API
----------
``convert_overpass_json_to_osm_xml(overpass_json_path, output_osm_path, ...)``
    Convert one Overpass-JSON file to one OSM-XML file on disk. Returns a
    small stats dict (node/way/relation counts) for logging/provenance.

``merge_osm_xml_files(primary_osm_path, secondary_osm_path, output_osm_path)``
    Merge two already-valid OSM-XML files into one, renumbering the
    secondary file's elements into negative id space if they collide with
    the primary file's (positive) ids. Used to combine a roads ``.osm`` file
    with this module's converted-buildings ``.osm`` file into a single input
    OSM2World can consume (its CLI only accepts one ``-i`` input file).
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# OSM's own coordinate precision is 1e-7 degrees (~1.1cm at the equator).
# Round to this before deduplicating so coincident corners in the source
# data (which Overpass "out geom" repeats verbatim per way/member, with no
# shared node table) collapse onto a single synthesized node.
_COORD_PRECISION = 7


def _round_coord(lat: float, lon: float) -> Tuple[float, float]:
    return (round(float(lat), _COORD_PRECISION), round(float(lon), _COORD_PRECISION))


def _extract_ring(geometry: Iterable[Dict[str, Any]]) -> List[Tuple[float, float]]:
    """Turn an Overpass ``geometry`` array into a list of (lat, lon) tuples.

    Overpass sometimes includes ``null`` entries for nodes it could not
    resolve (rare, but documented behaviour for partial extracts); those are
    skipped rather than raising, matching ``osm_polygon_loader``'s
    fail-open convention.
    """
    ring: List[Tuple[float, float]] = []
    for pt in geometry or []:
        if not pt:
            continue
        try:
            ring.append((float(pt["lat"]), float(pt["lon"])))
        except (KeyError, TypeError, ValueError):
            continue
    return ring


class _NodePool:
    """Deduplicates (lat, lon) -> synthetic negative OSM node id."""

    def __init__(self, start_id: int = -1) -> None:
        self._next_id = start_id
        self._coord_to_id: Dict[Tuple[float, float], int] = {}
        # Ordered so output is deterministic (insertion order == first-seen order).
        self.nodes: "list[Tuple[int, float, float]]" = []

    def get_or_create(self, lat: float, lon: float) -> int:
        key = _round_coord(lat, lon)
        existing = self._coord_to_id.get(key)
        if existing is not None:
            return existing
        node_id = self._next_id
        self._next_id -= 1
        self._coord_to_id[key] = node_id
        self.nodes.append((node_id, key[0], key[1]))
        return node_id

    def __len__(self) -> int:
        return len(self.nodes)


def convert_overpass_json_to_osm_xml(
    overpass_json_path: str,
    output_osm_path: str,
    *,
    emit_relations: bool = False,
    min_ring_points: int = 3,
) -> Dict[str, int]:
    """Convert an Overpass "out geom" JSON building export to OSM XML.

    Args:
        overpass_json_path: path to the Overpass JSON file (``elements`` list
            of ``way``/``relation`` objects, each carrying an embedded
            ``geometry`` array of ``{lat, lon}`` points -- the same format
            ``OSMPolygonLoader.load_buildings_from_geojson`` reads).
        output_osm_path: path to write the synthesized ``.osm`` XML file to.
            Parent directories are created if missing.
        emit_relations: if True, also emit ``<relation type="multipolygon">``
            elements for source relations (referencing the synthesized outer
            way(s)) in addition to flattening them to ways. Off by default
            because OSM2World renders a building volume from the way alone;
            see module docstring.
        min_ring_points: rings with fewer than this many points are dropped
            (degenerate geometry -- cannot form a polygon).

    Returns:
        Stats dict: ``{"elements_read": N, "ways_in": N, "relations_in": N,
        "nodes_written": N, "ways_written": N, "relations_written": N,
        "skipped_degenerate": N}``.

    Raises:
        FileNotFoundError: if ``overpass_json_path`` does not exist.
        ValueError: if the JSON has no top-level ``elements`` list at all
            (i.e. is not Overpass-JSON-shaped), or if conversion produced
            zero ways (nothing usable to hand to OSM2World).
    """
    src_path = Path(overpass_json_path)
    if not src_path.exists():
        raise FileNotFoundError(f"Overpass JSON source not found: {overpass_json_path}")

    with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
        data = json.load(f)

    elements = data.get("elements")
    if elements is None:
        raise ValueError(
            f"{overpass_json_path} has no top-level 'elements' list -- "
            "not Overpass 'out geom' JSON shaped input."
        )

    pool = _NodePool()
    way_records: List[Tuple[int, List[int], Dict[str, str], Optional[int]]] = []
    # (synthetic_way_id, node_id_list, tags, source_overpass_id_or_None)
    relation_records: List[Tuple[int, List[int], Dict[str, str], Optional[int]]] = []
    # (synthetic_relation_id, member_way_synthetic_ids, tags, source_overpass_id)

    ways_in = 0
    relations_in = 0
    skipped_degenerate = 0

    # Way/relation ids are allocated from their OWN negative range, well below
    # (more negative than) anything the node pool could ever use, so the two
    # id spaces can never collide even though both are "synthetic negative
    # ids". A generous fixed offset (1e9) is simpler and more obviously
    # correct than computing it from len(elements).
    _WAY_ID_BASE = -1_000_000_000
    next_way_id = _WAY_ID_BASE

    def _next_way_id() -> int:
        nonlocal next_way_id
        wid = next_way_id
        next_way_id -= 1
        return wid

    def _ring_to_node_ids(ring: List[Tuple[float, float]]) -> List[int]:
        node_ids = [pool.get_or_create(lat, lon) for lat, lon in ring]
        if node_ids and node_ids[0] != node_ids[-1]:
            node_ids.append(node_ids[0])
        return node_ids

    for elem in elements:
        etype = elem.get("type")

        if etype == "way":
            ways_in += 1
            tags = dict(elem.get("tags") or {})
            ring = _extract_ring(elem.get("geometry"))
            if len(ring) < min_ring_points:
                skipped_degenerate += 1
                continue
            node_ids = _ring_to_node_ids(ring)
            if len(node_ids) < min_ring_points:
                skipped_degenerate += 1
                continue
            way_records.append((_next_way_id(), node_ids, tags, elem.get("id")))

        elif etype == "relation":
            relations_in += 1
            rtags = dict(elem.get("tags") or {})
            if rtags.get("type") != "multipolygon" or "building" not in rtags:
                continue
            member_way_ids: List[int] = []
            for member in elem.get("members") or []:
                if member.get("type") != "way":
                    continue
                if member.get("role") not in ("outer", "", None):
                    continue
                ring = _extract_ring(member.get("geometry"))
                if len(ring) < min_ring_points:
                    skipped_degenerate += 1
                    continue
                node_ids = _ring_to_node_ids(ring)
                if len(node_ids) < min_ring_points:
                    skipped_degenerate += 1
                    continue
                # Each outer ring becomes its own way, tagged with the
                # relation's tags (so OSM2World's building module -- which
                # keys off `building=*` on the way -- renders it without
                # needing multipolygon relation support at all).
                wid = _next_way_id()
                way_records.append((wid, node_ids, rtags, elem.get("id")))
                member_way_ids.append(wid)

            if emit_relations and member_way_ids:
                rel_id = _next_way_id()  # shares the same negative id space
                relation_records.append((rel_id, member_way_ids, rtags, elem.get("id")))

    if not way_records:
        raise ValueError(
            f"{overpass_json_path}: conversion produced 0 usable ways "
            f"(elements_read={len(elements)}, ways_in={ways_in}, "
            f"relations_in={relations_in}, skipped_degenerate={skipped_degenerate}). "
            "Nothing to hand to OSM2World."
        )

    root = ET.Element("osm", {"version": "0.6", "generator": "overpass_to_osm_xml.py"})

    for node_id, lat, lon in pool.nodes:
        ET.SubElement(
            root,
            "node",
            {
                "id": str(node_id),
                "lat": f"{lat:.7f}",
                "lon": f"{lon:.7f}",
                "visible": "true",
            },
        )

    for way_id, node_ids, tags, _src_id in way_records:
        way_el = ET.SubElement(root, "way", {"id": str(way_id), "visible": "true"})
        for nid in node_ids:
            ET.SubElement(way_el, "nd", {"ref": str(nid)})
        for k, v in tags.items():
            if v is None:
                continue
            ET.SubElement(way_el, "tag", {"k": str(k), "v": str(v)})

    for rel_id, member_way_ids, tags, _src_id in relation_records:
        rel_el = ET.SubElement(root, "relation", {"id": str(rel_id), "visible": "true"})
        for wid in member_way_ids:
            ET.SubElement(rel_el, "member", {"type": "way", "ref": str(wid), "role": "outer"})
        for k, v in tags.items():
            if v is None:
                continue
            ET.SubElement(rel_el, "tag", {"k": str(k), "v": str(v)})

    out_path = Path(output_osm_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)

    return {
        "elements_read": len(elements),
        "ways_in": ways_in,
        "relations_in": relations_in,
        "nodes_written": len(pool),
        "ways_written": len(way_records),
        "relations_written": len(relation_records),
        "skipped_degenerate": skipped_degenerate,
    }


def merge_osm_xml_files(
    primary_osm_path: str,
    secondary_osm_path: str,
    output_osm_path: str,
) -> Dict[str, int]:
    """Merge two OSM XML files into one, avoiding id collisions.

    ``primary_osm_path`` (typically the roads file) keeps its node/way/
    relation ids unchanged. Every node/way/relation id from
    ``secondary_osm_path`` (typically this module's converted buildings
    file) that collides with a ``primary`` id is renumbered into unused
    negative id space; ``<nd ref=...>``/``<member ref=...>`` references are
    rewritten to match. In practice this module's own converter output
    already uses negative synthetic ids and the roads file uses positive
    ids, so no renumbering is needed for that specific pairing -- this
    function is written generically so it is correct even when that
    assumption does not hold (e.g. two converter outputs merged together).

    Returns a stats dict: ``{"primary_nodes": N, "primary_ways": N,
    "primary_relations": N, "secondary_nodes": N, "secondary_ways": N,
    "secondary_relations": N, "renumbered": N}``.
    """
    primary_tree = ET.parse(primary_osm_path)
    primary_root = primary_tree.getroot()
    secondary_tree = ET.parse(secondary_osm_path)
    secondary_root = secondary_tree.getroot()

    used_ids = {
        (el.tag, el.get("id"))
        for el in primary_root
        if el.tag in ("node", "way", "relation") and el.get("id") is not None
    }

    # Find a safe starting point for renumbering: below the lowest id used
    # anywhere in either file (so new negative ids can never collide).
    all_ids: List[int] = []
    for el in list(primary_root) + list(secondary_root):
        if el.tag in ("node", "way", "relation"):
            try:
                all_ids.append(int(el.get("id")))
            except (TypeError, ValueError):
                continue
    next_free_id = (min(all_ids) - 1) if all_ids else -1

    renumber_map: Dict[Tuple[str, str], str] = {}
    renumbered_count = 0

    def _remap_id(tag: str, old_id: str) -> str:
        nonlocal next_free_id, renumbered_count
        key = (tag, old_id)
        if key in renumber_map:
            return renumber_map[key]
        if (tag, old_id) not in used_ids:
            used_ids.add((tag, old_id))
            renumber_map[key] = old_id
            return old_id
        new_id = str(next_free_id)
        next_free_id -= 1
        while (tag, new_id) in used_ids:
            new_id = str(next_free_id)
            next_free_id -= 1
        used_ids.add((tag, new_id))
        renumber_map[key] = new_id
        renumbered_count += 1
        return new_id

    merged_root = ET.Element("osm", dict(primary_root.attrib))

    secondary_nodes = secondary_root.findall("node")
    secondary_ways = secondary_root.findall("way")
    secondary_relations = secondary_root.findall("relation")

    for el in primary_root:
        merged_root.append(el)

    for node in secondary_nodes:
        old_id = node.get("id")
        new_id = _remap_id("node", old_id)
        new_node = ET.Element("node", dict(node.attrib))
        new_node.set("id", new_id)
        for child in node:
            new_node.append(child)
        merged_root.append(new_node)

    for way in secondary_ways:
        old_id = way.get("id")
        new_id = _remap_id("way", old_id)
        new_way = ET.Element("way", dict(way.attrib))
        new_way.set("id", new_id)
        for child in way:
            if child.tag == "nd":
                ref = child.get("ref")
                new_ref = renumber_map.get(("node", ref), ref)
                new_child = ET.Element("nd", {"ref": new_ref})
                new_way.append(new_child)
            else:
                new_way.append(child)
        merged_root.append(new_way)

    for rel in secondary_relations:
        old_id = rel.get("id")
        new_id = _remap_id("relation", old_id)
        new_rel = ET.Element("relation", dict(rel.attrib))
        new_rel.set("id", new_id)
        for child in rel:
            if child.tag == "member" and child.get("type") == "way":
                ref = child.get("ref")
                new_ref = renumber_map.get(("way", ref), ref)
                new_child = ET.Element("member", dict(child.attrib))
                new_child.set("ref", new_ref)
                new_rel.append(new_child)
            else:
                new_rel.append(child)
        merged_root.append(new_rel)

    out_path = Path(output_osm_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged_tree = ET.ElementTree(merged_root)
    ET.indent(merged_tree, space="  ")
    merged_tree.write(out_path, encoding="UTF-8", xml_declaration=True)

    return {
        "primary_nodes": len(primary_root.findall("node")),
        "primary_ways": len(primary_root.findall("way")),
        "primary_relations": len(primary_root.findall("relation")),
        "secondary_nodes": len(secondary_nodes),
        "secondary_ways": len(secondary_ways),
        "secondary_relations": len(secondary_relations),
        "renumbered": renumbered_count,
    }


# ---------------------------------------------------------------------------
# CLI entry point for direct/manual use
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert Overpass JSON building export to OSM XML, "
        "optionally merged with an existing roads .osm file."
    )
    parser.add_argument("--overpass-json", required=True, help="Path to Overpass JSON source")
    parser.add_argument("--out", required=True, help="Output .osm path")
    parser.add_argument(
        "--merge-with",
        default=None,
        help="Optional existing OSM XML file (e.g. roads) to merge the converted buildings into",
    )
    parser.add_argument(
        "--emit-relations",
        action="store_true",
        help="Also emit <relation type=multipolygon> elements (off by default)",
    )
    args = parser.parse_args()

    if args.merge_with:
        tmp_buildings = str(Path(args.out).with_suffix(".buildings_only.osm"))
        stats = convert_overpass_json_to_osm_xml(
            args.overpass_json, tmp_buildings, emit_relations=args.emit_relations
        )
        print(f"Converted buildings: {stats}")
        merge_stats = merge_osm_xml_files(args.merge_with, tmp_buildings, args.out)
        print(f"Merged into {args.out}: {merge_stats}")
    else:
        stats = convert_overpass_json_to_osm_xml(
            args.overpass_json, args.out, emit_relations=args.emit_relations
        )
        print(f"Converted: {stats} -> {args.out}")
