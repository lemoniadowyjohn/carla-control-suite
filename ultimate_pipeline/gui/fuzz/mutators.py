"""Registered mutator families.

Each family is a separate, registered component with a declared contract:

``input_preconditions`` -- what the family needs to run at all.
``schema_legality``     -- whether the output is legal by schema or is a
                          deliberate violation.
``expected_outcome``    -- what a correct system must do.
``max_work_cost``       -- an explicit bound, in explicit units.
``reversible``          -- whether the mutation can be undone.
``seeded``              -- determinism.

Families deliberately stop at *guarded* construction. They build isolated case
inputs; they never touch a simulator. Live mutation stays disabled.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ultimate_pipeline.gui.fuzz.service import (
    SCENARIO_SCHEMA,
    ScenarioError,
    validate_scenario,
)

__all__ = [
    "MutatorContract", "MutatorFamily", "MutatorRegistry", "MUTATORS",
    "MutationResult", "registry",
]


@dataclass(frozen=True)
class MutatorContract:
    """The declared contract a mutator family must satisfy."""

    name: str
    input_preconditions: tuple[str, ...]
    schema_legality: str          # LEGAL | ILLEGAL_BY_DESIGN
    expected_outcome: str         # INPUT_REJECTED_AS_DESIGNED | BUG_CANDIDATE
    max_work_cost: str            # explicit units
    reversible: bool
    seeded: bool = True
    requires_simulator: bool = False

    def as_dict(self) -> dict:
        return {"name": self.name, "input_preconditions": list(self.input_preconditions),
                "schema_legality": self.schema_legality,
                "expected_outcome": self.expected_outcome,
                "max_work_cost": self.max_work_cost, "reversible": self.reversible,
                "seeded": self.seeded, "requires_simulator": self.requires_simulator}


@dataclass
class MutationResult:
    """An isolated case input/output pair. Never shared between cases."""

    case_id: str
    mutator: str
    payload: dict
    expected_outcome: str
    seed: int
    detail: str = ""

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "mutator": self.mutator,
                "expected_outcome": self.expected_outcome, "seed": self.seed,
                "detail": self.detail, "payload_keys": sorted(self.payload)}


@dataclass
class MutatorFamily:
    """A registered family: a contract plus a pure builder function."""

    contract: MutatorContract
    build: Callable[[str, int, dict], dict]

    def run(self, case_id: str, seed: int, base: dict | None = None) -> MutationResult:
        """Build one ISOLATED case. The base is deep-copied, never mutated."""
        payload = self.build(case_id, seed, copy.deepcopy(base or {}))
        return MutationResult(case_id, self.contract.name, payload,
                              self.contract.expected_outcome, seed)


# ------------------------------------------------------------------ families
def _scenario(**overrides: Any) -> dict:
    payload = {"schema": SCENARIO_SCHEMA, "seed": 1, "steps": [],
               "max_actors": 0, "max_sensors": 0}
    payload.update(overrides)
    return payload


def _build_config_missing(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["config"] = {"missing_key": "__ABSENT__"}
    return payload


def _build_config_invalid_type(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["config"] = {"tick_limit": "not-an-integer"}
    return payload


def _build_config_out_of_range(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["config"] = {"tick_limit": 10_000_000}
    return payload


def _build_malformed_xodr(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["map"] = {"xodr_text": "<OpenDRIVE><road></OpenDRIVE>"}  # not well-formed
    return payload


def _build_xodr_with_doctype(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["map"] = {
        "xodr_text": ('<!DOCTYPE lolz [<!ENTITY lol "lol">]>'
                      '<OpenDRIVE><road name="&lol;"/></OpenDRIVE>')}
    return payload


def _build_osm_constrained(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["map"] = {"osm_elements": [{"type": "node", "id": -1, "lat": 91.0,
                                        "lon": 181.0}]}  # impossible coordinates
    return payload


def _build_dangling_lane_link(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["map"] = {"lane_links": [{"from": 1, "to": 99999}]}  # to-id does not exist
    return payload


def _build_geometry_discontinuity(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["map"] = {"geometry": [{"x": 0.0, "y": 0.0, "z": 0.0},
                                   {"x": 1000.0, "y": 0.0, "z": 0.0}]}
    return payload


def _build_bad_crs(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["georeference"] = {"proj4": "+proj=tmerc +lat_0=0"}  # missing required keys
    return payload


def _build_calibration_roundtrip(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["calibration"] = {"profile": {"profile_id": "p", "sensors": {}},
                              "observed_pixels": None}  # reprojection NOT measurable
    return payload


def _build_weather_storm(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["weather"] = {"cloudiness": 100.0, "precipitation": 100.0,
                          "rain": 100.0, "sun_altitude_angle": -80.0}
    payload["requires_exclusive_world"] = True
    return payload


def _build_traffic_saturation(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["traffic"] = {"sync_mode": True, "tm_port": 8000,
                          "percentage_speed_difference": -100.0}
    payload["requires_exclusive_world"] = True
    return payload


def _build_actor_fault(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["actors"] = {"spawn": "vehicle.tesla.model3", "max_actors": 25}
    payload["requires_exclusive_world"] = True
    return payload


def _build_sensor_fault(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["sensors"] = {"attach": "sensor.camera.rgb", "max_sensors": 12,
                          "drop_frames": True}
    payload["requires_exclusive_world"] = True
    return payload


def _build_route_fault(case_id: str, seed: int, base: dict) -> dict:
    payload = _scenario(seed=seed)
    payload["route"] = {"waypoints": []}  # fewer than two waypoints
    payload["requires_exclusive_world"] = True
    return payload


_FAMILIES: tuple[tuple[MutatorContract, Callable[..., dict]], ...] = (
    (MutatorContract("config_missing_key",
                     ("a valid scenario",), "LEGAL",
                     "INPUT_REJECTED_AS_DESIGNED",
                     "O(1) config entries", True), _build_config_missing),
    (MutatorContract("config_invalid_type",
                     ("a valid scenario",), "LEGAL",
                     "INPUT_REJECTED_AS_DESIGNED",
                     "O(1) config entries", True), _build_config_invalid_type),
    (MutatorContract("config_out_of_range",
                     ("a valid scenario",), "LEGAL",
                     "INPUT_REJECTED_AS_DESIGNED",
                     "O(1) config entries", True), _build_config_out_of_range),
    (MutatorContract("malformed_xodr",
                     ("a valid scenario",), "LEGAL",
                     "INPUT_REJECTED_AS_DESIGNED",
                     "O(1) bytes, single parse", True), _build_malformed_xodr),
    (MutatorContract("xodr_with_doctype",
                     ("a valid scenario",), "LEGAL",
                     "INPUT_REJECTED_AS_DESIGNED",
                     "O(1) bytes, refused pre-parse", True), _build_xodr_with_doctype),
    (MutatorContract("osm_constrained",
                     ("a valid scenario",), "LEGAL",
                     "INPUT_REJECTED_AS_DESIGNED",
                     "O(n) elements", True), _build_osm_constrained),
    (MutatorContract("dangling_lane_link",
                     ("a valid scenario",), "LEGAL",
                     "INPUT_REJECTED_AS_DESIGNED",
                     "O(n) links", True), _build_dangling_lane_link),
    (MutatorContract("geometry_discontinuity",
                     ("a valid scenario",), "LEGAL",
                     "INPUT_REJECTED_AS_DESIGNED",
                     "O(n) points", True), _build_geometry_discontinuity),
    (MutatorContract("bad_crs",
                     ("a valid scenario",), "LEGAL",
                     "INPUT_REJECTED_AS_DESIGNED",
                     "O(1) key set", True), _build_bad_crs),
    (MutatorContract("calibration_roundtrip",
                     ("a valid scenario",), "LEGAL",
                     "INPUT_REJECTED_AS_DESIGNED",
                     "O(sensors) matrices", True), _build_calibration_roundtrip),
    (MutatorContract("weather_storm",
                     ("a valid scenario", "EXCLUSIVE_WORLD authority"),
                     "LEGAL", "BUG_CANDIDATE", "1 weather apply", False,
                     requires_simulator=True), _build_weather_storm),
    (MutatorContract("traffic_saturation",
                     ("a valid scenario", "EXCLUSIVE_TM_PORT authority"),
                     "LEGAL", "BUG_CANDIDATE", "1 TM apply", False,
                     requires_simulator=True), _build_traffic_saturation),
    (MutatorContract("actor_fault",
                     ("a valid scenario", "EXCLUSIVE_WORLD authority"),
                     "LEGAL", "BUG_CANDIDATE", "1 spawn", False,
                     requires_simulator=True), _build_actor_fault),
    (MutatorContract("sensor_fault",
                     ("a valid scenario", "EXCLUSIVE_WORLD authority"),
                     "LEGAL", "BUG_CANDIDATE", "1 attach", False,
                     requires_simulator=True), _build_sensor_fault),
    (MutatorContract("route_fault",
                     ("a valid scenario", "EXCLUSIVE_WORLD authority"),
                     "LEGAL", "BUG_CANDIDATE", "O(1) waypoints", False,
                     requires_simulator=True), _build_route_fault),
)


class MutatorRegistry:
    def __init__(self, families: Iterable[MutatorFamily] = ()) -> None:
        self._families: dict[str, MutatorFamily] = {f.contract.name: f for f in families}

    def register(self, family: MutatorFamily) -> None:
        self._families[family.contract.name] = family

    def names(self) -> list[str]:
        return sorted(self._families)

    def get(self, name: str) -> MutatorFamily:
        if name not in self._families:
            raise KeyError(f"no such mutator family: {name!r}")
        return self._families[name]

    def contracts(self) -> list[dict]:
        return [f.contract.as_dict() for f in
                sorted(self._families.values(), key=lambda f: f.contract.name)]

    def offline_families(self) -> list[str]:
        return sorted(n for n, f in self._families.items()
                      if not f.contract.requires_simulator)

    def simulator_families(self) -> list[str]:
        return sorted(n for n, f in self._families.items()
                      if f.contract.requires_simulator)


def _build_default() -> MutatorRegistry:
    return MutatorRegistry(MutatorFamily(contract, build) for contract, build in _FAMILIES)


registry = _build_default()
MUTATORS = registry