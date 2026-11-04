from __future__ import annotations

import json
import inspect
import math

import pytest

from ultimate_pipeline.pipeline_stages import stage_05_geometry as stage
from ultimate_pipeline.quality.check_road_link_reciprocity import (
    EXIT_HEADING_DISCONTINUITY_DEG,
)
from ultimate_pipeline.tools.junction_connector_snap import snap_junction_connectors


class _VerificationReport:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def add_dict(self, key: str, value: dict) -> None:
        self.records[key] = value


class _Stage:
    def __init__(self, out_dir) -> None:
        self.out_dir = str(out_dir)
        self.vreport = _VerificationReport()
        self.settings = type(
            "Settings", (), {"RELEASE_PROFILE": "debug", "ENABLE_JUNCTION_CONNECTOR_SNAP": False}
        )()


def test_connector_snap_is_disabled_by_default_and_records_policy(monkeypatch, tmp_path):
    """Unset configuration must preserve unqualified lane-border geometry."""
    stage_instance = _Stage(tmp_path)
    monkeypatch.delenv("UP_ENABLE_JUNCTION_CONNECTOR_SNAP", raising=False)
    monkeypatch.setattr(
        stage, "load_xodr", lambda _path: pytest.fail("default must not load or rewrite"),
        raising=False,
    )
    result = stage._run_junction_connector_snap(stage_instance, "input.xodr")
    assert result["status"] == "DISABLED"
    assert result["connectors_snapped"] == 0
    assert result["residual_count"] is None
    assert result["measurement_status"] == "NOT_MEASURED"
    assert stage_instance.vreport.records == {"junction_connector_snap": result}
    assert json.loads((tmp_path / "junction_connector_snap_report.json").read_text()) == result


def test_connector_snap_disabled_via_explicit_opt_out(monkeypatch, tmp_path):
    stage_instance = _Stage(tmp_path)
    monkeypatch.setenv("UP_ENABLE_JUNCTION_CONNECTOR_SNAP", "0")
    monkeypatch.setattr(
        stage, "load_xodr", lambda _path: pytest.fail("must not load"), raising=False
    )

    result = stage._run_junction_connector_snap(stage_instance, "input.xodr")
    assert result["status"] == "DISABLED"
    assert stage_instance.vreport.records == {"junction_connector_snap": result}


def test_release_profile_blocks_env_opt_in(monkeypatch, tmp_path):
    stage_instance = _Stage(tmp_path)
    stage_instance.settings.RELEASE_PROFILE = "structural_release"
    monkeypatch.setenv("UP_ENABLE_JUNCTION_CONNECTOR_SNAP", "1")
    monkeypatch.setattr(
        stage, "load_xodr", lambda _path: pytest.fail("release must not mutate"), raising=False
    )
    result = stage._run_junction_connector_snap(stage_instance, "input.xodr")
    assert result["status"] == "BLOCKED"
    assert result["residual_count"] is None
    assert result["measurement_status"] == "NOT_MEASURED"


def test_strict_debug_profile_blocks_env_opt_in(monkeypatch, tmp_path):
    stage_instance = _Stage(tmp_path)
    monkeypatch.setenv("UP_ENABLE_JUNCTION_CONNECTOR_SNAP", "1")
    monkeypatch.setenv("UP_STRICT_QUALITY_GATES", "true")
    monkeypatch.setattr(
        stage, "load_xodr", lambda _path: pytest.fail("strict mode must not mutate"), raising=False
    )
    result = stage._run_junction_connector_snap(stage_instance, "input.xodr")
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "experimental_snap_forbidden_by_release_profile"


def test_direct_policy_api_cannot_bypass_strict_mode(monkeypatch):
    from ultimate_pipeline.contracts.release_profile import (
        unsafe_junction_connector_snap_enabled,
    )

    class Settings:
        RELEASE_PROFILE = "debug"
        ENABLE_JUNCTION_CONNECTOR_SNAP = True

    monkeypatch.setenv("UP_ENABLE_JUNCTION_CONNECTOR_SNAP", "1")
    monkeypatch.setenv("UP_STRICT_QUALITY_GATES", "1")
    assert unsafe_junction_connector_snap_enabled(Settings()) is False


@pytest.mark.parametrize("thesis_attr, thesis_env", [(True, None), (False, "1")])
def test_thesis_strict_blocks_env_opt_in(monkeypatch, tmp_path, thesis_attr, thesis_env):
    stage_instance = _Stage(tmp_path)
    stage_instance.settings.THESIS_STRICT = thesis_attr
    monkeypatch.setenv("UP_ENABLE_JUNCTION_CONNECTOR_SNAP", "1")
    if thesis_env is None:
        monkeypatch.delenv("UP_THESIS_STRICT", raising=False)
    else:
        monkeypatch.setenv("UP_THESIS_STRICT", thesis_env)
    monkeypatch.setattr(stage, "load_xodr", lambda _path: pytest.fail("thesis strict must not load"), raising=False)
    assert stage._run_junction_connector_snap(stage_instance, "input.xodr")["status"] == "BLOCKED"


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
    assert result["qualification"] == "UNQUALIFIED_EXPERIMENTAL"
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
    result = stage._run_junction_connector_snap(stage_instance, "input.xodr")
    assert result["status"] == "BLOCKED"
    assert result["connectors_snapped"] == 0


def _lane_border_xodr(*, uturn: bool = False) -> str:
    exit_hdg = math.pi if uturn else 0.0
    connector_hdg = math.atan(1 / 2) if uturn else 0.0
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <road id="1" junction="-1" length="50"><link><successor elementType="junction" elementId="100"/></link><planView><geometry s="0" x="-50" y="0" hdg="0" length="50"><line/></geometry></planView><lanes><laneSection s="0"><center><lane id="0" type="none"/></center><right><lane id="-1" type="driving"><width sOffset="0" a="3.25" b="0" c="0" d="0"/></lane><lane id="-2" type="driving"><width sOffset="0" a="3.25" b="0" c="0" d="0"/></lane></right></laneSection></lanes></road>
  <road id="2" junction="100" length="10"><link><predecessor elementType="road" elementId="1" contactPoint="end"/><successor elementType="road" elementId="3" contactPoint="start"/></link><planView><geometry s="0" x="0" y="-3.25" hdg="{connector_hdg}" length="10"><line/></geometry></planView><lanes><laneSection s="0"><center><lane id="0" type="none"/></center><right><lane id="-1" type="driving"><width sOffset="0" a="3.25" b="0" c="0" d="0"/></lane></right></laneSection></lanes></road>
  <road id="3" junction="-1" length="50"><planView><geometry s="0" x="10" y="-3.25" hdg="{exit_hdg}" length="50"><line/></geometry></planView><lanes><laneSection s="0"><center><lane id="0" type="none"/></center><right><lane id="-1" type="driving"><width sOffset="0" a="3.25" b="0" c="0" d="0"/></lane></right></laneSection></lanes></road>
  <junction id="100"><connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start"><laneLink from="-2" to="-1"/></connection></junction>
</OpenDRIVE>'''


@pytest.mark.parametrize("uturn", [False, True], ids=["lane_border", "shared_reference_uturn"])
def test_default_disabled_preserves_real_lane_border_fixture(tmp_path, monkeypatch, uturn):
    stage_instance = _Stage(tmp_path)
    monkeypatch.delenv("UP_ENABLE_JUNCTION_CONNECTOR_SNAP", raising=False)
    path = tmp_path / "lane_border.xodr"
    original = _lane_border_xodr(uturn=uturn).encode("utf-8")
    path.write_bytes(original)
    report = stage._run_junction_connector_snap(stage_instance, str(path))
    assert report["status"] == "DISABLED"
    assert path.read_bytes() == original


def test_connector_snap_threshold_contract_unchanged():
    assert EXIT_HEADING_DISCONTINUITY_DEG == 30.0
    assert inspect.signature(snap_junction_connectors).parameters["max_gap_m"].default == 2.0
