"""Bounded persistence for the Stage-6 mesh-continuity diagnostic."""
from __future__ import annotations

import gzip
import hashlib
import json
import time
from pathlib import Path

import pytest

from ultimate_pipeline.diagnostics import continuity_heatmap, continuity_summary
from ultimate_pipeline.geometry.mesh_continuity_repairer import MeshContinuityRepairer
from ultimate_pipeline.pipeline_stages import stage_06_links
from ultimate_pipeline.tools import ost_run_protocol_adapter


def _large_scan(road_count: int = 1_000, local_count: int = 25) -> dict[str, object]:
    return {
        str(index): {
            "max_gap": float(index),
            "max_hdg": float(index) / 10.0,
            "max_len": float(index) / 100.0,
            "local": [
                {"gap": float(index), "hdg": 0.1, "len": 1.0}
                for _ in range(local_count)
            ],
        }
        for index in range(road_count)
    }


def test_continuity_summary_is_bounded_and_detail_preserves_every_item(tmp_path: Path) -> None:
    scan = _large_scan()

    summary = stage_06_links._bounded_continuity_scan_summary(scan)
    detail = stage_06_links._write_continuity_scan_detail(str(tmp_path), scan)

    summary_bytes = len(json.dumps(summary, sort_keys=True).encode("utf-8"))
    assert summary_bytes <= stage_06_links.STAGE6_CONTINUITY_SUMMARY_MAX_BYTES
    assert summary["road_count"] == len(scan)
    assert len(summary["worst_roads"]) == stage_06_links.STAGE6_CONTINUITY_TOP_N
    assert summary["omitted_road_count"] == len(scan) - stage_06_links.STAGE6_CONTINUITY_TOP_N

    detail_path = tmp_path / detail["path"]
    assert detail_path.is_file()
    assert hashlib.sha256(detail_path.read_bytes()).hexdigest() == detail["sha256"]
    with gzip.open(detail_path, "rt", encoding="utf-8") as fh:
        assert json.load(fh) == scan


def test_continuity_detail_is_deterministic_across_writes_more_than_a_second_apart(
    tmp_path: Path,
) -> None:
    scan = _large_scan(2, 1)
    first = stage_06_links._write_continuity_scan_detail(str(tmp_path), scan)
    time.sleep(1.1)
    second = stage_06_links._write_continuity_scan_detail(str(tmp_path), scan)

    assert first["sha256"] == second["sha256"]


def test_continuity_detail_write_failure_leaves_no_partial_final_or_temp(
    tmp_path: Path, monkeypatch
) -> None:
    def _fail_mid_write(*args, **kwargs):
        raise OSError("injected detail write failure")

    monkeypatch.setattr(stage_06_links.json, "dump", _fail_mid_write)

    with pytest.raises(OSError, match="injected detail write failure"):
        stage_06_links._write_continuity_scan_detail(str(tmp_path), _large_scan(2, 1))

    assert not (tmp_path / stage_06_links.STAGE6_CONTINUITY_DETAIL_FILENAME).exists()
    assert not list(tmp_path.glob("*.tmp"))


def _write_v2_runtime(run_dir: Path, scan: dict[str, object]) -> dict[str, object]:
    detail = stage_06_links._write_continuity_scan_detail(str(run_dir), scan)
    report = {
        "schema": "stage6_containment_runtime_v2",
        "mesh_continuity_scan": stage_06_links._bounded_continuity_scan_summary(scan),
        "mesh_continuity_detail": detail,
    }
    (run_dir / "stage6_containment_runtime.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    return report


def test_v2_runtime_is_consumed_by_real_summary_adapter_and_heatmap_reader(
    tmp_path: Path, monkeypatch
) -> None:
    scan = _large_scan(2, 1)
    report = _write_v2_runtime(tmp_path, scan)

    v2_summary = continuity_summary.run_summary(str(tmp_path))
    assert not (tmp_path / "continuity_debug.json").exists()

    detail_path = tmp_path / report["mesh_continuity_detail"]["path"]
    assert continuity_heatmap._load_severity_from_debug(str(detail_path))

    monkeypatch.setattr(
        "sys.argv", ["ost_run_protocol_adapter.py", "--run-dir", str(tmp_path), "--repo-root", str(tmp_path)]
    )
    assert ost_run_protocol_adapter.main() == 0
    health = json.loads((tmp_path / "pipeline_health_summary.json").read_text(encoding="utf-8"))
    assert health["gates"]["geometric_continuity"]["sources"] == [
        "stage6_containment_runtime.json + continuity_debug.json.gz"
    ]
    assert {"stage6_containment_runtime.json", "continuity_debug.json.gz"} <= set(
        health["sources"]["files"]
    )

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "continuity_debug.json").write_text(json.dumps(scan), encoding="utf-8")
    legacy_summary = continuity_summary.run_summary(str(legacy_dir))
    assert legacy_summary["continuity"] == v2_summary["continuity"]


def test_legacy_stage6_artifacts_use_the_same_bounded_detail_implementation(tmp_path: Path) -> None:
    report = stage_06_links._write_legacy_continuity_runtime_report(
        str(tmp_path), _large_scan(2, 1)
    )

    assert report["mesh_continuity_scan"]["road_count"] == 2
    assert (tmp_path / report["mesh_continuity_detail"]["path"]).is_file()
    assert not (tmp_path / "continuity_debug.json").exists()


def test_legacy_mesh_repair_path_can_skip_unbounded_debug_write(tmp_path: Path) -> None:
    source = tmp_path / "input.xodr"
    output = tmp_path / "output.xodr"
    source.write_text(
        "<OpenDRIVE><road id=\"1\" length=\"1\" junction=\"-1\">"
        "<planView><geometry s=\"0\" x=\"0\" y=\"0\" hdg=\"0\" length=\"1\">"
        "<line/></geometry></planView></road></OpenDRIVE>",
        encoding="utf-8",
    )

    MeshContinuityRepairer.run(str(source), str(output), write_debug=False)

    assert output.is_file()
    assert not (tmp_path / "continuity_debug.json").exists()
