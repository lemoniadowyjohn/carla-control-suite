from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.roadrunner.capability_probe import (
    MATLAB_ENV,
    ROADRUNNER_ENV,
    run_capability_probe,
)
from ultimate_pipeline.roadrunner.models import ArtifactRole, RoadRunnerMode


def test_capability_probe_blocks_when_roadrunner_is_missing(monkeypatch) -> None:
    monkeypatch.delenv(ROADRUNNER_ENV, raising=False)
    monkeypatch.delenv(MATLAB_ENV, raising=False)
    monkeypatch.setenv("PATH", "")

    report = run_capability_probe()

    assert report.overall_status == "blocked"
    assert report.capabilities == ()
    by_name = {result.name: result for result in report.results}
    assert by_name["roadrunner_executable"].available is False


def test_capability_probe_reports_donor_capability_from_env(tmp_path: Path, monkeypatch) -> None:
    rr = tmp_path / "RoadRunner.exe"
    rr.write_text("", encoding="utf-8")
    monkeypatch.setenv(ROADRUNNER_ENV, str(rr))
    monkeypatch.delenv(MATLAB_ENV, raising=False)
    monkeypatch.setenv("PATH", "")

    report = run_capability_probe()

    assert report.overall_status == "partial"
    assert len(report.capabilities) == 1
    capability = report.capabilities[0]
    assert RoadRunnerMode.ROUNDTRIP_CANDIDATE in capability.supported_modes
    assert ArtifactRole.CARLA_PACKAGE in capability.supported_exports
    assert report.to_dict()["capabilities"][0]["capability_id"] == "rr-local-authoring"
