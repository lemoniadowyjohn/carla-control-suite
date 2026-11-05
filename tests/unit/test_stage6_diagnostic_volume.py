"""Bounded persistence for the Stage-6 mesh-continuity diagnostic."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from ultimate_pipeline.pipeline_stages import stage_06_links


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


def test_continuity_detail_is_written_once(tmp_path: Path, monkeypatch) -> None:
    scan = _large_scan(2, 1)
    writes: list[Path] = []
    real_open = gzip.open

    def _counting_open(path, *args, **kwargs):
        writes.append(Path(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(stage_06_links.gzip, "open", _counting_open)
    detail = stage_06_links._write_continuity_scan_detail(str(tmp_path), scan)

    assert writes == [tmp_path / detail["path"]]


def test_v2_report_keeps_the_v1_mesh_scan_field_readable() -> None:
    summary = stage_06_links._bounded_continuity_scan_summary(_large_scan(1, 1))
    report = {"schema": "stage6_containment_runtime_v2", "mesh_continuity_scan": summary}

    # A v1 consumer that only reads this field still receives a mapping.
    assert report["mesh_continuity_scan"]["road_count"] == 1
