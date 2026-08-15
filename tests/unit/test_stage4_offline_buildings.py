from __future__ import annotations

from types import SimpleNamespace

from ultimate_pipeline.pipeline_stages.stage_04_enrichment import (
    resolve_buildings_geojson_for_stage4,
)


class _ExplodingDownloader:
    def ensure_osm_geojson_exists(self, gps_bounds, geojson_path):
        raise AssertionError("offline mode must not call downloader")


class _RecordingDownloader:
    def __init__(self):
        self.calls = []

    def ensure_osm_geojson_exists(self, gps_bounds, geojson_path):
        self.calls.append((gps_bounds, geojson_path))
        return str(geojson_path)


def test_stage4_offline_mode_skips_missing_building_geojson_download(tmp_path, monkeypatch):
    missing = tmp_path / "missing" / "buildings.geojson"
    settings = SimpleNamespace(OFFLINE_ONLY=True)

    got = resolve_buildings_geojson_for_stage4(
        settings=settings,
        gps_bounds={"lat_min": 1.0, "lat_max": 2.0, "lon_min": 3.0, "lon_max": 4.0},
        buildings_path=str(missing),
        downloader_factory=_ExplodingDownloader,
    )

    assert got is None
    assert not missing.exists()


def test_stage4_env_offline_mode_skips_missing_building_geojson_download(tmp_path, monkeypatch):
    monkeypatch.setenv("UP_OFFLINE_ONLY", "1")
    missing = tmp_path / "missing" / "buildings.geojson"
    settings = SimpleNamespace(OFFLINE_ONLY=False)

    got = resolve_buildings_geojson_for_stage4(
        settings=settings,
        gps_bounds={},
        buildings_path=str(missing),
        downloader_factory=_ExplodingDownloader,
    )

    assert got is None
    assert not missing.exists()


def test_stage4_online_missing_building_geojson_uses_downloader(tmp_path):
    missing = tmp_path / "missing" / "buildings.geojson"
    settings = SimpleNamespace(OFFLINE_ONLY=False)
    downloader = _RecordingDownloader()

    got = resolve_buildings_geojson_for_stage4(
        settings=settings,
        gps_bounds={"lat_min": 1.0},
        buildings_path=str(missing),
        downloader_factory=lambda: downloader,
    )

    assert got == str(missing)
    assert downloader.calls == [({"lat_min": 1.0}, str(missing))]


def test_stage4_existing_building_geojson_is_used_in_offline_mode(tmp_path):
    existing = tmp_path / "buildings.geojson"
    existing.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    settings = SimpleNamespace(OFFLINE_ONLY=True)

    got = resolve_buildings_geojson_for_stage4(
        settings=settings,
        gps_bounds={},
        buildings_path=str(existing),
        downloader_factory=_ExplodingDownloader,
    )

    assert got == str(existing)
