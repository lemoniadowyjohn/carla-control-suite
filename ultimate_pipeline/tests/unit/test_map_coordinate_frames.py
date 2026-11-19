from __future__ import annotations

import hashlib
import math

import pytest
from pyproj import Transformer

from ultimate_pipeline.carla_tools.map_coordinate_frames import (
    AUTO_NATIVE_PROJ4,
    AUTO_TRANSFORM_ID,
    MANUAL_CRS_AUTHORITY,
    MANUAL_TRANSFORM_ID,
    MapCoordinateError,
    load_map_coordinate_frame,
)


AUTO_OFFSET = (832671.676, 5458671.104)
AUTO_SOURCE_SHA = "b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f"


def _fixture(tmp_path, *, auto: bool, crs_authority: str | None = None, offset=None):
    if auto:
        offset = AUTO_OFFSET if offset is None else offset
        payload = (
            '<OpenDRIVE><header><geoReference>+proj=tmerc</geoReference>'
            f'<offset x="{offset[0]}" y="{offset[1]}"/></header></OpenDRIVE>'
        ).encode()
        key = "auto_map_of_record"
        entry = {
            "frame_id": "ingolstadt_local_rebased",
            "frame_kind": "rebased_local",
            "crs_authority": crs_authority or f"OSM2ODR native tmerc: {AUTO_NATIVE_PROJ4}",
            "rebase_dx": offset[0],
            "rebase_dy": offset[1],
            "frame_source_sha256": AUTO_SOURCE_SHA,
            "frame_transform_id": AUTO_TRANSFORM_ID,
        }
    else:
        payload = b"<OpenDRIVE><header/></OpenDRIVE>"
        key = "manual_grid0828"
        entry = {
            "frame_id": "UTM-32N",
            "frame_kind": "projected_crs",
            "crs_authority": crs_authority or MANUAL_CRS_AUTHORITY,
            "frame_transform_id": MANUAL_TRANSFORM_ID,
        }
    rel = "maps/fixture.xodr"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    entry.update(
        path=rel,
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        role="auto" if auto else "manual",
        frame="fixture frame",
        aliases=[key],
    )
    return key, {key: entry}


@pytest.mark.parametrize(
    "name,xy,tolerance",
    [
        ("auto_map_of_record", (9083.809803843033, 7422.26424662862), 1e-5),
        ("manual_grid0828", (680672.0126395663, 5403162.549654662), 1e-7),
    ],
)
def test_pinned_map_projection_matches_independent_ingolstadt_anchor(tmp_path, name, xy, tolerance):
    key, registry = _fixture(tmp_path, auto=name == "auto_map_of_record")
    frame = load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)
    # OSM node 5572889514: lon=11.4582121, lat=48.7552397.
    projected = frame.wgs84_to_map(
        11.4582121, 48.7552397, source_id="node/5572889514"
    )
    assert projected["map_xy"]["x"] == pytest.approx(xy[0], abs=tolerance)
    assert projected["map_xy"]["y"] == pytest.approx(xy[1], abs=tolerance)
    assert projected["map_sha256"] == registry[key]["sha256"]
    assert projected["registry_sha256"] == frame.registry_sha256
    assert projected["waypoint_source_id"] == "node/5572889514"
    assert projected["source_data_sha256"] == (AUTO_SOURCE_SHA if frame.registry_key == "auto_map_of_record" else None)
    lon, lat = frame.map_to_wgs84(*xy)
    assert (lon, lat) == pytest.approx((11.4582121, 48.7552397), abs=1e-10)


def test_auto_frame_uses_offset_before_native_inverse_and_not_utm(tmp_path):
    point = (11.4582121, 48.7552397)
    key, registry = _fixture(tmp_path, auto=True)
    frame = load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)
    xy = frame.wgs84_to_map(*point, source_id="node/5572889514")["map_xy"]
    # Applying UTM directly to auto-local coordinates is a grossly different frame.
    assert math.hypot(xy["x"] + AUTO_OFFSET[0] - 680672.0126395663,
                      xy["y"] + AUTO_OFFSET[1] - 5403162.549654662) > 100_000


def test_wrong_utm_zone_and_y_reflection_are_negative_controls(tmp_path):
    key, registry = _fixture(tmp_path, auto=False)
    frame = load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)
    lon, lat = 11.4582121, 48.7552397
    correct = frame.wgs84_to_map(lon, lat, source_id="node/5572889514")["map_xy"]
    wrong_x, wrong_y = Transformer.from_crs(
        "EPSG:4326", "EPSG:32631", always_xy=True
    ).transform(lon, lat)
    assert math.hypot(wrong_x - correct["x"], wrong_y - correct["y"]) > 100_000
    with pytest.raises(MapCoordinateError):
        frame.map_to_wgs84(correct["x"], -correct["y"])


def test_missing_automatic_georeference_is_rejected(tmp_path):
    key, registry = _fixture(tmp_path, auto=True)
    path = tmp_path / registry[key]["path"]
    payload = (
        f'<OpenDRIVE><header><offset x="{AUTO_OFFSET[0]}" '
        f'y="{AUTO_OFFSET[1]}"/></header></OpenDRIVE>'
    ).encode()
    path.write_bytes(payload)
    registry[key]["sha256"] = hashlib.sha256(payload).hexdigest()
    registry[key]["bytes"] = len(payload)
    with pytest.raises(MapCoordinateError, match="no native geoReference"):
        load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)


def test_wrong_authority_and_wrong_header_offset_fail_closed(tmp_path):
    key, registry = _fixture(tmp_path, auto=True, crs_authority=MANUAL_CRS_AUTHORITY)
    with pytest.raises(MapCoordinateError, match="provenance"):
        load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)
    key, registry = _fixture(tmp_path, auto=True, offset=(0.0, 0.0))
    registry[key]["rebase_dx"], registry[key]["rebase_dy"] = AUTO_OFFSET
    with pytest.raises(MapCoordinateError, match="header offset"):
        load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)


@pytest.mark.parametrize(
    "lon,lat",
    [(48.755, 11.458), (680672.0, 5403162.0), (float("nan"), 48.75)],
)
def test_axis_swap_nonfinite_and_degrees_meters_mixups_are_rejected(tmp_path, lon, lat):
    key, registry = _fixture(tmp_path, auto=True)
    frame = load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)
    with pytest.raises(MapCoordinateError):
        frame.wgs84_to_map(lon, lat, source_id="negative-control")


def test_missing_waypoint_source_id_and_source_hash_mismatch_are_rejected(tmp_path):
    key, registry = _fixture(tmp_path, auto=True)
    frame = load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)
    with pytest.raises(MapCoordinateError, match="source_id"):
        frame.wgs84_to_map(11.4582121, 48.7552397, source_id=" ")
    registry[key]["frame_source_sha256"] = "c" * 64
    with pytest.raises(MapCoordinateError, match="provenance"):
        load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)


def test_forged_digest_and_unknown_alignment_frame_are_rejected(tmp_path):
    key, registry = _fixture(tmp_path, auto=True)
    registry[key]["sha256"] = "0" * 64
    with pytest.raises(MapCoordinateError, match="verification failed"):
        load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)
    registry[key]["sha256"] = hashlib.sha256(
        (tmp_path / registry[key]["path"]).read_bytes()
    ).hexdigest()
    registry[key]["frame_transform_id"] = "rigid-se2-shape-alignment-v1"
    with pytest.raises(MapCoordinateError, match="provenance"):
        load_map_coordinate_frame(key, base_dir=tmp_path, registry=registry)
