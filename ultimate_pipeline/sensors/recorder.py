from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any, Dict, List, Optional, Tuple


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backpressure / drain / frame-integrity outcome codes
# ---------------------------------------------------------------------------

CAPTURE_FRAME_DROP = "CAPTURE_FRAME_DROP"
CAPTURE_FRAME_ARTIFACT_MISMATCH = "CAPTURE_FRAME_ARTIFACT_MISMATCH"
CAPTURE_FRAME_ID_INVALID = "CAPTURE_FRAME_ID_INVALID"

WRITER_DRAIN_PASS = "WRITER_DRAIN_PASS"
WRITER_DRAIN_TIMEOUT = "WRITER_DRAIN_TIMEOUT"
WRITER_DRAIN_FAILURE = "WRITER_DRAIN_FAILURE"

FRAME_CORRESPONDENCE_SCHEMA = "FRAME_CORRESPONDENCE/v1"

#: Default writer queue capacity. Explicit so the accounted capacity and the
#: semaphore are provably the same number.
DEFAULT_WRITER_QUEUE_CAPACITY = 200


class FrameIdMissingError(RuntimeError):
    """Raised by _next_frame_id (NEW-287) when a sensor callback's data has
    no valid integer .frame -- fail closed instead of fabricating an ID."""


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

    # --- backpressure / strictness -------------------------------------
    #: Writer queue capacity. This is the capacity the accounting is measured
    #: against, so reducing it is how a caller or test exercises saturation
    #: deterministically. None restores DEFAULT_WRITER_QUEUE_CAPACITY.
    writer_queue_capacity: Optional[int] = None
    writer_max_workers: int = 4
    #: Strict mode: ANY dropped or failed mandatory-sensor frame invalidates the
    #: capture as CAPTURE_FRAME_DROP. Completeness may never be inferred from
    #: aggregate file counts.
    strict: bool = False
    #: Sensor names whose frames are mandatory. Empty means every attached
    #: sensor is mandatory.
    required_sensors: Tuple[str, ...] = ()
    #: Require the strict multimodal frame intersection across mandatory sensors.
    require_frame_correspondence: bool = False
    #: Require every artifact to be bound to an actual callback frame id.
    require_artifact_frame_binding: bool = False


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

        self._queue_capacity = int(
            getattr(self.cfg, "writer_queue_capacity", None)
            or DEFAULT_WRITER_QUEUE_CAPACITY
        )
        self._write_slots = BoundedSemaphore(value=self._queue_capacity)
        #: Slots held: pending (queued, not started) + executing.
        self._write_jobs_pending = 0
        self._write_jobs_executing = 0
        self._queue_high_water_mark = 0
        self._write_jobs_completed = 0
        self._write_jobs_failed = 0
        self._frames_dropped = 0
        #: Cleared when the recorder stops accepting new callbacks (drain).
        self._accept_callbacks = True
        self._drain_state: Optional[str] = None
        self._drain_evidence: Dict[str, Any] = {}

        self._saved_images = 0
        self._saved_semseg = 0
        self._saved_lidars = 0
        self._sensor_frame_counts: Dict[str, int] = {}
        self._save_errors: list[str] = []
        self._listener_attach: Dict[str, Dict[str, Any]] = {}
        self._callbacks_in_flight = 0
        self._lock = Lock()

        # --- per-sensor frame accounting (authoritative for completeness) ---
        # These hold callback frame ids, never counts. Counts cannot detect a
        # duplicated frame, a missing frame, or cross-sensor skew, so the
        # completeness verdict is computed from these ordered id sets.
        self._frame_ids: Dict[str, List[int]] = {}
        self._write_attempted_frame_ids: Dict[str, List[int]] = {}
        self._write_accepted_frame_ids: Dict[str, List[int]] = {}
        self._write_completed_frame_ids: Dict[str, List[int]] = {}
        self._write_failed_frame_ids: Dict[str, List[int]] = {}
        self._write_dropped_frame_ids: Dict[str, List[int]] = {}
        self._duplicate_frame_ids: Dict[str, List[int]] = {}
        self._invalid_frame_ids: Dict[str, List[str]] = {}
        #: sensor_name -> callback_frame_id -> artifact record
        self._artifacts: Dict[str, Dict[int, Dict[str, Any]]] = {}
        #: sensor_name -> frame ids that produced more than one artifact
        self._duplicate_artifacts: Dict[str, List[int]] = {}

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

    def close(self) -> Dict[str, Any]:
        """Finalize recording and release resources.

        Returns the completeness verdict, derived from exact callback frame ids,
        artifact-to-frame binding and the writer drain state. It is never
        derived from aggregate file counts.
        """
        drain = self.prepare_for_destroy()
        if not self._manifest_written:
            self._manifest_written = bool(self._write_manifest())
        return self.final_report(drain=drain)

    def _drain_in_flight_callbacks(self, timeout_s: float = 2.0) -> None:
        drain_deadline = time.time() + float(timeout_s)
        while time.time() < drain_deadline:
            with self._lock:
                if int(getattr(self, "_callbacks_in_flight", 0) or 0) <= 0:
                    break
            time.sleep(0.05)

    def prepare_for_destroy(self) -> Dict[str, Any]:
        """Stop listeners and drain queued writes before actor destroy.

        Returns the drain outcome; the caller must not treat a non-PASS drain as
        a finished capture.
        """
        try:
            self.stop()
        except Exception as exc:
            self._record_error(f"sensor_stop_failed:close:{exc}")
        self._flush_post_stop_tick()
        self._drain_in_flight_callbacks(timeout_s=2.0)
        return self.join_writer_threads(timeout_s=5.0)

    def finalize(self) -> Dict[str, Any]:
        """Compatibility alias used by older callers/tests."""
        return self.close()

    # ------------------------------------------------------------------
    # frame correspondence + completeness verdict
    # ------------------------------------------------------------------

    def _mandatory_sensors(self) -> List[str]:
        required = [str(n) for n in (getattr(self.cfg, "required_sensors", ()) or ())]
        if required:
            return [n for n in required if n in self.sensors]
        return sorted(self.sensors)

    def frame_correspondence(self) -> Dict[str, Any]:
        """Exact per-sensor callback frame correspondence.

        Built from actual callback frame ids only. Equal per-sensor frame COUNTS
        are explicitly not treated as synchronisation evidence: two sensors can
        each deliver N frames over entirely disjoint frame ranges.
        """
        with self._lock:
            per_sensor_all = {
                name: [int(i) for i in ids]
                for name, ids in sorted(self._frame_ids.items())
            }
            duplicates = {
                name: [int(i) for i in ids]
                for name, ids in sorted(self._duplicate_frame_ids.items())
                if ids
            }

        mandatory = self._mandatory_sensors()
        considered = {n: per_sensor_all.get(n, []) for n in mandatory}

        # None means "no accumulator yet". An empty list is a real result: a
        # sensor that delivered no frames intersects to nothing, and that must
        # not be mistaken for an unstarted accumulator (which would let a later
        # sensor's frames leak in as if they were common to all).
        common: Optional[List[int]] = None
        for ids in considered.values():
            id_set = set(ids)
            common = (
                sorted(id_set) if common is None else [i for i in common if i in id_set]
            )
        common_ids = sorted(int(i) for i in (common or []))
        common_set = set(common_ids)

        missing_by_sensor: Dict[str, List[int]] = {}
        extra_by_sensor: Dict[str, List[int]] = {}
        for name, ids in considered.items():
            id_set = set(ids)
            missing_by_sensor[name] = sorted(
                int(i) for i in common_ids if i not in id_set
            )
            extra_by_sensor[name] = sorted(int(i) for i in ids if i not in common_set)

        sequence_non_decreasing: Dict[str, bool] = {}
        for name, ids in considered.items():
            finite_ints = all(
                isinstance(i, int) and not isinstance(i, bool) for i in ids
            )
            non_decreasing = all(int(a) <= int(b) for a, b in zip(ids, ids[1:]))
            sequence_non_decreasing[name] = bool(finite_ints and non_decreasing)

        return {
            "schema": FRAME_CORRESPONDENCE_SCHEMA,
            "mandatory_sensors": list(mandatory),
            "per_sensor_frame_ids": considered,
            "common_frame_ids": common_ids,
            "common_frame_count": len(common_ids),
            "first_common_frame": common_ids[0] if common_ids else None,
            "last_common_frame": common_ids[-1] if common_ids else None,
            "missing_by_sensor": missing_by_sensor,
            "extra_by_sensor": extra_by_sensor,
            "duplicates_by_sensor": duplicates,
            "callback_sequence_non_decreasing": sequence_non_decreasing,
            "frame_ids_finite_integers": {
                name: all(
                    isinstance(i, int) and not isinstance(i, bool) for i in ids
                )
                for name, ids in considered.items()
            },
            "note": (
                "Correspondences come from actual CARLA callback data.frame values. "
                "Equal per-sensor frame counts are not synchronisation evidence."
            ),
        }

    def write_frame_correspondence_artifact(self, path: Any = None) -> Path:
        """Emit FRAME_CORRESPONDENCE.json next to the capture."""
        payload = self.frame_correspondence()
        out = (
            Path(path) if path is not None else (self.out_dir / "FRAME_CORRESPONDENCE.json")
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return out

    def _artifact_report(self) -> Dict[str, Any]:
        with self._lock:
            artifacts = {
                name: {str(fid): dict(rec) for fid, rec in sorted(per.items())}
                for name, per in sorted(self._artifacts.items())
            }
            duplicate_artifacts = {
                name: sorted(int(i) for i in ids)
                for name, ids in sorted(self._duplicate_artifacts.items())
                if ids
            }
            dropped = {
                name: [int(i) for i in ids]
                for name, ids in sorted(self._write_dropped_frame_ids.items())
                if ids
            }
            failed = {
                name: [int(i) for i in ids]
                for name, ids in sorted(self._write_failed_frame_ids.items())
                if ids
            }
            completed = {
                name: set(int(i) for i in ids)
                for name, ids in self._write_completed_frame_ids.items()
            }

        mismatched: List[Dict[str, Any]] = []
        for name, per in artifacts.items():
            for _fid, rec in per.items():
                if not rec.get("filename_matches_callback_frame_id"):
                    mismatched.append(
                        {
                            "sensor_name": name,
                            "callback_frame_id": rec.get("callback_frame_id"),
                            "filename_frame_id": rec.get("filename_frame_id"),
                            "output_path": rec.get("output_path"),
                        }
                    )

        # A callback receipt with no artifact, and an artifact with no receipt.
        receipts_without_file: List[Dict[str, Any]] = []
        files_without_receipt: List[Dict[str, Any]] = []
        for name, ids in completed.items():
            per = artifacts.get(name, {})
            for fid in sorted(ids):
                if int(fid) not in per:
                    receipts_without_file.append(
                        {"sensor_name": name, "callback_frame_id": int(fid)}
                    )
        for name, per in artifacts.items():
            for fid, rec in per.items():
                if (
                    str(rec.get("write_status")) != "WRITTEN"
                    or int(fid) not in completed.get(name, set())
                ):
                    files_without_receipt.append(
                        {
                            "sensor_name": name,
                            "callback_frame_id": int(fid),
                            "output_path": rec.get("output_path"),
                            "write_status": rec.get("write_status"),
                        }
                    )

        return {
            "artifacts": artifacts,
            "duplicate_artifacts_by_sensor": duplicate_artifacts,
            "dropped_frames_by_sensor": dropped,
            "failed_frames_by_sensor": failed,
            "filename_frame_id_mismatches": mismatched,
            "callback_receipt_without_file": receipts_without_file,
            "file_without_callback_receipt": files_without_receipt,
        }

    def backpressure_report(self) -> Dict[str, Any]:
        """Per-sensor write accounting plus queue-level counters."""
        with self._lock:
            return {
                "schema": "RECORDER_BACKPRESSURE/v1",
                "queue_capacity": int(self._queue_capacity),
                "queue_high_water_mark": int(self._queue_high_water_mark),
                "write_jobs_pending": int(self._write_jobs_pending),
                "write_jobs_executing": int(self._write_jobs_executing),
                "write_jobs_completed": int(self._write_jobs_completed),
                "write_jobs_failed": int(self._write_jobs_failed),
                "frames_dropped": int(self._frames_dropped),
                "accepting_callbacks": bool(self._accept_callbacks),
                "callback_frame_ids": {
                    k: [int(i) for i in v] for k, v in sorted(self._frame_ids.items())
                },
                "write_attempted_frame_ids": {
                    k: [int(i) for i in v]
                    for k, v in sorted(self._write_attempted_frame_ids.items())
                },
                "write_accepted_frame_ids": {
                    k: [int(i) for i in v]
                    for k, v in sorted(self._write_accepted_frame_ids.items())
                },
                "write_completed_frame_ids": {
                    k: [int(i) for i in v]
                    for k, v in sorted(self._write_completed_frame_ids.items())
                },
                "write_failed_frame_ids": {
                    k: [int(i) for i in v]
                    for k, v in sorted(self._write_failed_frame_ids.items())
                },
                "write_dropped_frame_ids": {
                    k: [int(i) for i in v]
                    for k, v in sorted(self._write_dropped_frame_ids.items())
                },
                "duplicate_frame_ids": {
                    k: [int(i) for i in v]
                    for k, v in sorted(self._duplicate_frame_ids.items())
                    if v
                },
                "invalid_frame_ids": {
                    k: list(v) for k, v in sorted(self._invalid_frame_ids.items()) if v
                },
            }

    def final_report(self, *, drain: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Assemble the capture verdict from exact frame-id evidence.

        Completeness is never inferred from aggregate file counts: a dropped
        mandatory frame invalidates the capture even when the surviving files
        look complete.
        """
        drain = drain if drain is not None else dict(self._drain_evidence)
        drain_state = str(drain.get("state") or self._drain_state or "")
        correspondence = self.frame_correspondence()
        artifacts = self._artifact_report()
        backpressure = self.backpressure_report()

        strict = bool(getattr(self.cfg, "strict", False))
        mandatory = set(correspondence["mandatory_sensors"])
        invalid: List[str] = []
        warnings: List[str] = []

        dropped = {
            name: ids
            for name, ids in artifacts["dropped_frames_by_sensor"].items()
            if name in mandatory
        }
        failed = {
            name: ids
            for name, ids in artifacts["failed_frames_by_sensor"].items()
            if name in mandatory
        }
        if dropped:
            invalid.append(CAPTURE_FRAME_DROP)
        if failed:
            invalid.append(f"{CAPTURE_FRAME_DROP}:write_failed:{sorted(failed)}")

        duplicates = {
            name: ids
            for name, ids in correspondence["duplicates_by_sensor"].items()
            if name in mandatory
        }
        if duplicates and strict:
            invalid.append(f"{CAPTURE_FRAME_DROP}:duplicate_frames:{sorted(duplicates)}")

        for name, ok in correspondence["frame_ids_finite_integers"].items():
            if not ok and name in mandatory:
                invalid.append(f"{CAPTURE_FRAME_ID_INVALID}:{name}")

        if drain_state and drain_state != WRITER_DRAIN_PASS:
            invalid.append(str(drain_state))

        if strict and bool(getattr(self.cfg, "require_frame_correspondence", False)):
            for name in sorted(mandatory):
                if correspondence["missing_by_sensor"].get(name):
                    invalid.append(
                        f"{CAPTURE_FRAME_DROP}:missing_frames:{name}:"
                        f"{correspondence['missing_by_sensor'][name][:20]}"
                    )
            if correspondence["common_frame_count"] == 0 and mandatory:
                invalid.append(f"{CAPTURE_FRAME_DROP}:no_common_frames:{sorted(mandatory)}")
            for name, ok in correspondence["callback_sequence_non_decreasing"].items():
                if not ok and name in mandatory:
                    invalid.append(f"{CAPTURE_FRAME_ID_INVALID}:{name}:non_monotonic")

        if strict or bool(getattr(self.cfg, "require_artifact_frame_binding", False)):
            if artifacts["filename_frame_id_mismatches"]:
                invalid.append(CAPTURE_FRAME_ARTIFACT_MISMATCH)
            if artifacts["duplicate_artifacts_by_sensor"]:
                invalid.append(
                    f"{CAPTURE_FRAME_ARTIFACT_MISMATCH}:duplicate_files:"
                    f"{sorted(artifacts['duplicate_artifacts_by_sensor'])}"
                )
            if artifacts["callback_receipt_without_file"]:
                invalid.append(
                    f"{CAPTURE_FRAME_ARTIFACT_MISMATCH}:receipt_without_file:"
                    f"{len(artifacts['callback_receipt_without_file'])}"
                )
            if artifacts["file_without_callback_receipt"]:
                invalid.append(
                    f"{CAPTURE_FRAME_ARTIFACT_MISMATCH}:file_without_receipt:"
                    f"{len(artifacts['file_without_callback_receipt'])}"
                )

        # A mandatory sensor that never delivered a frame is a hard failure:
        # "zero frames" is not "fine".
        for name in sorted(mandatory):
            if not correspondence["per_sensor_frame_ids"].get(name):
                invalid.append(f"{CAPTURE_FRAME_DROP}:no_frames:{name}")
                warnings.append(f"sensor_delivered_no_frames:{name}")

        return {
            "schema": "RECORDER_CAPTURE_VERDICT/v1",
            "valid": not invalid,
            "capture_valid": not invalid,
            "strict": strict,
            "invalid_reasons": invalid,
            "warnings": warnings,
            "drain": drain,
            "drain_state": drain_state,
            "backpressure": backpressure,
            "frame_correspondence": correspondence,
            "artifacts": artifacts,
            "verdict_basis": (
                "exact callback frame ids, artifact-to-frame binding and writer drain "
                "state; aggregate file counts are not used"
            ),
        }

    def _pending_write_frames(self) -> Dict[str, List[int]]:
        """Frame ids accepted by the writer but not yet completed."""
        with self._lock:
            settled: set = set()
            for lst in self._write_completed_frame_ids.values():
                settled.update(int(x) for x in lst)
            for lst in self._write_failed_frame_ids.values():
                settled.update(int(x) for x in lst)
            out: Dict[str, List[int]] = {}
            for name, ids in self._write_accepted_frame_ids.items():
                remaining = sorted(int(i) for i in ids if int(i) not in settled)
                if remaining:
                    out[name] = remaining
            return out

    def _record_drain_outcome(
        self,
        state: str,
        *,
        timeout_s: float,
        pending: Dict[str, List[int]],
        error: str = "",
    ) -> Dict[str, Any]:
        with self._lock:
            payload: Dict[str, Any] = {
                "state": str(state),
                "timeout_s": float(timeout_s),
                "pending_frame_ids_by_sensor": {k: list(v) for k, v in pending.items()},
                "pending_frame_count": int(sum(len(v) for v in pending.values())),
                "write_jobs_pending": int(self._write_jobs_pending),
                "write_jobs_executing": int(self._write_jobs_executing),
                "write_jobs_completed": int(self._write_jobs_completed),
                "write_jobs_failed": int(self._write_jobs_failed),
                "queue_high_water_mark": int(self._queue_high_water_mark),
                "frames_dropped": int(self._frames_dropped),
                "error": str(error),
                "capture_complete": state == WRITER_DRAIN_PASS,
                "note": (
                    "All queued writer jobs completed before the timeout."
                    if state == WRITER_DRAIN_PASS
                    else "Writer drain did not complete cleanly. Output is incomplete "
                    "and must not be treated as a passing capture."
                ),
            }
        self._drain_evidence = dict(payload)
        self._drain_state = str(state)
        return payload

    def join_writer_threads(self, timeout_s: float = 5.0) -> Dict[str, Any]:
        """Drain queued writes under a REAL deadline and report the outcome.

        The previous implementation accepted ``timeout_s`` and discarded it
        (``del timeout_s``) before calling ``executor.shutdown(wait=True)``, which
        blocks until every job finishes. A hanging writer therefore hung the
        caller forever and the timeout was a lie.

        A Python thread cannot be force-killed, so this method does not pretend a
        running job can be cancelled. It:

        1. stops accepting new callbacks;
        2. hands the already-accepted work to the executor without discarding it
           (``cancel_futures`` is deliberately not used: every queued job is an
           accepted frame, so cancelling one would silently lose a frame the
           recorder already promised to write);
        3. waits at most ``timeout_s``, polling a real deadline;
        4. on timeout reports WRITER_DRAIN_TIMEOUT with the still-pending frame
           ids and the still-executing job count, quarantines the output, and
           never claims the capture is complete.

        Architectural limitation: with a ThreadPoolExecutor a strict shutdown
        cannot be *guaranteed* bounded, because a job already running in a
        thread cannot be interrupted. For a hard bound, strict writer execution
        must be isolated in a separate process whose lifetime can be terminated.
        """
        timeout_s = float(timeout_s)
        # 1. Refuse new work from this point on.
        self._accept_callbacks = False

        executor = getattr(self, "_executor", None)
        if executor is None:
            return self._record_drain_outcome(
                WRITER_DRAIN_PASS, timeout_s=timeout_s, pending={}
            )

        self._executor_shutdown = True

        # 2. Hand the accepted work over, then poll to the deadline.
        #
        # `cancel_futures=True` is deliberately NOT used. Every queued job is
        # already accounted as an accepted frame, so cancelling a not-yet-started
        # one would silently discard a frame the recorder promised to write --
        # exactly the silent frame loss this module exists to prevent. The drain
        # therefore waits for accepted work up to the deadline and, if the
        # deadline passes, reports the pending frame ids explicitly so the
        # capture is visibly incomplete rather than quietly short.
        try:
            executor.shutdown(wait=False)
        except Exception as exc:
            return self._record_drain_outcome(
                WRITER_DRAIN_FAILURE,
                timeout_s=timeout_s,
                pending=self._pending_write_frames(),
                error=f"{type(exc).__name__}:{exc}",
            )

        # 3. Poll to a real deadline.
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            with self._lock:
                busy = (
                    int(self._write_jobs_pending) > 0
                    or int(self._write_jobs_executing) > 0
                )
            if not busy:
                break
            if time.monotonic() >= deadline:
                payload = self._record_drain_outcome(
                    WRITER_DRAIN_TIMEOUT,
                    timeout_s=timeout_s,
                    pending=self._pending_write_frames(),
                    error=(
                        "writer_drain_timeout:still_running="
                        f"{int(self._write_jobs_pending)}+{int(self._write_jobs_executing)}"
                    ),
                )
                self._write_drain_quarantine_marker(payload)
                self._executor = None
                return payload
            time.sleep(0.01)

        self._executor = None
        return self._record_drain_outcome(
            WRITER_DRAIN_PASS, timeout_s=timeout_s, pending={}
        )

    def _write_drain_quarantine_marker(self, payload: Dict[str, Any]) -> None:
        """Mark an undrained capture incomplete on disk.

        Output of a timed-out drain is quarantined rather than published as a
        finished capture.
        """
        marker = {
            "schema": "RECORDER_DRAIN_QUARANTINE/v1",
            "state": str(payload.get("state")),
            "capture_complete": False,
            "invalid_reason": WRITER_DRAIN_TIMEOUT,
            "timeout_s": payload.get("timeout_s"),
            "pending_frame_ids_by_sensor": payload.get("pending_frame_ids_by_sensor"),
            "pending_frame_count": payload.get("pending_frame_count"),
            "write_jobs_executing": payload.get("write_jobs_executing"),
            "write_jobs_pending": payload.get("write_jobs_pending"),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            (self.out_dir / "DRAIN_INCOMPLETE.json").write_text(
                json.dumps(marker, indent=2, sort_keys=True), encoding="utf-8"
            )
        except Exception as exc:
            self._record_error(f"drain_quarantine_marker_failed:{exc}")

    def tick(self) -> Dict[str, Any]:
        if self._attached and self.sensors and not self._running:
            self.start()
        self._append_world_snapshot()
        with self._lock:
            # P0-1: frames_recorded is computed inline. get_recorded_frame_count()
            # acquires this same non-reentrant Lock, so calling it while already
            # holding the lock deadlocked tick() on every invocation.
            if not self._sensor_frame_counts:
                frames_recorded = 0
            else:
                frames_recorded = int(
                    min(int(v or 0) for v in self._sensor_frame_counts.values())
                )
            return {
                "ok": True,
                "running": bool(self._running),
                "saved_images": int(self._saved_images),
                "saved_semseg": int(self._saved_semseg),
                "saved_lidars": int(self._saved_lidars),
                "frames_recorded": frames_recorded,
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
    def _canonical_sensor_subdir(sensor_name: str, sensor_kind: str) -> str:
        """Map a sensor name to its per-camera dataset subdirectory.

        Live-capture rigs name semantic cameras ``semseg_<cam>`` (thesis rig)
        or ``seg_<cam>`` (dominik rig) and RGB cameras ``<cam>`` /
        ``rgb_<cam>``.  The training/eval readers pair RGB with semantic
        labels by using ONE camera name for both ``rgb/<cam>/`` and
        ``semseg_raw/<cam>/`` roots, so the modality prefix must be stripped
        here to keep the two subdirectories pairable (C8).
        """
        name = str(sensor_name)
        if sensor_kind in {"rgb", "semseg_raw"}:
            lower = name.lower()
            for prefix in ("semseg_", "seg_", "rgb_"):
                if lower.startswith(prefix) and len(name) > len(prefix):
                    name = name[len(prefix):]
                    break
        return SensorRecorder._sanitize_name(name)

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
        raise FrameIdMissingError(
            f"sensor data has no valid integer .frame (got {frame!r}); "
            "refusing to fabricate a frame id"
        )

    def _output_path(self, sensor_name: str, sensor_kind: str, frame_id: int, ext: str) -> Path:
        sensor_dir = (
            self.out_dir
            / sensor_kind
            / self._canonical_sensor_subdir(sensor_name, sensor_kind)
        )
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

    # ------------------------------------------------------------------
    # per-sensor frame accounting
    # ------------------------------------------------------------------

    @staticmethod
    def _append_frame_id(bucket: Dict[str, List[int]], sensor_name: str, frame_id: int) -> None:
        lst = bucket.setdefault(sensor_name, [])
        if frame_id not in lst:
            lst.append(int(frame_id))
            lst.sort()

    def _record_callback_frame(self, sensor_name: str, frame_id: int) -> None:
        """Record a callback frame id, flagging a repeated delivery.

        Deliberately does NOT touch ``_sensor_frame_counts``: that counter means
        "frames whose bytes reached disk" and is maintained by
        ``_record_saved_frame``. Conflating delivered frames with saved frames
        would let a dropped write still read as a recorded frame.
        """
        with self._lock:
            seen = self._frame_ids.setdefault(sensor_name, [])
            if frame_id in seen:
                dups = self._duplicate_frame_ids.setdefault(sensor_name, [])
                if frame_id not in dups:
                    dups.append(int(frame_id))
                    dups.sort()
                return
            seen.append(int(frame_id))
            seen.sort()

    def _record_invalid_frame(self, sensor_name: str, reason: str) -> None:
        with self._lock:
            self._invalid_frame_ids.setdefault(sensor_name, []).append(str(reason))
            self._save_errors.append(f"{CAPTURE_FRAME_ID_INVALID}:{sensor_name}:{reason}")

    def _record_write_attempted(self, sensor_name: str, frame_id: int) -> None:
        with self._lock:
            self._append_frame_id(self._write_attempted_frame_ids, sensor_name, frame_id)

    def _record_write_accepted(self, sensor_name: str, frame_id: int) -> None:
        with self._lock:
            self._append_frame_id(self._write_accepted_frame_ids, sensor_name, frame_id)
            self._write_jobs_pending = int(self._write_jobs_pending) + 1
            in_use = int(self._write_jobs_pending) + int(self._write_jobs_executing)
            if in_use > int(self._queue_high_water_mark):
                self._queue_high_water_mark = in_use

    def _record_write_dropped(self, sensor_name: str, frame_id: int, reason: str) -> None:
        """A callback arrived but its write was refused: the frame is lost.

        This is the backpressure signal that must never be laundered into a
        successful capture.
        """
        with self._lock:
            self._append_frame_id(self._write_dropped_frame_ids, sensor_name, frame_id)
            self._frames_dropped = int(self._frames_dropped) + 1
            self._save_errors.append(
                f"{CAPTURE_FRAME_DROP}:{sensor_name}:{frame_id}:{reason}"
            )

    def _record_write_completed(self, sensor_name: str, frame_id: int) -> None:
        with self._lock:
            self._append_frame_id(self._write_completed_frame_ids, sensor_name, frame_id)
            self._write_jobs_completed = int(self._write_jobs_completed) + 1

    def _record_write_failed(self, sensor_name: str, frame_id: int, reason: str) -> None:
        with self._lock:
            self._append_frame_id(self._write_failed_frame_ids, sensor_name, frame_id)
            self._write_jobs_failed = int(self._write_jobs_failed) + 1
            self._save_errors.append(f"save_failed:{sensor_name}:{frame_id}:{reason}")

    def _bind_artifact(
        self,
        *,
        sensor_name: str,
        sensor_kind: str,
        callback_frame_id: int,
        output_path: Path,
        write_status: str,
        sensor: Any = None,
        sim_timestamp: Any = None,
    ) -> Dict[str, Any]:
        """Bind one written artifact to the callback frame id that produced it.

        The filename frame id must equal the callback frame id; a mismatch is
        recorded rather than silently accepted.
        """
        try:
            digest = hashlib.sha256(Path(output_path).read_bytes()).hexdigest()
        except Exception:
            digest = ""
        record: Dict[str, Any] = {
            "sensor_name": str(sensor_name),
            "sensor_kind": str(sensor_kind),
            "sensor_actor_id": int(getattr(sensor, "id", -1) or -1) if sensor is not None else -1,
            "sensor_type": str(getattr(sensor, "type_id", "") or ""),
            "callback_frame_id": int(callback_frame_id),
            "sim_timestamp": float(sim_timestamp) if sim_timestamp is not None else None,
            "output_path": str(output_path),
            "output_sha256": digest,
            "write_status": str(write_status),
        }
        try:
            filename_frame_id: Optional[int] = int(Path(output_path).stem)
        except (TypeError, ValueError):
            filename_frame_id = None
        record["filename_frame_id"] = filename_frame_id
        record["filename_matches_callback_frame_id"] = (
            filename_frame_id is not None and filename_frame_id == int(callback_frame_id)
        )
        if not record["filename_matches_callback_frame_id"]:
            self._record_error(
                f"{CAPTURE_FRAME_ARTIFACT_MISMATCH}:{sensor_name}:"
                f"callback={callback_frame_id}:filename={filename_frame_id}"
            )
        with self._lock:
            per_sensor = self._artifacts.setdefault(str(sensor_name), {})
            if int(callback_frame_id) in per_sensor:
                dups = self._duplicate_artifacts.setdefault(str(sensor_name), [])
                if int(callback_frame_id) not in dups:
                    dups.append(int(callback_frame_id))
                    dups.sort()
            per_sensor[int(callback_frame_id)] = record
        return record

    def _run_write_job(
        self,
        *,
        sensor_name: str,
        sensor_kind: str,
        frame_id: int,
        write_fn: Any,
        sensor: Any = None,
        out_path: Optional[Path] = None,
    ) -> None:
        # Executing is counted separately from pending so a drain timeout can
        # report exactly what was still running.
        with self._lock:
            self._write_jobs_executing = int(self._write_jobs_executing) + 1
            if int(self._write_jobs_pending) > 0:
                self._write_jobs_pending = int(self._write_jobs_pending) - 1
        try:
            if callable(write_fn):
                written = write_fn()
                # Bind to the path the writer ACTUALLY used. If a writer
                # substitutes a different filename, binding to the requested
                # out_path would hide that substitution, so a returned Path is
                # preferred and the requested path is only a fallback.
                actual = written if isinstance(written, Path) else out_path
                if actual is not None:
                    self._bind_artifact(
                        sensor_name=str(sensor_name),
                        sensor_kind=str(sensor_kind),
                        callback_frame_id=int(frame_id),
                        output_path=Path(actual),
                        write_status="WRITTEN",
                        sensor=sensor,
                    )
                self._record_saved_frame(
                    sensor_name=str(sensor_name),
                    sensor_kind=str(sensor_kind),
                )
                self._record_write_completed(str(sensor_name), int(frame_id))
        except Exception as exc:
            self._record_write_failed(
                str(sensor_name), int(frame_id), f"{type(exc).__name__}:{exc}"
            )
        finally:
            with self._lock:
                self._write_jobs_executing = max(
                    0, int(self._write_jobs_executing) - 1
                )
            self._release_write_slot()

    def _queue_write_job(
        self,
        *,
        sensor_name: str,
        sensor_kind: str,
        frame_id: int,
        write_fn: Any,
        sensor: Any = None,
        out_path: Optional[Path] = None,
    ) -> bool:
        """Queue one write. False means the frame was DROPPED.

        In strict mode a False return is CAPTURE_FRAME_DROP; it may never be
        absorbed as a successful capture.
        """
        self._record_write_attempted(str(sensor_name), int(frame_id))

        if not bool(getattr(self, "_accept_callbacks", True)):
            self._record_write_dropped(
                str(sensor_name), int(frame_id), "writer_not_accepting"
            )
            return False

        executor = getattr(self, "_executor", None)
        if executor is None or bool(getattr(self, "_executor_shutdown", False)):
            self._record_write_dropped(
                str(sensor_name), int(frame_id), "writer_executor_missing"
            )
            return False
        if not self._reserve_write_slot():
            self._record_write_dropped(
                str(sensor_name), int(frame_id), "writer_queue_full"
            )
            return False
        # Account as pending BEFORE submitting: the worker may start and
        # decrement pending before submit() returns, so accounting after the
        # submit would re-increment a job that already ran and leave pending
        # permanently non-zero, making every later drain look like a timeout.
        self._record_write_accepted(str(sensor_name), int(frame_id))
        try:
            executor.submit(
                self._run_write_job,
                sensor_name=str(sensor_name),
                sensor_kind=str(sensor_kind),
                frame_id=int(frame_id),
                write_fn=write_fn,
                sensor=sensor,
                out_path=out_path,
            )
            return True
        except Exception as exc:
            self._release_write_slot()
            with self._lock:
                self._write_jobs_pending = max(0, int(self._write_jobs_pending) - 1)
            self._record_write_dropped(
                str(sensor_name),
                int(frame_id),
                f"writer_submit_failed:{type(exc).__name__}:{exc}",
            )
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

    @staticmethod
    def _write_semseg_raw_png(data: Any, out_path: Path) -> None:
        """Write a single-channel uint8 label PNG whose pixel value is the
        CARLA semantic class id (R channel of the BGRA sensor buffer).

        This is the training-label contract shared with capture_writer
        (rgb/+semseg_raw/, raw ids, never palette-colorized) — the C8 fix.
        Works on real carla.Image objects and offline duck-typed fakes.
        """
        import numpy as np

        arr = np.frombuffer(
            data.raw_data, dtype=np.uint8
        ).reshape((int(data.height), int(data.width), 4))
        class_id = np.ascontiguousarray(arr[:, :, 2])  # BGRA -> index 2 is R
        try:
            from PIL import Image as PILImage

            PILImage.fromarray(class_id, mode="L").save(out_path.as_posix())
        except Exception:
            import imageio.v2 as imageio

            imageio.imwrite(out_path.as_posix(), class_id.astype(np.uint8))

    @staticmethod
    def _write_semseg_viz_png(data: Any, out_path: Path) -> bool:
        """Best-effort CityScapes-palette copy for human viewing ONLY.

        Written under semseg_viz/<cam>/ so it can never be mistaken for a
        training label; never read by any trainer/eval/class-weight code.
        """
        try:
            import carla  # type: ignore

            if hasattr(data, "convert"):
                data.convert(carla.ColorConverter.CityScapesPalette)
                data.save_to_disk(str(out_path))
                return True
        except Exception:
            pass
        return False

    def _save_camera_frame(
        self, data: Any, *, out_path: Path, apply_cityscapes: bool
    ) -> Path:
        # Returns the path actually written so the caller can bind the artifact
        # to it (and detect a substituted filename).
        # NOTE: apply_cityscapes must only ever be True for the semseg_viz
        # copy (see _make_sensor_callback). Training labels in semseg_raw/
        # are always written by _write_semseg_raw_png from the raw R channel.
        if apply_cityscapes:
            try:
                import carla  # type: ignore

                if hasattr(data, "convert"):
                    data.convert(carla.ColorConverter.CityScapesPalette)
            except Exception:
                pass
        data.save_to_disk(str(out_path))
        return out_path

    def _write_semseg_frame(
        self, data: Any, *, out_path: Path, viz_path: Optional[Path] = None
    ) -> Path:
        """Persist one semantic frame: raw class-id training label first,
        then (optionally) a palette copy for human viewing.  The palette
        conversion mutates the image in place, so it must run AFTER the raw
        label has been written — never before (C8).

        Returns the training-label path actually written."""
        self._write_semseg_raw_png(data, out_path)
        if viz_path is not None:
            try:
                viz_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            self._write_semseg_viz_png(data, viz_path)
        return out_path

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
            try:
                # P0-2: frame_id is resolved INSIDE the try. Previously
                # _next_frame_id() ran before the try, so a FrameIdMissingError
                # escaped before the finally decrement and permanently leaked
                # _callbacks_in_flight, making every later drain wait forever.
                frame_id = self._next_frame_id(data)
                # Exact frame-id authority: this is the actual CARLA callback
                # frame, recorded before any queueing decision.
                self._record_callback_frame(sensor_name, frame_id)
                if sensor_kind in {"rgb", "semseg_raw", "other"}:
                    image_ext = str(getattr(self.cfg, "image_format", "png") or "png")
                    image_ext = image_ext.lstrip(".").lower() or "png"
                    effective_sensor_kind = (
                        sensor_kind if sensor_kind != "other" else "rgb"
                    )
                    if sensor_kind == "semseg_raw":
                        # C8: semseg_raw/ must hold raw class-id labels. The
                        # palette is only ever written as a separate human
                        # viz copy (segmentation_mode="cityscapes"), never
                        # into the training label.
                        out_path = self._output_path(
                            sensor_name=sensor_name,
                            sensor_kind="semseg_raw",
                            frame_id=frame_id,
                            ext=image_ext,
                        )
                        write_viz = str(
                            getattr(self.cfg, "segmentation_mode", "cityscapes") or ""
                        ).lower() in ("cityscapes", "viz")
                        viz_path: Optional[Path] = None
                        if write_viz:
                            viz_dir = (
                                self.out_dir
                                / "semseg_viz"
                                / self._canonical_sensor_subdir(
                                    sensor_name, "semseg_raw"
                                )
                            )
                            viz_path = viz_dir / f"{int(frame_id):08d}.{image_ext}"
                        self._queue_write_job(
                                sensor_name=sensor_name,
                                sensor_kind="semseg_raw",
                                frame_id=frame_id,
                                sensor=sensor,
                                out_path=out_path,
                                write_fn=lambda data=data, out_path=out_path, viz_path=viz_path: self._write_semseg_frame(
                                data, out_path=out_path, viz_path=viz_path
                            ),
                        )
                        return

                    out_path = self._output_path(
                        sensor_name=sensor_name,
                        sensor_kind=effective_sensor_kind,
                        frame_id=frame_id,
                        ext=image_ext,
                    )
                    self._queue_write_job(
                            sensor_name=sensor_name,
                            sensor_kind=effective_sensor_kind,
                            frame_id=frame_id,
                            sensor=sensor,
                            out_path=out_path,
                            write_fn=lambda data=data, out_path=out_path: self._save_camera_frame(
                            data, out_path=out_path, apply_cityscapes=False
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
                        sensor=sensor,
                        out_path=out_path,
                        write_fn=lambda data=data, out_path=out_path: self._save_lidar_frame(
                            data, out_path=out_path
                        ),
                    )
                    return

            except Exception as exc:
                # P0-2: frame_id is unbound when _next_frame_id() raised, so
                # referencing it directly would raise NameError and mask the
                # original error.
                fid = frame_id if "frame_id" in locals() else "unknown"
                self._record_error(f"save_failed:{sensor_name}:{fid}:{exc}")
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
                sensor_dir = (
                    self.out_dir
                    / sensor_kind
                    / self._canonical_sensor_subdir(sensor_name, sensor_kind)
                )
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
