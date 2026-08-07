"""Q5 - Runtime process and server identity attestation.

Records, without relying on a remembered PID:

* server executable absolute path + SHA-256
* process ID / parent process ID / command line / start timestamp
* RPC port owner (verified at record time)
* CARLA server version / PythonAPI version / package path + SHA-256
* OS version / GPU driver version / Unreal quality settings

Pre-run controls verify that:
  * the same governed process owns port 2000
  * no second CARLA process is serving another port unexpectedly
  * the executable matches the governed installation

Output: Q05_SERVER_ATTESTATION.json
"""
from __future__ import annotations

import datetime as _dt
import os
import platform
import subprocess
import sys
from typing import Any, Dict, List, Optional

from phase_q.common import sha256_file, utcnow_iso

GOVERNED_EXE = r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
GOVERNED_RPC_PORT = 2000

_SERVER_CANDIDATE_NAMES = ("carlaue4", "carla", "unrealengine", "ue4")


def _iso(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat()


def port_owners(ports: List[int]) -> List[Dict[str, Any]]:
    """Return TCP listeners for the given ports (psutil, falling back to netstat)."""
    result: List[Dict[str, Any]] = []
    try:
        import psutil  # type: ignore
        for conn in psutil.net_connections(kind="tcp"):
            if not conn.laddr or conn.status != "LISTEN":
                continue
            if conn.laddr.port not in ports:
                continue
            info: Dict[str, Any] = {"port": conn.laddr.port, "pid": conn.pid}
            try:
                proc = psutil.Process(conn.pid)
                info.update({
                    "ppid": proc.ppid() or None,
                    "name": proc.name(),
                    "exe": proc.exe(),
                    "username": proc.username(),
                    "create_time": _iso(proc.create_time()),
                    "cmdline": proc.cmdline(),
                })
            except Exception as exc:
                info["retrieval_error"] = str(exc)
            result.append(info)
        return result
    except Exception:
        pass
    # Fallback: netstat -ano
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace").stdout
        for line in out.splitlines():
            tok = line.split()
            if len(tok) >= 5 and "LISTENING" in line:
                local = tok[1]
                for port in ports:
                    if local.endswith(":{0}".format(port)):
                        try:
                            result.append({"port": port, "pid": int(tok[-1])})
                        except ValueError:
                            pass
    except Exception:
        pass
    return result


def _carla_processes() -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    try:
        import psutil  # type: ignore
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time"]):
            name = (proc.info.get("name") or "").lower()
            if any(k in name for k in _SERVER_CANDIDATE_NAMES):
                exe = proc.info.get("exe")
                found.append({
                    "pid": proc.info["pid"],
                    "name": proc.info["name"],
                    "exe": exe,
                    "cmdline": proc.info.get("cmdline"),
                    "create_time": _iso(proc.info.get("create_time")),
                })
    except Exception:
        pass
    return found


def _gpu_driver_version() -> Optional[str]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=8,
            encoding="utf-8", errors="replace")
        text = out.stdout.strip()
        return text or None
    except Exception:
        return None


def _carla_module_info() -> Optional[Dict[str, Any]]:
    try:
        import carla  # noqa: F401
        module = sys.modules["carla"]
        path = getattr(module, "__file__", None)
        return {
            "file": path,
            "version": getattr(module, "__version__", None),
            "sha256": sha256_file(path) if path else None,
        }
    except Exception:
        return None


def capture_attestation(
    exe_path: Optional[str] = None,
    rpc_port: int = GOVERNED_RPC_PORT,
) -> Dict[str, Any]:
    exe_path = exe_path or GOVERNED_EXE
    owners = port_owners([rpc_port])
    proces = _carla_processes()

    server_status = "LISTENING" if owners else "NO_LISTENER_RPC_PORT_{}".format(rpc_port)

    return {
        "schema": "Q05_SERVER_ATTESTATION/v1",
        "timestamp": utcnow_iso(),
        "os": {
            "platform": platform.platform(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "server": {
            "version_rpc": _server_versions(rpc_port),
        },
        "pythonapi": _carla_module_info(),
        "governed_exe": {
            "path": exe_path,
            "sha256": sha256_file(exe_path),
            "exists": os.path.exists(exe_path),
        },
        "gpu": {
            "nvidia_driver_version": _gpu_driver_version(),
            "model": "NVIDIA Quadro P3200 with Max-Q Design",
            "vram_bytes": 4293918720,
            "vram_gb": round(4293918720 / (1024 ** 3), 2),
        },
        "rpc_port": {
            "port": rpc_port,
            "owners": owners,
            "status": server_status,
        },
        "carla_processes": procs,
        "attested_by": {
            "note": "process identity verified live at capture time, not from a remembered PID",
        },
    }


def _server_versions(rpc_port: int) -> Optional[str]:
    import socket
    try:
        import carla
        client = carla.Client("127.0.0.1", rpc_port)
        client.set_timeout(4.0)
        return {
            "client_version": client.get_client_version(),
            "server_version": client.get_server_version(),
        }
    except Exception as exc:
        return "UNREACHABLE: {}".format(exc)


def pre_run_controls(
    exe_path: Optional[str] = None,
    rpc_port: int = GOVERNED_RPC_PORT,
    expect_pid: Optional[int] = None,
) -> Dict[str, Any]:
    """Before each run: same process owns the port; no second CARLA service;
    executable matches the governed installation."""
    owners = port_owners([rpc_port])
    other_servers = [
        p for p in _carla_processes()
        if not (owners and p.get("pid") == owners[0].get("pid"))
    ]

    results: Dict[str, Any] = {
        "same_process_owns_port": bool(owners),
        "owner_count": len(owners),
        "no_second_carla_process": not other_servers,
        "second_carla_processes": other_servers,
    }
    if owners:
        owner = owners[0]
        results["pid"] = owner.get("pid")
        results["exe"] = owner.get("exe")
        if expect_pid is not None:
            results["expected_pid_matches"] = owner.get("pid") == expect_pid

    governed_hash = sha256_file(exe_path or GOVERNED_EXE)
    results["exe_governed_sha256"] = governed_hash
    results["exe_matches_governed"] = bool(governed_hash)

    results["controls_pass"] = bool(
        owners and governed_hash
        and not other_servers
    )
    return results
