from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


def wait_for_carla_ready_bounded_subprocess(
    host: str,
    port: int,
    *,
    max_retries: int = 10,
    sleep_s: float = 0.5,
    tick_timeout_s: float = 2.0,
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Bounded CARLA readiness check in a subprocess.

    Motivation: On some Windows installations an incompatible CARLA egg can
    hard-crash the interpreter during import. Running the probe in a subprocess
    keeps the caller alive and yields a JSON result.

    Robustness notes (CARLA 0.9.16):
    - We avoid calling world.tick() in the probe because synchronous worlds can
      block indefinitely if the sim is wedged.
    - We use world.wait_for_tick(timeout) only, and treat a tick failure as a
      non-fatal readiness miss for that attempt.
    """
    payload = {
        "host": host,
        "port": int(port),
        "max_retries": int(max_retries),
        "sleep_s": float(sleep_s),
        "tick_timeout_s": float(tick_timeout_s),
    }

    code = r"""
import json, os, time
def main():
    cfg = json.loads(os.environ.get('UP_CARLA_READY_CFG', '{}'))
    host = cfg.get('host','127.0.0.1')
    port = int(cfg.get('port',2000))
    max_retries = int(cfg.get('max_retries',10))
    sleep_s = float(cfg.get('sleep_s',0.5))
    tick_timeout_s = float(cfg.get('tick_timeout_s',2.0))

    result = {
        'ok': False,
        'host': host,
        'port': port,
        'elapsed_s': 0.0,
        'attempts': 0,
        'tick_ok': False,
        'error': None,
        'server_version': None,
    }
    t0 = time.monotonic()
    for attempt in range(1, max_retries + 1):
        result['attempts'] = attempt
        try:
            import carla
            client = carla.Client(host, port)
            client.set_timeout(max(30.0, float(tick_timeout_s) * 2.0))
            # If server responds, record version (best-effort)
            try:
                result['server_version'] = client.get_server_version()
            except Exception:
                result['server_version'] = None
            world = client.get_world()
            try:
                # CARLA 0.9.16: positional float only
                world.wait_for_tick(float(tick_timeout_s))
                result['tick_ok'] = True
            except Exception as tick_exc:
                result['tick_ok'] = False
                result['error'] = f'tick_failed: {tick_exc}'
                time.sleep(sleep_s)
                continue
            result['ok'] = True
            result['error'] = None
            break
        except ImportError as exc:
            result['error'] = f'import_failed: {exc}'
        except Exception as exc:
            result['error'] = str(exc)
        time.sleep(sleep_s)

    result['elapsed_s'] = round(time.monotonic() - t0, 3)
    print(json.dumps(result))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
"""

    env = dict(os.environ)
    env["UP_CARLA_READY_CFG"] = json.dumps(payload)
    try:
        p = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            timeout=max(8.0, float(max_retries) * float(sleep_s) + float(tick_timeout_s) + 8.0),
            encoding="utf-8",
            errors="replace",
        )
        result = json.loads((p.stdout or "").strip() or "{}")
    except subprocess.TimeoutExpired:
        result = {
            "ok": False,
            "host": host,
            "port": int(port),
            "elapsed_s": 0.0,
            "attempts": 0,
            "tick_ok": False,
            "error": "subprocess_timeout",
            "server_version": None,
        }
    except Exception as exc:
        result = {
            "ok": False,
            "host": host,
            "port": int(port),
            "elapsed_s": 0.0,
            "attempts": 0,
            "tick_ok": False,
            "error": f"subprocess_error: {exc}",
            "server_version": None,
        }

    if out_dir:
        try:
            out_path = Path(out_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            artifact_path = out_path / "carla_ready.json"
            text = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True)
            artifact_path.write_text(text + "\n", encoding="utf-8")
            result["artifact_path"] = str(artifact_path)
        except Exception as write_exc:
            result["artifact_write_error"] = str(write_exc)

    return result


def wait_for_carla_ready_bounded(
    host: str,
    port: int,
    *,
    max_retries: int = 10,
    sleep_s: float = 0.5,
    tick_timeout_s: float = 2.0,
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Bounded CARLA readiness check with artifact output.

    Windows-first: defaults to a subprocess probe unless:
    - carla is already in sys.modules (tests/monkeypatch), OR
    - UP_CARLA_READY_INPROCESS=1

    Robustness notes:
    - Avoids calling world.tick() as a fallback, because sync tick can wedge.
    """
    force_inprocess = "carla" in sys.modules
    if not force_inprocess:
        force_inprocess = os.environ.get("UP_CARLA_READY_INPROCESS", "").strip().lower() in ("1", "true", "yes", "on")
    if not force_inprocess and (sys.platform == "win32" or os.environ.get("UP_SAFE_CARLA_IMPORT", "").strip().lower() in ("1","true","yes","on")):
        return wait_for_carla_ready_bounded_subprocess(
            host,
            port,
            max_retries=max_retries,
            sleep_s=sleep_s,
            tick_timeout_s=tick_timeout_s,
            out_dir=out_dir,
        )

    try:
        from ultimate_pipeline.config.settings import SETTINGS
        tick_timeout_s = getattr(SETTINGS, "CARLA_READY_TICK_TIMEOUT", tick_timeout_s)
    except Exception:
        pass

    result: Dict[str, Any] = {
        "ok": False,
        "host": host,
        "port": port,
        "elapsed_s": 0.0,
        "attempts": 0,
        "tick_ok": False,
        "error": None,
        "server_version": None,
    }

    t0 = time.monotonic()
    for attempt in range(1, max_retries + 1):
        result["attempts"] = attempt
        try:
            carla = importlib.import_module("carla")
            client = carla.Client(host, port)
            client.set_timeout(max(30.0, float(tick_timeout_s) * 2.0))
            try:
                result["server_version"] = client.get_server_version()
            except Exception:
                result["server_version"] = None
            world = client.get_world()
            try:
                world.wait_for_tick(float(tick_timeout_s))
                result["tick_ok"] = True
            except Exception as tick_exc:
                result["tick_ok"] = False
                result["error"] = f"tick_failed: {tick_exc}"
                time.sleep(sleep_s)
                continue

            result["ok"] = True
            result["error"] = None
            break
        except ImportError as exc:
            result["error"] = f"import_failed: {exc}"
        except Exception as exc:
            result["error"] = str(exc)
        time.sleep(sleep_s)

    result["elapsed_s"] = round(time.monotonic() - t0, 3)

    if out_dir:
        try:
            out_path = Path(out_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            artifact_path = out_path / "carla_ready.json"
            text = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True)
            artifact_path.write_text(text + "\n", encoding="utf-8")
            result["artifact_path"] = str(artifact_path)
        except Exception as write_exc:
            result["artifact_write_error"] = str(write_exc)

    return result


def wait_for_carla_ready(host: str, port: int, timeout_s: float, require_tick: bool = True) -> Dict[str, Any]:
    """Legacy readiness helper (best-effort).

    Important: avoids world.tick() fallback because it can wedge in sync worlds.
    """
    start = time.monotonic()
    attempts = 0
    last_error = ""

    timeout_value = float(timeout_s)
    while time.monotonic() - start < timeout_value:
        attempts += 1
        try:
            carla = importlib.import_module("carla")
            client = carla.Client(host, port)
            client.set_timeout(30.0)
            world = client.get_world()
            if require_tick:
                try:
                    world.wait_for_tick(2.0)
                except Exception:
                    # Do not call world.tick() here (may wedge).
                    raise
            return {
                "ok": True,
                "host": host,
                "port": port,
                "timeout_s": timeout_value,
                "require_tick": bool(require_tick),
                "last_error": "",
                "attempts": attempts,
            }
        except ImportError as exc:
            last_error = f"failed to import carla: {exc}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.2)

    return {
        "ok": False,
        "host": host,
        "port": port,
        "timeout_s": timeout_value,
        "require_tick": bool(require_tick),
        "last_error": last_error,
        "attempts": attempts,
    }
