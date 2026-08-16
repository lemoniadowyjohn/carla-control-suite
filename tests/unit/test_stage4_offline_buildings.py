from __future__ import annotations

from types import SimpleNamespace

import pytest

from ultimate_pipeline.pipeline_stages.stage_04_enrichment import (
    enforce_buildings_fail_closed,
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


def test_stage4_offline_mode_falls_back_to_pinned_campaign_source(tmp_path):
    """
    CODEX C7: when the configured buildings.geojson is missing/absent and we
    are offline, fall back to the tracked, pinned campaign building source
    (campaigns/.../source/ingolstadt_buildings_overpass.json) instead of
    giving up immediately -- this is what makes an offline rebuild land a
    realistic building count instead of silently landing at 0/1.
    """
    missing = tmp_path / "missing" / "buildings.geojson"
    pinned = tmp_path / "pinned_buildings.json"
    pinned.write_text(
        '{"elements":[{"type":"way","id":1,"tags":{"building":"yes"},'
        '"geometry":[{"lat":48.75,"lon":11.43},{"lat":48.75001,"lon":11.43},'
        '{"lat":48.75001,"lon":11.43001}]}]}',
        encoding="utf-8",
    )
    settings = SimpleNamespace(
        OFFLINE_ONLY=True,
        PINNED_BUILDINGS_SOURCE=str(pinned),
    )

    got = resolve_buildings_geojson_for_stage4(
        settings=settings,
        gps_bounds={},
        buildings_path=str(missing),
        downloader_factory=_ExplodingDownloader,
    )

    assert got == str(pinned)


def test_stage4_offline_mode_pinned_fallback_absent_returns_none(tmp_path):
    missing = tmp_path / "missing" / "buildings.geojson"
    settings = SimpleNamespace(
        OFFLINE_ONLY=True,
        PINNED_BUILDINGS_SOURCE=str(tmp_path / "also_missing.json"),
    )

    got = resolve_buildings_geojson_for_stage4(
        settings=settings,
        gps_bounds={},
        buildings_path=str(missing),
        downloader_factory=_ExplodingDownloader,
    )

    assert got is None


def test_enforce_buildings_fail_closed_raises_on_zero_buildings():
    with pytest.raises(RuntimeError, match="[Bb]uilding"):
        enforce_buildings_fail_closed(inserted_count=0, buildings_source=None)


def test_enforce_buildings_fail_closed_passes_with_buildings():
    # Should not raise.
    enforce_buildings_fail_closed(inserted_count=5693, buildings_source="osm")


def test_enforce_buildings_fail_closed_env_override_allows_empty(monkeypatch):
    monkeypatch.setenv("UP_ALLOW_EMPTY_BUILDINGS", "1")
    # Should not raise when the escape hatch is explicitly set.
    enforce_buildings_fail_closed(inserted_count=0, buildings_source=None)
