import numpy as np

from carla_map_quality_toolkit.crs import roundtrip_max_error, transform_points


def test_wgs84_utm_roundtrip() -> None:
    points = np.array([[11.576124, 48.137154], [11.576900, 48.137154]])
    utm = transform_points(points, "EPSG:4326", "EPSG:32632")
    assert utm.shape == (2, 2)
    assert roundtrip_max_error(points, "EPSG:4326", "EPSG:32632") < 1e-8
