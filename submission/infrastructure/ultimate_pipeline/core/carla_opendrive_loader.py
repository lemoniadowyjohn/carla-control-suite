from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional, Sequence, TYPE_CHECKING

import importlib
import xml.etree.ElementTree as ET

_CARLA = None

if TYPE_CHECKING:
    import carla


class CarlaOpendrivePreflightError(RuntimeError):
    """Raised when XODR preflight validation fails before CARLA is touched."""


def _preflight_xodr(xodr_text: str, source_sha256: str) -> None:
    """Run the strict CARLA-compatibility gate on XODR text before any CARLA call.

    A deterministic preflight error must:
    - not be retried;
    - not start CARLA map generation;
    - not fall back to Town10HD_Opt;
    - not be converted into a generic timeout.
    """
    try:
        root = ET.fromstring(xodr_text)
    except ET.ParseError as exc:
        raise CarlaOpendrivePreflightError(
            f"XODR preflight failed: XML parse error (source_sha256={source_sha256}): {exc}"
        ) from exc

    from ultimate_pipeline.quality.check_carla_opendrive_compat import StrictCarlaOpendriveGate

    issues = StrictCarlaOpendriveGate.validate(root)
    fatal = [i for i in issues if i.get("severity") == "error"]
    if fatal:
        codes = "; ".join(f"{i['code']}: {i['message']}" for i in fatal[:5])
        raise CarlaOpendrivePreflightError(
            f"XODR preflight failed: {len(fatal)} fatal issue(s) (source_sha256={source_sha256}): {codes}"
        )


def _lazy_carla():
    """Import CARLA lazily so offline usage (HPC, tests) stays import-safe."""
    global _CARLA
    if _CARLA is None:
        _CARLA = importlib.import_module("carla")
    return _CARLA


def safe_reload_world(client: carla.Client) -> None:
    """Reload the current CARLA world in a version-tolerant way."""
    try:
        client.reload_world()  # most versions
        return
    except TypeError:
        pass

    # Some forks accept a bool; try best-effort fallback
    try:
        client.reload_world(False)
        return
    except Exception:
        # Last attempt
        client.reload_world()


def ensure_world_ticks(
    world: "carla.World",
    *,
    n: int = 3,
    timeout_per_tick_s: float = 2.0,
) -> dict:
    """Verify the simulation is actually progressing by observing tick frames."""
    n = max(1, int(n))
    frames: list[int] = []
    t0 = time.time()
    last_frame: Optional[int] = None

    for _ in range(n):
        snap = world.wait_for_tick(float(float(timeout_per_tick_s)))
        frame = int(getattr(snap, "frame", -1))
        frames.append(frame)
        if last_frame is not None and frame <= last_frame:
            raise RuntimeError(
                f"CARLA ticks did not progress: frames={frames} (timeout_per_tick_s={timeout_per_tick_s})"
            )
        last_frame = frame

    return {
        "ok": True,
        "n": n,
        "frames": frames,
        "elapsed_s": float(time.time() - t0),
        "timeout_per_tick_s": float(timeout_per_tick_s),
    }


def _resolve_ready_timeout_s(value: Optional[float] = None) -> float:
    """Resolve CARLA readiness timeout from explicit value or environment."""
    if value is not None:
        return float(value)
    raw = os.environ.get("UP_CARLA_READY_TIMEOUT_S", "60.0")
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return 60.0
    if parsed <= 0.0:
        return 60.0
    return parsed


def wait_for_carla_ready(
    client: carla.Client,
    timeout_s: Optional[float] = None,
    *,
    probe_timeout_s: Optional[float] = None,
    restore_timeout_s: Optional[float] = None,
    ready_ticks: Optional[int] = None,
    tick_timeout_s: Optional[float] = None,
) -> carla.World:
    """Wait until CARLA responds with a usable world+map.

    Key rule: readiness probes must use a SHORT timeout, but must NOT leave the client
    configured with that short timeout afterwards.

    - timeout_s: explicit readiness timeout. If omitted, uses env UP_CARLA_READY_TIMEOUT_S (default 60.0).
    - probe_timeout_s: timeout used for get_world()/get_map probes (defaults to env UP_CARLA_PROBE_TIMEOUT_S or 2.0)
    - restore_timeout_s: timeout to restore on the client after probe (if provided)
    """
    effective_timeout_s = _resolve_ready_timeout_s(timeout_s)

    if probe_timeout_s is None:
        probe_timeout_s = float(os.environ.get("UP_CARLA_PROBE_TIMEOUT_S", "2.0"))

    if ready_ticks is None:
        ready_ticks = int(os.environ.get("UP_CARLA_READY_TICKS", "3"))
    if tick_timeout_s is None:
        tick_timeout_s = float(os.environ.get("UP_CARLA_READY_TICK_TIMEOUT_S", "2.0"))

    # Use short timeout for probing
    try:
        client.set_timeout(float(probe_timeout_s))
    except Exception:
        pass

    t0 = time.time()
    last_exc: Optional[BaseException] = None
    while time.time() - t0 < float(effective_timeout_s):
        try:
            world = client.get_world()
            _ = world.get_map()
            ensure_world_ticks(
                world,
                n=int(ready_ticks),
                timeout_per_tick_s=float(tick_timeout_s),
            )

            # IMPORTANT: restore a sane timeout after readiness probe
            if restore_timeout_s is not None:
                try:
                    client.set_timeout(float(restore_timeout_s))
                except Exception:
                    pass

            return world
        except Exception as e:
            last_exc = e
            time.sleep(0.5)

    # restore on failure too (so caller doesn't inherit probe timeout)
    if restore_timeout_s is not None:
        try:
            client.set_timeout(float(restore_timeout_s))
        except Exception:
            pass

    raise RuntimeError(f"CARLA not ready after {effective_timeout_s}s. Last error: {last_exc}")


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_list(name: str) -> list[str]:
    v = os.environ.get(name, "").strip()
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]


BUILTIN_TOWN_PREFIXES = ("Town", "Carla/Maps/Town")


def _is_builtin_town(map_name: str) -> bool:
    name = str(map_name or "").strip()
    return any(name.startswith(prefix) for prefix in BUILTIN_TOWN_PREFIXES)


def _normalize_georef_in_xodr_text(xodr_text: str) -> str:
    if not xodr_text or "<geoReference" not in xodr_text:
        return xodr_text
    try:
        import xml.etree.ElementTree as ET
        from ultimate_pipeline.core.georef_utils import normalize_georeference

        root = ET.fromstring(xodr_text)
        header = root.find("header")
        if header is not None:
            geo = header.find("geoReference")
            if geo is not None and geo.text:
                geo.text = normalize_georeference(geo.text)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    except Exception:
        return xodr_text


def default_opendrive_generation_params(carla_mod) -> object:
    params = carla_mod.OpendriveGenerationParameters()
    params.map_layers = carla_mod.MapLayer.NONE
    params.wall_height = 0.0
    params.additional_width = 0.0
    params.vertex_distance = float(os.environ.get("UP_OD_VERTEX_DISTANCE", "1.0"))
    params.smooth_junctions = True
    return params


def load_builtin_world(
    client: carla.Client,
    map_name: str,
    *,
    timeout_s: float = 60.0,
    ready_timeout_s: Optional[float] = None,
) -> carla.World:
    """Load a built-in CARLA town (e.g., Town03) and wait until it is usable."""
    ready_timeout_s = _resolve_ready_timeout_s(ready_timeout_s)
    client.set_timeout(float(timeout_s))
    try:
        client.load_world(map_name)
    except Exception as e:
        raise RuntimeError(f"Failed to load built-in map '{map_name}': {e}") from e
    return wait_for_carla_ready(client, timeout_s=float(ready_timeout_s), restore_timeout_s=float(timeout_s))


def hard_reset_world(
    client: carla.Client,
    *,
    timeout_s: float = 30.0,
    ready_timeout_s: Optional[float] = None,
) -> carla.World:
    """Best-effort 'reset': reload current world and wait until it's responsive."""
    ready_timeout_s = _resolve_ready_timeout_s(ready_timeout_s)
    client.set_timeout(float(timeout_s))
    safe_reload_world(client)
    return wait_for_carla_ready(client, timeout_s=float(ready_timeout_s), restore_timeout_s=float(timeout_s))


def load_opendrive_world(
    client: carla.Client,
    xodr_text: str,
    *,
    params: Optional[carla.OpendriveGenerationParameters] = None,
    timeout_s: float = 180.0,
    retries: int = 2,
    do_reload: bool = True,
    ready_timeout_s: Optional[float] = None,
    # Fallback: if OpenDRIVE generation fails, switch to a built-in map so perception capture can continue.
    fallback_enabled: Optional[bool] = None,
    fallback_maps: Optional[Sequence[str]] = None,
    fallback_timeout_s: float = 60.0,
    source_sha256: str = "",
    governed_payload_sha256: str = "",
) -> carla.World:
    """Robust OpenDRIVE load with optional built-in map fallback.

    ``governed_payload_sha256`` enables release mode (Q4): the supplied
    ``xodr_text`` must be byte-identical to the governed load-payload
    artifact.  Any runtime-only transformation (in-memory re-normalization)
    is then forbidden and raises before CARLA is touched.
    """
    # Preflight: validate XODR before any CARLA interaction.
    _preflight_xodr(xodr_text, source_sha256=source_sha256)

    # Always start with a long timeout for real work.
    client.set_timeout(float(timeout_s))
    if governed_payload_sha256:
        import hashlib
        actual_sha = hashlib.sha256(xodr_text.encode("utf-8")).hexdigest()
        if actual_sha != governed_payload_sha256:
            raise RuntimeError(
                "release_mode_governed_payload_mismatch: input byte sha256={} != "
                "governed payload {}; no runtime-only transformation is permitted "
                "in release mode.".format(actual_sha, governed_payload_sha256)
            )
    else:
        xodr_text = _normalize_georef_in_xodr_text(xodr_text)
    ready_timeout_s = _resolve_ready_timeout_s(ready_timeout_s)

    last_exc: Optional[BaseException] = None
    attempts = max(0, int(retries)) + 1

    for attempt in range(1, attempts + 1):
        try:
            # Pre-flight: CARLA responding (probe uses short timeout but restores to long timeout)
            wait_for_carla_ready(
                client,
                timeout_s=float(ready_timeout_s),
                restore_timeout_s=float(timeout_s),
            )

            if do_reload:
                # Reload can be slow; make sure we are NOT on a 2s probe timeout
                client.set_timeout(float(timeout_s))
                safe_reload_world(client)
                wait_for_carla_ready(
                    client,
                    timeout_s=float(ready_timeout_s),
                    restore_timeout_s=float(timeout_s),
                )

            # CRITICAL: force long timeout immediately before OpenDRIVE generation.
            client.set_timeout(float(timeout_s))

            if params is None:
                params = default_opendrive_generation_params(_lazy_carla())
            world = client.generate_opendrive_world(xodr_text, params)

            # Post-flight: ensure map is actually accessible
            map_obj = world.get_map()
            map_name = str(getattr(map_obj, "name", "") or "")
            if _is_builtin_town(map_name):
                raise RuntimeError(
                    f"opendrive_load_fallback_blocked: expected OpenDriveMap, got {map_name}"
                )
            tick_report = ensure_world_ticks(
                world,
                n=int(os.environ.get("UP_CARLA_POSTLOAD_TICKS", "3")),
                timeout_per_tick_s=float(
                    os.environ.get("UP_CARLA_POSTLOAD_TICK_TIMEOUT_S", "2.0")
                ),
            )
            if not bool((tick_report or {}).get("ok", False)):
                raise RuntimeError("opendrive_load_tick_failed: world not confirmed")
            return world

        except Exception as e:
            last_exc = e
            # ASCII-only log (Windows-safe)
            print(f"[CARLA_IMPORT] attempt {attempt}/{attempts} failed: {type(e).__name__}: {e}")
            time.sleep(min(2.0, 0.5 * attempt))

    # -----------------------------
    # Fallback to built-in map
    # -----------------------------
    if fallback_enabled is None:
        fallback_enabled = _env_bool("UP_CARLA_FALLBACK_ENABLED", default=False)

    if fallback_enabled:
        maps: list[str] = []
        if fallback_maps:
            maps = [str(m) for m in fallback_maps if str(m).strip()]
        else:
            maps = _env_list("UP_CARLA_FALLBACK_MAPS")
            if not maps:
                single = os.environ.get("UP_CARLA_FALLBACK_MAP", "").strip()
                if single:
                    maps = [single]

        if not maps:
            maps = ["Town10HD_Opt", "Town05", "Town03", "Town01"]

        for m in maps:
            try:
                print(f"[WARN] OpenDRIVE generation failed; falling back to built-in map: {m}")
                fallback_world = load_builtin_world(
                    client,
                    m,
                    timeout_s=float(fallback_timeout_s),
                    ready_timeout_s=float(ready_timeout_s),
                )
                fb_map_name = str(
                    getattr(getattr(fallback_world, "get_map", lambda: None)(), "name", "")
                    or ""
                )
                if _is_builtin_town(fb_map_name):
                    raise RuntimeError(
                        f"opendrive_load_fallback_blocked: expected OpenDriveMap, got {fb_map_name}"
                    )
                return fallback_world
            except Exception as e:
                last_exc = e
                if str(e).startswith("opendrive_load_fallback_blocked:"):
                    raise
                continue

    raise RuntimeError(f"Failed to generate OpenDRIVE world after {attempts} attempts. Last error: {last_exc}")


def load_opendrive_world_from_file(
    client: carla.Client,
    xodr_path: str | Path,
    *,
    params: Optional[carla.OpendriveGenerationParameters] = None,
    timeout_s: float = 180.0,
    retries: int = 2,
    do_reload: bool = True,
fallback_enabled: Optional[bool] = None,
    fallback_maps: Optional[Sequence[str]] = None,
    source_sha256: str = "",
    governed_payload_sha256: str = "",
) -> carla.World:
    """Convenience wrapper around `load_opendrive_world` for .xodr files."""
    xodr_path = Path(xodr_path)
    xodr_text = xodr_path.read_text(encoding="utf-8", errors="ignore")
    if not source_sha256:
        import hashlib
        source_sha256 = hashlib.sha256(xodr_text.encode("utf-8")).hexdigest()
    return load_opendrive_world(
        client,
        xodr_text,
        params=params,
        timeout_s=timeout_s,
        retries=retries,
        do_reload=do_reload,
        ready_timeout_s=ready_timeout_s,
        fallback_enabled=fallback_enabled,
        fallback_maps=fallback_maps,
        source_sha256=source_sha256,
        governed_payload_sha256=governed_payload_sha256,
    )


# -------------------------------------------------------------------
# Backwards-compat helpers (older scripts might still import this)
# -------------------------------------------------------------------

def generate_world_from_xodr_file(
    client: carla.Client,
    xodr_path: str | Path,
    *,
    timeout_s: float = 180.0,
    fixed_delta_seconds: float | None = None,
) -> carla.World:
    """Legacy name kept for backward compatibility."""
    world = load_opendrive_world_from_file(
        client,
        xodr_path,
        timeout_s=timeout_s,
        retries=2,
        do_reload=True,
    )

    if fixed_delta_seconds is not None:
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = float(fixed_delta_seconds)
        world.apply_settings(settings)
        for _ in range(10):
            world.tick()

    return world
