"""RoadRunner roundtrip comparison orchestration.

Ties together XODR parsing (xodr_diff), semantic diff computation,
and hard-gate validation (validation) to produce a complete
RoundtripReport comparing a parent (governed) XODR with a
RoadRunner-exported candidate XODR.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .exceptions import RoadRunnerContractError
from .models import GateStatus, SerializableContract, deterministic_json, utc_now_iso, validate_identifier, validate_sha256
from .validation import (
    DiffClassification,
    DiffRecord,
    GateResult,
    RoundtripConfig,
    apply_hard_gates,
    compute_overall_status,
)
from .xodr_diff import XodrSnapshot, compute_diffs, parse_xodr


@dataclass(frozen=True)
class RoundtripReport(SerializableContract):
    """Complete roundtrip validation report.

    Attributes:
        report_id: Unique identifier for this report.
        parent_path: Path to the parent (governed) XODR.
        candidate_path: Path to the RoadRunner-exported candidate XODR.
        parent_sha256: SHA-256 of the parent XODR file.
        candidate_sha256: SHA-256 of the candidate XODR file.
        config: Configuration used for the comparison.
        diffs: All semantic differences found.
        gates: All hard-gate results.
        overall_status: Aggregated status from all gates.
        generated_at: ISO-8601 timestamp of report generation.
    """

    report_id: str
    parent_path: str
    candidate_path: str
    parent_sha256: str
    candidate_sha256: str
    config: RoundtripConfig
    diffs: tuple[DiffRecord, ...]
    gates: tuple[GateResult, ...]
    overall_status: GateStatus
    generated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "report_id", validate_identifier(self.report_id, "report_id"))
        object.__setattr__(self, "parent_sha256", validate_sha256(self.parent_sha256, "parent_sha256"))
        object.__setattr__(self, "candidate_sha256", validate_sha256(self.candidate_sha256, "candidate_sha256"))
        object.__setattr__(self, "diffs", tuple(self.diffs))
        object.__setattr__(self, "gates", tuple(self.gates))
        object.__setattr__(
            self, "overall_status", self._coerce_status(self.overall_status)
        )
        object.__setattr__(self, "config", self.config)

    @staticmethod
    def _coerce_status(value: GateStatus | str) -> GateStatus:
        if isinstance(value, GateStatus):
            return value
        if isinstance(value, str):
            try:
                return GateStatus(value)
            except ValueError as exc:
                raise RoadRunnerContractError(
                    f"overall_status must be one of {[s.value for s in GateStatus]}, got {value!r}"
                ) from exc
        raise RoadRunnerContractError("overall_status must be GateStatus or str")

    @property
    def diff_count(self) -> int:
        return len(self.diffs)

    @property
    def gate_count(self) -> int:
        return len(self.gates)

    @property
    def failed_gate_count(self) -> int:
        return sum(1 for g in self.gates if g.status is GateStatus.FAIL)

    @property
    def blocked_gate_count(self) -> int:
        return sum(1 for g in self.gates if g.status is GateStatus.BLOCKED)

    @property
    def passed_gate_count(self) -> int:
        return sum(1 for g in self.gates if g.status is GateStatus.PASS)

    def to_summary_dict(self) -> dict[str, Any]:
        """Return a compact summary suitable for JSON output."""
        return {
            "report_id": self.report_id,
            "parent_sha256": self.parent_sha256,
            "candidate_sha256": self.candidate_sha256,
            "parent_path": self.parent_path,
            "candidate_path": self.candidate_path,
            "overall_status": self.overall_status.value,
            "diff_count": self.diff_count,
            "gate_count": self.gate_count,
            "passed_gates": self.passed_gate_count,
            "failed_gates": self.failed_gate_count,
            "blocked_gates": self.blocked_gate_count,
            "generated_at": self.generated_at,
            "gates": [
                {
                    "gate_id": g.gate_id,
                    "status": g.status.value,
                    "required": g.required,
                    "message": g.message,
                    "metrics": dict(g.metrics),
                }
                for g in self.gates
            ],
            "diffs": [
                {
                    "dimension": d.dimension,
                    "element_id": d.element_id,
                    "parent_value": d.parent_value,
                    "candidate_value": d.candidate_value,
                    "classification": d.classification.value,
                    "message": d.message,
                    "evidence": list(d.evidence),
                }
                for d in self.diffs
            ],
        }

    def to_json(self) -> str:
        """Serialize the full report to deterministic JSON."""
        return deterministic_json(self.to_summary_dict())


def _try_import_shapely() -> bool:
    """Attempt to import shapely; return True if available."""
    try:
        import shapely  # noqa: F401
        return True
    except ImportError:
        return False


def compare_roundtrip(
    parent_path: str | Path,
    candidate_path: str | Path,
    config: RoundtripConfig | None = None,
    report_id: str | None = None,
) -> RoundtripReport:
    """Compare a parent XODR with a RoadRunner-exported candidate XODR.

    This function is read-only: it does not modify either input file.

    Args:
        parent_path: Path to the parent (governed/candidate) XODR.
        candidate_path: Path to the RoadRunner-exported candidate XODR.
        config: Optional configuration. If None, defaults are used.
        report_id: Optional report identifier. If None, one is generated.

    Returns:
        A RoundtripReport containing all diffs and gate results.
    """
    parent_path = Path(parent_path)
    candidate_path = Path(candidate_path)

    if not parent_path.is_file():
        raise RoadRunnerContractError(f"Parent XODR not found: {parent_path}")
    if not candidate_path.is_file():
        raise RoadRunnerContractError(f"Candidate XODR not found: {candidate_path}")

    if config is None:
        shapely_available = _try_import_shapely()
        config = RoundtripConfig(shapely_available=shapely_available)

    parent_snapshot = parse_xodr(parent_path)
    candidate_snapshot = parse_xodr(candidate_path)

    diffs = compute_diffs(parent_snapshot, candidate_snapshot, config)
    gates = apply_hard_gates(diffs, config)
    overall_status = compute_overall_status(gates)

    if report_id is None:
        report_id = f"roundtrip-{parent_path.stem}-{candidate_path.stem}"

    return RoundtripReport(
        report_id=report_id,
        parent_path=parent_path.as_posix(),
        candidate_path=candidate_path.as_posix(),
        parent_sha256=parent_snapshot.sha256,
        candidate_sha256=candidate_snapshot.sha256,
        config=config,
        diffs=diffs,
        gates=gates,
        overall_status=overall_status,
    )


def write_report(report: RoundtripReport, output_path: str | Path) -> str:
    """Write a roundtrip report to a JSON file.

    Returns the path to the written file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = report.to_json()
    output_path.write_text(text, encoding="utf-8", newline="\n")
    return output_path.as_posix()


__all__ = [
    "RoundtripReport",
    "compare_roundtrip",
    "write_report",
]
