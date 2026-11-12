"""Stage B4 acceptance tests: camera tabs wired to the native sensor service.

T-CAM-01..08: authority-gated attach, tile routing with honest source
labels, non-image payload handling, detach lifecycle, inventory truthfulness
(NOT_IMPLEMENTED radar/gnss/imu), recording honesty, diagnostics counters,
and external-producer regression.
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QImage

from ultimate_pipeline.gui.adapters.mock_backend import MockCarlaBackend
from ultimate_pipeline.gui.control_center.sensor_feeds import (
    CAMERA_TILE_MAP, RENDERABLE_CAMERA_TYPES, SensorFeedBridge)
from ultimate_pipeline.gui.health import SessionAuthority
from ultimate_pipeline.gui.sensors.queues import Frame
from ultimate_pipeline.gui.services.sensors import SensorService


@pytest.fixture
def app():
    from ultimate_pipeline.gui.shell.main_window import create_application
    return create_application([])


def _image() -> QImage:
    image = QImage(2, 2, QImage.Format.Format_RGB888)
    image.fill(0)
    return image


def _panel(**kwargs):
    from ultimate_pipeline.gui.control_center.feeds import FeedsPanel
    return FeedsPanel(**kwargs)


def _service() -> SensorService:
    return SensorService(MockCarlaBackend())


def _exclusive_panel():
    return _panel(sensors=_service(),
                  authority_provider=lambda: SessionAuthority.EXCLUSIVE_WORLD)


# ============================================================ T-CAM-01
def test_T_CAM_01_attach_refused_under_shared_readonly(app):
    panel = _panel(sensors=_service(),
                   authority_provider=lambda: SessionAuthority.SHARED_READONLY)
    result = panel.sensor_bridge.attach_camera("rgb_camera")
    assert result.ok is False
    assert result.error_class == "AuthorityRequired"
    assert "ATTACH REFUSED" in panel.state.text()
    assert panel.sensor_bridge.sensors.sensor_ids() == ()
    assert panel.sensor_bridge.polling is False


def test_T_CAM_01_without_authority_provider_fails_closed(app):
    panel = _panel(sensors=_service())
    result = panel.sensor_bridge.attach_camera("rgb_camera")
    assert result.ok is False
    assert "ATTACH REFUSED" in panel.state.text()


# ============================================================ T-CAM-02
def test_T_CAM_02_attach_routes_frames_to_the_mapped_tile(app):
    panel = _exclusive_panel()
    result = panel.sensor_bridge.attach_camera("rgb_camera")
    assert result.ok, result.reason
    attachment = result.unwrap()
    sensor_id = attachment.sensor_id
    assert panel.sensor_bridge.tile_for(sensor_id) == "Front RGB"
    assert panel.sensor_bridge.polling is True
    assert attachment.source_class == "MOCK_BACKEND"
    assert "ATTACHED rgb_camera" in panel.state.text()
    assert "not LIVE_VERIFIED" in panel.state.text()

    frame = Frame(frame_id=7, timestamp=1.25, payload=_image(),
                  sensor_id=sensor_id)
    assert panel.sensor_bridge.sensors.deliver(sensor_id, frame).ok
    assert panel.sensor_bridge.poll_once() == 1

    tile = panel.tiles["Front RGB"]
    assert "ADAPTER MOCK_BACKEND" in tile.header.text()
    assert "Frame ID 7" in tile.caption.text()
    assert "1.250" in tile.caption.text()
    assert "ADAPTER FRAMES" in panel.state.text()

    other = panel.tiles["Depth"]
    assert "UNBOUND" in other.header.text()


def test_T_CAM_02_tile_map_covers_the_renderable_cameras_only():
    assert CAMERA_TILE_MAP == {
        "rgb_camera": "Front RGB",
        "depth_camera": "Depth",
        "semantic_segmentation": "Semantic",
    }
    assert RENDERABLE_CAMERA_TYPES == tuple(CAMERA_TILE_MAP)
    assert "instance_segmentation" not in CAMERA_TILE_MAP


def test_T_CAM_02_non_camera_type_refused_by_bridge(app):
    panel = _exclusive_panel()
    result = panel.sensor_bridge.attach_camera("lidar")
    assert result.ok is False
    assert result.error_class == "KeyError"


# ============================================================ T-CAM-03
def test_T_CAM_03_non_image_payloads_are_counted_never_rendered(app):
    panel = _exclusive_panel()
    sensor_id = panel.sensor_bridge.attach_camera("depth_camera").unwrap().sensor_id
    sensors = panel.sensor_bridge.sensors
    sensors.deliver(sensor_id, Frame(frame_id=1, timestamp=0.5, payload=b"raw",
                                     sensor_id=sensor_id))
    sensors.deliver(sensor_id, Frame(frame_id=2, timestamp=0.6, payload=_image(),
                                     sensor_id=sensor_id))
    assert panel.sensor_bridge.poll_once() == 1
    assert "non-image payloads skipped (never rendered): 1" in (
        panel.sensor_bridge.diagnostics_text())
    tile = panel.tiles["Depth"]
    assert "Frame ID 2" in tile.caption.text()


# ============================================================ T-CAM-04
def test_T_CAM_04_detach_closes_channel_and_stops_polling(app):
    panel = _exclusive_panel()
    sensor_id = panel.sensor_bridge.attach_camera("rgb_camera").unwrap().sensor_id
    result = panel.sensor_bridge.detach(sensor_id)
    assert result.ok, result.reason
    assert "DETACHED" in panel.state.text()
    assert panel.sensor_bridge.tile_for(sensor_id) is None
    assert panel.sensor_bridge.sensors.channel(sensor_id) is None
    assert panel.sensor_bridge.polling is False
    assert panel.sensor_bridge.sensors.sensor_ids() == ()


def test_T_CAM_04_detach_refused_under_readonly_keeps_channel(app):
    service = _service()
    panel = _panel(sensors=service,
                   authority_provider=lambda: SessionAuthority.EXCLUSIVE_WORLD)
    sensor_id = panel.sensor_bridge.attach_camera("rgb_camera").unwrap().sensor_id
    panel.sensor_bridge._authority_provider = (
        lambda: SessionAuthority.SHARED_READONLY)
    result = panel.sensor_bridge.detach(sensor_id)
    assert result.ok is False
    assert result.error_class == "AuthorityRequired"
    assert "DETACH REFUSED" in panel.state.text()
    assert service.channel(sensor_id) is not None
    assert panel.sensor_bridge.polling is True
    # a refused detach must not orphan the tile: still mapped, still visible
    assert panel.sensor_bridge.tile_for(sensor_id) == "Front RGB"
    assert panel.sensor_bridge.source_label(sensor_id) == "ADAPTER MOCK_BACKEND"


# ============================================================ T-CAM-05
def test_T_CAM_05_inventory_lists_native_and_not_implemented_rows(app):
    panel = _exclusive_panel()
    panel.sensor_bridge.attach_camera("rgb_camera")
    panel.refresh_inventory()
    texts = []
    for row in range(panel.inventory_table.rowCount()):
        texts.append(tuple(
            panel.inventory_table.item(row, col).text()
            for col in range(3)))
    names = [name for name, _, _ in texts]
    for native in ("rgb_camera", "depth_camera", "semantic_segmentation",
                   "instance_segmentation", "lidar"):
        assert native in names, native
    for absent in ("radar", "gnss", "imu"):
        assert absent in names, absent
        row = texts[names.index(absent)]
        assert row[2].startswith("NOT_IMPLEMENTED")
        assert "no truthful adapter" in row[2]
    attached = [t for t in texts if t[0].startswith("attached:")]
    assert len(attached) == 1
    assert "MOCK_BACKEND" in attached[0][2]
    assert "ATTACHED rgb_camera" in panel.state.text()


# ============================================================ T-CAM-06
def test_T_CAM_06_recording_tab_declares_not_implemented(app):
    panel = _panel()
    index = next(i for i in range(panel.tabs.count())
                 if panel.tabs.tabText(i) == "Recording")
    panel.tabs.setCurrentIndex(index)
    texts = [label.text() for label in panel.tabs.widget(index).findChildren(object)
             if hasattr(label, "text")]
    assert any("NOT_IMPLEMENTED" in text for text in texts)
    assert any("never simulated" in text for text in texts)


# ============================================================ T-CAM-07
def test_T_CAM_07_diagnostics_show_real_queue_counters(app):
    panel = _exclusive_panel()
    sensor_id = panel.sensor_bridge.attach_camera("semantic_segmentation").unwrap().sensor_id
    sensors = panel.sensor_bridge.sensors
    for frame_id in range(1, 4):
        sensors.deliver(sensor_id, Frame(frame_id=frame_id, timestamp=float(frame_id),
                                         payload=_image(), sensor_id=sensor_id))
    panel.sensor_bridge.poll_once()
    panel.refresh_diagnostics()
    text = panel.diag_report.toPlainText()
    assert sensor_id in text
    assert "enqueued=3" in text
    assert "monotonic=True" in text
    assert "gaps=0" in text
    assert "Frame Age:" in panel.frame_age_label.text()
    assert "N/A" not in panel.frame_age_label.text()


# ============================================================ T-CAM-08
def test_T_CAM_08_external_producers_keep_their_label(app):
    panel = _panel()
    panel.on_frame("Front RGB", _image(), 42, 1.5)
    tile = panel.tiles["Front RGB"]
    assert "EXTERNAL FRAME PRODUCER" in tile.header.text()
    assert "Frame ID 42" in tile.caption.text()
    assert "EXTERNAL FRAMES RECEIVED" in panel.state.text()


def test_T_CAM_08_panel_without_sensors_builds_unavailable_inventory(app):
    panel = _panel()
    assert panel.sensor_bridge is None
    assert panel.inventory_table.item(0, 0).text() == "sensor service"
    assert "UNAVAILABLE" in panel.inventory_table.item(0, 2).text()
    panel.attach_native_camera()
    assert "NO SENSOR SERVICE" in panel.state.text()


def test_T_CAM_08_close_stops_bridge_polling(app):
    panel = _exclusive_panel()
    panel.sensor_bridge.attach_camera("rgb_camera")
    assert panel.sensor_bridge.polling is True
    panel.close()
    assert panel.sensor_bridge.polling is False


def test_T_CAM_08_workspace_route_08_provides_the_sensor_service(app):
    from ultimate_pipeline.gui.control_center.feeds import FeedsPanel
    from ultimate_pipeline.gui.control_center.workspaces import (
        create_operator_workspace)
    from ultimate_pipeline.gui.shell.services import build_registry

    registry = build_registry()
    workspace = create_operator_workspace(
        "08_sensors_streams", registry, lambda *_: None)
    panels = workspace.findChildren(FeedsPanel)
    assert panels, "route 08 must contain a FeedsPanel"
    assert panels[0].sensor_bridge is not None
    assert panels[0].sensor_bridge.sensors is registry.resolve("sensors")
    # No authority_provider: the badge is display state, never a grant, so
    # the workspace-wired panel fails closed until a claim flow exists.
    assert panels[0].sensor_bridge._authority_provider is None


# ============================================================ T-CAM-09
def test_T_CAM_09_world_change_invalidates_native_attachments(app):
    from ultimate_pipeline.gui.session.runtime_session import WorldChangedEvent

    panel = _exclusive_panel()
    sensor_id = panel.sensor_bridge.attach_camera("rgb_camera").unwrap().sensor_id
    assert panel.sensor_bridge.tile_for(sensor_id) == "Front RGB"
    assert panel.sensor_bridge.polling is True

    panel._on_runtime_world_changed(WorldChangedEvent(
        generation=1, reason="MAP_LOAD", map_identity="map-b",
        source="test", world_bound=True, client_bound=False))

    assert panel.sensor_bridge.sensors.sensor_ids() == ()
    assert panel.sensor_bridge.sensors.channel(sensor_id) is None
    assert panel.sensor_bridge.tile_for(sensor_id) is None
    assert panel.sensor_bridge.polling is False
    assert "WORLD CHANGED" in panel.state.text()
    assert "native sensors invalidated" in panel.state.text()

    # a stale (same or older) generation must never re-invalidate
    panel.sensor_bridge.attach_camera("rgb_camera")
    panel._on_runtime_world_changed(WorldChangedEvent(
        generation=1, reason="MAP_LOAD", map_identity="map-b",
        source="test", world_bound=True, client_bound=False))
    assert panel.sensor_bridge.sensors.sensor_ids() != ()


# =========================================================== T-CAM-10
def test_T_CAM_10_shutdown_detaches_everything_and_refreshes_inventory(app):
    panel = _exclusive_panel()
    sensor_id = panel.sensor_bridge.attach_camera("rgb_camera").unwrap().sensor_id
    assert panel.sensor_bridge.polling is True

    panel.shutdown()

    assert panel.sensor_bridge.sensors.sensor_ids() == ()
    assert panel.sensor_bridge.polling is False
    assert panel.sensor_bridge.tile_for(sensor_id) is None
    names = [panel.inventory_table.item(row, 0).text()
             for row in range(panel.inventory_table.rowCount())]
    assert not any(name.startswith("attached:") for name in names), names
    assert panel.sensor_bridge.sensors.channel(sensor_id) is None


# =========================================================== T-CAM-11
def test_T_CAM_11_detach_recent_follows_attachment_order(app):
    panel = _exclusive_panel()
    first = panel.sensor_bridge.attach_camera("rgb_camera").unwrap().sensor_id
    second = panel.sensor_bridge.attach_camera("depth_camera").unwrap().sensor_id

    panel.detach_native_camera()  # most recent first, not lexicographic
    assert second not in panel.sensor_bridge.sensors.sensor_ids()
    assert first in panel.sensor_bridge.sensors.sensor_ids()
    assert panel.sensor_bridge.tile_for(first) == "Front RGB"
    assert panel.sensor_bridge.tile_for(second) is None

    panel.detach_native_camera()
    assert panel.sensor_bridge.sensors.sensor_ids() == ()

    panel.detach_native_camera()  # nothing left: honest refusal
    assert "DETACH REFUSED" in panel.state.text()
    assert "no attached native camera" in panel.state.text()


# =========================================================== T-CAM-12
def test_T_CAM_12_zombie_channel_marked_in_operator_surfaces(app):
    from ultimate_pipeline.gui.results import Result

    panel = _exclusive_panel()
    sensor_id = panel.sensor_bridge.attach_camera("rgb_camera").unwrap().sensor_id

    # force a backend detach failure: the attachment must stay registered
    # as a retryable zombie, never vanish and never read as healthy
    panel.sensor_bridge.sensors._backend.detach_sensor = (
        lambda sid: Result.failure("backend refused detach",
                                   error_class="RuntimeError",
                                   error_source="test"))
    result = panel.sensor_bridge.detach(sensor_id)
    assert result.ok is False
    assert sensor_id in panel.sensor_bridge.sensors.sensor_ids()
    assert panel.sensor_bridge.tile_for(sensor_id) == "Front RGB"
    assert panel.sensor_bridge.polling is True

    panel.refresh_inventory()
    rows = [tuple(panel.inventory_table.item(row, col).text()
                  for col in range(3))
            for row in range(panel.inventory_table.rowCount())]
    attached = [r for r in rows if r[0].startswith("attached:")]
    assert attached and "CHANNEL CLOSED" in attached[0][2], rows

    panel.refresh_diagnostics()
    text = panel.diag_report.toPlainText()
    assert "closed=True" in text
    assert "zombie" in text
