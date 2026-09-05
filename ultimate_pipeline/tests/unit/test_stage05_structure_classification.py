# Round-6: stage_05_geometry.py's _resolve_structure_road_ids wires F3
# structure classification (bridge/tunnel/elevated/underpass) into the live
# DEM-elevation step. This is net-new in the pipeline -- a classification
# failure must degrade to (None, ...) [byte-identical to pre-fix apply_dem
# behavior] rather than newly blocking a regen that previously succeeded,
# unless THESIS_STRICT is set.
from __future__ import annotations

import pytest

from ultimate_pipeline.pipeline_stages import stage_05_geometry as stage


class TestResolveStructureRoadIdsGracefulDegradation:
    def test_missing_osm_file_degrades_gracefully_when_not_strict(self, tmp_path):
        xodr_path = str(tmp_path / "does_not_matter.xodr")
        road_ids, report = stage._resolve_structure_road_ids(
            xodr_path, str(tmp_path / "nonexistent.osm"), thesis_strict=False
        )
        assert road_ids is None
        assert report["status"] == "failed"
        assert "reason" in report

    def test_missing_osm_file_raises_when_thesis_strict(self, tmp_path):
        xodr_path = str(tmp_path / "does_not_matter.xodr")
        with pytest.raises(RuntimeError, match="THESIS_STRICT"):
            stage._resolve_structure_road_ids(
                xodr_path, str(tmp_path / "nonexistent.osm"), thesis_strict=True
            )

    def test_classification_exception_degrades_gracefully_when_not_strict(
        self, tmp_path, monkeypatch
    ):
        osm_path = tmp_path / "real.osm"
        osm_path.write_text('<osm version="0.6"></osm>', encoding="utf-8")

        def _boom(*args, **kwargs):
            raise RuntimeError("synthetic classification failure")

        monkeypatch.setattr(
            "ultimate_pipeline.enrichment.structure_classifier.classify_xodr_roads", _boom
        )
        road_ids, report = stage._resolve_structure_road_ids(
            str(tmp_path / "whatever.xodr"), str(osm_path), thesis_strict=False
        )
        assert road_ids is None
        assert report["status"] == "failed"
        assert "synthetic classification failure" in report["reason"]

    def test_classification_exception_raises_when_thesis_strict(self, tmp_path, monkeypatch):
        osm_path = tmp_path / "real.osm"
        osm_path.write_text('<osm version="0.6"></osm>', encoding="utf-8")

        def _boom(*args, **kwargs):
            raise RuntimeError("synthetic classification failure")

        monkeypatch.setattr(
            "ultimate_pipeline.enrichment.structure_classifier.classify_xodr_roads", _boom
        )
        with pytest.raises(RuntimeError, match="THESIS_STRICT"):
            stage._resolve_structure_road_ids(
                str(tmp_path / "whatever.xodr"), str(osm_path), thesis_strict=True
            )
