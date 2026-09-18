from __future__ import annotations

import json
from unittest.mock import patch


def test_sumo_repair_result_is_backward_compatible(tmp_path):
    """RepairResult must work as a plain string AND carry .meta."""
    from ultimate_pipeline.topology.sumo_repair import RepairResult

    r = RepairResult("/some/path.xodr", {"enabled": False})
    assert str(r) == "/some/path.xodr"
    assert r.meta["enabled"] is False
    path = r
    assert path == "/some/path.xodr"


def test_sumo_meta_schema(tmp_path):
    """When SUMO is disabled, meta must have enabled=false."""
    from ultimate_pipeline.topology.sumo_repair import SUMORepair

    src = tmp_path / "in.xodr"
    dst = tmp_path / "out.xodr"
    src.write_text("<OpenDRIVE/>", encoding="utf-8")

    with patch("ultimate_pipeline.topology.sumo_repair.SETTINGS") as settings_mock:
        settings_mock.ENABLE_SUMO_REPAIR = False
        result = SUMORepair.repair(str(src), str(dst))

    assert str(result) == str(dst)
    assert result.meta["enabled"] is False


def test_attach_full_report_sidecars_loads_sumo_meta_from_run_root(tmp_path):
    from ultimate_pipeline.run_full_domain_gap import _attach_full_report_sidecars

    run_root = tmp_path / "run_001"
    output_dir = run_root / "domain_gap"
    output_dir.mkdir(parents=True)
    (run_root / "sumo_repair.json").write_text(
        json.dumps({"enabled": True, "returncode": 0, "warnings": {"sharp_turns": 2}}),
        encoding="utf-8",
    )

    full_report = {}
    _attach_full_report_sidecars(
        output_dir=str(output_dir),
        full_report=full_report,
        generated_xodr=str(run_root / "08_final_mock.xodr"),
        run_root=str(run_root),
    )

    assert full_report["sumo_repair"]["enabled"] is True
    assert full_report["sumo_repair"]["warnings"]["sharp_turns"] == 2


def test_attach_full_report_sidecars_marks_prebuilt_xodr_when_meta_missing(tmp_path):
    from ultimate_pipeline.run_full_domain_gap import _attach_full_report_sidecars

    output_dir = tmp_path / "domain_gap"
    output_dir.mkdir(parents=True)

    full_report = {}
    _attach_full_report_sidecars(
        output_dir=str(output_dir),
        full_report=full_report,
        generated_xodr=str(tmp_path / "prebuilt_auto.xodr"),
    )

    assert full_report["sumo_repair"]["enabled"] == "unknown_prebuilt_xodr"
    assert "SUMO stage unknown" in full_report["sumo_repair"]["note"]
