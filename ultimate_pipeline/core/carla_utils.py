from __future__ import annotations
import socket
try:
    import psutil  # type: ignore
except Exception:
    psutil = None  # type: ignore

import subprocess
import time
import os
from pathlib import Path
from typing import Tuple, TYPE_CHECKING
from types import ModuleType

from ultimate_pipeline.optional.carla_api import get_carla

if TYPE_CHECKING:  # pragma: no cover
    import carla  # type: ignore


_CARLA_MODULE: ModuleType | None = None


def _carla_module() -> ModuleType:
    global _CARLA_MODULE
    if _CARLA_MODULE is None:
        _CARLA_MODULE = get_carla()
    return _CARLA_MODULE


def _require_carla() -> None:
    try:
        _carla_module()
    except RuntimeError as exc:
        raise ModuleNotFoundError(
            "CARLA Python API is not installed. "
            "Install the matching CARLA Python package/egg for your CARLA build, "
            "or run with CARLA-dependent features disabled."
        ) from exc


from ultimate_pipeline.config.settings import SETTINGS


def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def _streaming_disabled() -> bool:
    """Check if streaming is disabled (does not imply skipping probes)."""
    return (
        _env_flag("UP_DISABLE_STREAMING", False) or
        _env_flag("UP_TILE_QA_DISABLE_STREAMING", False)
    )


def _streaming_skip_probe() -> bool:
    """Explicit opt-out of streaming probe (unit-test friendly)."""
    return _env_flag("UP_SKIP_STREAMING_PROBE", False)


def _load_xodr_text_normalized(path: str) -> str:
    """Load XODR and normalize <geoReference> to single-line for CARLA import."""
    try:
        import xml.etree.ElementTree as ET
        from io import BytesIO
        from ultimate_pipeline.core.georef_utils import normalize_georeference

        tree = ET.parse(path)
        root = tree.getroot()
        header = root.find("header")
        if header is not None:
            geo = header.find("geoReference")
            if geo is not None and geo.text:
                geo.text = normalize_georeference(geo.text)
        buf = BytesIO()
        tree.write(buf, encoding="utf-8", xml_declaration=True)
        return buf.getvalue().decode("utf-8")
    except Exception:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""


# Global flag to track if streaming warning has been issued (warn-once).
_STREAMING_WARNED = False


def _get_carla_log_path() -> str | None:
    # Prefer per-run log path set by pipeline (env var), fallback to settings.
    p = os.environ.get("UP_CARLA_LOG_PATH")
    if p:
        return p
    return getattr(SETTINGS, "CARLA_SERVER_LOG", None)


def _resolve_carla_log_path_for_launch() -> str:
    """C20 Tier 3: never discard the server log. Defined but never called before
    this fix -- restart_carla() sent stdout/stderr straight to DEVNULL, so every
    past hang was undiagnosable after the fact. Falls back to a timestamped path
    under reports/ so a log always exists, even with no explicit configuration.
    """
    configured = _get_carla_log_path()
    if configured:
        return configured
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    default_dir = Path("reports") / "post_audit_hardening" / "_carla_server_logs"
    default_dir.mkdir(parents=True, exist_ok=True)
    return str(default_dir / f"carla_server_{ts}.log")


def _carla_ready_timeout_s(default: float = 600.0) -> float:
    """C20 Tier 3: configurable readiness timeout. The old hardcoded 30s
    (ensure_carla_ready's retries=30 * delay_s=1.0 default) is far too short
    for a slow-starting server and, worse, gave restart_carla() no way to
    honestly confirm RPC responds before printing a misleading success
    message based on the TCP port alone."""
    raw = os.environ.get("UP_CARLA_READY_TIMEOUT_S")
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _gpu_tdr_preflight() -> dict:
    from ultimate_pipeline.core.gpu_tdr_preflight import windows_gpu_tdr_preflight_from_env

    return windows_gpu_tdr_preflight_from_env()


def _format_gpu_tdr_block(report: dict) -> str:
    reason = report.get("reason")
    sampled = report.get("event_count_sampled")
    lookback = report.get("lookback_hours")
    return (
        "GPU watchdog/TDR preflight blocked CARLA runtime evidence "
        f"(reason={reason}, sampled_events={sampled}, lookback_hours={lookback}). "
        "Fix the NVIDIA driver/hardware TDR stream first; see "
        "reports/post_audit_hardening/C20_GPU_TDR_20260821/FINDINGS.md."
    )


def _require_gpu_tdr_clean_for_carla() -> dict:
    report = _gpu_tdr_preflight()
    if not report.get("ok", False):
        raise RuntimeError(_format_gpu_tdr_block(report))
    return report


# ============================================================
# Crash cleanup (NEW)
# ============================================================

def _cleanup_carla_crash_artifacts():
    """
    Remove Unreal Engine crash leftovers before restarting CARLA.
    """
    import shutil

    base = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "CarlaUE4",
        "Saved"
    )

    if not os.path.isdir(base):
        return

    crashes = os.path.join(base, "Crashes")
    if os.path.isdir(crashes):
        try:
            shutil.rmtree(crashes)
            print("🧹 Removed CARLA crash reports.")
        except Exception as e:
            print(f"⚠ Could not remove crash reports: {e}")

    cache = os.path.join(base, "DerivedDataCache")
    if os.path.isdir(cache):
        try:
            shutil.rmtree(cache)
            print("🧹 Removed CARLA derived data cache.")
        except Exception as e:
            print(f"⚠ Could not remove cache: {e}")

    temp = os.path.join(base, "Temp")
    if os.path.isdir(temp):
        try:
            shutil.rmtree(temp)
        except Exception:
            pass


# ============================================================
# Process + port utilities
# ============================================================
def _kill_stuck_carla():
    exe_names = ("CarlaUE4.exe", "CarlaUE4-Win64-Shipping.exe")

    # Preferred: psutil (if installed)
    if psutil is not None:
        for p in psutil.process_iter(["name"]):
            try:
                if p.info.get("name") in exe_names:
                    p.kill()
            except Exception:
                pass
        return

    # Fallback: no psutil installed (Windows taskkill / Linux pkill)
    if os.name == "nt":
        for exe in exe_names:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/IM", exe],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass
    else:
        for exe in exe_names:
            try:
                subprocess.run(
                    ["pkill", "-f", exe],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass



def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_ports(host: str, ports: list[int], timeout_s: float = 60.0) -> bool:
    """Wait until all TCP ports are reachable."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if all(_port_open(host, int(p), timeout=1.0) for p in ports):
            return True
        time.sleep(0.5)
    return False


# Backwards-compat alias (older modules used this name)
_carla_port_open = _port_open


def _resolve_rpc_streaming_ports(
    rpc_port: int,
    configured_streaming_port: int | None,
) -> Tuple[int, int]:
    """Resolve RPC/streaming ports with a hard non-collision contract."""
    rpc = int(rpc_port)
    env_stream = os.environ.get("UP_CARLA_STREAMING_PORT")
    if env_stream is not None and str(env_stream).strip():
        try:
            stream = int(str(env_stream).strip())
        except Exception:
            stream = int(configured_streaming_port or (rpc + 1))
    else:
        stream = int(configured_streaming_port or (rpc + 1))
    if stream == rpc:
        stream = rpc + 1
    return rpc, stream


# ============================================================
# Restart logic (SINGLE authority)
# ============================================================

def restart_carla(host: str | None = None, port: int | None = None) -> bool:
    """Restart the CARLA server process.

    Backwards compatible: if host/port are not provided, uses SETTINGS.
    """
    host = host or SETTINGS.CARLA_HOST
    requested_port = int(port or SETTINGS.CARLA_PORT)
    default_map_name = str(
        os.environ.get("UP_CARLA_DEFAULT_MAP", getattr(SETTINGS, "CARLA_DEFAULT_MAP", ""))
        or ""
    ).strip()
    configured_streaming_port = int(
        getattr(SETTINGS, "CARLA_STREAMING_PORT", requested_port + 1)
        or (requested_port + 1)
    )
    port, streaming_port = _resolve_rpc_streaming_ports(
        requested_port, configured_streaming_port
    )

    print("💀 Restarting CARLA server...")

    try:
        _require_gpu_tdr_clean_for_carla()
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return False

    _cleanup_carla_crash_artifacts()
    _kill_stuck_carla()
    time.sleep(2)

    exe = SETTINGS.CARLA_EXE
    if not os.path.exists(exe):
        print(f"❌ CARLA executable not found at: {exe}")
        return False

    # CARLA uses RPC (control) + Streaming (sensor/actor data).
    # For many QA workloads (tile QA), streaming is optional and can be flaky on Windows.
    # If streaming is disabled via env flags, do not require the streaming port to open.
    streaming_disabled = (
        _env_flag("UP_DISABLE_STREAMING", False)
        or _env_flag("UP_TILE_QA_DISABLE_STREAMING", False)
        or _env_flag("UP_SKIP_STREAMING_PROBE", False)
    )
    ports = [port] if streaming_disabled else [port, streaming_port]

    # C20 Tier 3: minimal-render / nullrhi diagnostic flags, opt-in via env so
    # normal callers are unaffected. -nullrhi disables the render hardware
    # interface entirely (no cameras/sensors -- confirmed via C20_TIER1_PROBE
    # to isolate render/VRAM-bound stalls from other causes); UP_CARLA_MIN_RENDER
    # shrinks the render target to cut VRAM/fill cost without disabling it.
    render_flags: list[str]
    if _env_flag("UP_CARLA_NULLRHI", False):
        render_flags = ["-nullrhi", "-nosound"]
    elif _env_flag("UP_CARLA_MIN_RENDER", False):
        render_flags = ["-RenderOffScreen", "-quality-level=Low", "-nosound", "-ResX=64", "-ResY=64", "-windowed"]
    else:
        render_flags = ["-RenderOffScreen", "-quality-level=Low", "-nosound", "-windowed", "-ResX=800", "-ResY=600"]

    # Try a couple of common flag styles for different CARLA builds.
    map_arg = [default_map_name] if default_map_name else []
    launch_variants = [
        [
            exe, *render_flags,
            f"-carla-rpc-port={port}",
            *([] if streaming_disabled else [f"-carla-streaming-port={streaming_port}"]),
            *map_arg,
        ],
        [
            exe, *render_flags,
            f"-carla-port={port}",
            *([] if streaming_disabled else [f"-carla-streaming-port={streaming_port}"]),
            *map_arg,
        ],
    ]

    _vram_preflight()

    for cmd in launch_variants:
        # C20 Tier 3: stop discarding the server log -- every past hang was
        # undiagnosable after the fact because stdout/stderr went to DEVNULL.
        log_path = _resolve_carla_log_path_for_launch()
        cmd = [*cmd, "-log"]
        try:
            log_file = open(log_path, "w", encoding="utf-8", errors="replace")
        except OSError:
            log_file = subprocess.DEVNULL  # type: ignore[assignment]
            log_path = "<unavailable>"
        try:
            subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except Exception as e:
            print(f"❌ Failed to start CARLA: {e}")
            continue
        finally:
            if log_file is not subprocess.DEVNULL:
                log_file.close()  # type: ignore[union-attr]
        print(f"[carla] server log -> {log_path}")

        if _wait_for_ports(host, ports, timeout_s=120.0):
            # C20 Tier 3: the port opening is NOT the same as CARLA being ready
            # -- the UE game thread can bind the TCP port while never servicing
            # its first RPC tick (a livelock, confirmed via C20_TIER1_PROBE).
            # Verify RPC actually responds before claiming success; the old
            # port-only check produced a misleading "restarted and listening"
            # message on exactly this failure mode.
            client = _carla_module().Client(host, port)
            client.set_timeout(2.0)
            rpc_ready = ensure_carla_ready(client, timeout_s=_carla_ready_timeout_s())
            if rpc_ready:
                if streaming_disabled:
                    print(f"✅ CARLA restarted and RPC-ready on {host}:{port} (streaming disabled)")
                else:
                    print(f"✅ CARLA restarted and RPC-ready on {host}:{port} (streaming {streaming_port})")
                return True
            print(
                f"⚠ CARLA port {port} opened but RPC never responded within "
                f"{_carla_ready_timeout_s():.0f}s (see {log_path}) -- treating as not ready."
            )

        # If the port(s) never appeared, or RPC never responded, kill and
        # retry the next launch variant.
        _kill_stuck_carla()
        time.sleep(2)

    print("❌ CARLA did not come back after restart.")
    return False


def _vram_preflight(*, max_used_mib: float = 500.0) -> None:
    """C20 Tier 3: warn and clean up before launch if a stale CARLA instance
    is still holding significant VRAM -- a leaked prior instance at high VRAM
    usage guarantees the next launch is GPU-starved from the start."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip()
        used_mib = float(out.splitlines()[0]) if out else 0.0
    except Exception:
        return  # no nvidia-smi available (or not an NVIDIA GPU) -- skip silently
    if used_mib > max_used_mib:
        print(f"⚠ [carla-preflight] {used_mib:.0f} MiB VRAM already in use before launch "
              f"(>{max_used_mib:.0f} MiB threshold) -- killing stale CARLA instances.")
        _kill_stuck_carla()
        time.sleep(2)


# ============================================================
# Public API
# ============================================================

def ensure_carla_ready(
    client: carla.Client,
    *,
    retries: int = 30,
    delay_s: float = 1.0,
    require_map: bool = False,
    timeout_s: float | None = None,
) -> bool:
    """Check if CARLA responds.

    This function does not restart CARLA.

    Notes:
    - On Windows restarts, the RPC port can be open before the simulator is fully ready.
      A single `get_world()` probe is often too optimistic.
    - `require_map=True` waits until `world.get_map()` also succeeds.
    - C20 Tier 3: pass `timeout_s` for a wall-clock deadline instead of a fixed
      retry count -- overrides `retries` when given (retries*delay_s was a
      hardcoded ~30s ceiling, far too short for a slow-starting server).
    """
    last_exc: Exception | None = None
    deadline = (time.time() + float(timeout_s)) if timeout_s is not None else None
    attempts = 0
    while True:
        attempts += 1
        if deadline is None and attempts > max(1, int(retries)):
            break
        if deadline is not None and time.time() >= deadline:
            break
        try:
            world = client.get_world()
            if require_map:
                world.get_map()

            # Helpful debug: version mismatch can produce weird streaming behavior.
            try:
                sv = client.get_server_version()
                cv = client.get_client_version()
                if sv and cv and sv != cv:
                    print(
                        f"⚠ CARLA version mismatch (server={sv}, client={cv}). "
                        "Consider using matching PythonAPI."
                    )
            except Exception:
                pass

            return True
        except Exception as e:
            last_exc = e
            time.sleep(float(delay_s))

    if last_exc is not None:
        # Keep it low-noise but actionable when diagnosing readiness races.
        print(f"[WARN] CARLA not ready after {retries} probes: {last_exc}")
    return False


def autostart_carla_if_needed(
    host: str | None = None,
    port: int | None = None,
    *,
    timeout_s: float | None = None,
) -> carla.Client:
    """Return a connected, responsive CARLA client (restarting server if needed).

    Backwards compatible: callers can still use autostart_carla_if_needed() with no args.

    Streaming behavior (critical for tile QA stability):
    - Streaming probes run once per call (hard-capped to 1 attempt).
    - UP_DISABLE_STREAMING/UP_TILE_QA_DISABLE_STREAMING disables streaming usage but does not skip probes.
    - UP_SKIP_STREAMING_PROBE=1 explicitly skips the probe and returns status="disabled".
    - If streaming port is unreachable, warn once and continue (streaming_status="refused").
    - Streaming refusal does NOT trigger CARLA restart (prevents crash loop).
    - Connection attempts to streaming port are hard-capped to 1.
    """
    global _STREAMING_WARNED
    host = host or SETTINGS.CARLA_HOST
    requested_port = int(port or SETTINGS.CARLA_PORT)
    timeout_s = float(timeout_s if timeout_s is not None else getattr(SETTINGS, "CARLA_TIMEOUT", 20.0))
    port, streaming_port = _resolve_rpc_streaming_ports(
        requested_port,
        int(getattr(SETTINGS, "CARLA_STREAMING_PORT", requested_port + 1) or (requested_port + 1)),
    )
    streaming_skip_probe = _streaming_skip_probe()

    streaming_status: str | None = None

    _require_gpu_tdr_clean_for_carla()

    def _determine_streaming_status() -> str:
        """Check streaming port once; return status. Warn-once on refusal."""
        nonlocal streaming_status
        global _STREAMING_WARNED
        if streaming_status is not None:
            return streaming_status
        if streaming_skip_probe or streaming_port <= 0:
            streaming_status = "disabled"
            return streaming_status
        reachable = _port_open(host, streaming_port, timeout=1.0)
        if reachable:
            streaming_status = "ok"
            return streaming_status
        if not _STREAMING_WARNED:
            print(
                f"[WARN] Streaming port {streaming_port} refused (continuing without streaming). "
                "Set UP_DISABLE_STREAMING=1 to suppress."
            )
            _STREAMING_WARNED = True
        streaming_status = "refused"
        return streaming_status

    # ------------------------------------------------------------
    # Worker-safe mode: never restart CARLA from a subprocess.
    # The parent pipeline manages CARLA lifecycle (restart/settle).
    # ------------------------------------------------------------
    if _env_flag("UP_NO_CARLA_AUTOSTART", False):
        if not _port_open(host, port):
            raise RuntimeError(f"CARLA RPC port not reachable ({host}:{port})")

        client = _carla_module().Client(host, port)
        client.set_timeout(timeout_s)

        # In worker mode, only require the RPC side to be responsive.
        # The streaming port can flap briefly on Windows restarts.
        if not ensure_carla_ready(client):
            raise RuntimeError("CARLA not ready (no-autostart mode).")

        streaming_status = _determine_streaming_status()
        client._streaming_status = streaming_status  # type: ignore[attr-defined]
        client._streaming_port = int(streaming_port)  # type: ignore[attr-defined]
        client._rpc_port = int(port)  # type: ignore[attr-defined]

        print("CARLA connection confirmed.")
        return client


    print("Checking CARLA availability...")

    # Check RPC port first (required). Streaming check is separate and non-fatal.
    rpc_reachable = _port_open(host, port)
    streaming_status = _determine_streaming_status()

    # Only launch CARLA if RPC is unreachable (streaming refusal is NOT a launch trigger)
    if not rpc_reachable:
        print("CARLA RPC not reachable - launching.")
        if not restart_carla(host=host, port=port):
            raise RuntimeError("CARLA could not be launched.")
        # Do not re-check streaming (hard cap to a single attempt)
        streaming_status = _determine_streaming_status()

    client = _carla_module().Client(host, port)
    client.set_timeout(timeout_s)

    # Only restart if RPC is unresponsive (not streaming)
    if not ensure_carla_ready(client):
        print("CARLA RPC unresponsive - restarting.")
        if not restart_carla(host=host, port=port):
            raise RuntimeError("CARLA restart failed.")

        client = _carla_module().Client(host, port)
        client.set_timeout(timeout_s)
        streaming_status = _determine_streaming_status()

        if not ensure_carla_ready(client):
            raise RuntimeError("CARLA never became ready.")

    client._streaming_status = streaming_status  # type: ignore[attr-defined]
    client._streaming_port = int(streaming_port)  # type: ignore[attr-defined]
    client._rpc_port = int(port)  # type: ignore[attr-defined]
    print(f"CARLA connection confirmed (streaming_status={streaming_status}).")
    return client


# ============================================================
# XODR load with one retry
# ============================================================

def carla_load_xodr_with_restart(
    client: carla.Client,
    xodr_path: str,
    label: str,
    timeout_sec: float = 60.0,
) -> Tuple[bool, carla.Client]:

    print(f"\n🧪 CARLA Load Test: {label}")

    if not os.path.exists(xodr_path):
        print(f"❌ File not found: {xodr_path}")
        return False, client

    # ------------------------------------------------------------------
    # STRICT PRE-FLIGHT: block known CARLA-crash patterns *before* calling
    # generate_opendrive_world(). This keeps CARLA alive and makes failures
    # actionable.
    # ------------------------------------------------------------------
    effective_xodr_path = xodr_path

    try:
        from ultimate_pipeline.quality.xodr_junction_ref_cleanup import prune_invalid_junction_connections_in_file
        from ultimate_pipeline.quality.xodr_strict_validator import StrictXodrValidator

        # Conservative autofix: upstream steps may remove roads but leave stale junction refs.
        # Prune them into a sibling file and validate that file.
        pruned_path, pruned_stats = prune_invalid_junction_connections_in_file(xodr_path)
        if pruned_path != Path(xodr_path):
            effective_xodr_path = str(pruned_path)
            print(
                f"[AUTO-FIX] Pruned invalid junction references: "
                f"connections_removed={pruned_stats.removed_connections}, "
                f"junctions_removed={pruned_stats.removed_junctions} → {effective_xodr_path}"
            )

        rep = StrictXodrValidator().validate_path(effective_xodr_path)
        if not rep.get("ok", False):
            print("\n❌ Strict XODR preflight failed (blocking CARLA load to prevent crash).")
            print(f"   Errors: {rep.get('n_errors')}  Warnings: {rep.get('n_warnings')}  Total: {rep.get('n_issues')}")
            # Print the first few high-signal issues
            for it in rep.get("issues", [])[:20]:
                sev = it.get("severity")
                code = it.get("code")
                msg = it.get("message")
                ctx = it.get("context")
                print(f"   - [{sev}] {code}: {msg} | {ctx}")
            return False, client
    except Exception as e:
        # Preflight must never crash the pipeline.
        print(f"⚠ Strict XODR preflight skipped due to validator error: {e}")

    def _do_load(c: carla.Client) -> bool:
        data = _load_xodr_text_normalized(effective_xodr_path)

        from ultimate_pipeline.core.carla_opendrive_loader import (
            default_opendrive_generation_params,
            load_opendrive_world,
        )

        params = default_opendrive_generation_params(_carla_module())

        load_opendrive_world(
            c,
            data,
            params=params,
            timeout_s=float(timeout_sec),
            retries=0,
            do_reload=True,
        )
        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            try:
                world = c.get_world()
                world.get_map()
                print("✅ Map loaded and responsive.")
                return True
            except Exception:
                time.sleep(1)

        return False

    try:
        if _do_load(client):
            return True, client
    except Exception as e:
        print(f"⚠ Load failed: {e}")

    print("💀 Retrying after CARLA restart.")

    if not restart_carla():
        return False, client

    new_client = _carla_module().Client(SETTINGS.CARLA_HOST, SETTINGS.CARLA_PORT)
    # Align RPC timeout with the (potentially longer) load timeout.
    base_timeout = float(getattr(SETTINGS, "CARLA_TIMEOUT", 20.0))
    new_client.set_timeout(max(base_timeout, float(timeout_sec)))

    # After a restart the ports may be listening before the simulator is fully ready.
    if not ensure_carla_ready(new_client, retries=60, delay_s=1.0):
        return False, new_client

    try:
        return _do_load(new_client), new_client
    except Exception:
        return False, new_client
