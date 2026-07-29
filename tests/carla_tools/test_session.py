import pytest

from ultimate_pipeline.carla_tools.data_manager import DataManager
from ultimate_pipeline.carla_tools.sensor_registry import (
    SensorRegistry,
    SensorSpec,
)
from ultimate_pipeline.carla_tools.session import CarlaSession


def test_session_connect_no_server() -> None:
    with pytest.raises(Exception):
        CarlaSession.connect(host="localhost", port=29999, timeout=1.0)


def test_session_context_manager() -> None:
    session = CarlaSession(host="localhost", port=2000, timeout=5.0)
    assert session.host == "localhost"
    assert session.port == 2000
    assert session.timeout == 5.0
    assert session.client is None
    assert session.world is None


def test_sensor_registry_empty() -> None:
    reg = SensorRegistry()
    assert reg.sensors == {}
    assert reg.to_dict() == {}


def test_sensor_registry_remove_nonexistent() -> None:
    reg = SensorRegistry()
    reg.remove("nonexistent")
    assert reg.sensors == {}


def test_data_manager_basic(tmp_path) -> None:
    dm = DataManager(tmp_path)
    dm.store("key1", "value1")
    assert dm.retrieve("key1") == "value1"
    assert dm.retrieve("nonexistent") is None


def test_data_manager_record(tmp_path) -> None:
    dm = DataManager(tmp_path)
    dm.record(1, "cam", "image_data")
    dm.record(2, "lidar", "point_cloud")
    assert dm.capture_count == 2


def test_data_manager_save(tmp_path) -> None:
    dm = DataManager(tmp_path)
    dm.store("test", 42)
    dm.record(0, "sensor1", b"data")
    data_path = dm.save_data("test_data.json")
    log_path = dm.save_capture_log("test_capture.json")
    assert data_path.exists()
    assert log_path.exists()


def test_data_manager_clear(tmp_path) -> None:
    dm = DataManager(tmp_path)
    dm.store("x", 1)
    dm.record(0, "s1", b"d")
    dm.clear()
    assert dm.capture_count == 0
    assert dm.retrieve("x") is None


def test_sensor_spec_to_dict() -> None:
    spec = SensorSpec(blueprint="sensor.camera.rgb", attributes={"image_size_x": "800"})
    d = spec.to_dict()
    assert d["blueprint"] == "sensor.camera.rgb"
    assert d["attributes"]["image_size_x"] == "800"


def test_capture_config_defaults() -> None:
    from ultimate_pipeline.carla_tools.capture import CaptureConfig
    config = CaptureConfig()
    assert config.frames == 10
    assert config.tick_delta == 1.0 / 60.0
    assert config.sensors == {}
