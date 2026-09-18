from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from typing import Any, Dict, Optional

CRASH_SERIALIZATION_ERROR = "SERIALIZATION_ERROR"
CRASH_OPENDRIVE_LOAD_ERROR = "OPENDRIVE_LOAD_ERROR"
CRASH_GPU_DRIVER_ERROR = "GPU_DRIVER_ERROR"
CRASH_CONNECTION_TIMEOUT = "CONNECTION_TIMEOUT"
CRASH_UNKNOWN = "UNKNOWN"

_GPU_TOKENS = (
    "dxgi_error",
    "device removed",
    "device lost",
    "vulkan",
    "d3d",
    "graphics driver",
    "render thread exception",
    "gpu crash",
)


def _carla_preflight_inprocess(host: str = "127.0.0.1", port: int = 2000, timeout_s: float = 8.0) -> Dict[str, Any]:
    """
    Lightweight CARLA preflight:
      - Import CARLA PythonAPI
      - Connect to server (host/port)
      - Capture server version and map name when possible

    Returns dict with keys: ok, client_version, server_version, map_name, error, detail.
    Never raises.
    """
    result: Dict[str, Any] = {
        "ok": False,
        "host": host,
        "port": int(port),
        "timeout_s": float(timeout_s),
        "client_version": None,
        "server_version": None,
        "map_name": None,
        "error": None,
        "detail": None,
        "checked_at": time.time(),
        "streaming": {
            "disabled": os.environ.get("UP_DISABLE_STREAMING", "").strip() in ("1", "true", "yes", "on", "y"),
            "port": int(port) + 1,
            "tcp_reachable": False,
            "warning": None,
        },
    }

    try:
        import carla  # type: ignore

        result["client_version"] = getattr(carla, "__version__", None)
    except Exception as exc:  # pragma: no cover - import-time failures are environment-specific
        result["error"] = "import_failed"
        result["detail"] = str(exc)
        return result

    # Optional streaming port probe (warn-only, never blocks preflight).
    if result["streaming"]["disabled"]:
        result["streaming"]["tcp_reachable"] = False
        result["streaming"]["warning"] = "streaming_port_disabled"
    else:
        try:
            with socket.create_connection((host, int(port) + 1), timeout=min(2.0, float(timeout_s))):
                result["streaming"]["tcp_reachable"] = True
                result["streaming"]["warning"] = None
        except Exception as exc:
            result["streaming"]["tcp_reachable"] = False
            result["streaming"]["warning"] = f"streaming_port_not_reachable: {exc}"

    try:
        client = carla.Client(host, port)
        # Windows-safe: allow slow RPC responses during load_world/get_world.
        client.set_timeout(max(30.0, float(timeout_s)))

        # Some CARLA builds may raise here due to streaming port issues; treat as warn-only.
        try:
            result["server_version"] = client.get_server_version()
        except Exception as exc:
            result["server_version"] = None
            result["server_version_error"] = str(exc)

        # Preflight success depends on RPC + world tick, not streaming.
        world = client.get_world()
        # CARLA 0.9.16: must use positional float, not keyword arg
        world.wait_for_tick(float(min(2.0, float(timeout_s))))

        try:
            carla_map = world.get_map()
            if carla_map:
                result["map_name"] = carla_map.name
        except Exception as exc:
            result["map_error"] = str(exc)

        result["ok"] = True
        return result
    except Exception as exc:  # pragma: no cover - connection failures are runtime-specific
        detail = str(exc)
        result["error"] = "connection_failed"
        result["detail"] = detail
        result["timeout"] = "timeout" in detail.lower() or "timed out" in detail.lower()
        return result


def carla_preflight_subprocess(host: str = "127.0.0.1", port: int = 2000, timeout_s: float = 8.0) -> Dict[str, Any]:
    """CARLA preflight in a subprocess.

    On some Windows setups, importing an incompatible CARLA PythonAPI can *hard-crash*
    the Python interpreter (access violation). A subprocess keeps the orchestrator alive
    and turns "fatal error" into a diagnosable JSON result.
    """
    payload = {"host": host, "port": int(port), "timeout_s": float(timeout_s)}

    code = r"""
import json, os, time
def main():
    cfg = json.loads(os.environ.get('UP_PREFLIGHT_CFG', '{}'))
    host = cfg.get('host','127.0.0.1')
    port = int(cfg.get('port',2000))
    timeout_s = float(cfg.get('timeout_s',8.0))
    # Inline copy of in-process behavior (kept minimal)
    import socket
    result = {
        'ok': False,
        'host': host,
        'port': port,
        'timeout_s': timeout_s,
        'client_version': None,
        'server_version': None,
        'map_name': None,
        'error': None,
        'detail': None,
        'checked_at': time.time(),
        'streaming': {
            'disabled': os.environ.get('UP_DISABLE_STREAMING','').strip().lower() in ('1','true','yes','on','y'),
            'port': port + 1,
            'tcp_reachable': False,
            'warning': None,
        },
    }
    try:
        import carla
        result['client_version'] = getattr(carla, '__version__', None)
    except Exception as exc:
        result['error'] = 'import_failed'
        result['detail'] = str(exc)
        print(json.dumps(result))
        return 0

    if result['streaming']['disabled']:
        result['streaming']['tcp_reachable'] = False
        result['streaming']['warning'] = 'streaming_port_disabled'
    else:
        try:
            with socket.create_connection((host, port + 1), timeout=min(2.0, timeout_s)):
                result['streaming']['tcp_reachable'] = True
        except Exception as exc:
            result['streaming']['tcp_reachable'] = False
            result['streaming']['warning'] = f'streaming_port_not_reachable: {exc}'

    try:
        client = carla.Client(host, port)
        client.set_timeout(max(30.0, timeout_s))
        try:
            result['server_version'] = client.get_server_version()
        except Exception as exc:
            result['server_version'] = None
            result['server_version_error'] = str(exc)
        world = client.get_world()
        world.wait_for_tick(float(min(2.0, timeout_s)))
        try:
            m = world.get_map()
            result['map_name'] = m.name if m else None
        except Exception as exc:
            result['map_error'] = str(exc)
        result['ok'] = True
    except Exception as exc:
        detail = str(exc)
        result['error'] = 'connection_failed'
        result['detail'] = detail
        result['timeout'] = ('timeout' in detail.lower()) or ('timed out' in detail.lower())

    print(json.dumps(result))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
"""

    env = dict(os.environ)
    env["UP_PREFLIGHT_CFG"] = json.dumps(payload)
    try:
        p = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            timeout=max(5.0, float(timeout_s) + 5.0),
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "host": host,
            "port": int(port),
            "timeout_s": float(timeout_s),
            "error": "subprocess_timeout",
            "detail": "carla_preflight_subprocess timed out",
            "client_version": None,
            "server_version": None,
            "map_name": None,
        }

    if p.returncode != 0 and not (p.stdout or "").strip():
        return {
            "ok": False,
            "host": host,
            "port": int(port),
            "timeout_s": float(timeout_s),
            "error": "subprocess_failed",
            "detail": (p.stderr or "").strip()[:2000],
            "client_version": None,
            "server_version": None,
            "map_name": None,
        }
    try:
        return json.loads((p.stdout or "").strip() or "{}")
    except Exception:
        return {
            "ok": False,
            "host": host,
            "port": int(port),
            "timeout_s": float(timeout_s),
            "error": "invalid_json",
            "detail": (p.stdout or "").strip()[:2000] or (p.stderr or "").strip()[:2000],
            "client_version": None,
            "server_version": None,
            "map_name": None,
        }


def carla_preflight(host: str = "127.0.0.1", port: int = 2000, timeout_s: float = 8.0) -> Dict[str, Any]:
    """Lightweight CARLA preflight.

    By default this runs in a subprocess on Windows to avoid import-time hard crashes.
    You can force in-process behavior with UP_CARLA_PREFLIGHT_INPROCESS=1.

    If carla is already in sys.modules (e.g. monkeypatched by tests), we run in-process
    so that the patched module is used.
    """
    # If carla is already loaded (e.g. monkeypatched by tests), use in-process path
    # so that the patched module is actually used.
    if "carla" in sys.modules:
        return _carla_preflight_inprocess(host=host, port=port, timeout_s=timeout_s)

    force_inprocess = os.environ.get("UP_CARLA_PREFLIGHT_INPROCESS", "").strip().lower() in ("1", "true", "yes", "on")
    if (sys.platform == "win32" and not force_inprocess) or os.environ.get("UP_SAFE_CARLA_IMPORT", "").strip().lower() in ("1", "true", "yes", "on"):
        return carla_preflight_subprocess(host=host, port=port, timeout_s=timeout_s)
    return _carla_preflight_inprocess(host=host, port=port, timeout_s=timeout_s)


def classify_carla_crash(
    stderr: str,
    *,
    preflight: Optional[Dict[str, Any]] = None,
    status_before: Optional[Dict[str, Any]] = None,
    status_after: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Classify common CARLA failure signatures for downstream crash reports.
    Uses stderr text plus optional preflight/status info.
    """
    low = (stderr or "").lower()

    if preflight and not preflight.get("ok") and preflight.get("error") == "connection_failed":
        return CRASH_CONNECTION_TIMEOUT

    if status_after and not status_after.get("tcp_reachable", True):
        return CRASH_CONNECTION_TIMEOUT

    if "serialization" in low or "serialize" in low or "deserialize" in low:
        return CRASH_SERIALIZATION_ERROR

    if "opendrive" in low or "xodr" in low:
        return CRASH_OPENDRIVE_LOAD_ERROR

    if any(token in low for token in _GPU_TOKENS):
        return CRASH_GPU_DRIVER_ERROR

    if "timeout" in low or "timed out" in low:
        return CRASH_CONNECTION_TIMEOUT

    return CRASH_UNKNOWN


def write_crash_report(out_dir: str, payload: Dict[str, Any], filename: str = "crash_report.json") -> str:
    """
    Persist a crash report payload into out_dir/filename using deterministic JSON.
    Returns the full file path.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    if not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path
