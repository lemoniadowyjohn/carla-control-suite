from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional, Sequence

import carla


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


def wait_for_carla_ready(
    client: carla.Client,
    timeout_s: float = 30.0,
    *,
    probe_timeout_s: Optional[float] = None,
    restore_timeout_s: Optional[float] = None,
) -> carla.World:
    """Wait until CARLA responds with a usable world+map.

    Key rule: readiness probes must use a SHORT timeout, but must NOT leave the client
    configured with that short timeout afterwards.

    - probe_timeout_s: timeout used for get_world()/get_map probes (defaults to env UP_CARLA_PROBE_TIMEOUT_S or 2.0)
    - restore_timeout_s: timeout to restore on the client after probe (if provided)
    """
    if probe_timeout_s is None:
        probe_timeout_s = float(os.environ.get("UP_CARLA_PROBE_TIMEOUT_S", "2.0"))

    # Use short timeout for probing
    try:
        client.set_timeout(float(probe_timeout_s))
    except Exception:
        pass

    t0 = time.time()
    last_exc: Optional[BaseException] = None
    while time.time() - t0 < float(timeout_s):
        try:
            world = client.get_world()
            _ = world.get_map()
            # Give the server one tick to fully initialize streaming/state.
            try:
                world.wait_for_tick(timeout=1.0)
            except Exception:
                pass

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

    raise RuntimeError(f"CARLA not ready after {timeout_s}s. Last error: {last_exc}")


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


def load_builtin_world(
    client: carla.Client,
    map_name: str,
    *,
    timeout_s: float = 60.0,
    ready_timeout_s: float = 30.0,
) -> carla.World:
    """Load a built-in CARLA town (e.g., Town03) and wait until it is usable."""
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
    ready_timeout_s: float = 30.0,
) -> carla.World:
    """Best-effort 'reset': reload current world and wait until it's responsive."""
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
    ready_timeout_s: float = 30.0,
    # Fallback: if OpenDRIVE generation fails, switch to a built-in map so perception capture can continue.
    fallback_enabled: Optional[bool] = None,
    fallback_maps: Optional[Sequence[str]] = None,
    fallback_timeout_s: float = 60.0,
) -> carla.World:
    """Robust OpenDRIVE load with optional built-in map fallback."""
    # Always start with a long timeout for real work.
    client.set_timeout(float(timeout_s))

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
                world = client.generate_opendrive_world(xodr_text)
            else:
                world = client.generate_opendrive_world(xodr_text, params)

            # Post-flight: ensure map is actually accessible
            _ = world.get_map()
            try:
                world.wait_for_tick(timeout=2.0)
            except Exception:
                pass
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
                return load_builtin_world(
                    client,
                    m,
                    timeout_s=float(fallback_timeout_s),
                    ready_timeout_s=float(ready_timeout_s),
                )
            except Exception as e:
                last_exc = e
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
) -> carla.World:
    """Convenience wrapper around `load_opendrive_world` for .xodr files."""
    xodr_path = Path(xodr_path)
    xodr_text = xodr_path.read_text(encoding="utf-8", errors="ignore")
    return load_opendrive_world(
        client,
        xodr_text,
        params=params,
        timeout_s=timeout_s,
        retries=retries,
        do_reload=do_reload,
        fallback_enabled=fallback_enabled,
        fallback_maps=fallback_maps,
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
