"""Validation types and hard gates for RoadRunner roundtrip comparison.

Defines the difference classification taxonomy, diff record model,
gate result model, roundtrip configuration, and the set of hard gates
that enforce strict semantic preservation between a parent (governed)
XODR and a RoadRunner-exported candidate XODR.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .exceptions import RoadRunnerContractError
from .models import GateStatus, SerializableContract, validate_identifier


class DiffClassification(Enum):
    """Classification of a single semantic difference between parent and candidate."""

    IDENTICAL = "IDENTICAL"
    FORMAT_ONLY = "FORMAT_ONLY"
    APPROVED_IMPROVEMENT = "APPROVED_IMPROVEMENT"
    POTENTIAL_LOSS = "POTENTIAL_LOSS"
    CRITICAL_REGRESSION = "CRITICAL_REGRESSION"
    UNSUPPORTED_COMPARISON = "UNSUPPORTED_COMPARISON"


@dataclass(frozen=True)
class DiffRecord:
    """A single semantic difference between parent and candidate XODR.

    Attributes:
        dimension: Comparison dimension (e.g. "georeference", "road_count", "lane_width").
        element_id: Identifier of the element being compared (road id, lane id, etc.).
        parent_value: Value in the parent XODR (stringified for JSON stability).
        candidate_value: Value in the candidate XODR (stringified for JSON stability).
        classification: How the difference is classified.
        message: Human-readable description of the difference.
        evidence: Additional context strings (file:line, raw values, etc.).
    """

    dimension: str
    element_id: str | None
    parent_value: str | None
    candidate_value: str | None
    classification: DiffClassification
    message: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension", validate_identifier(self.dimension, "dimension"))
        if self.element_id is not None:
            object.__setattr__(self, "element_id", str(self.element_id))
        if self.parent_value is not None:
            object.__setattr__(self, "parent_value", str(self.parent_value))
        if self.candidate_value is not None:
            object.__setattr__(self, "candidate_value", str(self.candidate_value))
        object.__setattr__(self, "classification", self._coerce_classification(self.classification))
        object.__setattr__(self, "evidence", tuple(str(e) for e in self.evidence))

    @staticmethod
    def _coerce_classification(value: DiffClassification | str) -> DiffClassification:
        if isinstance(value, DiffClassification):
            return value
        if isinstance(value, str):
            try:
                return DiffClassification(value)
            except ValueError as exc:
                raise RoadRunnerContractError(
                    f"classification must be one of {[c.value for c in DiffClassification]}, got {value!r}"
                ) from exc
        raise RoadRunnerContractError("classification must be DiffClassification or str")


@dataclass(frozen=True)
class GateResult:
    """Result of a single hard gate evaluation."""

    gate_id: str
    status: GateStatus
    required: bool
    message: str
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_id", validate_identifier(self.gate_id, "gate_id"))
        object.__setattr__(self, "status", self._coerce_status(self.status))
        object.__setattr__(self, "metrics", dict(self.metrics))

    @staticmethod
    def _coerce_status(value: GateStatus | str) -> GateStatus:
        if isinstance(value, GateStatus):
            return value
        if isinstance(value, str):
            try:
                return GateStatus(value)
            except ValueError as exc:
                raise RoadRunnerContractError(
                    f"status must be one of {[s.value for s in GateStatus]}, got {value!r}"
                ) from exc
        raise RoadRunnerContractError("status must be GateStatus or str")


@dataclass(frozen=True)
class RoundtripConfig(SerializableContract):
    """Configuration for roundtrip validation thresholds.

    All tolerances are in metres unless otherwise noted.
    """

    tangent_regression_threshold_deg: float = 1.0
    position_tolerance_m: float = 0.1
    length_tolerance_m: float = 0.5
    width_tolerance_m: float = 0.05
    curvature_tolerance: float = 0.01
    sample_interval_m: float = 1.0
    shapely_available: bool = False

    def __post_init__(self) -> None:
        for name in (
            "tangent_regression_threshold_deg",
            "position_tolerance_m",
            "length_tolerance_m",
            "width_tolerance_m",
            "curvature_tolerance",
            "sample_interval_m",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)):
                raise RoadRunnerContractError(f"{name} must be numeric")
            if not math.isfinite(value):
                raise RoadRunnerContractError(f"{name} must be finite")
            if value < 0:
                raise RoadRunnerContractError(f"{name} must be non-negative")
        if self.sample_interval_m <= 0:
            raise RoadRunnerContractError("sample_interval_m must be positive")


def _classify_no_road_deletion(diffs: Sequence[DiffRecord]) -> GateResult:
    """Gate: no road or junction deletion."""
    deleted = [
        d for d in diffs
        if d.dimension in ("road_id", "junction_id")
        and d.classification in (DiffClassification.CRITICAL_REGRESSION, DiffClassification.POTENTIAL_LOSS)
        and d.candidate_value is None
    ]
    if deleted:
        ids = sorted({d.element_id for d in deleted if d.element_id})
        return GateResult(
            gate_id="no_road_junction_deletion",
            status=GateStatus.FAIL,
            required=True,
            message=f"Road/junction deletion detected: {ids}",
            metrics={"deleted_count": len(deleted), "deleted_ids": ids},
        )
    return GateResult(
        gate_id="no_road_junction_deletion",
        status=GateStatus.PASS,
        required=True,
        message="No road or junction deletion detected",
        metrics={"deleted_count": 0},
    )


def _classify_no_georeference_loss(diffs: Sequence[DiffRecord]) -> GateResult:
    """Gate: no georeference loss."""
    georef_loss = [
        d for d in diffs
        if d.dimension == "georeference"
        and d.classification in (DiffClassification.CRITICAL_REGRESSION, DiffClassification.POTENTIAL_LOSS)
        and (d.parent_value is not None and d.candidate_value is None)
    ]
    if georef_loss:
        return GateResult(
            gate_id="no_georeference_loss",
            status=GateStatus.FAIL,
            required=True,
            message="Georeference lost in candidate",
            metrics={"loss_count": len(georef_loss)},
        )
    return GateResult(
        gate_id="no_georeference_loss",
        status=GateStatus.PASS,
        required=True,
        message="Georeference preserved",
        metrics={"loss_count": 0},
    )


def _classify_no_lanelink_loss(diffs: Sequence[DiffRecord]) -> GateResult:
    """Gate: no loss of native LaneLinks without approved replacement."""
    lanelink_loss = [
        d for d in diffs
        if d.dimension in ("lane_link", "lane_predecessor", "lane_successor")
        and d.classification in (DiffClassification.CRITICAL_REGRESSION, DiffClassification.POTENTIAL_LOSS)
        and d.candidate_value is None
    ]
    if lanelink_loss:
        return GateResult(
            gate_id="no_lanelink_loss",
            status=GateStatus.FAIL,
            required=True,
            message=f"LaneLink loss detected: {len(lanelink_loss)} link(s) removed without replacement",
            metrics={"loss_count": len(lanelink_loss)},
        )
    return GateResult(
        gate_id="no_lanelink_loss",
        status=GateStatus.PASS,
        required=True,
        message="No LaneLink loss detected",
        metrics={"loss_count": 0},
    )


def _classify_no_signal_loss(diffs: Sequence[DiffRecord]) -> GateResult:
    """Gate: no signal or controller loss."""
    signal_loss = [
        d for d in diffs
        if d.dimension in ("signal", "controller")
        and d.classification in (DiffClassification.CRITICAL_REGRESSION, DiffClassification.POTENTIAL_LOSS)
        and d.candidate_value is None
    ]
    if signal_loss:
        dims = sorted({d.dimension for d in signal_loss})
        return GateResult(
            gate_id="no_signal_controller_loss",
            status=GateStatus.FAIL,
            required=True,
            message=f"Signal/controller loss detected: {len(signal_loss)} element(s) removed",
            metrics={"loss_count": len(signal_loss), "dimensions": dims},
        )
    return GateResult(
        gate_id="no_signal_controller_loss",
        status=GateStatus.PASS,
        required=True,
        message="No signal or controller loss detected",
        metrics={"loss_count": 0},
    )


def _classify_no_negative_width(diffs: Sequence[DiffRecord]) -> GateResult:
    """Gate: no negative lane width."""
    neg_width = [
        d for d in diffs
        if d.dimension == "lane_width"
        and d.classification in (DiffClassification.CRITICAL_REGRESSION, DiffClassification.POTENTIAL_LOSS)
        and d.candidate_value is not None
        and _is_negative(d.candidate_value)
    ]
    if neg_width:
        return GateResult(
            gate_id="no_negative_width",
            status=GateStatus.FAIL,
            required=True,
            message=f"Negative lane width detected: {len(neg_width)} lane(s)",
            metrics={"negative_count": len(neg_width)},
        )
    return GateResult(
        gate_id="no_negative_width",
        status=GateStatus.PASS,
        required=True,
        message="No negative lane width detected",
        metrics={"negative_count": 0},
    )


def _classify_no_driving_centre_lane(diffs: Sequence[DiffRecord]) -> GateResult:
    """Gate: no driving centre lane (lane id=0 should not be type=driving)."""
    driving_centre = [
        d for d in diffs
        if d.dimension == "lane_type"
        and d.element_id == "0"
        and d.classification in (DiffClassification.CRITICAL_REGRESSION, DiffClassification.POTENTIAL_LOSS)
        and d.candidate_value is not None
        and d.candidate_value.lower() == "driving"
    ]
    if driving_centre:
        return GateResult(
            gate_id="no_driving_centre_lane",
            status=GateStatus.FAIL,
            required=True,
            message="Driving centre lane (id=0) detected in candidate",
            metrics={"count": len(driving_centre)},
        )
    return GateResult(
        gate_id="no_driving_centre_lane",
        status=GateStatus.PASS,
        required=True,
        message="No driving centre lane detected",
        metrics={"count": 0},
    )


def _classify_no_line_fallback(diffs: Sequence[DiffRecord]) -> GateResult:
    """Gate: no new unsupported line fallback (poly3/paramPoly3 replaced by line)."""
    line_fallback = [
        d for d in diffs
        if d.dimension == "geometry_type"
        and d.classification in (DiffClassification.CRITICAL_REGRESSION, DiffClassification.POTENTIAL_LOSS)
        and d.parent_value is not None
        and d.candidate_value is not None
        and d.parent_value.lower() in ("poly3", "parampoly3", "spiral")
        and d.candidate_value.lower() == "line"
    ]
    if line_fallback:
        return GateResult(
            gate_id="no_line_fallback",
            status=GateStatus.FAIL,
            required=True,
            message=f"Unsupported line fallback detected: {len(line_fallback)} geometry segment(s) degraded",
            metrics={"fallback_count": len(line_fallback)},
        )
    return GateResult(
        gate_id="no_line_fallback",
        status=GateStatus.PASS,
        required=True,
        message="No unsupported line fallback detected",
        metrics={"fallback_count": 0},
    )


def _classify_no_tangent_regression(
    diffs: Sequence[DiffRecord], config: RoundtripConfig
) -> GateResult:
    """Gate: no tangent regression over project threshold."""
    threshold_deg = config.tangent_regression_threshold_deg
    tangent_regression = [
        d for d in diffs
        if d.dimension == "endpoint_tangent"
        and d.classification == DiffClassification.CRITICAL_REGRESSION
        and d.parent_value is not None
        and d.candidate_value is not None
        and _angle_diff_deg(d.parent_value, d.candidate_value) > threshold_deg
    ]
    if tangent_regression:
        max_diff = max(
            _angle_diff_deg(d.parent_value or "0", d.candidate_value or "0")
            for d in tangent_regression
        )
        return GateResult(
            gate_id="no_tangent_regression",
            status=GateStatus.FAIL,
            required=True,
            message=f"Tangent regression over {threshold_deg} deg detected: {len(tangent_regression)} segment(s)",
            metrics={"regression_count": len(tangent_regression), "max_diff_deg": max_diff, "threshold_deg": threshold_deg},
        )
    return GateResult(
        gate_id="no_tangent_regression",
        status=GateStatus.PASS,
        required=True,
        message=f"No tangent regression over {threshold_deg} deg",
        metrics={"regression_count": 0, "threshold_deg": threshold_deg},
    )


def _classify_no_authority_change(diffs: Sequence[DiffRecord]) -> GateResult:
    """Gate: no changed authority classification."""
    authority_change = [
        d for d in diffs
        if d.dimension == "authority_class"
        and d.classification in (DiffClassification.CRITICAL_REGRESSION, DiffClassification.POTENTIAL_LOSS)
        and d.parent_value is not None
        and d.candidate_value is not None
        and d.parent_value != d.candidate_value
    ]
    if authority_change:
        return GateResult(
            gate_id="no_authority_change",
            status=GateStatus.FAIL,
            required=True,
            message=f"Authority classification changed: {len(authority_change)} element(s)",
            metrics={"change_count": len(authority_change)},
        )
    return GateResult(
        gate_id="no_authority_change",
        status=GateStatus.PASS,
        required=True,
        message="No authority classification change detected",
        metrics={"change_count": 0},
    )


def _classify_shapely_gate(config: RoundtripConfig) -> GateResult:
    """Gate: BLOCKED for polygon-specific checks when Shapely is unavailable."""
    if not config.shapely_available:
        return GateResult(
            gate_id="polygon_checks_shapely",
            status=GateStatus.BLOCKED,
            required=True,
            message="Shapely not available; polygon-specific checks are BLOCKED",
            metrics={"shapely_available": False},
        )
    return GateResult(
        gate_id="polygon_checks_shapely",
        status=GateStatus.PASS,
        required=True,
        message="Shapely available; polygon checks enabled",
        metrics={"shapely_available": True},
    )


def _is_negative(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False


def _angle_diff_deg(a: str | None, b: str | None) -> float:
    try:
        va = float(a) if a is not None else 0.0
        vb = float(b) if b is not None else 0.0
        diff = abs(va - vb)
        diff = min(diff, 360.0 - diff)
        return diff
    except (TypeError, ValueError):
        return 0.0


HARD_GATE_FUNCTIONS: tuple = (
    _classify_no_road_deletion,
    _classify_no_georeference_loss,
    _classify_no_lanelink_loss,
    _classify_no_signal_loss,
    _classify_no_negative_width,
    _classify_no_driving_centre_lane,
    _classify_no_line_fallback,
    _classify_no_tangent_regression,
    _classify_no_authority_change,
    _classify_shapely_gate,
)


def apply_hard_gates(
    diffs: Sequence[DiffRecord],
    config: RoundtripConfig | None = None,
) -> tuple[GateResult, ...]:
    """Apply all hard gates to a set of diff records.

    Returns a tuple of GateResult objects, one per gate.
    """
    if config is None:
        config = RoundtripConfig()
    results: list[GateResult] = []
    for gate_fn in HARD_GATE_FUNCTIONS:
        if gate_fn is _classify_no_tangent_regression:
            results.append(gate_fn(diffs, config))
        elif gate_fn is _classify_shapely_gate:
            results.append(gate_fn(config))
        else:
            results.append(gate_fn(diffs))
    return tuple(results)


def compute_overall_status(gates: Sequence[GateResult]) -> GateStatus:
    """Compute overall roundtrip status from gate results."""
    if not gates:
        return GateStatus.NOT_APPLICABLE
    has_blocked = any(g.status is GateStatus.BLOCKED for g in gates if g.required)
    has_fail = any(g.status is GateStatus.FAIL for g in gates if g.required)
    if has_blocked:
        return GateStatus.BLOCKED
    if has_fail:
        return GateStatus.FAIL
    return GateStatus.PASS


__all__ = [
    "DiffClassification",
    "DiffRecord",
    "GateResult",
    "RoundtripConfig",
    "apply_hard_gates",
    "compute_overall_status",
]
