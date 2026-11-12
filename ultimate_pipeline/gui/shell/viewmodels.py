"""View models for the runtime and workflow screens (Task 14).

Each view model consumes an injected service contract and never touches the
CARLA API directly. They are Qt-free so they can be unit tested without a
display and so the page widgets stay presentational.

Two rules are enforced throughout:

* the *measured* value is kept distinct from the *requested* value, and
* a model with no measurement returns ``NOT_EVALUATED`` rather than a
  plausible number.

Every capability listed in ``blocked()`` must stay visibly disabled: it is
something an operator could otherwise click believing it worked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ultimate_pipeline.gui.run_status import RunStatus

__all__ = [
    "Cell", "BaseModel", "WorldTimeModel", "MapsModel", "TrafficManagerModel",
    "ActorsRoutesModel", "SensorsModel", "CalibrationModel", "ScenarioModel",
    "FuzzerModel", "ExperimentsModel", "JobsModel", "ExperimentRegistryPort",
    "UNAVAILABLE",
]

# Not a RunStatus member: RunStatus has no UNSUPPORTED value. This is a
# presentation-only marker for a capability that has no truthful adapter.
UNAVAILABLE = "UNAVAILABLE"

NOT_EVALUATED = RunStatus.NOT_EVALUATED.value
BLOCKED_EXTERNAL = RunStatus.BLOCKED_EXTERNAL.value


@dataclass
class Cell:
    """One displayed field. ``measured`` False means the value is requested."""

    name: str
    value: Any
    measured: bool = True
    state: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "value": self.value,
                "measured": self.measured, "state": self.state,
                "note": self.note}


class BaseModel:
    route = ""

    def rows(self) -> list[Cell]:  # pragma: no cover - overridden
        return []

    def blocked(self) -> list[str]:
        """Capabilities that must not be silently enabled."""
        return []


class WorldTimeModel(BaseModel):
    """04 World / Time."""

    route = "04_world_time"

    def __init__(self, config_model: Any) -> None:
        self.config = config_model

    def _staged(self) -> dict:
        staged = self.config.staged_values()
        return dict(staged) if isinstance(staged, dict) else {}

    def rows(self) -> list[Cell]:
        try:
            payload = self._staged()
        except Exception as exc:
            return [Cell("world settings", None, False, NOT_EVALUATED,
                         f"{type(exc).__name__}: {exc}")]
        rows = []
        for field_name in ("synchronous_mode", "fixed_delta_seconds",
                           "weather_preset"):
            present = field_name in payload
            rows.append(Cell(
                field_name, payload.get(field_name), measured=present,
                state="" if present else NOT_EVALUATED,
                note="" if present else "not staged in this session"))
        rows.append(Cell("loaded_map", "", measured=False,
                         state=NOT_EVALUATED,
                         note="no map is bound in this session"))
        rows.append(Cell("tick authority", "NONE", measured=False,
                         state=NOT_EVALUATED,
                         note="no second authority claimed"))
        return rows

    def blocked(self) -> list[str]:
        return ["substepping: CARLA substep support was never independently "
                "verified, so no substep parameter is exposed"]


class MapsModel(BaseModel):
    """05 Maps / GIS / Cooking: four distinct layers, never conflated."""

    route = "05_maps_gis_cooking"

    LAYERS = ("source xodr", "generated xodr", "cooked content", "runtime loaded")

    def __init__(self, map_registry: Any,
                 cook_capability: str = "UE426_BLOCKED_OPERATOR_INSTALL") -> None:
        self.registry = map_registry
        self.cook_capability = cook_capability

    def rows(self) -> list[Cell]:
        rows = [Cell("source xodr", "PINNED_MAP_REGISTRY", False,
                     note="resolved via the registry, never by mtime or glob")]
        for layer in self.LAYERS[1:]:
            rows.append(Cell(layer, "NOT_BOUND", False, NOT_EVALUATED,
                             "no artefact bound in this session"))
        return rows

    def cook(self) -> Cell:
        return Cell("cook", "BLOCKED", False, BLOCKED_EXTERNAL,
                    f"{self.cook_capability}; operator must install UE4.26")

    def blocked(self) -> list[str]:
        return [f"cook: {self.cook_capability}; operator-only, never automated",
                "GIS import: no truthful import adapter exists upstream"]


class TrafficManagerModel(BaseModel):
    """06 Traffic Manager: WRITE_ONLY, so nothing can be confirmed."""

    route = "06_traffic_manager"

    def __init__(self, tm_port: Any) -> None:
        self.tm = tm_port

    def rows(self) -> list[Cell]:
        holder = getattr(self.tm, "claim_holder", None) or "NONE"
        declared = getattr(self.tm, "declared_only", None)
        if isinstance(declared, (list, tuple, set, frozenset)):
            declared_text = ", ".join(str(d) for d in declared)
        elif declared is None:
            declared_text = ""
        else:
            declared_text = str(declared)
        return [
            Cell("port claim", holder, True),
            Cell("confirmed settings", 0, True,
                 note="CARLA 0.9.16 exposes no getter; nothing is confirmable"),
            Cell("restore TM defaults", UNAVAILABLE, False, NOT_EVALUATED,
                 "values cannot be read back, so no snapshot/restore exists"),
            Cell("declared only", declared_text, True,
                 note="declared upstream but never implemented"),
        ]

    def blocked(self) -> list[str]:
        return ["per-actor TM settings: WRITE_ONLY, so nothing can be confirmed",
                "restore TM defaults: no readable state exists to restore from",
                "global-vs-per-vehicle grouping is display-only"]


class ActorsRoutesModel(BaseModel):
    """07 Actors / Routes."""

    route = "07_actors_routes"

    def __init__(self, actor_registry: Any, catalog: Any = None) -> None:
        self.registry = actor_registry
        self.catalog = catalog

    def rows(self) -> list[Cell]:
        # OwnedActorRegistry exposes actor_ids only; it deliberately does not
        # track which actors were pre-existing, so no external count is claimed.
        return [
            Cell("owned actors", len(self.registry.actor_ids()), True),
            Cell("preserved external", UNAVAILABLE, False, NOT_EVALUATED,
                 "the registry does not record pre-existing actors, so no "
                 "external count can be claimed"),
            Cell("cleanup report", self.registry.cleanup_report(), True,
                 note="destroyed vs preserved, from the registry itself"),
        ]

    def blocked(self) -> list[str]:
        return ["route persistence: no truthful route store exists upstream",
                "traffic manager coupling to actors: WRITE_ONLY"]


class SensorsModel(BaseModel):
    """08 Sensors: backpressure metrics only when actually recorded."""

    route = "08_sensors_streams"

    def __init__(self) -> None:
        self.stats: dict[str, Any] | None = None

    def record(self, stats: dict) -> None:
        self.stats = stats

    def rows(self) -> list[Cell]:
        if not self.stats:
            return [Cell("callback metrics", None, False, NOT_EVALUATED,
                         "no callback has been recorded in this session")]
        return [Cell(key, value, True) for key, value in sorted(self.stats.items())]

    def blocked(self) -> list[str]:
        return ["radar / GNSS / IMU: no truthful adapter exists upstream"]


class CalibrationModel(BaseModel):
    """09 Calibration: no unmeasured reprojection or drift PASS."""

    route = "09_calibration_workbench"

    def __init__(self) -> None:
        self.stats: dict[str, Any] | None = None

    def record(self, stats: dict) -> None:
        self.stats = stats

    def rows(self) -> list[Cell]:
        rows = [Cell("intrinsics", None, False, NOT_EVALUATED,
                     "no calibration profile is loaded"),
                Cell("extrinsics", None, False, NOT_EVALUATED,
                     "no calibration profile is loaded")]
        if not self.stats:
            rows.append(Cell("reprojection", None, False, NOT_EVALUATED,
                             "no observed pixels: reprojection is NOT MEASURED"))
            rows.append(Cell("drift", None, False, NOT_EVALUATED,
                             "no owner-approved drift tolerance (Q11)"))
        else:
            rows.append(Cell("reprojection", self.stats.get("reprojection"),
                             measured="reprojection" in self.stats))
            rows.append(Cell("drift", self.stats.get("drift"),
                             measured="drift" in self.stats))
        rows.append(Cell("radar / GNSS / IMU", UNAVAILABLE, False,
                         NOT_EVALUATED,
                         "no truthful adapter exists upstream"))
        return rows

    def blocked(self) -> list[str]:
        return [
            "radar/GNSS/IMU: no truthful adapter exists, so these stay unavailable",
            "reprojection cannot be shown as PASS without observed pixels",
            "drift cannot be shown as PASS without an owner-approved tolerance",
            "geometry_continuity stays INCONCLUSIVE (no approved threshold)",
        ]


class ExperimentRegistryPort:
    """Injection point for the experiment registry.

    Importing ``ultimate_pipeline.experiments.registry`` transitively pulls
    ``ultimate_pipeline.main_pipeline`` and therefore the CARLA API. Mock and
    offline mode must work with no CARLA import at all, so the shell never
    imports it: the port is injected by the caller, and the default
    implementation reports the registry as unavailable instead of guessing a
    count.
    """

    reason = ("importing the experiment registry pulls the CARLA API, which "
              "mock/offline mode forbids; inject a port to populate this view")

    def __init__(self, experiments: Any = None) -> None:
        self._experiments = experiments

    @property
    def EXPERIMENTS(self) -> Any:
        return self._experiments if self._experiments is not None else {}

    @property
    def available(self) -> bool:
        return self._experiments is not None

    def discover_experiments(self) -> Any:
        """The upstream call returns None; never report it as a result."""
        return None


class ScenarioModel(BaseModel):
    """11 Scenario Studio."""

    route = "11_scenario_test_studio"

    def __init__(self, experiment_registry: Any = None) -> None:
        self.registry = experiment_registry or ExperimentRegistryPort()

    def rows(self) -> list[Cell]:
        if not getattr(self.registry, "available", False):
            return [
                Cell("registered experiments", None, False, NOT_EVALUATED,
                     ExperimentRegistryPort.reason),
                Cell("scenario mutation", "NOT_AUTHORIZED", False,
                     BLOCKED_EXTERNAL,
                     "live world mutation is not authorized in this stage"),
            ]
        return [
            Cell("registered experiments", len(self.registry.EXPERIMENTS), True),
            Cell("discovery result", UNAVAILABLE, False, NOT_EVALUATED,
                 "discover_experiments() returns None, so no structured "
                 "discovery outcome can be reported"),
            Cell("scenario mutation", "NOT_AUTHORIZED", False,
                 BLOCKED_EXTERNAL,
                 "live world mutation is not authorized in this stage"),
        ]

    def blocked(self) -> list[str]:
        return ["scenario authoring that mutates the live world: not authorized"]


class FuzzerModel(BaseModel):
    """12 Operational Fuzzer: live Start stays gated on an owned lease."""

    route = "12_operational_fuzzer"

    def __init__(self, mutator_registry: Any, live_available: bool = False) -> None:
        self.mutators = mutator_registry
        self.live_available = live_available

    def rows(self) -> list[Cell]:
        return [
            Cell("families", len(self.mutators.names()), True),
            Cell("offline families", len(self.mutators.offline_families()), True),
            Cell("simulator-guarded", len(self.mutators.simulator_families()), True,
                 note="built only; never executed"),
            Cell("live Start",
                 "DISABLED" if not self.live_available else "ENABLED",
                 measured=False,
                 state="" if self.live_available else BLOCKED_EXTERNAL,
                 note="no exclusively owned isolated server lease (Q22)"),
            Cell("budgets", "PROPOSED", False, NOT_EVALUATED,
                 "not operator-approved for live use"),
        ]

    def blocked(self) -> list[str]:
        return ["live Start: no exclusively owned isolated server lease (Q22)",
                "simulator-guarded families: built, never executed here",
                "oracle-backed fuzzing: 43 upstream oracles remain unimplemented"]


class ExperimentsModel(BaseModel):
    """14 Experiments / Runs."""

    route = "14_experiments_runs"

    def __init__(self, experiment_registry: Any = None) -> None:
        self.registry = experiment_registry or ExperimentRegistryPort()

    def rows(self) -> list[Cell]:
        if not getattr(self.registry, "available", False):
            return [
                Cell("registered experiments", None, False, NOT_EVALUATED,
                     ExperimentRegistryPort.reason),
                Cell("last verdict", RunStatus.NOT_EVALUATED.value, False,
                     NOT_EVALUATED,
                     "no run has been executed in this session"),
            ]
        return [
            Cell("registered experiments", len(self.registry.EXPERIMENTS), True),
            Cell("last verdict", RunStatus.NOT_EVALUATED.value, False,
                 NOT_EVALUATED,
                 "no run has been executed in this session"),
        ]

    def blocked(self) -> list[str]:
        return ["experiment execution: requires an owned session authority"]


class JobsModel(BaseModel):
    """15 Jobs / Locks: three lock authorities, shown separately."""

    route = "15_job_control"

    EXPECTED = ("REPO_WRITER", "WORKTREE_LEASE", "MACHINE_LEASE")

    def __init__(self, observations: Any = ()) -> None:
        self.observations = list(observations)

    def rows(self) -> list[Cell]:
        by_authority = {obs.authority: obs for obs in self.observations}
        rows = []
        for authority in self.EXPECTED:
            obs = by_authority.get(authority)
            if obs is None:
                rows.append(Cell(authority, "NOT_OBSERVED", False,
                                 NOT_EVALUATED,
                                 "no observation recorded for this authority"))
                continue
            state = "MALFORMED_LOCK" if obs.malformed else obs.state
            rows.append(Cell(authority, state, True,
                             state if obs.malformed else "",
                             obs.detail))
        for authority in sorted(set(by_authority) - set(self.EXPECTED)):
            rows.append(Cell(authority, "UNKNOWN_AUTHORITY", False,
                             NOT_EVALUATED,
                             "not one of the three authoritative locks"))
        return rows

    def blocked(self) -> list[str]:
        return ["scheduled / SLURM submission is never claimed",
                "job control stays read-only unless scheduling is explicitly allowed"]