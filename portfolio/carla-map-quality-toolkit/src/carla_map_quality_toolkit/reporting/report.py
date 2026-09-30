from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from carla_map_quality_toolkit.lane_quality.width import LaneWidthMetrics


@dataclass(frozen=True)
class QualityThresholds:
    hausdorff_max_m: float = 1.0
    alignment_rmse_max_m: float = 0.50
    lane_width_p95_max_m: float = 0.15
    topology_errors_max: int = 0


@dataclass(frozen=True)
class QualityReport:
    status: str
    metrics: dict[str, Any]
    thresholds: QualityThresholds
    failures: tuple[str, ...]
    provenance: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["thresholds"] = asdict(self.thresholds)
        return payload

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def write_markdown(self, path: str | Path) -> None:
        lines = [
            "# Map Quality Report",
            "",
            f"**Gate:** {self.status}",
            "",
            "## Metrics",
            "",
            "| Metric | Value | Threshold |",
            "|---|---:|---:|",
            (
                "| Symmetric Hausdorff | "
                f"{self.metrics['hausdorff_m']:.3f} m | "
                f"≤ {self.thresholds.hausdorff_max_m:.3f} m |"
            ),
            (
                "| SE(2) alignment RMSE | "
                f"{self.metrics['alignment_rmse_m']:.3f} m | "
                f"≤ {self.thresholds.alignment_rmse_max_m:.3f} m |"
            ),
            (
                "| Lane-width p95 deviation | "
                f"{self.metrics['lane_width_p95_m']:.3f} m | "
                f"≤ {self.thresholds.lane_width_p95_max_m:.3f} m |"
            ),
            (
                "| Topology errors | "
                f"{self.metrics['topology_errors']} | "
                f"≤ {self.thresholds.topology_errors_max} |"
            ),
            "",
            "## Gate Findings",
            "",
        ]
        findings = [f"- {failure}" for failure in self.failures]
        lines.extend(findings or ["- No threshold violations."])
        lines += ["", "## Provenance", ""]
        lines.extend([f"- **{k}:** `{v}`" for k, v in self.provenance.items()])
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_quality_report(
    *,
    hausdorff_m: float,
    alignment_rmse_m: float,
    lane_width: LaneWidthMetrics,
    topology_errors: int,
    provenance: dict[str, str] | None = None,
    thresholds: QualityThresholds | None = None,
) -> QualityReport:
    thresholds = thresholds or QualityThresholds()
    failures: list[str] = []
    if hausdorff_m > thresholds.hausdorff_max_m:
        failures.append("Hausdorff distance exceeds geometric threshold")
    if alignment_rmse_m > thresholds.alignment_rmse_max_m:
        failures.append("SE(2) alignment residual exceeds threshold")
    if lane_width.p95_abs_deviation_m > thresholds.lane_width_p95_max_m:
        failures.append("Lane-width p95 deviation exceeds threshold")
    if topology_errors > thresholds.topology_errors_max:
        failures.append("Topology validation found invalid references/lane links")

    metrics = {
        "hausdorff_m": float(hausdorff_m),
        "alignment_rmse_m": float(alignment_rmse_m),
        "lane_width_mean_m": lane_width.mean_abs_deviation_m,
        "lane_width_p95_m": lane_width.p95_abs_deviation_m,
        "lane_width_max_m": lane_width.max_abs_deviation_m,
        "lane_width_violation_fraction": lane_width.violation_fraction,
        "topology_errors": int(topology_errors),
    }
    return QualityReport(
        status="PASS" if not failures else "FAIL",
        metrics=metrics,
        thresholds=thresholds,
        failures=tuple(failures),
        provenance=provenance or {},
    )
