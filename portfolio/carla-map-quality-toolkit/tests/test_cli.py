import json

from carla_map_quality_toolkit.cli import _demo


def test_demo_writes_passing_report(tmp_path) -> None:
    output = tmp_path / "pass"
    assert _demo(output) == 0
    payload = json.loads((output / "quality_report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["failures"] == []
    assert payload["provenance"]["mode"] == "passing_demo"


def test_demo_failure_mode_rejects_degraded_input(tmp_path) -> None:
    output = tmp_path / "fail"
    assert _demo(output, inject_failure=True) == 2
    payload = json.loads((output / "quality_report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert len(payload["failures"]) == 4
    assert payload["metrics"]["topology_errors"] == 2
    assert payload["provenance"]["mode"] == "intentional_failure"
