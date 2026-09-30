from carla_map_quality_toolkit.lane_quality import LaneWidthMetrics
from carla_map_quality_toolkit.reporting import build_quality_report


def test_gate_pass_and_fail() -> None:
    width_ok = LaneWidthMetrics(0.02, 0.04, 0.05, 0.0)
    report = build_quality_report(
        hausdorff_m=0.2,
        alignment_rmse_m=0.1,
        lane_width=width_ok,
        topology_errors=0,
    )
    assert report.status == "PASS"

    width_bad = LaneWidthMetrics(0.2, 0.3, 0.4, 0.7)
    failed = build_quality_report(
        hausdorff_m=1.5,
        alignment_rmse_m=0.8,
        lane_width=width_bad,
        topology_errors=2,
    )
    assert failed.status == "FAIL"
    assert len(failed.failures) == 4
