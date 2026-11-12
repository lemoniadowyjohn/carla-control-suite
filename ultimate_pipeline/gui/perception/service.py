"""Perception and localization service with honest capability gating.

The governing fact: **the repository contains no model weights.** No ``*.pt``,
``*.onnx``, ``*.pth`` or ``*.engine`` exists at HEAD, and
``ml/lane_gnn_refiner.py`` is explicitly stubbed. Therefore this service never
fabricates inference or a mAP number.

Capability states are typed and explicit:

``MODEL_MISSING``     -- weights were expected and are not present.
``UNSUPPORTED``       -- the backend has no implementation for this capability.
``NOT_MEASURED``      -- the capability exists but nothing was measured.
``AVAILABLE``         -- genuinely usable, with provenance.

Weather and traffic are recorded only as **experiment variables**. No causal
claim is derivable from them without measurement, and this module refuses to
make one.

Calibration reprojection stays unavailable without observed pixels: the caller
is *disabled*, not shown a PASS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from ultimate_pipeline.gui.results import Result

__all__ = [
    "CapabilityState", "ObservationKind", "ModelSpec", "CapabilityProbe",
    "PerceptionCapability", "Observation", "FrameSync", "ExperimentVariable",
    "PerceptionService", "discover_model_weights", "WEIGHT_SUFFIXES",
    "FABRICATED_METRICS_FORBIDDEN",
]


class CapabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    MODEL_MISSING = "MODEL_MISSING"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_MEASURED = "NOT_MEASURED"


class ObservationKind(str, Enum):
    """Synthetic and live observations are never mixed."""

    SYNTHETIC = "SYNTHETIC"
    LIVE = "LIVE"


#: A metric with no measured observation behind it is never reported.
FABRICATED_METRICS_FORBIDDEN = frozenset({
    "map50", "map50_95", "mAP", "precision", "recall", "f1",
})

WEIGHT_SUFFIXES = (".pt", ".onnx", ".pth", ".engine")


@dataclass(frozen=True)
class ModelSpec:
    """A model the GUI would like to use, and what it needs to run it."""

    name: str
    weights_path: str
    required_frameworks: tuple[str, ...] = ()
    source: str = ""          # where the requirement came from

    def as_dict(self) -> dict:
        return {"name": self.name, "weights_path": self.weights_path,
                "required_frameworks": list(self.required_frameworks),
                "source": self.source}


@dataclass(frozen=True)
class CapabilityProbe:
    """The result of honestly asking whether something can be done."""

    capability: str
    state: str
    detail: str = ""
    remediation: str = ""
    provenance: str = ""

    @property
    def usable(self) -> bool:
        return self.state == CapabilityState.AVAILABLE.value

    def as_dict(self) -> dict:
        return {"capability": self.capability, "state": self.state,
                "usable": self.usable, "detail": self.detail,
                "remediation": self.remediation, "provenance": self.provenance}


def discover_model_weights(search_roots: Iterable[Path]) -> list[Path]:
    """Find actual weight files. Absence is a real, reportable result."""
    found: list[Path] = []
    for root in search_roots:
        base = Path(root)
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() in WEIGHT_SUFFIXES and path.is_file():
                found.append(path)
    return sorted(found)


@dataclass
class PerceptionCapability:
    """A named capability with its honest state."""

    name: str
    state: str
    detail: str = ""
    remediation: str = ""
    provenance: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "state": self.state, "detail": self.detail,
                "remediation": self.remediation, "provenance": self.provenance}


@dataclass(frozen=True)
class Observation:
    """One measurement, with its provenance and kind."""

    sequence: int
    frame_id: int
    kind: str
    metric: str
    value: float | None
    map_fingerprint: str = ""
    sensor_ids: tuple[str, ...] = ()
    recorded_at: str = ""

    @property
    def measured(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict:
        return {"sequence": self.sequence, "frame_id": self.frame_id,
                "kind": self.kind, "metric": self.metric, "value": self.value,
                "map_fingerprint": self.map_fingerprint,
                "sensor_ids": list(self.sensor_ids)}


@dataclass
class FrameSync:
    """Frame/timestamp bookkeeping across sensors."""

    expected: int | None = None
    received: int = 0
    first_frame_id: int | None = None
    last_frame_id: int | None = None
    max_skew_ms: float | None = None

    def record(self, frame_id: int, timestamp: float) -> None:
        self.received += 1
        if self.first_frame_id is None:
            self.first_frame_id = frame_id
        if self.last_frame_id is not None and frame_id < self.last_frame_id:
            raise ValueError(
                f"frame id went backwards: {self.last_frame_id} -> {frame_id}")
        self.last_frame_id = frame_id

    @property
    def missing(self) -> int:
        """Frame ids absent from the observed span.

        Derived from the observed first/last frame ids alone. Requiring an
        ``expected`` count here would silently report zero gaps whenever the
        caller had not declared one, which is exactly when gaps matter most.
        """
        if self.first_frame_id is None or self.last_frame_id is None:
            return 0
        span = self.last_frame_id - self.first_frame_id + 1
        return max(0, span - self.received)

    def as_dict(self) -> dict:
        return {"expected": self.expected, "received": self.received,
                "first_frame_id": self.first_frame_id,
                "last_frame_id": self.last_frame_id, "missing": self.missing,
                "max_skew_ms": self.max_skew_ms}


@dataclass(frozen=True)
class ExperimentVariable:
    """Weather / traffic are *recorded variables*, never causal claims."""

    name: str
    value: str
    controlled: bool = False

    def as_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "controlled": self.controlled,
                "causal_claim": "NOT CLAIMED - an uncontrolled variable"}


class PerceptionService:
    """Diagnostics-only perception service that never fabricates a result."""

    def __init__(self, *, search_roots: Iterable[Path] = (),
                 models: Iterable[ModelSpec] = ()) -> None:
        self._roots = [Path(r) for r in search_roots]
        self._models = list(models)
        self.sync = FrameSync()
        self.observations: list[Observation] = []
        self.variables: list[ExperimentVariable] = []

    # -- capability --------------------------------------------------------
    def weights_present(self) -> list[Path]:
        return discover_model_weights(self._roots)

    def probe_model(self, spec: ModelSpec) -> CapabilityProbe:
        """Ask honestly whether a model can run."""
        path = Path(spec.weights_path)
        if not path.is_file():
            return CapabilityProbe(
                spec.name, CapabilityState.MODEL_MISSING.value,
                detail=f"no weights at {spec.weights_path}",
                remediation="supply weights, or use the diagnostics-only view",
                provenance=spec.source or "requested by the GUI specification",
            )
        for framework in spec.required_frameworks:
            try:
                __import__(framework)
            except ImportError:
                return CapabilityProbe(
                    spec.name, CapabilityState.UNSUPPORTED.value,
                    detail=f"required framework {framework!r} is not installed",
                    remediation=f"pip install {framework}",
                    provenance=spec.source or "requested by the GUI specification",
                )
        return CapabilityProbe(spec.name, CapabilityState.AVAILABLE.value,
                               detail=f"weights present at {spec.weights_path}",
                               provenance=spec.source or "discovered on disk")

    def probe_gpu(self) -> CapabilityProbe:
        """GPU capability. A CPU-only build is reported, never assumed away."""
        try:
            import torch
        except ImportError:
            return CapabilityProbe(
                "gpu_inference", CapabilityState.UNSUPPORTED.value,
                detail="torch is not installed in this environment",
                remediation="install torch with CUDA support before GPU work",
                provenance="checked at runtime, not assumed")
        if not torch.cuda.is_available():
            version = getattr(torch, "__version__", "unknown")
            return CapabilityProbe(
                "gpu_inference", CapabilityState.UNSUPPORTED.value,
                detail=f"torch {version} is a CPU-only build; no CUDA runtime",
                remediation="install a CUDA-enabled torch build before GPU work",
                provenance="checked at runtime, not assumed")
        total_mib = int(torch.cuda.get_device_properties(0).total_memory / 1048576)
        return CapabilityProbe(
            "gpu_inference", CapabilityState.AVAILABLE.value,
            detail=f"{torch.cuda.get_device_name(0)}, {total_mib} MiB",
            provenance="checked at runtime")

    def calibration_reprojection(self, observed_pixels) -> CapabilityProbe:
        """Reprojection is DISABLED without observed pixels -- never a PASS."""
        if observed_pixels is None:
            return CapabilityProbe(
                "calibration_reprojection", CapabilityState.NOT_MEASURED.value,
                detail="no observed pixels: reprojection cannot be computed",
                remediation="supply observed pixels from a live capture")
        return CapabilityProbe(
            "calibration_reprojection", CapabilityState.AVAILABLE.value,
            detail="observed pixels present")

    # -- observations ------------------------------------------------------
    def record(self, observation: Observation) -> None:
        if observation.kind not in (ObservationKind.SYNTHETIC.value,
                                    ObservationKind.LIVE.value):
            raise ValueError(f"unknown observation kind: {observation.kind}")
        self.observations.append(observation)
        self.sync.record(observation.frame_id, 0.0)

    def summarise_metric(self, metric: str, kind: str | None = None) -> Result:
        """Summarise a metric, refusing to invent one."""
        values = [
            o.value for o in self.observations
            if o.metric == metric and o.value is not None
            and (kind is None or o.kind == kind)
        ]
        if not values:
            state = (CapabilityState.MODEL_MISSING.value
                     if metric in FABRICATED_METRICS_FORBIDDEN
                     else CapabilityState.NOT_MEASURED.value)
            return Result.blocked(
                f"no measured value for {metric!r}",
                remediation="run a real experiment; static or example metrics "
                            "are never promoted to observations")
        return Result.success({"metric": metric, "n": len(values),
                               "mean": sum(values) / len(values)})

    def causal_claim(self, variable: str) -> Result:
        """Refuse any causal claim from an uncontrolled variable."""
        entry = next((v for v in self.variables if v.name == variable), None)
        if entry is None:
            return Result.blocked(f"{variable!r} was never recorded as a variable")
        if not entry.controlled:
            return Result.blocked(
                f"{variable} is an UNCONTROLLED variable; no causal gain may be claimed",
                remediation="run a controlled A/B experiment")
        return Result.success({"variable": variable, "controlled": True})

    # -- page mode ---------------------------------------------------------
    def page_mode(self) -> str:
        """The perception page is diagnostics/replay-only without weights."""
        return "LIVE" if self.weights_present() else "DIAGNOSTICS_REPLAY_ONLY"

    def as_dict(self) -> dict:
        return {"page_mode": self.page_mode(),
                "weights_found": [str(p) for p in self.weights_present()],
                "observations": len(self.observations),
                "frame_sync": self.sync.as_dict(),
                "variables": [v.as_dict() for v in self.variables]}