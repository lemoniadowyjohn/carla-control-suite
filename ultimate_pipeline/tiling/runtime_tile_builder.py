"""Build self-contained, locally rebased OpenDRIVE tiles for CARLA runtime use.

The existing :mod:`tile_extractor` intentionally produces overlapping
observation windows for domain-gap analysis.  Those windows retain references
to roads outside the window and omit root-level junction definitions, so they
are not a safe input to ``generate_opendrive_world``.  This module implements
an explicitly separate, fail-closed artifact type for runtime experiments.

It deliberately does not change the source map, the analytical tiler, or any
release profile.  A successful offline result is only
``READY_FOR_LIVE_CARLA_VALIDATION``; it is not a CARLA certification.
"""

from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ultimate_pipeline.tiling.tile_equivalence import road_bounds_curve_aware


_ROAD_LINK_TAGS = ("predecessor", "successor")
_EPSILON = 1e-9


@dataclass(frozen=True)
class RuntimeTileRequest:
    """Immutable build parameters for one standalone runtime tile."""

    input_xodr: Path
    output_xodr: Path
    center_x: float
    center_y: float
    tile_size_m: float
    buffer_m: float = 100.0
    max_closure_roads: int = 5000

    def __post_init__(self) -> None:
        if not math.isfinite(self.center_x) or not math.isfinite(self.center_y):
            raise ValueError("runtime tile center must be finite")
        if not math.isfinite(self.tile_size_m) or self.tile_size_m <= 0.0:
            raise ValueError("tile_size_m must be positive and finite")
        if not math.isfinite(self.buffer_m) or self.buffer_m < 0.0:
            raise ValueError("buffer_m must be finite and non-negative")
        if self.max_closure_roads <= 0:
            raise ValueError("max_closure_roads must be positive")


@dataclass(frozen=True)
class RuntimeTileBuildResult:
    """Paths and static-contract result for a generated runtime tile."""

    output_xodr: Path
    manifest_path: Path
    static_validation: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_source_header_offset(root: ET.Element) -> tuple[float, float]:
    """Accept an X/Y source-frame offset but reject unsupported transforms."""

    header = root.find("header")
    offset = header.find("offset") if header is not None else None
    if offset is None:
        return 0.0, 0.0
    values: dict[str, float] = {}
    for name in ("x", "y", "z", "hdg"):
        try:
            values[name] = float(offset.get(name, "0"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"runtime tile input has invalid header offset {name}") from exc
        if not math.isfinite(values[name]):
            raise RuntimeError(f"runtime tile input has non-finite header offset {name}")
    if abs(values["z"]) > _EPSILON or abs(values["hdg"]) > _EPSILON:
        raise RuntimeError(
            "runtime tile input has unsupported non-zero header offset z or hdg; "
            "a local horizontal rebase cannot preserve that transform"
        )
    return values["x"], values["y"]


def _natural_id(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, value)


def _clone(element: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(element, encoding="utf-8"))


def _intersects(
    bounds: dict[str, Any],
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
) -> bool:
    return not (
        float(bounds["x_max"]) < xmin
        or float(bounds["x_min"]) > xmax
        or float(bounds["y_max"]) < ymin
        or float(bounds["y_min"]) > ymax
    )


def _road_bounds(roads_by_id: dict[str, ET.Element]) -> dict[str, dict[str, Any]]:
    return {road_id: road_bounds_curve_aware(road) for road_id, road in roads_by_id.items()}


def _junction_indexes(
    root: ET.Element,
) -> tuple[dict[str, ET.Element], dict[str, set[str]]]:
    junctions_by_id: dict[str, ET.Element] = {}
    road_to_junctions: dict[str, set[str]] = {}
    for junction in root.findall("junction"):
        junction_id = (junction.get("id") or "").strip()
        if not junction_id:
            continue
        junctions_by_id[junction_id] = junction
        for connection in junction.findall("connection"):
            for attribute in ("incomingRoad", "connectingRoad"):
                road_id = (connection.get(attribute) or "").strip()
                if road_id:
                    road_to_junctions.setdefault(road_id, set()).add(junction_id)
    return junctions_by_id, road_to_junctions


def _road_link_target_ids(road: ET.Element) -> Iterable[tuple[str, str]]:
    for link in road.findall("./link/*"):
        element_type = (link.get("elementType") or "").strip()
        target_id = (link.get("elementId") or "").strip()
        if element_type and target_id:
            yield element_type, target_id


def _junction_road_ids(
    junction: ET.Element,
    roads_by_id: dict[str, ET.Element],
) -> set[str]:
    """Return all roads needed to retain a complete junction transition.

    OpenDRIVE connections name incoming and connecting roads.  The outgoing
    road is encoded by the connector's ordinary road link, so add it when it
    is a road target as well.
    """

    result: set[str] = set()
    connector_ids: set[str] = set()
    for connection in junction.findall("connection"):
        for attribute in ("incomingRoad", "connectingRoad"):
            road_id = (connection.get(attribute) or "").strip()
            if road_id in roads_by_id:
                result.add(road_id)
        connector_id = (connection.get("connectingRoad") or "").strip()
        if connector_id in roads_by_id:
            connector_ids.add(connector_id)

    for connector_id in connector_ids:
        for element_type, target_id in _road_link_target_ids(roads_by_id[connector_id]):
            if element_type == "road" and target_id in roads_by_id:
                result.add(target_id)
    return result


def _closed_selection(
    root: ET.Element,
    roads_by_id: dict[str, ET.Element],
    bounds_by_id: dict[str, dict[str, Any]],
    request: RuntimeTileRequest,
) -> tuple[set[str], set[str], list[str]]:
    half_size = request.tile_size_m * 0.5
    xmin = request.center_x - half_size - request.buffer_m
    ymin = request.center_y - half_size - request.buffer_m
    xmax = request.center_x + half_size + request.buffer_m
    ymax = request.center_y + half_size + request.buffer_m
    initial_roads = {
        road_id
        for road_id, bounds in bounds_by_id.items()
        if _intersects(bounds, xmin, ymin, xmax, ymax)
    }
    if not initial_roads:
        raise RuntimeError("runtime tile core and buffer select no roads")

    junctions_by_id, road_to_junctions = _junction_indexes(root)
    selected_junctions: set[str] = set()
    closure_reasons: list[str] = []

    # A tile closes every junction touched by its *spatial* selection.  It
    # must not then recursively close junctions reached through an exit road:
    # that would walk an urban road graph until the maximum cap is hit rather
    # than produce a bounded runtime subset.  Links beyond this single-hop
    # structural closure are explicitly removed below.
    for road_id in sorted(initial_roads, key=_natural_id):
        road = roads_by_id[road_id]
        road_junction_id = (road.get("junction") or "").strip()
        if road_junction_id and road_junction_id != "-1":
            selected_junctions.add(road_junction_id)
        selected_junctions.update(road_to_junctions.get(road_id, set()))
        for element_type, target_id in _road_link_target_ids(road):
            if element_type == "junction" and target_id in junctions_by_id:
                selected_junctions.add(target_id)

    selected_roads = set(initial_roads)
    for junction_id in sorted(selected_junctions, key=_natural_id):
        junction = junctions_by_id.get(junction_id)
        if junction is None:
            continue
        required_roads = _junction_road_ids(junction, roads_by_id)
        new_roads = required_roads - selected_roads
        if new_roads:
            selected_roads.update(new_roads)
            closure_reasons.append(
                f"junction:{junction_id}:added:{','.join(sorted(new_roads, key=_natural_id))}"
            )
    if len(selected_roads) > request.max_closure_roads:
        raise RuntimeError(
            "runtime tile closure exceeds max_closure_roads "
            f"({len(selected_roads)} > {request.max_closure_roads})"
        )

    return selected_roads, selected_junctions, closure_reasons


def _remove_boundary_lane_links(road: ET.Element, direction: str) -> int:
    sections = road.findall("./lanes/laneSection")
    if not sections:
        return 0
    section = sections[0] if direction == "predecessor" else sections[-1]
    removed = 0
    for lane in section.findall(".//lane"):
        lane_link = lane.find("link")
        if lane_link is None:
            continue
        target = lane_link.find(direction)
        if target is not None:
            lane_link.remove(target)
            removed += 1
    return removed


def _scrub_external_links(
    roads_by_id: dict[str, ET.Element],
    selected_roads: set[str],
    selected_junctions: set[str],
) -> tuple[int, int]:
    removed_road_links = 0
    removed_lane_links = 0
    for road_id in sorted(selected_roads, key=_natural_id):
        road = roads_by_id[road_id]
        link_parent = road.find("link")
        if link_parent is None:
            continue
        for direction in _ROAD_LINK_TAGS:
            link = link_parent.find(direction)
            if link is None:
                continue
            element_type = (link.get("elementType") or "").strip()
            target_id = (link.get("elementId") or "").strip()
            has_target = (
                (element_type == "road" and target_id in selected_roads)
                or (element_type == "junction" and target_id in selected_junctions)
            )
            if not has_target:
                link_parent.remove(link)
                removed_road_links += 1
                removed_lane_links += _remove_boundary_lane_links(road, direction)
    return removed_road_links, removed_lane_links


def _selected_controllers(root: ET.Element, selected_roads: Iterable[ET.Element]) -> list[ET.Element]:
    signal_ids = {
        signal.get("id")
        for road in selected_roads
        for signal in road.findall("./signals/signal")
        if signal.get("id")
    }
    controllers: list[ET.Element] = []
    for controller in root.findall("controller"):
        controls = controller.findall("control")
        if any(control.get("signalId") in signal_ids for control in controls):
            clone = _clone(controller)
            for control in list(clone.findall("control")):
                if control.get("signalId") not in signal_ids:
                    clone.remove(control)
            if clone.findall("control"):
                controllers.append(clone)
    return controllers


def _translate_global_outline_points(root: ET.Element, dx: float, dy: float) -> int:
    """Translate the only absolute XODR object coordinates used by this repo."""

    translated = 0
    for point in root.findall(".//cornerGlobal") + root.findall(".//positionInertial"):
        try:
            point.set("x", repr(float(point.get("x")) - dx))
            point.set("y", repr(float(point.get("y")) - dy))
            translated += 1
        except (TypeError, ValueError):
            raise RuntimeError(f"runtime tile has non-numeric global point: {ET.tostring(point, encoding='unicode')}")
    return translated


def _rebase_geometry(root: ET.Element, dx: float, dy: float) -> int:
    translated = 0
    for geometry in root.findall(".//planView/geometry"):
        try:
            geometry.set("x", repr(float(geometry.get("x")) - dx))
            geometry.set("y", repr(float(geometry.get("y")) - dy))
            translated += 1
        except (TypeError, ValueError):
            raise RuntimeError(f"runtime tile has non-numeric geometry: {ET.tostring(geometry, encoding='unicode')}")
    translated += _translate_global_outline_points(root, dx, dy)
    return translated


def _set_runtime_header(
    root: ET.Element,
    *,
    tile_name: str,
) -> None:
    header = root.find("header")
    if header is None:
        header = ET.Element("header")
        root.insert(0, header)
    header.set("name", tile_name)
    header.attrib.pop("geometryFrozen", None)
    header.attrib.pop("geometryFreezeHash", None)
    offset = header.find("offset")
    if offset is not None:
        offset.set("x", "0")
        offset.set("y", "0")
        offset.set("z", "0")
        offset.set("hdg", "0")
    # The tile has been translated into an intentionally local runtime frame.
    # Keeping a global CRS declaration would falsely imply geographic positions.
    geo_reference = header.find("geoReference")
    if geo_reference is not None:
        header.remove(geo_reference)

    road_bounds = [road_bounds_curve_aware(road, include_lane_width=True) for road in root.findall("road")]
    # Header bounds now include the complete drivable cross-section (lane width margin)
    # per TIL-001. This ensures the header west/east/south/north describe the full
    # map extents rather than just centerline extents, eliminating ambiguity about
    # the described area.
    if not road_bounds:
        raise RuntimeError("runtime tile contains no roads after closure")
    header.set("west", repr(min(float(bounds["x_min"]) for bounds in road_bounds)))
    header.set("east", repr(max(float(bounds["x_max"]) for bounds in road_bounds)))
    header.set("south", repr(min(float(bounds["y_min"]) for bounds in road_bounds)))
    header.set("north", repr(max(float(bounds["y_max"]) for bounds in road_bounds)))


def _driving_lane_count(root: ET.Element) -> int:
    return len(root.findall(".//lane[@type='driving']"))


def _road_driving_lengths(root: ET.Element) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    for road in root.findall("road"):
        if not road.findall(".//lane[@type='driving']"):
            continue
        try:
            length = float(road.get("length", "0"))
        except ValueError:
            length = 0.0
        if math.isfinite(length) and length > 0.0:
            values.append((road.get("id", ""), length))
    return sorted(values, key=lambda value: (-value[1], _natural_id(value[0])))


def validate_runtime_tile(tile_path: Path | str) -> dict[str, Any]:
    """Validate the static standalone contract without importing CARLA."""

    tile_path = Path(tile_path)
    root = ET.parse(tile_path).getroot()

    # Collect all IDs first for duplicate detection
    road_ids: list[str] = []
    for road in root.findall("road"):
        rid = road.get("id")
        if rid:
            road_ids.append(rid.strip())

    junction_ids: list[str] = []
    for junction in root.findall("junction"):
        jid = junction.get("id")
        if jid:
            junction_ids.append(jid.strip())

    signal_ids: list[str] = []
    for road in root.findall("road"):
        for signal in road.findall("./signals/signal"):
            sid = signal.get("id")
            if sid:
                signal_ids.append(sid.strip())

    controller_ids: list[str] = []
    for controller in root.findall("controller"):
        cid = controller.get("id")
        if cid:
            controller_ids.append(cid.strip())

    # Detect duplicate IDs
    duplicate_road_ids = [rid for rid in road_ids if road_ids.count(rid) > 1]
    duplicate_junction_ids = [jid for jid in junction_ids if junction_ids.count(jid) > 1]
    duplicate_signal_ids = [sid for sid in signal_ids if signal_ids.count(sid) > 1]

    # For controller duplicates, also check within junctions
    duplicate_connection_ids: list[str] = []
    for junction in root.findall("junction"):
        for connection in junction.findall("connection"):
            conn_id = connection.get("id")
            if conn_id:
                duplicate_connection_ids.append(conn_id.strip())
    duplicate_connection_ids = [cid for cid in duplicate_connection_ids if duplicate_connection_ids.count(cid) > 1]

    # Remove duplicates from the sets for other checks
    unique_road_ids = set(road_ids)
    unique_junction_ids = set(junction_ids)

    dangling_road_links: list[dict[str, str]] = []
    dangling_junction_refs: list[dict[str, str]] = []
    dangling_connections: list[dict[str, str]] = []

    for road in root.findall("road"):
        road_id = road.get("id", "")
        road_junction = (road.get("junction") or "").strip()
        if road_junction and road_junction != "-1" and road_junction not in unique_junction_ids:
            dangling_junction_refs.append({"road_id": road_id, "junction_id": road_junction})
        for element_type, target_id in _road_link_target_ids(road):
            if element_type == "road" and target_id not in unique_road_ids:
                dangling_road_links.append({"road_id": road_id, "target_id": target_id})
            if element_type == "junction" and target_id not in unique_junction_ids:
                dangling_junction_refs.append({"road_id": road_id, "junction_id": target_id})

    for junction in root.findall("junction"):
        junction_id = junction.get("id", "")
        for connection in junction.findall("connection"):
            for attribute in ("incomingRoad", "connectingRoad"):
                road_id = (connection.get(attribute) or "").strip()
                if road_id not in unique_road_ids:
                    dangling_connections.append(
                        {"junction_id": junction_id, "connection_id": connection.get("id", ""), "attribute": attribute, "road_id": road_id}
                    )
            # Validate laneLinks within the connection
            from_lane = (connection.get("from") or "").strip()
            to_lane = (connection.get("to") or "").strip()
            if from_lane:
                # Check that from lane exists on incoming road
                incoming_road_id = (connection.get("incomingRoad") or "").strip()
                if incoming_road_id and incoming_road_id in unique_road_ids:
                    incoming_road = root.find(f".//road[@id='{incoming_road_id}']")
                    if incoming_road is not None:
                        # Check if from lane exists on incoming road
                        found_from = False
                        for lane in incoming_road.findall(".//lane"):
                            lane_id = (lane.get("id") or "").strip()
                            if lane_id == from_lane:
                                found_from = True
                                break
                        if not found_from:
                            # Lane not found - this is a dangling reference
                            pass  # Will be reported below
            if to_lane:
                # Check that to lane exists on connecting road
                connecting_road_id = (connection.get("connectingRoad") or "").strip()
                if connecting_road_id and connecting_road_id in unique_road_ids:
                    connecting_road = root.find(f".//road[@id='{connecting_road_id}']")
                    if connecting_road is not None:
                        # Check if to lane exists on connecting road
                        found_to = False
                        for lane in connecting_road.findall(".//lane"):
                            lane_id = (lane.get("id") or "").strip()
                            if lane_id == to_lane:
                                found_to = True
                                break
                        if not found_to:
                            # Lane not found - this is a dangling reference
                            pass  # Will be reported below

    # Duplicate ID checks - make tile invalid if duplicates found
    failures: list[str] = []
    if duplicate_road_ids:
        failures.append(f"duplicate_road_ids:{','.join(sorted(set(duplicate_road_ids), key=_natural_id))}")
    if duplicate_junction_ids:
        failures.append(f"duplicate_junction_ids:{','.join(sorted(set(duplicate_junction_ids), key=_natural_id))}")
    if duplicate_signal_ids:
        failures.append(f"duplicate_signal_ids:{','.join(sorted(set(duplicate_signal_ids)))}")
    if duplicate_connection_ids:
        failures.append(f"duplicate_connection_ids:{','.join(sorted(set(duplicate_connection_ids)))}")
    if root.tag != "OpenDRIVE":
        failures.append("root_not_opendrive")
    if root.find("header") is None:
        failures.append("missing_header")
    if not unique_road_ids:
        failures.append("no_roads")
    if _driving_lane_count(root) == 0:
        failures.append("no_driving_lanes")
    if not _road_driving_lengths(root):
        failures.append("no_positive_length_driving_road")
    if dangling_road_links:
        failures.append("dangling_road_links")
    if dangling_junction_refs:
        failures.append("dangling_junction_references")
    if dangling_connections:
        failures.append("dangling_junction_connections")

    # Validate lane-level predecessor/successor integrity
    dangling_lane_predecessors: list[dict[str, str]] = []
    dangling_lane_successors: list[dict[str, str]] = []

    for road in root.findall("road"):
        road_id = road.get("id", "")
        if road.find("./lanes") is not None:
            for lane_section in road.findall("./lanes/laneSection"):
                for lane in lane_section.findall(".//lane"):
                    lane_link = lane.find("link")
                    if lane_link is not None:
                        # Check predecessor
                        pred = lane_link.find("predecessor")
                        if pred is not None:
                            target_id = pred.get("id", "")
                            # id="-1" means "no specific target / external", which is valid
                            if target_id and target_id != "-1" and target_id not in unique_road_ids:
                                dangling_lane_predecessors.append(
                                    {"road_id": road_id, "target_id": target_id}
                                )
                        # Check successor
                        succ = lane_link.find("successor")
                        if succ is not None:
                            target_id = succ.get("id", "")
                            # id="-1" means "no specific target / external", which is valid
                            if target_id and target_id != "-1" and target_id not in unique_road_ids:
                                dangling_lane_successors.append(
                                    {"road_id": road_id, "target_id": target_id}
                                )

    if dangling_lane_predecessors:
        failures.append("dangling_lane_predecessors")
    if dangling_lane_successors:
        failures.append("dangling_lane_successors")

    # Validate junction laneLink integrity
    junction_lane_link_failures = False
    for junction in root.findall("junction"):
        for connection in junction.findall("connection"):
            from_lane = (connection.get("from") or "").strip()
            to_lane = (connection.get("to") or "").strip()
            if from_lane:
                incoming_road_id = (connection.get("incomingRoad") or "").strip()
                if incoming_road_id and incoming_road_id in unique_road_ids:
                    incoming_road = root.find(f".//road[@id='{incoming_road_id}']")
                    if incoming_road is not None:
                        found_from = False
                        for lane in incoming_road.findall(".//lane"):
                            lane_id = (lane.get("id") or "").strip()
                            if lane_id == from_lane:
                                found_from = True
                                break
                        if not found_from:
                            junction_lane_link_failures = True
            if to_lane:
                connecting_road_id = (connection.get("connectingRoad") or "").strip()
                if connecting_road_id and connecting_road_id in unique_road_ids:
                    connecting_road = root.find(f".//road[@id='{connecting_road_id}']")
                    if connecting_road is not None:
                        found_to = False
                        for lane in connecting_road.findall(".//lane"):
                            lane_id = (lane.get("id") or "").strip()
                            if lane_id == to_lane:
                                found_to = True
                                break
                        if not found_to:
                            junction_lane_link_failures = True
    if junction_lane_link_failures:
        failures.append("junction_lane_link_integrity")

    # Validate signals and controllers
    # Collect signal IDs from selected roads
    selected_signal_ids: set[str] = set()
    for road in root.findall("road"):
        for signal in road.findall("./signals/signal"):
            sid = signal.get("id")
            if sid:
                selected_signal_ids.add(sid.strip())

    # Check controllers: every control signalId must reference a retained signal
    controller_failures: list[str] = []
    for controller in root.findall("controller"):
        controls = controller.findall("control")
        if controls:
            for control in controls:
                control_signal_id = (control.get("signalId") or "").strip()
                if control_signal_id and control_signal_id not in selected_signal_ids:
                    # Controller references a non-retained signal
                    already_reported = any(
                        f"controller_signal_{control_signal_id}" in fail
                        for fail in failures
                    )
                    if not already_reported:
                        controller_failures.append(
                            f"controller_signal_{control_signal_id}_not_retained"
                        )

    # Check signalReferences: every retained signalReference must reference existing signal
    # (This is a structural check - signalReference elements within the XODR)
    for signal_ref in root.findall(".//signalReference"):
        ref_id = (signal_ref.get("id") or "").strip()
        if ref_id and ref_id not in selected_signal_ids:
            already_reported = any(
                f"signal_reference_{ref_id}_not_retained" in fail
                for fail in failures
            )
            if not already_reported:
                controller_failures.append(
                    f"signal_reference_{ref_id}_not_retained"
                )

    if controller_failures:
        failures.extend(controller_failures)

    driving_lengths = _road_driving_lengths(root)
    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "road_count": len(unique_road_ids),
        "junction_count": len(unique_junction_ids),
        "driving_lane_count": _driving_lane_count(root),
        "candidate_spawn_road_id": driving_lengths[0][0] if driving_lengths else None,
        "candidate_spawn_road_length_m": driving_lengths[0][1] if driving_lengths else None,
        "dangling_road_links": sorted(dangling_road_links, key=lambda item: (_natural_id(item["road_id"]), _natural_id(item["target_id"]))),
        "dangling_junction_references": sorted(dangling_junction_refs, key=lambda item: (_natural_id(item["road_id"]), _natural_id(item["junction_id"]))),
        "dangling_junction_connections": sorted(
            dangling_connections,
            key=lambda item: (_natural_id(item["junction_id"]), item["connection_id"], item["attribute"]),
        ),
        "dangling_lane_predecessors": sorted(
            dangling_lane_predecessors, key=lambda item: (_natural_id(item["road_id"]), _natural_id(item["target_id"]))
        ),
        "dangling_lane_successors": sorted(
            dangling_lane_successors, key=lambda item: (_natural_id(item["road_id"]), _natural_id(item["target_id"]))
        ),
        "duplicate_detection": {
            "duplicate_road_ids": sorted(set(duplicate_road_ids)) if duplicate_road_ids else [],
            "duplicate_junction_ids": sorted(set(duplicate_junction_ids)) if duplicate_junction_ids else [],
            "duplicate_signal_ids": sorted(set(duplicate_signal_ids)) if duplicate_signal_ids else [],
            "duplicate_connection_ids": sorted(set(duplicate_connection_ids)) if duplicate_connection_ids else [],
        },
    }


def build_runtime_tile(request: RuntimeTileRequest) -> RuntimeTileBuildResult:
    """Build one standalone local-frame tile and a hash-bound sidecar manifest."""

    source_path = request.input_xodr.resolve()
    output_path = request.output_xodr.resolve()
    if source_path == output_path:
        raise ValueError("runtime tile output must not overwrite its source map")
    if not source_path.is_file():
        raise FileNotFoundError(f"input XODR not found: {source_path}")

    source_sha256 = _sha256(source_path)
    source_root = ET.parse(source_path).getroot()
    source_header_offset_xy = _read_source_header_offset(source_root)
    roads_by_id = {
        road_id: road
        for road in source_root.findall("road")
        if (road_id := (road.get("id") or "").strip())
    }
    if not roads_by_id:
        raise RuntimeError("input XODR contains no roads")
    bounds_by_id = _road_bounds(roads_by_id)
    selected_roads, selected_junctions, closure_reasons = _closed_selection(
        source_root,
        roads_by_id,
        bounds_by_id,
        request,
    )

    output_root = ET.Element("OpenDRIVE")
    source_header = source_root.find("header")
    output_root.append(_clone(source_header) if source_header is not None else ET.Element("header"))
    output_roads_by_id = {
        road_id: _clone(roads_by_id[road_id])
        for road_id in sorted(selected_roads, key=_natural_id)
    }
    for road in output_roads_by_id.values():
        output_root.append(road)

    source_junctions, _ = _junction_indexes(source_root)
    for junction_id in sorted(selected_junctions, key=_natural_id):
        junction = source_junctions.get(junction_id)
        if junction is not None:
            output_root.append(_clone(junction))
    for controller in _selected_controllers(source_root, output_roads_by_id.values()):
        output_root.append(controller)

    removed_road_links, removed_lane_links = _scrub_external_links(
        output_roads_by_id,
        selected_roads,
        selected_junctions,
    )
    translated_points = _rebase_geometry(output_root, request.center_x, request.center_y)
    _set_runtime_header(output_root, tile_name=output_path.stem)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(output_root).write(output_path, encoding="utf-8", xml_declaration=True)
    validation = validate_runtime_tile(output_path)
    if validation["status"] != "PASS":
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"runtime tile static validation failed: {validation['failures']}")

    output_sha256 = _sha256(output_path)
    manifest_path = output_path.with_suffix(".runtime_tile.json")
    manifest = {
        "schema_version": 1,
        "artifact_type": "standalone_carla_runtime_tile",
        "status": "READY_FOR_LIVE_CARLA_VALIDATION",
        "source": {"path": str(source_path), "sha256": source_sha256},
        "runtime_tile": {
            "path": str(output_path),
            "sha256": output_sha256,
            "road_count": validation["road_count"],
            "junction_count": validation["junction_count"],
            "driving_lane_count": validation["driving_lane_count"],
            "candidate_spawn_road_id": validation["candidate_spawn_road_id"],
            "candidate_spawn_road_length_m": validation["candidate_spawn_road_length_m"],
        },
        "local_frame": {
            "translation_from_source_xy_m": [request.center_x, request.center_y],
            "source_header_offset_xy_m": list(source_header_offset_xy),
            "georeference": "REMOVED_LOCAL_RUNTIME_FRAME",
            "geometry_frozen_attestation": "REMOVED_AFTER_TRANSLATION",
        },
        "selection": {
            "core_center_xy_m": [request.center_x, request.center_y],
            "tile_size_m": request.tile_size_m,
            "buffer_m": request.buffer_m,
            "max_closure_roads": request.max_closure_roads,
        },
        "closure": {
            "selected_road_ids": sorted(selected_roads, key=_natural_id),
            "selected_junction_ids": sorted(selected_junctions, key=_natural_id),
            "closure_reasons": closure_reasons,
            "boundary_road_links_removed": removed_road_links,
            "boundary_lane_links_removed": removed_lane_links,
        },
        "static_validation": validation,
        "reference_inventory": "reports/production_readiness/RUNTIME_TILE_REFERENCE_INVENTORY.json",
        "live_carla": "NOT_RUN",
        "claim_boundary": (
            "Offline structural closure only. The artifact is not a map-of-record, "
            "has not been loaded by CARLA, and has not been runtime-certified."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return RuntimeTileBuildResult(output_xodr=output_path, manifest_path=manifest_path, static_validation=validation)
