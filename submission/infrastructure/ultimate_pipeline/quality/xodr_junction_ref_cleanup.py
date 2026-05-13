from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Set, Tuple


@dataclass(frozen=True)
class JunctionRefCleanupStats:
    removed_connections: int
    removed_junctions: int


def _road_ids(root: ET.Element) -> Set[str]:
    ids: Set[str] = set()
    for r in root.findall("road"):
        rid = r.get("id")
        if rid:
            ids.add(rid)
    return ids


def _iter_connection_refs(conn: ET.Element) -> Iterable[Tuple[str, str]]:
    incoming = conn.get("incomingRoad")
    connecting = conn.get("connectingRoad")
    if incoming is not None:
        yield "incomingRoad", incoming
    if connecting is not None:
        yield "connectingRoad", connecting


def prune_invalid_junction_connections(root: ET.Element) -> JunctionRefCleanupStats:
    """
    Prune `<junction><connection>` entries that reference road IDs that don't exist.

    This is a conservative structural cleanup intended to make OpenDRIVE loadable in CARLA
    when upstream steps removed roads but left stale junction references.
    """

    road_ids = _road_ids(root)
    removed_connections = 0
    removed_junctions = 0

    # NOTE: xml.etree.ElementTree has no parent pointers, so we remove children from the
    # junction element directly, and remove empty junctions from the root.
    for j in list(root.findall("junction")):
        connections = list(j.findall("connection"))
        for c in connections:
            # Remove malformed connections with missing refs.
            incoming = c.get("incomingRoad")
            connecting = c.get("connectingRoad")
            if not incoming or not connecting:
                j.remove(c)
                removed_connections += 1
                continue

            # Remove connections pointing to non-existent roads.
            if incoming not in road_ids or connecting not in road_ids:
                j.remove(c)
                removed_connections += 1

        if not list(j.findall("connection")):
            root.remove(j)
            removed_junctions += 1

    return JunctionRefCleanupStats(
        removed_connections=removed_connections,
        removed_junctions=removed_junctions,
    )


def prune_invalid_junction_connections_in_file(xodr_path: str | Path) -> tuple[Path, JunctionRefCleanupStats]:
    """Write a pruned copy next to the input and return `(new_path, stats)`.

    If no changes are required, returns the original path.
    """

    in_path = Path(xodr_path)
    tree = ET.parse(in_path)
    root = tree.getroot()

    stats = prune_invalid_junction_connections(root)
    if stats.removed_connections == 0 and stats.removed_junctions == 0:
        return in_path, stats

    out_path = in_path.with_name(f"{in_path.stem}__junction_refs_pruned{in_path.suffix}")
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path, stats
