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

    road_bounds = [road_bounds_curve_aware(road, include_lane_width=False) for road in root.findall("road")]
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


def _road_lane_ids(road: ET.Element) -> set[str]:
    """All explicit left/right lane ids of a road (the only linkable ids).

    OpenDRIVE laneLink ``from``/``to`` map driving-lane ids on the incoming
    and connecting roads; the center lane (``id=0``, type none) is never a
    legal link target. An empty return means the tile cannot resolve any
    laneLink against this road.
    """
    lanes_elem = road.find("lanes")
    if lanes_elem is None:
        return set()
    ids: set[str] = set()
    for section in lanes_elem.findall("laneSection"):
        for side in ("left", "right"):
            side_elem = section.find(side)
            if side_elem is None:
                continue
            for lane in side_elem.findall("lane"):
                lid = lane.get("id")
                if lid is not None:
                    ids.add(lid)
    return ids


def _tile_signal_ids(root: ET.Element) -> set[str]:
    return {signal.get("id") for signal in root.findall(".//signal") if signal.get("id")}


def _duplicate_ids(root: ET.Element, tag: str) -> list[str]:
    counts: dict[str, int] = {}
    for element in root.iter(tag):
        element_id = (element.get("id") or "").strip()
        if not element_id:
            continue
        counts[element_id] = counts.get(element_id, 0) + 1
    return sorted(element_id for element_id, count in counts.items() if count > 1)


def validate_runtime_tile(tile_path: Path | str) -> dict[str, Any]:
    """Validate the static standalone contract without importing CARLA."""

    tile_path = Path(tile_path)
    root = ET.parse(tile_path).getroot()
    road_ids = {road.get("id") for road in root.findall("road") if road.get("id")}
    junction_ids = {junction.get("id") for junction in root.findall("junction") if junction.get("id")}
    dangling_road_links: list[dict[str, str]] = []
    dangling_junction_refs: list[dict[str, str]] = []
    dangling_connections: list[dict[str, str]] = []

    for road in root.findall("road"):
        road_id = road.get("id", "")
        road_junction = (road.get("junction") or "").strip()
        if road_junction and road_junction != "-1" and road_junction not in junction_ids:
            dangling_junction_refs.append({"road_id": road_id, "junction_id": road_junction})
        for element_type, target_id in _road_link_target_ids(road):
            if element_type == "road" and target_id not in road_ids:
                dangling_road_links.append({"road_id": road_id, "target_id": target_id})
            if element_type == "junction" and target_id not in junction_ids:
                dangling_junction_refs.append({"road_id": road_id, "junction_id": target_id})

    for junction in root.findall("junction"):
        junction_id = junction.get("id", "")
        for connection in junction.findall("connection"):
            for attribute in ("incomingRoad", "connectingRoad"):
                road_id = (connection.get(attribute) or "").strip()
                if road_id not in road_ids:
                    dangling_connections.append(
                        {"junction_id": junction_id, "connection_id": connection.get("id", ""), "attribute": attribute, "road_id": road_id}
                    )

    signal_ids = _tile_signal_ids(root)
    dangling_controller_refs: list[dict[str, str]] = []
    for controller in root.findall("controller"):
        controller_id = controller.get("id", "")
        for control in controller.findall("control"):
            signal_id = (control.get("signalId") or "").strip()
            if signal_id and signal_id not in signal_ids:
                dangling_controller_refs.append(
                    {"controller_id": controller_id, "signal_id": signal_id}
                )

    lanes_by_road = {
        (road.get("id") or "").strip(): _road_lane_ids(road)
        for road in root.findall("road")
        if (road.get("id") or "").strip()
    }
    invalid_connection_lane_links: list[dict[str, Any]] = []
    for junction in root.findall("junction"):
        junction_id = junction.get("id", "")
        for connection in junction.findall("connection"):
            incoming = (connection.get("incomingRoad") or "").strip()
            connecting = (connection.get("connectingRoad") or "").strip()
            record: dict[str, Any] | None = None
            for lane_link in connection.findall("laneLink"):
                from_id = (lane_link.get("from") or "").strip()
                to_id = (lane_link.get("to") or "").strip()
                from_ok = not from_id or (incoming in lanes_by_road and from_id in lanes_by_road[incoming])
                to_ok = not to_id or (connecting in lanes_by_road and to_id in lanes_by_road[connecting])
                if from_ok and to_ok:
                    continue
                record = {
                    "junction_id": junction_id,
                    "connection_id": connection.get("id", ""),
                    "incomingRoad": incoming,
                    "connectingRoad": connecting,
                    "from": from_id or "",
                    "to": to_id or "",
                }
                break
            if record is not None:
                invalid_connection_lane_links.append(record)

    duplicate_road_ids = _duplicate_ids(root, "road")
    duplicate_junction_ids = _duplicate_ids(root, "junction")
    duplicate_signal_ids = _duplicate_ids(root, "signal")
    duplicated_ids = duplicate_road_ids + [e for e in duplicate_signal_ids if e not in duplicate_road_ids]

    driving_lengths = _road_driving_lengths(root)
    failures: list[str] = []
    if root.tag != "OpenDRIVE":
        failures.append("root_not_opendrive")
    if root.find("header") is None:
        failures.append("missing_header")
    if not road_ids:
        failures.append("no_roads")
    if _driving_lane_count(root) == 0:
        failures.append("no_driving_lanes")
    if not driving_lengths:
        failures.append("no_positive_length_driving_road")
    if dangling_road_links:
        failures.append("dangling_road_links")
    if dangling_junction_refs:
        failures.append("dangling_junction_references")
    if dangling_connections:
        failures.append("dangling_junction_connections")
    if dangling_controller_refs:
        failures.append("dangling_controller_refs")
    if invalid_connection_lane_links:
        failures.append("invalid_connection_lane_links")
    if duplicate_road_ids or duplicate_junction_ids:
        failures.append("duplicate_element_ids")

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "road_count": len(road_ids),
        "junction_count": len(junction_ids),
        "driving_lane_count": _driving_lane_count(root),
        "candidate_spawn_road_id": driving_lengths[0][0] if driving_lengths else None,
        "candidate_spawn_road_length_m": driving_lengths[0][1] if driving_lengths else None,
        "dangling_road_links": sorted(dangling_road_links, key=lambda item: (_natural_id(item["road_id"]), _natural_id(item["target_id"]))),
        "dangling_junction_references": sorted(dangling_junction_refs, key=lambda item: (_natural_id(item["road_id"]), _natural_id(item["junction_id"]))),
        "dangling_junction_connections": sorted(
            dangling_connections,
            key=lambda item: (_natural_id(item["junction_id"]), item["connection_id"], item["attribute"]),
        ),
        "dangling_controller_refs": sorted(
            dangling_controller_refs,
            key=lambda item: (item["controller_id"], item["signal_id"]),
        ),
        "invalid_connection_lane_links": sorted(
            invalid_connection_lane_links,
            key=lambda item: (
                _natural_id(item["junction_id"]),
                item["connection_id"],
                item["incomingRoad"],
            ),
        ),
        "duplicate_road_ids": duplicate_road_ids,
        "duplicate_junction_ids": duplicate_junction_ids,
        "duplicate_signal_ids": [e for e in duplicated_ids if e in duplicate_signal_ids],
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
        "live_carla": "NOT_RUN",
        "claim_boundary": (
            "Offline structural closure only. The artifact is not a map-of-record, "
            "has not been loaded by CARLA, and has not been runtime-certified."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return RuntimeTileBuildResult(output_xodr=output_path, manifest_path=manifest_path, static_validation=validation)
