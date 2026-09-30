import json
import sys

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


def test_cli_main_pass_path(monkeypatch, tmp_path) -> None:
    from carla_map_quality_toolkit.cli import main

    output = tmp_path / "main-pass"
    monkeypatch.setattr(
        sys,
        "argv",
        ["carla-map-quality", "demo", "--output", str(output)],
    )
    assert main() == 0
    payload = json.loads((output / "quality_report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"


def test_cli_main_failure_path(monkeypatch, tmp_path) -> None:
    from carla_map_quality_toolkit.cli import main

    output = tmp_path / "main-fail"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "carla-map-quality",
            "demo",
            "--inject-failure",
            "--output",
            str(output),
        ],
    )
    assert main() == 2
    payload = json.loads((output / "quality_report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
