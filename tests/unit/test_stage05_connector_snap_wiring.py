from __future__ import annotations

import json

import pytest

from ultimate_pipeline.pipeline_stages import stage_05_geometry as stage


class _VerificationReport:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def add_dict(self, key: str, value: dict) -> None:
        self.records[key] = value


class _Stage:
    def __init__(self, out_dir) -> None:
        self.out_dir = str(out_dir)
        self.vreport = _VerificationReport()


def test_connector_snap_is_disabled_by_default(monkeypatch, tmp_path):
    stage_instance = _Stage(tmp_path)
    monkeypatch.delenv("UP_ENABLE_JUNCTION_CONNECTOR_SNAP", raising=False)
    monkeypatch.setattr(
        stage, "load_xodr", lambda _path: pytest.fail("must not load"), raising=False
    )

    assert stage._run_junction_connector_snap(stage_instance, "input.xodr") is None
    assert stage_instance.vreport.records == {}
    assert not (tmp_path / "junction_connector_snap_report.json").exists()


def test_enabled_connector_snap_writes_only_after_real_repairs(monkeypatch, tmp_path):
    stage_instance = _Stage(tmp_path)
    saved: list[tuple[object, str]] = []
    fake_tree, fake_root = object(), object()
    result = {
        "connectors_examined": 1,
        "connectors_snapped": 1,
        "skipped_end_contact_point": 0,
    }

    monkeypatch.setenv("UP_ENABLE_JUNCTION_CONNECTOR_SNAP", "1")
    monkeypatch.setattr(
        stage, "load_xodr", lambda _path: (fake_tree, fake_root), raising=False
    )
    monkeypatch.setattr(
        stage,
        "save_xodr",
        lambda tree, path: saved.append((tree, path)),
        raising=False,
    )
    monkeypatch.setattr(
        "ultimate_pipeline.tools.junction_connector_snap.snap_junction_connectors",
        lambda root, max_gap_m: result,
    )

    assert stage._run_junction_connector_snap(stage_instance, "input.xodr") == result
    assert saved == [(fake_tree, "input.xodr")]
    assert stage_instance.vreport.records == {"junction_connector_snap": result}
    assert json.loads((tmp_path / "junction_connector_snap_report.json").read_text()) == result


def test_connector_snap_failure_raises_only_in_strict_mode(monkeypatch, tmp_path):
    stage_instance = _Stage(tmp_path)
    monkeypatch.setenv("UP_ENABLE_JUNCTION_CONNECTOR_SNAP", "1")
    monkeypatch.setattr(
        stage,
        "load_xodr",
        lambda _path: (_ for _ in ()).throw(ValueError("bad xodr")),
        raising=False,
    )

    monkeypatch.delenv("UP_STRICT_QUALITY_GATES", raising=False)
    assert stage._run_junction_connector_snap(stage_instance, "input.xodr") is None

    monkeypatch.setenv("UP_STRICT_QUALITY_GATES", "true")
    with pytest.raises(ValueError, match="bad xodr"):
        stage._run_junction_connector_snap(stage_instance, "input.xodr")
