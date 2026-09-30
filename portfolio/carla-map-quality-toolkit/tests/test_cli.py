import json
import sys
from pathlib import Path

from carla_map_quality_toolkit.cli import main


def test_cli_demo_writes_pass_reports(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["carla-map-quality", "demo", "--output", str(tmp_path)],
    )
    assert main() == 0

    stdout = capsys.readouterr().out
    assert "PASS" in stdout

    json_path = tmp_path / "quality_report.json"
    md_path = tmp_path / "quality_report.md"
    assert json_path.exists()
    assert md_path.exists()

    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["metrics"]["topology_errors"] == 0
    assert "Provenance" in md_path.read_text(encoding="utf-8")
