from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any, Dict, Optional, Tuple


log = logging.getLogger(__name__)


@dataclass
class RecorderConfig:
    """
    Minimal config object used by record_route and unit tests.

    Test contract:
    - must have low_mem_resolution attribute
    - default must be None
    """

    fps: int = 20
    synchronous: bool = True
    fixed_delta_seconds: Optional[float] = None
    sensor_timeout_s: float = 2.0

    # formats / flags (kept for backward compatibility with existing code)
    lidar_format: str = "npz"
    image_format: str = "png"
    segmentation_mode: str = "cityscapes"
    flip_vehicle_y: bool = True
    opencv_camera_axes: bool = True
    write_sensor_transforms: bool = True
    write_world_snapshot: bool = True

    # low-mem mode override
    low_mem_resolution: Optional[Tuple[int, int]] = None


class SensorRecorder:
    """
    Callback-based recorder for camera and LiDAR sensors.

    Supports two call styles:
      1) Legacy positional: SensorRecorder(world, ego, sensors, out_dir, cfg)
      2) Deferred attach:   SensorRecorder(output_dir=..., config=...) then attach(...)
    """

    def __init__(
        self,
        world: Any = None,
        ego_vehicle: Any = None,
        sensors: Any = None,
        out_dir: Optional[str] = None,
        cfg: Optional[RecorderConfig] = None,
        *,
        output_dir: Optional[str] = None,
        config: Optional[RecorderConfig] = None,
    ) -> None:
        # Legacy compatibility: SensorRecorder(world, logs_dir)
        if (
            output_dir is None
            and out_dir is None
            and isinstance(ego_vehicle, (str, os.PathLike))
            and sensors is None
            and cfg is None
            and config is None
        ):
            out_dir = str(ego_vehicle)
            ego_vehicle = None

        self.world = world
        self.ego_vehicle = ego_vehicle
        self.sensors: Dict[str, Any] = self._normalize_sensors(sensors)

        resolved_out_dir = output_dir if output_dir is not None else out_dir
        if resolved_out_dir is None:
            resolved_out_dir = str(Path.cwd() / "recording")
        self.out_dir = Path(str(resolved_out_dir)).expanduser()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = str(self.out_dir)

        self.cfg = (
            config
            if isinstance(config, RecorderConfig)
            else (cfg if isinstance(cfg, RecorderConfig) else RecorderConfig())
        )

        self._running = False
        self._attached = bool(self.world is not None and self.sensors)
        self._callbacks_attached = False
        self._sensor_transforms_written = False
        self._manifest_written = False
        self._manifest_error: str = ""
        self._started_utc: Optional[str] = None
        self._last_tick_snapshot: Optional[Dict[str, Any]] = None
        self._fallback_frame_counter = 0
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._executor_shutdown = False
        self._write_slots = BoundedSemaphore(value=200)

        self._saved_images = 0
        self._saved_semseg = 0
        self._saved_lidars = 0
        self._sensor_frame_counts: Dict[str, int] = {}
        self._save_errors: list[str] = []
        self._listener_attach: Dict[str, Dict[str, Any]] = {}
        self._callbacks_in_flight = 0
        self._lock = Lock()

        self._manifest_path = self.out_dir / "recorder_manifest.json"
        self._snapshot_log_path = self.out_dir / "meta" / "world_snapshots.jsonl"
        if self._attached:
            self.start()

    @staticmethod
    def _normalize_sensors(sensors: Any) -> Dict[str, Any]:
        if isinstance(sensors, dict):
            return {str(k): v for k, v in sensors.items()}
        if sensors is None:
            return {}
        if isinstance(sensors, (list, tuple, set)):
            return {f"sensor_{idx:03d}": sensor for idx, sensor in enumerate(sensors)}
        return {"sensor_000": sensors}

    def attach(self, world: Any, ego_vehicle: Any, sensors: Any) -> None:
        """Attach recorder to world, ego vehicle, and sensors (deferred initialization)."""
        if self._running or self._callbacks_attached:
            self.stop()
        self.world = world
        self.ego_vehicle = ego_vehicle
        self.sensors = self._normalize_sensors(sensors)
        self._attached = bool(self.world is not None and self.sensors)
        self._callbacks_attached = False
        with self._lock:
            self._listener_attach = {}
        self.start()

    def start(self) -> None:
        if self._running:
            return
        if not self._attached or not self.sensors:
            return

        self._ensure_writer_executor_started()
        self._running = True
        self._write_sensor_transforms()

        attached_count = 0
        attached_sensor_names: list[str] = []
        try:
            for sensor_name, sensor in self.sensors.items():
                listener_entry: Dict[str, Any] = {
                    "attempted": False,
                    "attached": False,
                    "error": "",
                }
                if sensor is None:
                    listener_entry["error"] = "sensor_missing"
                    with self._lock:
                        self._listener_attach[sensor_name] = dict(listener_entry)
                    continue
                if not hasattr(sensor, "listen"):
                    self._record_error(f"listen_unsupported:{sensor_name}")
                    listener_entry["attempted"] = True
                    listener_entry["error"] = "listen_unsupported"
                    with self._lock:
                        self._listener_attach[sensor_name] = dict(listener_entry)
                    continue
                try:
                    # Clear any temporary probe listener before registering the
                    # recorder callback. CARLA aborts natively on duplicate
                    # listen() calls for the same stream within one process.
                    if hasattr(sensor, "stop"):
                        try:
                            sensor.stop()
                        except Exception as exc:
                            log.debug(
                                "Pre-listen stop failed for %s: %r",
                                sensor_name,
                                exc,
                            )
                    sensor.listen(self._make_sensor_callback(sensor_name, sensor))
                    attached_count += 1
                    attached_sensor_names.append(sensor_name)
                    listener_entry["attempted"] = True
                    listener_entry["attached"] = True
                except Exception as exc:
                    self._record_error(f"listen_failed:{sensor_name}:{exc}")
                    listener_entry["attempted"] = True
                    listener_entry["error"] = f"listen_failed:{exc}"
                with self._lock:
                    self._listener_attach[sensor_name] = dict(listener_entry)
        except Exception:
            for sensor_name in attached_sensor_names:
                sensor = self.sensors.get(sensor_name)
                if sensor is None or not hasattr(sensor, "stop"):
                    continue
                try:
                    sensor.stop()
                except Exception as exc:
                    self._record_error(
                        f"listen_cleanup_failed:{sensor_name}:{exc}"
                    )
            raise

        self._callbacks_attached = attached_count > 0
        if self._callbacks_attached:
            self._started_utc = datetime.now(timezone.utc).isoformat()
        else:
            self._running = False

    def stop(self) -> None:
        self._running = False
        for sensor_name, sensor in self.sensors.items():
            try:
                if hasattr(sensor, "stop"):
                    sensor.stop()
            except Exception as exc:
                self._record_error(f"sensor_stop_failed:{sensor_name}:{exc}")

    def close(self) -> None:
        """Finalize recording and release resources."""
        self.prepare_for_destroy()
        if not self._manifest_written:
            self._manifest_written = bool(self._write_manifest())

    def _drain_in_flight_callbacks(self, timeout_s: float = 2.0) -> None:
        drain_deadline = time.time() + float(timeout_s)
        while time.time() < drain_deadline:
            with self._lock:
                if int(getattr(self, "_callbacks_in_flight", 0) or 0) <= 0:
                    break
            time.sleep(0.05)

    def prepare_for_destroy(self) -> None:
        """Stop listeners and drain queued writes before actor destroy."""
        try:
            self.stop()
        except Exception as exc:
            self._record_error(f"sensor_stop_failed:close:{exc}")
        self._flush_post_stop_tick()
        self._drain_in_flight_callbacks(timeout_s=2.0)
        self.join_writer_threads(timeout_s=5.0)

    def finalize(self) -> None:
        """Compatibility alias used by older callers/tests."""
        self.close()

    def join_writer_threads(self, timeout_s: float = 5.0) -> None:
        """Drain queued writes and wait for executor-backed write tasks to finish."""
        del timeout_s  # compatibility shim; executor shutdown blocks until completion
        executor = getattr(self, "_executor", None)
        if executor is None or bool(getattr(self, "_executor_shutdown", False)):
            return
        self._executor_shutdown = True
        try:
            try:
                executor.shutdown(wait=True, cancel_futures=False)
            except TypeError:
                executor.shutdown(wait=True)
        except Exception as exc:
            self._record_error(f"writer_join_failed:{exc}")
        finally:
            self._executor = None

    def tick(self) -> Dict[str, Any]:
        if self._attached and self.sensors and not self._running:
            self.start()
        self._append_world_snapshot()
        with self._lock:
            return {
                "ok": True,
                "running": bool(self._running),
                "saved_images": int(self._saved_images),
                "saved_semseg": int(self._saved_semseg),
                "saved_lidars": int(self._saved_lidars),
                "frames_recorded": int(self.get_recorded_frame_count()),
                "sensor_frame_counts": dict(self._sensor_frame_counts),
                "save_errors_tail": self._save_errors[-10:],
            }

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        Return structured diagnostics for perception_diagnostics.json.

        Used by run_perception_safe to build thesis-defensible failure artifacts.
        """
        with self._lock:
            # Build sensor spawn status
            sensor_spawn_status = {}
            for sensor_name, sensor in self.sensors.items():
                actor_id = -1
                type_id = ""
                spawned = sensor is not None
                try:
                    if sensor is not None:
                        actor_id = int(getattr(sensor, "id", -1))
                        type_id = str(getattr(sensor, "type_id", ""))
                except Exception:
                    pass
                sensor_spawn_status[sensor_name] = {
                    "spawned": bool(spawned),
                    "actor_id": int(actor_id),
                    "type_id": str(type_id),
                }

            # Extract listen errors from listener_attach tracking
            listen_errors = []
            listener_attach = dict(getattr(self, "_listener_attach", {}) or {})
            for sensor_name, attach_info in listener_attach.items():
                if isinstance(attach_info, dict):
                    err = attach_info.get("error", "")
                    if err:
                        listen_errors.append(f"{sensor_name}:{err}")

            return {
                "sensor_spawn_status": sensor_spawn_status,
                "listen_errors": listen_errors,
                "per_sensor_frame_counts": dict(self._sensor_frame_counts),
                "total_saved_images": int(self._saved_images),
                "total_saved_lidars": int(self._saved_lidars),
                "total_saved_semseg": int(self._saved_semseg),
                "callbacks_attached": bool(self._callbacks_attached),
                "running": bool(self._running),
                "save_errors_tail": self._save_errors[-50:],
                "listener_attach": listener_attach,
            }

    def get_listener_attach_status(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                str(name): dict(payload)
                for name, payload in (self._listener_attach or {}).items()
                if isinstance(payload, dict)
            }

    def get_save_errors_tail(self, limit: int = 100) -> list[str]:
        limit_i = max(1, int(limit))
        with self._lock:
            return [str(item) for item in self._save_errors[-limit_i:]]

    def get_recorded_frame_count(self) -> int:
        # Return the MINIMUM across all attached sensors — any sensor with 0 callbacks
        # means the capture is incomplete and should not be counted as successful frames.
        # Using max() would mask partial failures (e.g., LiDAR fires 0 while cameras fire 20).
        with self._lock:
            if not self._sensor_frame_counts:
                return 0
            return int(min(int(v or 0) for v in self._sensor_frame_counts.values()))

    @staticmethod
    def _sanitize_name(name: str) -> str:
        safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(name))
        return safe or "sensor"

    @staticmethod
    def _sensor_kind(sensor_name: str, sensor: Any) -> str:
        type_id = str(getattr(sensor, "type_id", "")).lower()
        name_lower = str(sensor_name).lower()

        if (
            "semantic_segmentation" in type_id
            or name_lower.startswith("seg_")
            or "semseg" in name_lower
            or "semantic" in name_lower
        ):
            return "semseg_raw"
        if "lidar" in type_id or "lidar" in name_lower:
            return "lidar"
        if "camera" in type_id or "rgb" in name_lower or "camera" in name_lower:
            return "rgb"
        return "other"

    def _next_frame_id(self, data: Any) -> int:
        frame = getattr(data, "frame", None)
        if isinstance(frame, int):
            return int(frame)
        try:
            return int(frame)
        except Exception:
            with self._lock:
                self._fallback_frame_counter += 1
                return int(self._fallback_frame_counter)

    def _output_path(self, sensor_name: str, sensor_kind: str, frame_id: int, ext: str) -> Path:
        sensor_dir = self.out_dir / sensor_kind / self._sanitize_name(sensor_name)
        sensor_dir.mkdir(parents=True, exist_ok=True)
        return sensor_dir / f"{int(frame_id):08d}.{ext}"

    def _record_error(self, message: str) -> None:
        with self._lock:
            self._save_errors.append(str(message))
            if len(self._save_errors) > 5000:
                self._save_errors = self._save_errors[-5000:]

    def _record_saved_frame(self, sensor_name: str, sensor_kind: str) -> None:
        with self._lock:
            self._sensor_frame_counts[sensor_name] = (
                self._sensor_frame_counts.get(sensor_name, 0) + 1
            )
            if sensor_kind == "lidar":
                self._saved_lidars += 1
            elif sensor_kind == "semseg_raw":
                self._saved_semseg += 1
                self._saved_images += 1
            elif sensor_kind == "rgb":
                self._saved_images += 1

    def _ensure_writer_executor_started(self) -> None:
        if self._executor is not None and not bool(getattr(self, "_executor_shutdown", False)):
            return
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="sensor-recorder-writer",
        )
        self._executor_shutdown = False

    def _reserve_write_slot(self) -> bool:
        try:
            return bool(self._write_slots.acquire(blocking=False))
        except TypeError:
            return bool(self._write_slots.acquire(False))
        except Exception:
            return False

    def _release_write_slot(self) -> None:
        try:
            self._write_slots.release()
        except Exception:
            pass

    def _run_write_job(
        self,
        *,
        sensor_name: str,
        sensor_kind: str,
        frame_id: int,
        write_fn: Any,
    ) -> None:
        try:
            if callable(write_fn):
                write_fn()
                self._record_saved_frame(
                    sensor_name=str(sensor_name),
                    sensor_kind=str(sensor_kind),
                )
        except Exception as exc:
            self._record_error(f"save_failed:{sensor_name}:{frame_id}:{exc}")
        finally:
            self._release_write_slot()

    def _queue_write_job(
        self,
        *,
        sensor_name: str,
        sensor_kind: str,
        frame_id: int,
        write_fn: Any,
    ) -> bool:
        executor = getattr(self, "_executor", None)
        if executor is None or bool(getattr(self, "_executor_shutdown", False)):
            self._record_error(f"writer_executor_missing:{sensor_name}:{frame_id}")
            return False
        if not self._reserve_write_slot():
            self._record_error(f"writer_queue_full:{sensor_name}:{frame_id}")
            return False
        try:
            executor.submit(
                self._run_write_job,
                sensor_name=str(sensor_name),
                sensor_kind=str(sensor_kind),
                frame_id=int(frame_id),
                write_fn=write_fn,
            )
            return True
        except Exception as exc:
            self._release_write_slot()
            self._record_error(f"writer_submit_failed:{sensor_name}:{frame_id}:{exc}")
            return False

    @staticmethod
    def _count_sensor_files(sensor_dir: Path, sensor_kind: str, image_ext: str) -> int:
        if not sensor_dir.is_dir():
            return 0
        if sensor_kind == "lidar":
            return sum(1 for _ in sensor_dir.glob("*.ply")) + sum(
                1 for _ in sensor_dir.glob("*.npz")
            )
        if sensor_kind in {"rgb", "semseg_raw", "other"}:
            ext = str(image_ext or "png").lstrip(".").lower() or "png"
            patterns = [f"*.{ext}"]
            if ext != "png":
                patterns.append("*.png")
            count = 0
            for pattern in patterns:
                count += sum(1 for _ in sensor_dir.glob(pattern))
            return count
        return sum(1 for _ in sensor_dir.glob("*"))

    def _save_camera_frame(
        self, data: Any, *, out_path: Path, apply_cityscapes: bool
    ) -> None:
        if apply_cityscapes:
            try:
                import carla  # type: ignore

                if hasattr(data, "convert"):
                    data.convert(carla.ColorConverter.CityScapesPalette)
            except Exception:
                pass
        data.save_to_disk(str(out_path))

    def _save_lidar_frame(self, data: Any, *, out_path: Path) -> Path:
        lidar_format = str(getattr(self.cfg, "lidar_format", "npz") or "npz").lower()
        if lidar_format == "ply":
            data.save_to_disk(str(out_path.with_suffix(".ply")))
            return out_path.with_suffix(".ply")

        npz_path = out_path.with_suffix(".npz")
        try:
            import numpy as np

            raw_data = getattr(data, "raw_data", b"")
            points = np.frombuffer(raw_data, dtype=np.float32)
            if points.size == 0:
                points = np.zeros((0, 4), dtype=np.float32)
            elif points.size % 4 == 0:
                points = points.reshape((-1, 4))
            elif points.size % 3 == 0:
                points = points.reshape((-1, 3))
            else:
                points = points.reshape((-1, 1))
            np.savez_compressed(str(npz_path), points=points)
            return npz_path
        except Exception:
            fallback = out_path.with_suffix(".ply")
            data.save_to_disk(str(fallback))
            return fallback

    def _flush_post_stop_tick(self) -> None:
        world = self.world
        if world is None or not hasattr(world, "tick") or not hasattr(world, "get_settings"):
            return
        try:
            settings = world.get_settings()
        except Exception:
            return
        if not bool(getattr(settings, "synchronous_mode", False)):
            return
        timeout_s = float(getattr(self.cfg, "sensor_timeout_s", 2.0) or 2.0)
        try:
            world.tick(timeout_s)
        except Exception as exc:
            self._record_error(f"post_stop_tick_failed:{exc}")

    def _make_sensor_callback(self, sensor_name: str, sensor: Any):
        sensor_kind = self._sensor_kind(sensor_name, sensor)

        def _callback(data: Any) -> None:
            if not self._running:
                return
            with self._lock:
                self._callbacks_in_flight += 1
            frame_id = self._next_frame_id(data)
            try:
                if sensor_kind in {"rgb", "semseg_raw", "other"}:
                    image_ext = str(getattr(self.cfg, "image_format", "png") or "png")
                    image_ext = image_ext.lstrip(".").lower() or "png"
                    out_path = self._output_path(
                        sensor_name=sensor_name,
                        sensor_kind=sensor_kind if sensor_kind != "other" else "rgb",
                        frame_id=frame_id,
                        ext=image_ext,
                    )
                    apply_cityscapes = (
                        sensor_kind == "semseg_raw"
                        and str(
                            getattr(self.cfg, "segmentation_mode", "cityscapes") or ""
                        ).lower()
                        == "cityscapes"
                    )
                    effective_sensor_kind = (
                        sensor_kind if sensor_kind != "other" else "rgb"
                    )
                    self._queue_write_job(
                        sensor_name=sensor_name,
                        sensor_kind=effective_sensor_kind,
                        frame_id=frame_id,
                        write_fn=lambda data=data, out_path=out_path, apply_cityscapes=apply_cityscapes: self._save_camera_frame(
                            data, out_path=out_path, apply_cityscapes=apply_cityscapes
                        ),
                    )
                    return

                if sensor_kind == "lidar":
                    out_path = self._output_path(
                        sensor_name=sensor_name,
                        sensor_kind="lidar",
                        frame_id=frame_id,
                        ext="npz",
                    )
                    self._queue_write_job(
                        sensor_name=sensor_name,
                        sensor_kind="lidar",
                        frame_id=frame_id,
                        write_fn=lambda data=data, out_path=out_path: self._save_lidar_frame(
                            data, out_path=out_path
                        ),
                    )
                    return

            except Exception as exc:
                self._record_error(f"save_failed:{sensor_name}:{frame_id}:{exc}")
            finally:
                with self._lock:
                    self._callbacks_in_flight = max(
                        0, int(getattr(self, "_callbacks_in_flight", 0) or 0) - 1
                    )

        return _callback

    @staticmethod
    def _transform_to_dict(actor: Any) -> Optional[Dict[str, Dict[str, float]]]:
        try:
            tf = actor.get_transform()
            return {
                "location": {
                    "x": float(tf.location.x),
                    "y": float(tf.location.y),
                    "z": float(tf.location.z),
                },
                "rotation": {
                    "roll": float(tf.rotation.roll),
                    "pitch": float(tf.rotation.pitch),
                    "yaw": float(tf.rotation.yaw),
                },
            }
        except Exception:
            return None

    def _write_sensor_transforms(self) -> None:
        if self._sensor_transforms_written:
            return
        if not bool(getattr(self.cfg, "write_sensor_transforms", True)):
            self._sensor_transforms_written = True
            return

        payload: Dict[str, Any] = {
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "ego_transform": self._transform_to_dict(self.ego_vehicle)
            if self.ego_vehicle is not None
            else None,
            "sensors": {},
        }
        for sensor_name, sensor in self.sensors.items():
            payload["sensors"][sensor_name] = {
                "type_id": str(getattr(sensor, "type_id", "")),
                "transform": self._transform_to_dict(sensor),
            }

        out_path = self.out_dir / "sensor_transforms.json"
        out_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )
        self._sensor_transforms_written = True

    def _append_world_snapshot(self) -> None:
        if not bool(getattr(self.cfg, "write_world_snapshot", True)):
            return
        if self.world is None or not hasattr(self.world, "get_snapshot"):
            return
        try:
            snapshot = self.world.get_snapshot()
        except Exception:
            return
        if snapshot is None:
            return

        timestamp = getattr(snapshot, "timestamp", None)
        payload: Dict[str, Any] = {
            "frame": int(getattr(snapshot, "frame", -1)),
            "elapsed_seconds": float(getattr(timestamp, "elapsed_seconds", -1.0))
            if timestamp is not None
            else None,
            "delta_seconds": float(getattr(timestamp, "delta_seconds", -1.0))
            if timestamp is not None
            else None,
        }
        try:
            self._snapshot_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._snapshot_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=True))
                f.write("\n")
            self._last_tick_snapshot = payload
        except Exception:
            self._record_error("world_snapshot_write_failed")

    @staticmethod
    def _sensor_kind_for_manifest(sensor_name: str, sensor: Any) -> str:
        kind = SensorRecorder._sensor_kind(sensor_name, sensor)
        if kind in {"rgb", "lidar", "semseg_raw"}:
            return kind
        return "other"

    def _build_manifest_payload(self, *, end_utc: Optional[str] = None) -> Dict[str, Any]:
        try:
            cfg_dict = asdict(self.cfg)
        except Exception:
            cfg_dict = {}

        with self._lock:
            end_time = end_utc or datetime.now(timezone.utc).isoformat()
            sensors_payload = []
            per_sensor_counts: Dict[str, Dict[str, Any]] = {}
            image_ext = str(getattr(self.cfg, "image_format", "png") or "png")
            image_ext = image_ext.lstrip(".").lower() or "png"
            rgb_total = 0
            lidar_total = 0
            semseg_total = 0
            resolved_sensor_counts: Dict[str, int] = {}

            for sensor_name in sorted(self.sensors.keys()):
                sensor = self.sensors.get(sensor_name)
                sensor_kind = self._sensor_kind_for_manifest(sensor_name, sensor)
                frame_count_mem = int(self._sensor_frame_counts.get(sensor_name, 0))
                sensor_dir = self.out_dir / sensor_kind / self._sanitize_name(sensor_name)
                frame_count_disk = self._count_sensor_files(
                    sensor_dir, sensor_kind, image_ext
                )
                frame_count = int(max(frame_count_mem, frame_count_disk))
                type_id = str(getattr(sensor, "type_id", "")) if sensor is not None else ""
                resolved_sensor_counts[sensor_name] = int(frame_count)
                per_sensor_counts[sensor_name] = {
                    "kind": sensor_kind,
                    "frames": frame_count,
                    "rgb_frames": frame_count if sensor_kind == "rgb" else 0,
                    "lidar_frames": frame_count if sensor_kind == "lidar" else 0,
                }
                sensors_payload.append(
                    {
                        "name": sensor_name,
                        "kind": sensor_kind,
                        "type_id": type_id,
                        "frame_count": frame_count,
                        "output_dir": str(sensor_dir),
                    }
                )
                if sensor_kind == "rgb":
                    rgb_total += int(frame_count)
                elif sensor_kind == "lidar":
                    lidar_total += int(frame_count)
                elif sensor_kind == "semseg_raw":
                    semseg_total += int(frame_count)

            total_files = int(rgb_total + semseg_total + lidar_total)

            payload = {
                "schema_version": 1,
                "started_utc": self._started_utc,
                "closed_utc": end_time,
                "start_time": self._started_utc,
                "end_time": end_time,
                "output_dir": str(self.out_dir),
                "output_roots": {
                    "rgb": str(self.out_dir / "rgb"),
                    "semseg": str(self.out_dir / "semseg_raw"),
                    "lidar": str(self.out_dir / "lidar"),
                    "meta": str(self.out_dir / "meta"),
                },
                "sensors": sensors_payload,
                "per_sensor_counts": per_sensor_counts,
                "recorder_config": cfg_dict,
                "counts": {
                    "rgb_files": rgb_total,
                    "semseg_files": semseg_total,
                    "lidar_files": lidar_total,
                    "total_files": total_files,
                },
                "sensor_frame_counts": resolved_sensor_counts,
                "save_errors_tail": self._save_errors[-100:],
                "last_tick_snapshot": self._last_tick_snapshot,
                "manifest_write_error": str(self._manifest_error or ""),
            }
        return payload

    def _write_manifest(self) -> bool:
        payload = self._build_manifest_payload()
        manifest_path = self._manifest_path
        tmp_path = manifest_path.with_suffix(".json.tmp")

        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
                encoding="utf-8",
            )
            tmp_path.replace(manifest_path)
            self._manifest_error = ""
            return True
        except Exception as exc:
            self._manifest_error = str(exc)
            self._record_error(f"manifest_write_failed:{exc}")
            try:
                payload["manifest_write_error"] = self._manifest_error
                manifest_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
                    encoding="utf-8",
                )
                return True
            except Exception as fallback_exc:
                self._manifest_error = f"{self._manifest_error};fallback={fallback_exc}"
                self._record_error(f"manifest_write_fallback_failed:{fallback_exc}")
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass
                return False

    def attach_to_vehicles(self, vehicles):
        """Best-effort camera attach helper used by diagnostics/autopilot_test."""
        vehicles = list(vehicles or [])
        if not vehicles:
            return []

        if self.world is None:
            try:
                self.world = vehicles[0].get_world()
            except Exception:
                self.world = None
        if self.world is None:
            return []

        if self.ego_vehicle is None:
            self.ego_vehicle = vehicles[0]

        try:
            import carla  # type: ignore
        except Exception:
            return []

        try:
            bp_lib = self.world.get_blueprint_library()
            camera_bp = bp_lib.find("sensor.camera.rgb")
        except Exception:
            return []

        width, height = (
            self.cfg.low_mem_resolution
            if self.cfg.low_mem_resolution is not None
            else (960, 540)
        )
        if camera_bp.has_attribute("image_size_x"):
            camera_bp.set_attribute("image_size_x", str(int(width)))
        if camera_bp.has_attribute("image_size_y"):
            camera_bp.set_attribute("image_size_y", str(int(height)))
        if camera_bp.has_attribute("fov"):
            camera_bp.set_attribute("fov", "90")

        spawned = []
        for idx, vehicle in enumerate(vehicles):
            try:
                tf = carla.Transform(carla.Location(x=1.5, y=0.0, z=2.4))
                sensor = self.world.spawn_actor(camera_bp, tf, attach_to=vehicle)
                sensor_name = f"rgb_vehicle_{idx:03d}"
                self.sensors[sensor_name] = sensor
                spawned.append(sensor)
            except RuntimeError as exc:
                self._record_error(f"attach_to_vehicles_failed:{idx}:{exc}")
            except Exception as exc:
                self._record_error(f"attach_to_vehicles_failed:{idx}:{exc}")

        self._attached = bool(self.world is not None and self.sensors)
        if spawned:
            self.start()
        return spawned
