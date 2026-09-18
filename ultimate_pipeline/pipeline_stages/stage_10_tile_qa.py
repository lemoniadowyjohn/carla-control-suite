# REFAC_VERSION = "v5_preserve"
# NOTE: This file is auto-extracted from ultimate_pipeline/main_pipeline.py.
# It delegates to original helpers by injecting main_pipeline globals at runtime.

from __future__ import annotations

def _inject_main_pipeline_globals():
    # Import is inside to avoid import-time side effects/cycles.
    from ultimate_pipeline import main_pipeline as _mp  # type: ignore
    g = globals()
    for k, v in _mp.__dict__.items():
        if k.startswith("__"):
            continue
        if k in ("_inject_main_pipeline_globals",):
            continue
        # Don't overwrite locally-defined names (e.g., stage functions).
        g.setdefault(k, v)


def _step10_tile_qa(self, graph_path: Optional[str], final_out: str) -> None:
    """
    Crash-proof STEP 10 Unified Tile QA with progress output.

    This version avoids the "looks frozen" issue by printing heartbeat progress
    while the supervisor subprocess runs.

    Guarantee preserved:
    - Parent process never imports/uses carla
    - Tile QA happens only in subprocesses
    """
    _inject_main_pipeline_globals()
    import os
    import sys
    import json
    import time
    import subprocess
    from pathlib import Path

    print(
        "\n============== 🧪 STEP 10: Unified Tile QA (crash-proof subprocess) =============="
    )

    # Bugfix: STEP 10 must not run when simulation gate is disabled.
    if not bool(getattr(self.settings, "ENABLE_SIMULATION_GATE", False)):
        status_path = os.path.join(self.out_dir, "step10_tile_qa_status.json")
        status = {
            "status": "SKIP",
            "reason": "simulation_gate_disabled",
            "ENABLE_SIMULATION_GATE": False,
        }
        try:
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2, ensure_ascii=True, default=str)
        except Exception:
            pass
        print(
            f"[STEP10] skipped: simulation gate disabled in settings (see {status_path})"
        )
        return

    # --- CARLA availability guard (thesis stability) ---

    # If CARLA is disabled/unreachable OR cannot tick a world, skip STEP10 tile QA.

    try:
        import os as _os, json as _json

        from pathlib import Path as _Path

        from ultimate_pipeline.tools.carla_preflight import (
            run_preflight as _carla_preflight,
        )

        reach = None

        if _os.getenv("UP_DISABLE_CARLA", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            _skip = True

            _reason = "carla_disabled_env"

        else:
            reach_path = _Path(self.out_dir) / "carla_reachability.json"

            if reach_path.exists():
                try:
                    reach = _json.loads(
                        reach_path.read_text(encoding="utf-8", errors="replace")
                    )

                except Exception:
                    reach = {}

            if not reach:
                # preflight now (optionally restart if env flags set)

                autostart = _os.getenv(
                    "UP_CARLA_AUTOSTART", ""
                ).strip().lower() in ("1", "true", "yes", "on")

                force_restart = _os.getenv(
                    "UP_CARLA_FORCE_RESTART", ""
                ).strip().lower() in ("1", "true", "yes", "on")

                reach = _carla_preflight(
                    host=getattr(self.settings, "CARLA_HOST", "127.0.0.1"),
                    port=int(getattr(self.settings, "CARLA_PORT", 2000)),
                    out_dir=self.out_dir,
                    autostart=autostart,
                    force_restart=force_restart,
                )

            _skip = not bool(reach.get("ok", False))

            _reason = "carla_not_tick_ready" if _skip else "carla_ok"

        if _skip and _os.getenv(
            "UP_SKIP_STEP10_WHEN_CARLA_DOWN", "1"
        ).strip().lower() in ("1", "true", "yes", "on"):
            status_path = _Path(self.out_dir) / "step10_tile_qa_status.json"

            status = {
                "status": "SKIP",
                "reason": _reason,
                "carla_reachability": reach,
            }

            try:
                status_path.write_text(
                    _json.dumps(status, indent=2, ensure_ascii=True, default=str),
                    encoding="utf-8",
                )

            except Exception:
                pass

            print(f"[STEP10] skipped: {_reason} (see {status_path})")

            return

    except Exception as _e:
        print(f"[STEP10] CARLA guard error (continuing): {_e}")

    if not getattr(self.settings, "ENABLE_TILING", False):
        print("⏭️ Tiling disabled — skipping STEP 10 tile QA.")
        return

    tiles_dir = os.path.join(self.out_dir, "tiles")
    if not os.path.isdir(tiles_dir):
        print(f"⚠️ STEP 10: tiles_dir missing: {tiles_dir} — skipping.")
        return

    if os.getenv("UP_SKIP_STEP10_TILE_QA", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        print("⏭️ STEP 10 skipped due to UP_SKIP_STEP10_TILE_QA.")
        try:
            status_path = os.path.join(self.out_dir, "step10_tile_qa_status.json")
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"status": "SKIP", "reason": "UP_SKIP_STEP10_TILE_QA"},
                    f,
                    indent=2,
                )
        except Exception:
            pass
        return

    # Count tiles for progress
    tile_paths = sorted(Path(tiles_dir).glob("tile_*.xodr")) or sorted(
        Path(tiles_dir).glob("*.xodr")
    )
    total_tiles = len(tile_paths)
    print(f"[STEP10] tiles detected: {total_tiles}")

    qa_out_dir = os.path.join(self.out_dir, "step10_tile_qa")
    os.makedirs(qa_out_dir, exist_ok=True)
    qa_log = os.path.join(qa_out_dir, "step10_tile_qa_supervisor.log")
    jsonl_path = os.path.join(qa_out_dir, "tile_results.jsonl")

    host = getattr(self.settings, "CARLA_HOST", "127.0.0.1")
    port = int(getattr(self.settings, "CARLA_PORT", 2000))

    carla_exe = (
        getattr(self.settings, "CARLA_EXE", None)
        or getattr(self.settings, "CARLA_SERVER_EXE", None)
        or os.getenv("UP_CARLA_EXE")
        or os.getenv("CARLA_EXE")
        or ""
    )

    timeout_s = int(getattr(self.settings, "TILE_WORKER_TIMEOUT_S", 180))
    restart_after = int(
        getattr(self.settings, "TILE_QA_RESTART_AFTER_CONSEC_FAIL", 5)
    )
    restart_on_crash = int(
        getattr(self.settings, "TILE_QA_RESTART_ON_HARD_CRASH", 1)
    )

    strict = os.getenv("UP_STRICT_TILE_QA", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    readiness_fix_enabled = os.getenv(
        "UP_CARLA_TILE_QA_READINESS_FIX", ""
    ).strip().lower() in ("1", "true", "yes", "on")
    if not readiness_fix_enabled:
        readiness_fix_enabled = bool(
            getattr(self.settings, "CARLA_TILE_QA_READINESS_FIX", False)
        )
    if readiness_fix_enabled:
        os.environ["UP_CARLA_TILE_QA_READINESS_FIX"] = "1"
        print("[STEP10] readiness fix enabled via UP_CARLA_TILE_QA_READINESS_FIX=1")

    def _env_or_setting_int(env_name: str, setting_name: str, default: int) -> int:
        raw = os.getenv(env_name, "").strip()
        if raw:
            try:
                return int(raw)
            except Exception:
                return int(default)
        try:
            return int(getattr(self.settings, setting_name, default))
        except Exception:
            return int(default)

    def _env_or_setting_float(env_name: str, setting_name: str, default: float) -> float:
        raw = os.getenv(env_name, "").strip()
        if raw:
            try:
                return float(raw)
            except Exception:
                return float(default)
        try:
            return float(getattr(self.settings, setting_name, default))
        except Exception:
            return float(default)

    connect_retries = max(
        1,
        _env_or_setting_int(
            "UP_TILE_QA_CONNECT_RETRIES", "TILE_QA_CONNECT_RETRIES", 1
        ),
    )
    load_retries = max(
        1,
        _env_or_setting_int(
            "UP_TILE_QA_WORLD_LOAD_RETRIES", "TILE_QA_WORLD_LOAD_RETRIES", 1
        ),
    )
    retry_backoff_s = max(
        0.0,
        _env_or_setting_float(
            "UP_TILE_QA_RETRY_BACKOFF_S", "TILE_QA_RETRY_BACKOFF_S", 0.5
        ),
    )
    readiness_timeout_s = max(
        0.0,
        _env_or_setting_float(
            "UP_TILE_QA_WAIT_FOR_SIMULATOR_TIMEOUT_S",
            "TILE_QA_WAIT_FOR_SIMULATOR_TIMEOUT_S",
            0.0,
        ),
    )
    tick_timeout_s = max(
        0.1,
        _env_or_setting_float(
            "UP_TILE_QA_TICK_TIMEOUT_S", "TILE_QA_TICK_TIMEOUT_S", 5.0
        ),
    )
    warmup_ticks_connect = max(
        0,
        _env_or_setting_int(
            "UP_TILE_QA_CONNECT_WARMUP_TICKS", "TILE_QA_CONNECT_WARMUP_TICKS", 0
        ),
    )
    warmup_ticks_post_load = max(
        0,
        _env_or_setting_int(
            "UP_TILE_QA_POST_LOAD_WARMUP_TICKS", "TILE_QA_POST_LOAD_WARMUP_TICKS", 0
        ),
    )

    cmd = [
        sys.executable,
        "-u",
        "-m",
        "ultimate_pipeline.tile_validation.step10_tile_qa_supervisor",
        "--tiles_dir",
        tiles_dir,
        "--out_dir",
        qa_out_dir,
        "--host",
        str(host),
        "--port",
        str(port),
        "--timeout_s",
        str(timeout_s),
        "--restart_after_consecutive_failures",
        str(restart_after),
        "--restart_on_hard_crash",
        "1" if restart_on_crash else "0",
        "--no_spawn",
        "1",
        "--strict",
        "1" if strict else "0",
        "--connect_retries",
        str(connect_retries),
        "--load_retries",
        str(load_retries),
        "--retry_backoff_s",
        str(retry_backoff_s),
        "--readiness_timeout_s",
        str(readiness_timeout_s),
        "--tick_timeout_s",
        str(tick_timeout_s),
        "--warmup_ticks_connect",
        str(warmup_ticks_connect),
        "--warmup_ticks_post_load",
        str(warmup_ticks_post_load),
    ]
    if carla_exe:
        cmd += ["--carla_exe", str(carla_exe)]

    print(f"[STEP10] supervisor log: {qa_log}")
    print(f"[STEP10] tip: tail it with: Get-Content '{qa_log}' -Tail 120 -Wait")
    print(f"[STEP10] launching supervisor...")

    # Run supervisor but keep console alive with heartbeat
    rc = -1
    log_f = None
    try:
        log_f = open(qa_log, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)

        last_done = -1
        last_print_t = 0.0
        start_t = time.time()

        while proc.poll() is None:
            time.sleep(2.0)
            now = time.time()
            if now - last_print_t < 5.0:
                continue
            last_print_t = now

            done = 0
            last_row = None
            try:
                if os.path.exists(jsonl_path):
                    # Count lines (small N, OK)
                    with open(
                        jsonl_path, "r", encoding="utf-8", errors="replace"
                    ) as f:
                        lines = f.readlines()
                    done = len(lines)
                    if lines:
                        try:
                            last_row = json.loads(lines[-1])
                        except Exception:
                            last_row = None
            except Exception:
                done = 0
                last_row = None

            if done != last_done:
                last_done = done

            msg = f"[STEP10] progress {done}/{total_tiles if total_tiles else '?'} tiles"
            if isinstance(last_row, dict):
                msg += f" | last={last_row.get('tile_id')} ok={last_row.get('ok')} reason={last_row.get('reason')} rc={last_row.get('worker_returncode')}"
            msg += f" | elapsed={int(now - start_t)}s"
            print(msg, flush=True)

        rc = int(proc.returncode) if proc.returncode is not None else -1

    except Exception as e:
        rc = -1
        try:
            with open(qa_log, "a", encoding="utf-8", errors="replace") as f:
                f.write(f"\n[STEP10] Supervisor launch/monitor exception: {e}\n")
        except Exception:
            pass
    finally:
        try:
            if log_f is not None:
                log_f.close()
        except Exception:
            pass

    status_path = os.path.join(self.out_dir, "step10_tile_qa_status.json")
    status = {
        "status": "OK" if rc == 0 else "FAIL",
        "return_code": rc,
        "qa_out_dir": qa_out_dir,
        "qa_log": qa_log,
        "carla_exe": carla_exe or None,
        "strict": bool(strict),
    }

    summary_path = os.path.join(qa_out_dir, "tile_results.summary.json")
    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                status["summary"] = json.load(f)
        except Exception:
            status["summary"] = None

    try:
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, ensure_ascii=True)
        print(f"[STEP10] status -> {status_path}")
    except Exception:
        pass

    if strict and rc != 0:
        raise RuntimeError(
            f"❌ STEP 10 tile QA supervisor failed (rc={rc}). See: {qa_log}"
        )

    print(f"[STEP10] Crash-proof tile QA finished (rc={rc}) -> {qa_out_dir}")


def _step10c_road_perception_screenshots(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    self._mark_stage("step10c_road_perception")
    s = self.settings

    if not getattr(s, "ENABLE_STEP10C", True):
        print("⏭️ Skipping STEP 10C (disabled via settings).")
        return

    # If CARLA is intentionally disabled, do not attempt any 10C/10D/10E work.
    # This keeps offline runs stable and makes the skip explicit in artifacts.
    carla_disabled_setting = not bool(getattr(s, "ENABLE_CARLA", True))
    carla_disabled_env = os.getenv("UP_DISABLE_CARLA", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if carla_disabled_setting or carla_disabled_env:
        status_path = os.path.join(self.out_dir, "step10c_status.json")
        status = {
            "status": "SKIP",
            "reason": "carla_disabled",
            "ENABLE_CARLA": (not carla_disabled_setting),
            "UP_DISABLE_CARLA": os.getenv("UP_DISABLE_CARLA", ""),
        }
        try:
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2, ensure_ascii=True, default=str)
            print(
                f"[STEP10C] CARLA disabled → skipping 10C/10D/10E (status -> {status_path})"
            )
        except Exception as e:
            print(f"[STEP10C] CARLA disabled; status write failed: {e}")
        return

    if os.getenv(
        "UP_REQUIRE_MAP_ACCEPTANCE_FOR_PERCEPTION", ""
    ).strip().lower() in ("1", "true", "yes", "on"):
        acceptance = getattr(self, "map_acceptance", None)
        if not isinstance(acceptance, dict) or not acceptance.get("valid", False):
            try:
                gate_path = os.path.join(self.out_dir, "perception_gate.json")
                with open(gate_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "status": "SKIP",
                            "reason": "map_acceptance_failed",
                            "map_acceptance": acceptance,
                        },
                        f,
                        indent=2,
                        default=str,
                    )
                print(
                    f"[STEP10C] perception skipped due to map acceptance -> {gate_path}"
                )
            except Exception as e:
                print(f"[STEP10C] perception skip report write failed: {e}")
            return

    world = None
    map_name = "UNKNOWN"

    if self._carla_isolation_enabled():
        # In isolation mode we never import/use CARLA in this process.
        # Ensure the *final* map is loaded into the CARLA server via subprocess,
        # so subsequent subprocess checks operate on the correct world.
        smoke = self._carla_smoke_load_subprocess(
            xodr_path=final_out,
            label="step10c_load_final",
            spawn_ego=False,
            tick_frames=2,
            screenshot=False,
            timeout_s=int(getattr(self.settings, "CARLA_TIMEOUT_S", 180.0)),
        )
        try:
            outp = os.path.join(self.out_dir, "step10c_carla_load_final.json")
            with open(outp, "w", encoding="utf-8") as f:
                json.dump(smoke, f, indent=2, default=str, ensure_ascii=True)
        except Exception:
            pass

        payload = smoke.get("payload") if isinstance(smoke, dict) else None
        load_ok = (
            bool(payload.get("load_ok", False))
            if isinstance(payload, dict)
            else False
        )
        if not load_ok:
            status_path = os.path.join(self.out_dir, "step10c_status.json")
            status = {
                "status": "SKIP",
                "reason": "carla_load_final_failed",
                "smoke_payload_path": smoke.get("payload_path"),
                "smoke": smoke,
            }
            try:
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump(status, f, indent=2, ensure_ascii=True, default=str)
                print(
                    f"[STEP10C] CARLA load-final failed; skipping (status -> {status_path})"
                )
            except Exception as write_exc:
                print(f"[STEP10C] status write failed: {write_exc}")
            return
        spawn_n = (
            int(payload.get("spawn_points_count", 0))
            if isinstance(payload, dict)
            else 0
        )
        print(
            f"[STEP10C] Final map loaded in CARLA (isolation). spawn_points={spawn_n}"
        )
    else:
        try:
            world = self._ensure_carla_ready_for_step10c()
        except Exception as e:
            status_path = os.path.join(self.out_dir, "step10c_status.json")
            status = {
                "status": "SKIP",
                "reason": "carla_unavailable",
                "error": str(e),
            }
            try:
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump(status, f, indent=2, ensure_ascii=True)
                print(
                    f"[STEP10C] CARLA unavailable; skipping (status -> {status_path})"
                )
            except Exception as write_exc:
                print(
                    f"[STEP10C] CARLA unavailable; status write failed: {write_exc}"
                )
            return
        try:
            map_name = (
                world.get_map().name if world and world.get_map() else "UNKNOWN"
            )
        except Exception:
            map_name = "UNKNOWN"
        print(f"[STEP10C] Using CARLA map: {map_name}")

    if getattr(s, "ENABLE_ROAD_DEFECT_SCAN", False):
        print("\n============== 🔍 STEP 10C: Road Defect Scan ==============")
        out_path = os.path.join(self.out_dir, "road_defects.json")

        if self._carla_isolation_enabled():
            host, port = self._carla_host_port()
            duration_sec = float(getattr(s, "ROAD_DEFECT_DURATION_SEC", 60.0))
            num_vehicles = int(getattr(s, "ROAD_DEFECT_NUM_VEHICLES", 5))

            worker = f"""import json, time
import carla
from ultimate_pipeline.carla_tools.road_defect_detector import RoadDefectDetector

host = {host!r}
port = {int(port)}
duration = {float(duration_sec)}
num_vehicles = {int(num_vehicles)}
out_path = {out_path!r}

client = carla.Client(host, port)
client.set_timeout(60.0)
world = client.get_world()

detector = RoadDefectDetector(client)
events = detector.scan_world(world, duration_sec=duration, num_vehicles=num_vehicles)

with open(out_path, "w", encoding="utf-8") as f:
json.dump([e.__dict__ for e in events], f, indent=2, default=str, ensure_ascii=True)

print(f"OK road_defects={{len(events)}} -> {{out_path}}")
"""

            res = self._run_carla_worker_script(
                name="step10c_road_defects",
                code=worker,
                timeout_s=int(max(60, duration_sec + 120)),
            )
            try:
                st = {
                    "status": "PASS" if res.get("ok") else "FAIL",
                    "run": res,
                    "out_path": out_path,
                }
                with open(
                    os.path.join(self.out_dir, "step10c_road_defects_status.json"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump(st, f, indent=2, default=str, ensure_ascii=True)
            except Exception:
                pass
            if not res.get("ok"):
                print(
                    f"⚠️ Road defect subprocess failed; continuing. See: {res.get('log_path')}"
                )
        else:
            from ultimate_pipeline.carla_tools.road_defect_detector import (
                RoadDefectDetector,
            )

            detector = RoadDefectDetector(self.client)
            events = detector.scan_world(world)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump([e.__dict__ for e in events], f, indent=2, default=str)
            print(f"📊 Road defects written -> {out_path}")
    else:
        print("⏭️ Road defect scan disabled.")
    if getattr(s, "ENABLE_LOCAL_PERCEPTION", False):
        print("\n============== 👁️ STEP 10D: Local Perception QA ==============")

        if self._carla_isolation_enabled():
            host, port = self._carla_host_port()
            map_arg = getattr(s, "CARLA_MAP_NAME", "Ingolstadt")
            worker = f"""import carla
import inspect

from ultimate_pipeline.carla_tools.local_perception_runner import LocalPerceptionRunner

host = {host!r}
port = {int(port)}
map_arg = {map_arg!r}

client = carla.Client(host, port)
client.set_timeout(120.0)

_sig = inspect.signature(LocalPerceptionRunner.__init__)
if "map_name" in _sig.parameters:
runner = LocalPerceptionRunner(client, map_name=map_arg)
else:
runner = LocalPerceptionRunner(client)

runner.run()
print("OK local_perception")
"""
            res = self._run_carla_worker_script(
                name="step10c_local_perception",
                code=worker,
                timeout_s=int(getattr(s, "LOCAL_PERCEPTION_TIMEOUT_S", 600)),
            )
            try:
                st = {"status": "PASS" if res.get("ok") else "FAIL", "run": res}
                with open(
                    os.path.join(
                        self.out_dir, "step10c_local_perception_status.json"
                    ),
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump(st, f, indent=2, default=str, ensure_ascii=True)
            except Exception:
                pass
            if not res.get("ok"):
                print(
                    f"⚠️ Local perception subprocess failed; continuing. See: {res.get('log_path')}"
                )
        else:
            from ultimate_pipeline.carla_tools.local_perception_runner import (
                LocalPerceptionRunner,
            )
            import inspect

            _sig = inspect.signature(LocalPerceptionRunner.__init__)
            map_arg = getattr(s, "CARLA_MAP_NAME", "Ingolstadt")
            if "map_name" in _sig.parameters:
                runner = LocalPerceptionRunner(self.client, map_name=map_arg)
            else:
                runner = LocalPerceptionRunner(self.client)
            try:
                runner.run()
            except Exception as e:
                print(f"❌ Local perception runner failed: {e}")
    else:
        print("⏭️ Local perception QA disabled.")

    # Optional thesis-grade perception capture (pair_manifest.json + recording_summary.json)
    # This is separate from LocalPerceptionRunner (which is QA-oriented).
    thesis_capture_enabled = bool(
        getattr(s, "ENABLE_THESIS_PERCEPTION_CAPTURE", False)
    ) or (
        os.getenv("UP_ENABLE_THESIS_PERCEPTION_CAPTURE", "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    if thesis_capture_enabled:
        print(
            "\n============== 🎓 STEP 10D2: Thesis Sensor Rig Capture =============="
        )
        host, port = self._carla_host_port()
        streaming_port = int(getattr(s, "CARLA_STREAMING_PORT", int(port) + 1))
        out_dir = os.path.join(self.out_dir, "perception_thesis")
        os.makedirs(out_dir, exist_ok=True)
        frames = int(getattr(s, "THESIS_PERCEPTION_FRAMES", 200))
        fps = float(getattr(s, "THESIS_PERCEPTION_FPS", 10.0))
        timeout_s = int(
            getattr(
                s,
                "THESIS_PERCEPTION_TIMEOUT_S",
                max(300, int(frames / max(fps, 1.0)) + 180),
            )
        )
        log_path = os.path.join(
            self.out_dir, "_tmp_workers", "step10d2_thesis_perception.log"
        )
        cmd = [
            sys.executable,
            "-u",
            "-m",
            "ultimate_pipeline.tools.run_perception_safe",
            "--manual-town",
            str(getattr(s, "CARLA_MAP_NAME", "AUTO")),
            "--xodr-in",
            str(final_out),
            "--out",
            str(out_dir),
            "--frames",
            str(frames),
            "--fps",
            str(fps),
            "--host",
            str(host),
            "--port",
            str(int(port)),
            "--streaming-port",
            str(int(streaming_port)),
            "--min-frames",
            str(frames),
        ]
        # By default, include semantic segmentation labels for training (disable with UP_THESIS_CAPTURE_SEG=0)
        if os.getenv("UP_THESIS_CAPTURE_SEG", "1").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            cmd.append("--seg")
            cmd += [
                "--seg-converter",
                os.getenv("UP_THESIS_CAPTURE_SEG_CONVERTER", "cityscapes"),
            ]
        if os.getenv("UP_PERCEPTION_FAIL_NONZERO", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            cmd.append("--fail-nonzero")
        # Run as subprocess even in non-isolation mode for stability (CARLA can hard-crash Python on Windows).
        res = self._run_subprocess(cmd, log_path=log_path, timeout_s=timeout_s)
        status_path = os.path.join(
            self.out_dir, "step10d2_thesis_perception_status.json"
        )
        status = {
            "status": "PASS" if res.get("ok") else "FAIL",
            "run": res,
            "out_dir": out_dir,
            "log_path": log_path,
        }
        try:
            # Attach summary if present
            rs = os.path.join(out_dir, "recording_summary.json")
            if os.path.exists(rs):
                with open(rs, "r", encoding="utf-8") as f:
                    status["recording_summary"] = json.load(f)
        except Exception:
            pass
        try:
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2, ensure_ascii=True, default=str)
            print(f"[STEP10D2] thesis perception status -> {status_path}")
        except Exception as e:
            print(f"[STEP10D2] status write failed: {e}")
        if not res.get("ok"):
            print(
                f"⚠️ Thesis perception subprocess failed; continuing. See: {log_path}"
            )

    # ------------------------------------------------------------
    # STEP 10D3: ScenarioRunner (optional, controlled scenarios)
    # ------------------------------------------------------------
    # CRITICAL: ScenarioRunner MUST run AFTER perception capture completes.
    # Both require exclusive CARLA tick ownership. Running them concurrently
    # causes tick conflicts and crashes. The sequential ordering above
    # (10D2 thesis perception -> 10D3 ScenarioRunner) enforces this.
    # ------------------------------------------------------------
    if os.getenv("UP_ENABLE_SCENARIORUNNER", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        xosc = os.getenv("UP_SCENARIO_XOSC", "").strip()
        if not xosc:
            print(
                "[STEP10D3] UP_ENABLE_SCENARIORUNNER=1 but UP_SCENARIO_XOSC not set; skipping."
            )
        else:
            try:
                import os as _os

                scenario_name = _os.path.splitext(_os.path.basename(xosc))[0]
                out_sub = (
                    os.getenv("UP_SCENARIORUNNER_OUT_SUBDIR", "scenarios").strip()
                    or "scenarios"
                )
                out_s = _os.path.join(self.out_dir, out_sub, scenario_name)
                timeout_s = int(
                    float(os.getenv("UP_SCENARIORUNNER_TIMEOUT_S", "900"))
                )
                cmd = [
                    sys.executable,
                    "-m",
                    "ultimate_pipeline.tools.run_scenariorunner_once",
                    "--xosc",
                    xosc,
                    "--host",
                    str(getattr(s, "CARLA_HOST", "127.0.0.1")),
                    "--port",
                    str(int(getattr(s, "CARLA_PORT", 2000))),
                    "--timeout-s",
                    str(timeout_s),
                    "--out",
                    out_s,
                ]
                res = self._run_subprocess(
                    cmd,
                    log_path=_os.path.join(out_s, "scenariorunner_driver.log"),
                    timeout_s=timeout_s + 60,
                )
                try:
                    import json as _json

                    with open(
                        _os.path.join(
                            self.out_dir, "step10d3_scenariorunner_status.json"
                        ),
                        "w",
                        encoding="utf-8",
                    ) as f:
                        _json.dump(res, f, indent=2, ensure_ascii=True, default=str)
                except Exception:
                    pass
                if not res.get("ok", False):
                    print(f"[STEP10D3] ScenarioRunner failed (see {out_s}).")
            except Exception as _e:
                print(f"[STEP10D3] ScenarioRunner integration error: {_e}")

    if getattr(s, "ENABLE_SCREENSHOTS", True):
        print("\n============== 📸 STEP 10E: Screenshot Generation ==============")
        ss_dir = os.path.join(self.out_dir, "screenshots")
        os.makedirs(ss_dir, exist_ok=True)
        status_path = os.path.join(ss_dir, "screenshot_status.json")
        gate_path = os.path.join(self.out_dir, "gate_failures.json")
        if os.path.exists(gate_path):
            try:
                with open(gate_path, "r", encoding="utf-8") as f:
                    gate_failures = json.load(f) or {}
                if any("lane_link" in str(k) for k in gate_failures.keys()):
                    status = {
                        "status": "SKIP",
                        "failure_reason": "lane_link_targets_failed",
                    }
                    with open(status_path, "w", encoding="utf-8") as f:
                        json.dump(status, f, indent=2, ensure_ascii=True)
                    print("⏭️ Screenshot tool skipped due to lane link failures.")
                    return
            except Exception:
                pass
        import glob

        pre_existing = set(glob.glob(os.path.join(ss_dir, "*.png")))

        def _truncate(text: str, limit: int = 4000) -> str:
            if not text:
                return ""
            return text if len(text) <= limit else text[:limit]

        cmd = [
            sys.executable,
            "-m",
            "ultimate_pipeline.tools.carla_screenshot_once",
            "--host",
            str(s.CARLA_HOST),
            "--port",
            str(s.CARLA_PORT),
            "--out",
            ss_dir,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            stdout_text = _truncate(result.stdout or "")
            stderr_text = _truncate(result.stderr or "")
            if stdout_text:
                print(stdout_text)
            if stderr_text:
                print(stderr_text)
            if result.returncode != 0:
                status = {
                    "status": "FAIL",
                    "failure_reason": f"tool_failed_rc_{result.returncode}",
                    "return_code": result.returncode,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                }
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump(status, f, indent=2, ensure_ascii=True)
                print("⏭️ Screenshot tool failed; continuing.")
            else:
                new_files = [
                    p
                    for p in glob.glob(os.path.join(ss_dir, "*.png"))
                    if p not in pre_existing
                ]
                status = {
                    "status": "PASS",
                    "paths": new_files,
                }
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump(status, f, indent=2, ensure_ascii=True)
                print("✅ Screenshot tool completed.")
        except subprocess.TimeoutExpired as e:
            status = {
                "status": "FAIL",
                "failure_reason": "tool_timeout",
                "return_code": None,
                "stdout": _truncate(getattr(e, "stdout", "") or ""),
                "stderr": _truncate(getattr(e, "stderr", "") or ""),
            }
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2, ensure_ascii=True)
            print("⏭️ Screenshot tool timeout; continuing.")
        except Exception as e:
            status = {
                "status": "FAIL",
                "failure_reason": f"tool_exception: {e}",
                "return_code": None,
                "stdout": "",
                "stderr": "",
            }
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2, ensure_ascii=True)
            print(f"⏭️ Screenshot tool exception: {e}")
    else:
        print("⏭️ Screenshot generator disabled.")
