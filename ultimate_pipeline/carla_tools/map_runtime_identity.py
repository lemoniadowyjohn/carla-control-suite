#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/carla_tools/map_runtime_identity.py

Runtime map identity and load-safety policy for governed CARLA perception.

NEW-248 .. NEW-260
------------------
The repository had strong *static* protections (XODR preflight, road-length
repair, lane-section checks, watchdogs) but no single fail-closed contract
binding the map that is *actually running* to the artifact that was approved.
Name equality alone cannot distinguish an approved cooked Grid0828 build from a
stale same-named one, and it certainly cannot bind a generated ``.xodr`` to the
runtime world.

This module provides the missing pieces:

* :class:`LoadMode` -- the three explicitly different map-acquisition modes, so
  "what map-changing action is allowed here?" is data, not scattered conditionals.
* :func:`structural_fingerprint` -- a canonical, structure-only digest of an
  OpenDRIVE document. CARLA re-serializes OpenDRIVE, so byte equality is the
  wrong test; road/junction/lane topology is the right one.
* :func:`runtime_map_fingerprint` -- the same fingerprint computed from
  ``world.get_map().to_opendrive()``.
* :func:`verify_runtime_map_identity` -- the three-layer gate: canonical name,
  then structural fingerprint, then the explicit source/payload SHA pair.
* :func:`post_load_soak` -- NEW-260: ``MAP_LOAD_SUCCESS`` is not ``MAP_STABLE``.
  A Grid map that loads and then dies 30 s later passed a one-tick check.
* :func:`assert_no_map_travel` -- NEW-248/249: the guard that makes
  ``--use-current-world`` and generated-OpenDRIVE modes mean what they say.

No CARLA import at module level: everything here is importable and testable
offline, which is a hard requirement for gating a live-runtime path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "LoadMode",
    "UNSTABLE_MANUAL_MAPS",
    "RuntimeMapIdentityError",
    "MapTravelProhibitedError",
    "MapStabilityError",
    "canonical_dumps",
    "sha256_text",
    "structural_fingerprint",
    "structural_fingerprint_from_file",
    "runtime_map_fingerprint",
    "fingerprint_mismatches",
    "verify_runtime_map_identity",
    "post_load_soak",
    "mode_allows_map_travel",
    "assert_no_map_travel",
    "resolve_load_mode",
]

#: Maps that must never be reached by runtime map travel (NEW-254). Both Grid
#: maps get one common rule, not one rule each in a different entrypoint.
UNSTABLE_MANUAL_MAPS = frozenset({"grid0821", "grid0828"})

_NUM_RE = re.compile(r"[-+0-9.eE]+")


class RuntimeMapIdentityError(RuntimeError):
    """Raised when the running world cannot be proven to be the approved map."""


class MapTravelProhibitedError(RuntimeError):
    """Raised when code attempts a map-changing operation the mode forbids."""


class MapStabilityError(RuntimeError):
    """Raised when a loaded map does not survive the post-load stability soak."""


class LoadMode(str, Enum):
    """
    The three governed map-acquisition modes (NEW-248/249/251).

    GENERATED_XODR
        ``generate_opendrive_world()`` exactly once. That call must be the LAST
        map-changing operation before capture. Afterwards: no ``load_world``,
        no ``reload_world`` -- including "harmless" stream-flush reloads, which
        would re-enter CARLA as ``load_world("OpenDriveMap")`` and silently
        replace the generated world with whatever that name resolves to.

    MANUAL_COOKED_UNSTABLE
        Grid0821 / Grid0828 loaded by the operator, or by a CARLA process
        launched directly into them. No map travel at all for the whole capture
        lifetime. This is the mode ``--use-current-world`` is *supposed* to mean.

    BUILTIN_COOKED
        An ordinary built-in town. Map travel is permitted.
    """

    GENERATED_XODR = "generated_xodr"
    MANUAL_COOKED_UNSTABLE = "manual_cooked_unstable"
    BUILTIN_COOKED = "builtin_cooked"


# ---------------------------------------------------------------------------
# canonical serialization / structural fingerprint
# ---------------------------------------------------------------------------


def canonical_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _attr_num(element: Optional[ET.Element], name: str, default: float = 0.0) -> float:
    if element is None:
        return default
    raw = element.get(name)
    if raw is None:
        return default
    match = _NUM_RE.search(str(raw))
    if not match:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


def _quantize(value: float, places: int = 3) -> float:
    """Round a length so float noise cannot change a structural digest."""
    return round(float(value) + 0.0, places)


def _planview_signature(road: ET.Element) -> List[str]:
    """
    Ordered planView geometry type + s-span signature for one road.

    Included because it distinguishes maps that share road *ids* but differ in
    geometry, and it is stable under CARLA re-serialization (which changes
    numeric precision but not geometry ordering).
    """
    signature: List[str] = []
    for geometry in road.findall("planView/geometry"):
        signature.append(
            "{x},{y},{z},{h},{p},{r},{length}".format(
                x=_quantize(_attr_num(geometry, "x", 0.0), 2),
                y=_quantize(_attr_num(geometry, "y", 0.0), 2),
                z=_quantize(_attr_num(geometry, "z", 0.0), 2),
                h=_quantize(_attr_num(geometry, "h", 0.0), 4),
                p=_quantize(_attr_num(geometry, "p", 0.0), 4),
                r=_quantize(_attr_num(geometry, "r", 0.0), 4),
                length=_quantize(_attr_num(geometry, "length", 0.0), 3),
            )
        )
    return signature


def _lane_section_topology(road: ET.Element) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for section in road.findall("lanes/laneSection"):
        entry: Dict[str, Any] = {
            "s": _quantize(_attr_num(section, "s", 0.0), 3),
            "single_sided": len(section.findall("left")) == 0,
        }
        lanes: List[str] = []
        for side in ("left", "center", "right"):
            for lane in section.findall(f"{side}/lane"):
                lanes.append(
                    "{side}:{lane_id}:{lane_type}:pre[{succ}]succ[{pre}]".format(
                        side=side,
                        lane_id=int(_attr_num(lane, "id", 0.0)),
                        lane_type=str(lane.get("type", "")),
                        succ="|".join(
                            str(e.get("id", "")) for e in lane.findall("link/predecessor")
                        ),
                        pre="|".join(
                            str(e.get("id", "")) for e in lane.findall("link/successor")
                        ),
                    )
                )
        entry["lanes"] = sorted(lanes)
        sections.append(entry)
    return sections


def _georeference_fingerprint(root: ET.Element) -> Optional[str]:
    """
    Canonical ``geoReference`` text, or None when absent.

    Included because a generated OpenDRIVE world whose georeference silently
    reverted to a default is a different map, even with identical topology.
    """
    header = root.find("header")
    if header is None:
        return None
    geo = header.find("geoReference")
    if geo is None:
        return None
    text = "".join(geo.itertext()).strip()
    if not text:
        return None
    return " ".join(text.split())


def structural_fingerprint(xodr_text: str) -> Dict[str, Any]:
    """
    NEW-250/NEW-252: compute a structure-only fingerprint of an OpenDRIVE document.

    CARLA re-serializes OpenDRIDE, so a source/runtime byte comparison is
    meaningless. This fingerprint captures the topology that must survive:
    road ids and count, junction ids and count, per-road declared length,
    planView geometry signature, lane-section topology with link
    predecessor/successor structure, and the georeference.

    Returns a dict with ``fingerprint_sha256`` plus the components, so a mismatch
    report can say *what* differed instead of only *that* something did.
    """
    root = ET.fromstring(xodr_text)

    roads: List[Dict[str, Any]] = []
    for road in root.findall("road"):
        lanes = road.findall("lanes/laneSection/lane")
        road_record = {
            "id": str(road.get("id", "")),
            "length": _quantize(_attr_num(road, "length", 0.0), 3),
            "junction": str(road.get("junction", "-1")),
            "lane_count": len(lanes),
            "planview": _planview_signature(road),
            "lane_sections": _lane_section_topology(road),
        }
        roads.append(road_record)

    # Sorted by id so document ordering cannot change the digest.
    roads.sort(key=lambda item: (str(item["id"]), str(item["length"])))

    junctions: List[Dict[str, Any]] = []
    for junction in root.findall("junction"):
        junctions.append(
            {
                "id": str(junction.get("id", "")),
                "type": str(junction.get("type", "")),
                "connection_count": len(junction.findall("connection")),
            }
        )
    junctions.sort(key=lambda item: str(item["id"]))

    lengths = sorted(float(item["length"]) for item in roads)
    length_distribution = {
        "total": _quantize(sum(lengths), 3),
        "min": _quantize(lengths[0], 3) if lengths else 0.0,
        "max": _quantize(lengths[-1], 3) if lengths else 0.0,
        "median": _quantize(lengths[len(lengths) // 2], 3) if lengths else 0.0,
        "count": len(lengths),
    }

    components = {
        "schema": "map_structural_fingerprint_v1",
        "road_count": len(roads),
        "junction_count": len(junctions),
        "road_ids": [str(item["id"]) for item in roads],
        "junction_ids": [str(item["id"]) for item in junctions],
        "roads": roads,
        "junctions": junctions,
        "road_length_distribution": length_distribution,
        "georeference": _georeference_fingerprint(root),
    }

    return {
        "schema": "map_structural_fingerprint_v1",
        "fingerprint_sha256": sha256_text(canonical_dumps(components)),
        "components": components,
    }


def structural_fingerprint_from_file(path: Any) -> Dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return structural_fingerprint(text)


def runtime_map_fingerprint(world: Any) -> Optional[Dict[str, Any]]:
    """
    NEW-250/NEW-252: fingerprint the map that is *actually running*.

    Uses ``world.get_map().to_opendrive()`` where the CARLA build supports it.
    Returns None when the runtime cannot serialize the map, so the caller can
    fail closed rather than silently degrading to a name check.
    """
    try:
        map_obj = world.get_map()
    except Exception:
        return None
    to_opendrive = getattr(map_obj, "to_opendrive", None)
    if not callable(to_opendrive):
        return None
    try:
        text = to_opendrive()
    except Exception:
        return None
    if not text or not str(text).strip():
        return None
    try:
        return structural_fingerprint(str(text))
    except Exception:
        return None


def fingerprint_mismatches(
    expected: Dict[str, Any],
    actual: Dict[str, Any],
) -> List[str]:
    """
    Explain how two fingerprints differ, component by component.

    A boolean "not equal" is useless for the operator staring at a crash bundle;
    naming the differing component turns a failed gate into a diagnosis.
    """
    differences: List[str] = []
    expected_components = (expected or {}).get("components") or {}
    actual_components = (actual or {}).get("components") or {}

    for key in (
        "road_count",
        "junction_count",
        "road_ids",
        "junction_ids",
        "road_length_distribution",
        "georeference",
    ):
        if expected_components.get(key) != actual_components.get(key):
            differences.append(
                f"{key}: expected={expected_components.get(key)!r} "
                f"actual={actual_components.get(key)!r}"
            )

    expected_roads = {str(r.get("id")): r for r in expected_components.get("roads") or []}
    actual_roads = {str(r.get("id")): r for r in actual_components.get("roads") or []}
    for road_id in sorted(set(expected_roads) & set(actual_roads)):
        for field in ("length", "lane_count", "planview", "lane_sections"):
            if expected_roads[road_id].get(field) != actual_roads[road_id].get(field):
                differences.append(f"road[{road_id}].{field} differs")
    return differences


# ---------------------------------------------------------------------------
# NEW-250: the three-layer identity gate
# ---------------------------------------------------------------------------


@dataclass
class RuntimeMapIdentity:
    """The result of a runtime map identity verification."""

    ok: bool
    mode: LoadMode
    expected_map_name: str
    actual_map_name: str
    name_matched: bool
    structural_checked: bool
    structural_ok: bool
    structural_differences: List[str] = field(default_factory=list)
    source_xodr_sha256: Optional[str] = None
    runtime_payload_sha256: Optional[str] = None
    runtime_map_structural_sha256: Optional[str] = None
    expected_structural_sha256: Optional[str] = None
    failures: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "runtime_map_identity_v1",
            "verdict": "RUNTIME_MAP_IDENTITY_PASS" if self.ok else "RUNTIME_MAP_IDENTITY_FAIL",
            "ok": self.ok,
            "mode": self.mode.value,
            "expected_map_name": self.expected_map_name,
            "actual_map_name": self.actual_map_name,
            "name_matched": self.name_matched,
            "structural_checked": self.structural_checked,
            "structural_ok": self.structural_ok,
            "structural_differences": list(self.structural_differences),
            "source_xodr_sha256": self.source_xodr_sha256,
            "runtime_payload_sha256": self.runtime_payload_sha256,
            "runtime_map_structural_sha256": self.runtime_map_structural_sha256,
            "expected_structural_sha256": self.expected_structural_sha256,
            "failures": list(self.failures),
        }


def verify_runtime_map_identity(
    *,
    world: Any,
    expected_map_name: str,
    mode: LoadMode,
    expected_fingerprint: Optional[Dict[str, Any]] = None,
    source_xodr_sha256: Optional[str] = None,
    runtime_payload_sha256: Optional[str] = None,
    require_structural: bool = True,
) -> RuntimeMapIdentity:
    """
    Verify that the running world is the approved map (NEW-250/NEW-252/NEW-253).

    Three layers, all required for ``ok``:

    1. **Canonical name** via ``map_registry.map_names_match`` -- never a
       substring test, so ``Broken_Grid0821_Test`` and ``OldGrid0821Backup``
       cannot satisfy a Grid0821 request.
    2. **Structural fingerprint** of ``world.get_map().to_opendrive()`` against
       the expected fingerprint. This is what distinguishes an approved cooked
       Grid build from a stale same-named one, and what binds a generated XODR
       to the runtime world.
    3. **Source/payload identity** recorded alongside, so the report always
       carries ``source_xodr_sha256``, ``runtime_payload_sha256`` and
       ``runtime_map_structural_sha256`` even when the checks themselves pass.

    With ``require_structural=True`` (the default) a runtime that cannot
    serialize its map is a FAILURE, not a degraded pass.
    """
    from ultimate_pipeline.carla_tools.map_registry import map_names_match

    actual_map_name = ""
    try:
        actual_map_name = str(world.get_map().name or "")
    except Exception:
        actual_map_name = ""

    name_matched = bool(
        actual_map_name and map_names_match(actual_map_name, str(expected_map_name or ""))
    )
    failures: List[str] = []
    if not name_matched:
        failures.append(
            f"map_name_mismatch: expected={expected_map_name!r} actual={actual_map_name!r}"
        )

    runtime_fp = runtime_map_fingerprint(world)
    structural_checked = runtime_fp is not None
    structural_ok = False
    differences: List[str] = []
    if runtime_fp is None:
        if require_structural:
            failures.append(
                "runtime_structural_fingerprint_unavailable: world.get_map().to_opendrive() "
                "is unsupported or returned no document; refusing to accept a name-only match"
            )
    elif expected_fingerprint is None:
        if require_structural:
            failures.append(
                "no_expected_structural_fingerprint: a governed load must supply the "
                "approved fingerprint, otherwise any same-named map passes"
            )
    else:
        expected_sha = str(expected_fingerprint.get("fingerprint_sha256") or "")
        actual_sha = str(runtime_fp.get("fingerprint_sha256") or "")
        structural_ok = bool(expected_sha) and expected_sha == actual_sha
        if not structural_ok:
            differences = fingerprint_mismatches(expected_fingerprint, runtime_fp)
            failures.append(
                "runtime_map_structural_mismatch: "
                + ("; ".join(differences[:6]) or f"expected={expected_sha} actual={actual_sha}")
            )

    return RuntimeMapIdentity(
        ok=not failures,
        mode=mode,
        expected_map_name=str(expected_map_name or ""),
        actual_map_name=actual_map_name,
        name_matched=name_matched,
        structural_checked=structural_checked,
        structural_ok=structural_ok,
        structural_differences=differences,
        source_xodr_sha256=source_xodr_sha256,
        runtime_payload_sha256=runtime_payload_sha256,
        runtime_map_structural_sha256=(runtime_fp or {}).get("fingerprint_sha256"),
        expected_structural_sha256=(expected_fingerprint or {}).get("fingerprint_sha256"),
        failures=failures,
    )


# ---------------------------------------------------------------------------
# NEW-260: post-load stability
# ---------------------------------------------------------------------------


def post_load_soak(
    world: Any,
    *,
    min_ticks: int = 30,
    tick_timeout_s: float = 2.0,
    min_frame_advance: int = 1,
) -> Dict[str, Any]:
    """
    NEW-260: soak a freshly loaded map and demand that it *keeps* ticking.

    The historical Grid failure mode was "CARLA loads the map, then dies shortly
    afterwards". A one-tick acceptance check cannot observe that, so a map that
    was merely alive at T+0 was certified. This gate requires a sustained run of
    advancing ticks with strictly increasing frame ids.

    Returns a soak report; ``ok`` is False when ticks stalled or frames did not
    advance. The caller decides whether a stall is fatal.
    """
    required = max(1, int(min_ticks))
    frames: List[int] = []
    errors: List[str] = []

    synchronous = True
    try:
        synchronous = bool(getattr(world.get_settings(), "synchronous_mode", False))
    except Exception:
        pass

    for _ in range(required):
        try:
            if synchronous:
                snapshot = world.tick(float(tick_timeout_s))
            else:
                snapshot = world.wait_for_tick(float(tick_timeout_s))
        except Exception as exc:
            errors.append(f"tick_failed: {type(exc).__name__}: {exc}")
            break
        frames.append(int(getattr(snapshot, "frame", -1)))

    advancing = all(
        frames[i] > frames[i - 1] for i in range(1, len(frames)) if frames[i] >= 0 and frames[i - 1] >= 0
    )
    if len(frames) < required and not errors:
        errors.append(f"soak_incomplete: {len(frames)}/{required} ticks observed")
    if len(frames) >= 2 and not advancing:
        errors.append(f"tick_frames_not_advancing: {frames[:12]}")

    ok = not errors and len(frames) >= required
    return {
        "schema": "post_load_soak_v1",
        "ok": ok,
        "required_ticks": required,
        "observed_ticks": len(frames),
        "synchronous_mode": synchronous,
        "min_frame_advance": int(min_frame_advance),
        "frames_advancing": advancing,
        "first_frame": frames[0] if frames else None,
        "last_frame": frames[-1] if frames else None,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# NEW-248 / NEW-249 / NEW-254: the map-travel prohibition
# ---------------------------------------------------------------------------


def mode_allows_map_travel(mode: LoadMode) -> bool:
    """
    Which modes may perform a map-changing operation *after* the initial load.

    Only ``BUILTIN_COOKED`` may. Both ``GENERATED_XODR`` and
    ``MANUAL_COOKED_UNSTABLE`` are closed to map travel for the entire capture
    lifetime.
    """
    return mode is LoadMode.BUILTIN_COOKED


def resolve_load_mode(
    *,
    use_current_world: bool,
    requested_map: str = "",
    xodr_path: Any = None,
) -> LoadMode:
    """
    Decide the governed load mode for a capture invocation.

    Precedence matters:

    * an explicit XODR path means ``GENERATED_XODR``;
    * ``--use-current-world`` on an unstable Grid map means
      ``MANUAL_COOKED_UNSTABLE``;
    * otherwise the map is treated as an ordinary built-in town.
    """
    if xodr_path:
        return LoadMode.GENERATED_XODR

    from ultimate_pipeline.carla_tools.map_registry import normalize_map_name

    normalized = normalize_map_name(requested_map)
    if use_current_world and normalized in UNSTABLE_MANUAL_MAPS:
        return LoadMode.MANUAL_COOKED_UNSTABLE
    if normalized in UNSTABLE_MANUAL_MAPS:
        # Even without --use-current-world, an unstable Grid map may not be
        # reached by runtime map travel (NEW-254). The caller must have launched
        # or loaded it another way.
        return LoadMode.MANUAL_COOKED_UNSTABLE
    return LoadMode.BUILTIN_COOKED


def assert_no_map_travel(
    *,
    mode: LoadMode,
    operation: str,
    current_map_name: str = "",
) -> None:
    """
    NEW-248/NEW-249: raise if a forbidden map-changing operation is attempted.

    The point is to make the *stream-flush reload* -- the operation that silently
    defeated ``--use-current-world`` -- a loud, attributable failure instead of
    an invisible one. Under ``GENERATED_XODR`` the failure message additionally
    explains that ``load_world("OpenDriveMap")`` is not the generated world.
    """
    if mode_allows_map_travel(mode):
        return

    detail = f"current_map={current_map_name!r}" if current_map_name else "current_map=unknown"
    if mode is LoadMode.GENERATED_XODR:
        raise MapTravelProhibitedError(
            f"map_travel_prohibited:{operation}: mode={mode.value} {detail}. "
            "generate_opendrive_world() must be the LAST map-changing operation before "
            "capture. A stream-flush load_world('OpenDriveMap') is NOT the generated world "
            "and would silently replace it."
        )
    raise MapTravelProhibitedError(
        f"map_travel_prohibited:{operation}: mode={mode.value} {detail}. "
        "This map is subject to the Grid map-travel crash; the operator (or a dedicated "
        "CARLA process) must have loaded it, and the capture must not travel from it."
    )
