#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Clean unified SETTINGS module for the Ultimate OSM→CARLA Pipeline.
Fully deduplicated, ordered, and synchronized with:

- main_pipeline.py
- CarlaSimulation
- TileStreamer + MeshStreamer
- Domain Gap tools
- Perception QA (local + HPC)
- Tiling, Seam Validation, QA modules

This file contains NO repeated keys and NO ambiguous overrides.
"""

import os
import math
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES
from ultimate_pipeline.utils.paths import repo_root, city_dir, resolve_path


PROJECT_ROOT = repo_root()
CITY_NAME = os.getenv("UP_CITY", "ingolstadt")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_timestamp() -> str:
    """Run tag used for output directory naming.

    - If UP_RUN_TAG is set, we use it verbatim (useful for determinism audits / HPC jobs).
    - Otherwise we include microseconds to avoid same-second collisions.
    """
    env = os.getenv("UP_RUN_TAG", "").strip()
    if env:
        return env
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _env_path(env_key: str, default: str) -> str:
    """Return an env-provided path if set, else default."""
    v = os.getenv(env_key, "").strip()
    return v if v else default


def _env_float(env_key: str, default: float) -> float:
    v = os.getenv(env_key, "").strip()
    if not v:
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)


def _env_int(env_key: str, default: int) -> int:
    v = os.getenv(env_key, "").strip()
    if not v:
        return int(default)
    try:
        return int(v)
    except Exception:
        return int(default)


def _env_bool(env_key: str, default: bool) -> bool:
    v = os.getenv(env_key, "").strip()
    if not v:
        return bool(default)
    return v.lower() in ("1", "true", "yes", "on")


def _env_bool_strict(env_key: str, default: bool) -> bool:
    v = os.getenv(env_key, "").strip()
    if not v:
        return bool(default)
    lowered = v.lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise RuntimeError(
        f"{env_key} must be one of 1,true,yes,on,0,false,no,off; got {v!r}"
    )


def _pick_existing(*candidates: str) -> str:
    """Pick the first candidate that exists on disk; otherwise return the first."""
    for c in candidates:
        try:
            if c and Path(c).exists():
                return c
        except Exception:
            continue
    return candidates[0] if candidates else ""


def _warn_missing_setting_path(
    label: str,
    value: str,
    *,
    env_var: str,
    expect: str = "path",
) -> None:
    """Emit a clear startup warning when an expected settings path is missing."""
    path_value = str(value or "").strip()
    if not path_value:
        return
    p = Path(path_value).expanduser()
    if expect == "file":
        exists = p.is_file()
    elif expect == "dir":
        exists = p.is_dir()
    else:
        exists = p.exists()
    if exists:
        return
    msg = (
        f"{label} resolved to missing {expect}: '{p}'. "
        f"Set {env_var} to a valid {expect}."
    )
    _boot_log(f"[WARN] {msg}")
    warnings.warn(msg, RuntimeWarning, stacklevel=2)


_BOOT_LOGS_ENABLED = None


def _boot_logs_enabled() -> bool:
    global _BOOT_LOGS_ENABLED
    if _BOOT_LOGS_ENABLED is not None:
        return bool(_BOOT_LOGS_ENABLED)

    env = os.getenv("UP_SETTINGS_BOOT_LOGS", "").strip().lower()
    if env:
        _BOOT_LOGS_ENABLED = env in ("1", "true", "yes", "on")
        return bool(_BOOT_LOGS_ENABLED)

    enabled = False
    try:
        import multiprocessing as _mp

        if _mp.parent_process() is not None:
            enabled = False
        else:
            try:
                import __main__ as _main

                main_spec = getattr(_main, "__spec__", None)
                main_name = str(getattr(main_spec, "name", "") or "")
                main_file = str(getattr(_main, "__file__", "") or "").replace(
                    "\\", "/"
                )
                enabled = (
                    main_name == "ultimate_pipeline.main_pipeline"
                    or main_file.endswith("/ultimate_pipeline/main_pipeline.py")
                )
            except Exception:
                enabled = False
    except Exception:
        enabled = False

    _BOOT_LOGS_ENABLED = bool(enabled)
    return bool(_BOOT_LOGS_ENABLED)


def _boot_log(message: str) -> None:
    if _boot_logs_enabled():
        print(message)


def _resolve_input_xodr_with_fallback(base_output_dir: str) -> str:
    """Search for newest 08_final*.xodr in base_output_dir subdirectories.

    Used when UP_DATA_ROOT is set but UP_INPUT_XODR is not, to automatically
    find the most recent pipeline output XODR file.

    Returns:
        Path to newest 08_final*.xodr or empty string if none found.
    """
    try:
        base = Path(base_output_dir)
        if not base.is_dir():
            return ""

        best_path = ""
        best_mtime = 0.0

        # Search subdirectories for 08_final*.xodr files
        for run_dir in base.iterdir():
            if not run_dir.is_dir():
                continue
            for xodr in run_dir.glob("08_final*.xodr"):
                try:
                    mtime = xodr.stat().st_mtime
                    if mtime > best_mtime:
                        best_mtime = mtime
                        best_path = str(xodr)
                except Exception:
                    continue

        return best_path
    except Exception:
        return ""


# =====================================================================
# MAIN SETTINGS CLASS
# =====================================================================
@dataclass
class Settings:
    SETTINGS_SCHEMA_VERSION = "1.0"

    REQUIRED_SNAPSHOT_KEYS = {
        "ENABLE_LIBOPENDRIVE_VALIDATION",
        "LIBOPENDRIVE_VALIDATION_STRICT",
        # --- Tile / QA ---
        "ENABLE_TILING",
        "USE_TILE_METADATA_GATE",
        "STRICT_TILE_SEMANTICS",
        "TILE_SIZE",
        "TILE_AUTO_FORENSICS_TRIGGER_N",
        "TILE_SPAWN_ATTEMPTS",
        "TILE_SPAWN_Z_OFFSET_M",
        "TILE_SPAWN_FORWARD_M",
        "ENABLE_SPAWN_QA",
        "ENABLE_TILE_STRESS_TEST",
        # --- CARLA ---
        "ALLOW_FULL_LOAD_IN_STEP_10",
        "CARLA_HOST",
        "CARLA_PORT",
        "CARLA_STREAMING_PORT",
        # --- Determinism ---
        "DETERMINISTIC_MODE",
        "DETERMINISTIC_SEED",
        # --- Tiling artifacts ---
        "TILE_ADJ_JSON",
        "TILE_METADATA_JSON",
        # --- Seams ---
        "SEAM_MAX_LATERAL",
        "SEAM_MAX_HEADING",
        "SEAM_MAX_ELEV",
        "ABORT_ON_SEAM_FAIL",
        "ENABLE_SEAM_STATS_EXPORT",
        "SEAM_STATS_JSON",
        "ENABLE_SEAM_ARTIFACTS",
        "ENABLE_JUNCTION_LINK_PATCH",
        "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR",
        "PLANVIEW_SEAM_AUTO_REPAIR_MAX_M",
        # --- Domain Gap ---
        "ENABLE_DOMAIN_GAP",
        "MANUAL_MAP_XODR",
        "MANUAL_TILES_DIR",
        "DOMAIN_GAP_OUT_DIR",
        "PERCEPTION_MANUAL_JSON",
        "PERCEPTION_AUTO_JSON",
        "MANUAL_CARLA_MAPS",
        "DEM_MIN_ELEVATION_STD",
        "DEM_STRICT_MIN_ELEVATION_STD_DEFAULT",
        "DEM_NODATA_RATIO_FAIL_THRESHOLD",
        "DEM_SUSPICIOUS_RASTER_RANGE_THRESHOLD",
        "DEM_FLAT_SAMPLE_RANGE_THRESHOLD",
        "AUTO_REPROJECT_DEM_ON_QC_FAIL",
        "DEM_SUSPICIOUS_SLOPE_THRESHOLD",
        "DEM_SUSPICIOUS_JUMP_THRESHOLD_M",
        "DEM_SUSPICIOUS_TOP_K",
        "STRICT_DEM_SUSPICIOUS_FAIL",
        "DEM_SUSPICIOUS_RATIO_FAIL_THRESHOLD",
        "STRICT_QUALITY_GATES",
        "THESIS_STRICT",
        "RELEASE_PROFILE",
        "ENABLE_UNSAFE_SHORT_SEGMENT_MERGE",
        "ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE",
        "ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING",
        "ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP",
        "ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE",
        "ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK",
    }

    RELEASE_PROFILES = {
        "DEVELOPMENT": {
            "description": "Exploratory development - permissive, allows heuristic repairs",
            "ENABLE_ROUNDABOUT_RECONSTRUCTION": False,
            "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR": False,
            "STRICT_QUALITY_GATES": False,
            "STRICT_TILE_SEMANTICS": False,
            "ENABLE_TRAFFIC_LIGHTS": True,
            "ENABLE_SIDEWALKS": True,
            "ENABLE_BUILDINGS": True,
            "ENABLE_REALISM": True,
            "ALLOW_FALLBACK_MAP": True,
            "ALLOW_TILE_QA_SKIP": True,
        },
        "EXPERIMENTAL_UNSAFE": {
            "description": "Explicit local diagnostics profile that may enable unsafe mutators by individual flag",
            "ENABLE_ROUNDABOUT_RECONSTRUCTION": False,
            "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR": False,
            "STRICT_QUALITY_GATES": False,
            "STRICT_TILE_SEMANTICS": False,
            "ENABLE_TRAFFIC_LIGHTS": True,
            "ENABLE_SIDEWALKS": True,
            "ENABLE_BUILDINGS": True,
            "ENABLE_REALISM": True,
            "ALLOW_FALLBACK_MAP": True,
            "ALLOW_TILE_QA_SKIP": True,
        },
        "STRUCTURAL_RELEASE": {
            "description": "Structural XODR readiness - immutable stages, fail-closed gates",
            "ENABLE_ROUNDABOUT_RECONSTRUCTION": False,
            "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR": False,
            "STRICT_QUALITY_GATES": True,
            "STRICT_TILE_SEMANTICS": True,
            "ENABLE_TRAFFIC_LIGHTS": False,
            "ENABLE_SIDEWALKS": False,
            "ENABLE_BUILDINGS": False,
            "ENABLE_REALISM": False,
            "ALLOW_FALLBACK_MAP": False,
            "ALLOW_TILE_QA_SKIP": False,
        },
        "CARLA_RELEASE": {
            "description": "CARLA drivable standalone - exact map load, distributed spawn/route/tick diagnostics",
            "ENABLE_ROUNDABOUT_RECONSTRUCTION": False,
            "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR": False,
            "STRICT_QUALITY_GATES": True,
            "STRICT_TILE_SEMANTICS": True,
            "ENABLE_TRAFFIC_LIGHTS": False,
            "ENABLE_SIDEWALKS": True,
            "ENABLE_BUILDINGS": True,
            "ENABLE_REALISM": True,
            "ALLOW_FALLBACK_MAP": False,
            "ALLOW_TILE_QA_SKIP": False,
        },
        "VISUAL_RELEASE": {
            "description": "Visual map cooking - aligned cooked package, semantics, materials, collision, LOD, signals",
            "ENABLE_ROUNDABOUT_RECONSTRUCTION": False,
            "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR": False,
            "STRICT_QUALITY_GATES": True,
            "STRICT_TILE_SEMANTICS": True,
            "ENABLE_TRAFFIC_LIGHTS": True,
            "ENABLE_SIDEWALKS": True,
            "ENABLE_BUILDINGS": True,
            "ENABLE_REALISM": True,
            "ALLOW_FALLBACK_MAP": False,
            "ALLOW_TILE_QA_SKIP": False,
        },
        "PERCEPTION_RELEASE": {
            "description": "Perception sensor readiness - canonical calibrated rig, stable multimodal capture",
            "ENABLE_ROUNDABOUT_RECONSTRUCTION": False,
            "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR": False,
            "STRICT_QUALITY_GATES": True,
            "STRICT_TILE_SEMANTICS": True,
            "ENABLE_TRAFFIC_LIGHTS": True,
            "ENABLE_SIDEWALKS": True,
            "ENABLE_BUILDINGS": True,
            "ENABLE_REALISM": True,
            "ALLOW_FALLBACK_MAP": False,
            "ALLOW_TILE_QA_SKIP": False,
        },
    }

    RELEASE_PROFILE: str = "DEVELOPMENT"

    def _apply_release_profile(self) -> None:
        """Apply release profile settings immutably - fail-closed for release profiles."""
        profile_name = self.RELEASE_PROFILE
        if profile_name not in self.RELEASE_PROFILES:
            raise RuntimeError(
                f"Unknown RELEASE_PROFILE: {profile_name}. "
                f"Valid: {list(self.RELEASE_PROFILES.keys())}"
            )
        profile = self.RELEASE_PROFILES[profile_name]
        unsafe_allowed = profile_name == "EXPERIMENTAL_UNSAFE" and not bool(self.THESIS_STRICT)
        is_release = profile_name not in ("DEVELOPMENT", "EXPERIMENTAL_UNSAFE")
        unsafe_keys = (
            "ENABLE_UNSAFE_SHORT_SEGMENT_MERGE",
            "ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE",
            "ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING",
            "ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP",
            "ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE",
            "ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK",
        )
        if not unsafe_allowed:
            for _unsafe_key in unsafe_keys:
                if getattr(self, _unsafe_key, False):
                    raise RuntimeError(
                        f"RELEASE_PROFILE={profile_name} forbids {_unsafe_key}=True. "
                        "Unsafe geometry mutations require RELEASE_PROFILE=EXPERIMENTAL_UNSAFE."
                    )
            if getattr(self, "ENABLE_GEOMETRY_START_RECOMPUTE", False):
                raise RuntimeError(
                    f"RELEASE_PROFILE={profile_name} forbids ENABLE_GEOMETRY_START_RECOMPUTE=True. "
                    "Use ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE only under RELEASE_PROFILE=EXPERIMENTAL_UNSAFE."
                )

        for key, value in profile.items():
            if key == "description":
                continue
            setattr(self, key, value)

        if is_release:
            self.THESIS_STRICT = True
            self.STRICT_QUALITY_GATES = True
            self.STRICT_TILE_SEMANTICS = True
            self.ALLOW_FALLBACK_MAP = False
            self.ALLOW_TILE_QA_SKIP = False

    def to_dict(self) -> dict:
        data = {
            # --- Meta ---
            "_schema_version": self.SETTINGS_SCHEMA_VERSION,
            "_exported_at_utc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "RELEASE_PROFILE": self.RELEASE_PROFILE,
            # --- Core paths ---
            "INPUT_XODR": self.INPUT_XODR,
            "OSM_FILE": self.OSM_FILE,
            # --- External validation (libOpenDRIVE) ---
            "ENABLE_LIBOPENDRIVE_VALIDATION": self.ENABLE_LIBOPENDRIVE_VALIDATION,
            "LIBOPENDRIVE_VALIDATION_STRICT": self.LIBOPENDRIVE_VALIDATION_STRICT,
            # --- Tile / QA ---
            "ENABLE_TILING": self.ENABLE_TILING,
            "USE_TILE_METADATA_GATE": self.USE_TILE_METADATA_GATE,
            "STRICT_TILE_SEMANTICS": self.STRICT_TILE_SEMANTICS,
            "TILE_SIZE": self.TILE_SIZE,
            "TILE_MATCH_MIN_IOU_FOR_GAP": getattr(
                self, "TILE_MATCH_MIN_IOU_FOR_GAP", 0.9
            ),
            "TILE_AUTO_FORENSICS_TRIGGER_N": self.TILE_AUTO_FORENSICS_TRIGGER_N,
            "TILE_SPAWN_ATTEMPTS": self.TILE_SPAWN_ATTEMPTS,
            "TILE_SPAWN_Z_OFFSET_M": self.TILE_SPAWN_Z_OFFSET_M,
            "TILE_SPAWN_FORWARD_M": self.TILE_SPAWN_FORWARD_M,
            "ENABLE_SPAWN_QA": self.ENABLE_SPAWN_QA,
            "ENABLE_TILE_STRESS_TEST": self.ENABLE_TILE_STRESS_TEST,
            # --- Geometry / Semantics ---
            "ENABLE_ROUNDABOUT_RECONSTRUCTION": self.ENABLE_ROUNDABOUT_RECONSTRUCTION,
            "ENABLE_SIDEWALKS": self.ENABLE_SIDEWALKS,
            "ENABLE_TRAFFIC_LIGHTS": self.ENABLE_TRAFFIC_LIGHTS,
            "ENABLE_BUILDINGS": self.ENABLE_BUILDINGS,
            "ENABLE_REALISM": self.ENABLE_REALISM,
            # --- Geometry tuning ---
            "CURVATURE_MAX_ALLOWED": self.CURVATURE_MAX_ALLOWED,
            "MIN_GEOM_MERGE_LENGTH": self.MIN_GEOM_MERGE_LENGTH,
            "ENABLE_UNSAFE_SHORT_SEGMENT_MERGE": self.ENABLE_UNSAFE_SHORT_SEGMENT_MERGE,
            "ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE": self.ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE,
            "ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING": self.ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING,
            "ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP": self.ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP,
            "ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE": self.ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE,
            "ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK": self.ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK,
            "CONTINUITY_MODE": self.CONTINUITY_MODE,
            # --- Domain-gap / metric performance ---
            "GEOMETRY_GAP_MAX_SAMPLES": getattr(self, "GEOMETRY_GAP_MAX_SAMPLES", None),
            "GEOMETRY_GAP_SKIP_HAUSDORFF": getattr(
                self, "GEOMETRY_GAP_SKIP_HAUSDORFF", None
            ),
            "DEM_MIN_ELEVATION_STD": float(getattr(self, "DEM_MIN_ELEVATION_STD", 0.0)),
            "DEM_STRICT_MIN_ELEVATION_STD_DEFAULT": float(
                getattr(self, "DEM_STRICT_MIN_ELEVATION_STD_DEFAULT", 0.01)
            ),
            "DEM_NODATA_RATIO_FAIL_THRESHOLD": float(
                getattr(self, "DEM_NODATA_RATIO_FAIL_THRESHOLD", 0.2)
            ),
            "DEM_SUSPICIOUS_RASTER_RANGE_THRESHOLD": float(
                getattr(self, "DEM_SUSPICIOUS_RASTER_RANGE_THRESHOLD", 0.5)
            ),
            "DEM_FLAT_SAMPLE_RANGE_THRESHOLD": float(
                getattr(self, "DEM_FLAT_SAMPLE_RANGE_THRESHOLD", 0.05)
            ),
            "AUTO_REPROJECT_DEM_ON_QC_FAIL": bool(
                getattr(self, "AUTO_REPROJECT_DEM_ON_QC_FAIL", False)
            ),
            "DEM_SUSPICIOUS_SLOPE_THRESHOLD": float(
                getattr(self, "DEM_SUSPICIOUS_SLOPE_THRESHOLD", 0.25)
            ),
            "DEM_SUSPICIOUS_JUMP_THRESHOLD_M": float(
                getattr(self, "DEM_SUSPICIOUS_JUMP_THRESHOLD_M", 0.5)
            ),
            "DEM_SUSPICIOUS_TOP_K": int(getattr(self, "DEM_SUSPICIOUS_TOP_K", 10)),
            "STRICT_DEM_SUSPICIOUS_FAIL": bool(
                getattr(self, "STRICT_DEM_SUSPICIOUS_FAIL", False)
            ),
            "DEM_SUSPICIOUS_RATIO_FAIL_THRESHOLD": float(
                getattr(self, "DEM_SUSPICIOUS_RATIO_FAIL_THRESHOLD", 0.25)
            ),
            # --- Research / strictness contract ---
            # These keys are part of REQUIRED_SNAPSHOT_KEYS and must always be present
            # to make research runs fully reproducible.
            "STRICT_QUALITY_GATES": bool(getattr(self, "STRICT_QUALITY_GATES", False)),
            "THESIS_STRICT": bool(getattr(self, "THESIS_STRICT", False)),
            "PREANCHOR_INPUT_XODR": bool(
                getattr(self, "PREANCHOR_INPUT_XODR", False)
            ),
            # --- Perception ---
            "ENABLE_LOCAL_PERCEPTION": self.ENABLE_LOCAL_PERCEPTION,
            "ENABLE_SCREENSHOTS": self.ENABLE_SCREENSHOTS,
            "LOW_MEMORY_PROFILE_ACTIVE": bool(
                getattr(self, "LOW_MEMORY_PROFILE_ACTIVE", False)
            ),
            "MAX_NPCS_LOCAL": int(getattr(self, "MAX_NPCS_LOCAL", 0)),
            "STRICT_FAIL_ON_GEOMETRIC_CONTINUITY_GATE": bool(
                getattr(
                    self,
                    "STRICT_FAIL_ON_GEOMETRIC_CONTINUITY_GATE",
                    False,
                )
            ),
            # --- CARLA ---
            "ALLOW_FULL_LOAD_IN_STEP_10": self.ALLOW_FULL_LOAD_IN_STEP_10,
            "CARLA_HOST": self.CARLA_HOST,
            "CARLA_PORT": self.CARLA_PORT,
            "CARLA_STREAMING_PORT": self.CARLA_STREAMING_PORT,
            "CARLA_DEFAULT_MAP": str(getattr(self, "CARLA_DEFAULT_MAP", "")),
            # --- Determinism ---
            "DETERMINISTIC_MODE": self.DETERMINISTIC_MODE,
            "DETERMINISTIC_SEED": self.DETERMINISTIC_SEED,
            # --- Tiling artifacts ---
            "TILE_ADJ_JSON": self.TILE_ADJ_JSON,
            "TILE_METADATA_JSON": self.TILE_METADATA_JSON,
            # --- Seams ---
            "SEAM_MAX_LATERAL": self.SEAM_MAX_LATERAL,
            "SEAM_MAX_HEADING": self.SEAM_MAX_HEADING,
            "SEAM_MAX_ELEV": self.SEAM_MAX_ELEV,
            "ABORT_ON_SEAM_FAIL": self.ABORT_ON_SEAM_FAIL,
            "ENABLE_SEAM_STATS_EXPORT": self.ENABLE_SEAM_STATS_EXPORT,
            "SEAM_STATS_JSON": self.SEAM_STATS_JSON,
            "ENABLE_SEAM_ARTIFACTS": self.ENABLE_SEAM_ARTIFACTS,
            "ENABLE_JUNCTION_LINK_PATCH": self.ENABLE_JUNCTION_LINK_PATCH,
            "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR": bool(
                getattr(self, "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR", True)
            ),
            "PLANVIEW_SEAM_AUTO_REPAIR_MAX_M": float(
                getattr(self, "PLANVIEW_SEAM_AUTO_REPAIR_MAX_M", 0.05)
            ),
            # --- Domain Gap ---
            "ENABLE_DOMAIN_GAP": self.ENABLE_DOMAIN_GAP,
            "MANUAL_MAP_XODR": self.MANUAL_MAP_XODR,
            "MANUAL_TILES_DIR": self.MANUAL_TILES_DIR,
            "DOMAIN_GAP_OUT_DIR": self.DOMAIN_GAP_OUT_DIR,
            "PERCEPTION_MANUAL_JSON": self.PERCEPTION_MANUAL_JSON,
            "PERCEPTION_AUTO_JSON": self.PERCEPTION_AUTO_JSON,
            "MANUAL_CARLA_MAPS": list(self.MANUAL_CARLA_MAPS),
        }

        missing = self.REQUIRED_SNAPSHOT_KEYS - data.keys()
        if missing:
            raise RuntimeError(
                f"Settings.to_dict() is missing required snapshot keys: {sorted(missing)}"
            )

        return data

    # (path normalization happens in the class-level __post_init__ at the bottom)

    # -----------------------------------------------------------------
    # 1) CARLA CORE CONFIGURATION
    # -----------------------------------------------------------------
    CARLA_HOST: str = "127.0.0.1"
    CARLA_PORT: int = 2000
    # CARLA uses a separate streaming port for sensor/actor data. By default this is RPC+1.
    # If you override this, you MUST also start the CARLA server with the matching flag.
    CARLA_STREAMING_PORT: int | None = None
    CARLA_TILE_WORKER_RPC_TIMEOUT: float = 30.0  # seconds: tile_worker RPC timeout
    CARLA_POST_LOAD_TICK_TIMEOUT: float = (
        5.0  # seconds: wait_for_tick after world (re)load/import
    )
    CARLA_READY_TICK_TIMEOUT: float = (
        2.0  # seconds: wait_for_tick during readiness check
    )
    CARLA_TIMEOUT: float = 20.0
    # UP_CARLA_EXE env override is authoritative (canonical = E:\CARLA\CARLA_0.9.16\CarlaUE4.exe).
    # _pick_existing fallback lists the canonical non-editor build first;
    # WindowsNoEditor is a secondary fallback only.
    CARLA_EXE: str = _env_path(
        "UP_CARLA_EXE",
        _pick_existing(
            r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe",
            r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe",
        ),
    )
    CARLA_STARTUP_MODE = "windows_safe"  # or "hpc"

    # -----------------------------------------------------------------
    # Map load policy + fallback (for perception capture)
    # -----------------------------------------------------------------
    CARLA_ENABLE_MAP_FALLBACK: bool = False
    ALLOW_FALLBACK_MAP: bool = True
    # Try these in order if OpenDRIVE generation fails
    CARLA_FALLBACK_MAPS = ("Town10HD_Opt", "Town05", "Town03", "Town01")
    # If True, skip OpenDRIVE entirely and use the built-in map below
    CARLA_FORCE_BUILTIN_MAP: bool = False
    CARLA_BUILTIN_MAP: str = "Town10HD_Opt"
    # Optional cooked map preload at CARLA server startup.
    CARLA_DEFAULT_MAP: str = os.getenv("UP_CARLA_DEFAULT_MAP", "").strip()

    # -----------------------------------------------------------------
    # Tile QA isolation control
    # -----------------------------------------------------------------
    ALLOW_TILE_QA_SKIP: bool = True

    # -----------------------------------------------------------------
    # CARLA startup / recovery tuning
    # -----------------------------------------------------------------
    CARLA_STARTUP_WAIT: float = 25.0  # seconds (Windows-safe)
    CARLA_CONNECT_RETRIES: int = 10
    CARLA_KILL_ON_FAIL: bool = True  # can be disabled for debugging

    # Manual CARLA maps available in the runtime (manual / thesis maps)
    MANUAL_CARLA_MAPS: tuple[str, ...] = ("Grid0821", "Grid0828")

    # -----------------------------------------------------------------
    # Legacy compatibility (do not remove yet)
    # -----------------------------------------------------------------
    @property
    def CARLA_SERVER_PATH(self) -> str:
        """
        Backward-compat alias for older CARLA startup code.
        """
        return self.CARLA_EXE

    def autodetect_carla_exe(self):
        """
        Try to auto-detect CARLA executable across drives.
        """
        drives = ["C:\\", "D:\\", "E:\\"]
        candidate_dirs = [
            "CARLA",
            "carla",
            os.path.join("Program Files", "CARLA"),
            os.path.join("Program Files", "carla"),
            os.path.join("Program Files (x86)", "CARLA"),
            os.path.join("Program Files (x86)", "carla"),
            os.path.join("Epic Games", "CARLA"),
            os.path.join("Epic Games", "carla"),
        ]
        candidate_rel_exes = [
            "CarlaUE4.exe",
            "CarlaUE4-Win64-Shipping.exe",
            os.path.join("WindowsNoEditor", "CarlaUE4.exe"),
            os.path.join("CarlaUE4", "Binaries", "Win64", "CarlaUE4-Win64-Shipping.exe"),
            os.path.join(
                "WindowsNoEditor",
                "CarlaUE4",
                "Binaries",
                "Win64",
                "CarlaUE4-Win64-Shipping.exe",
            ),
        ]
        for drive in drives:
            for rel_dir in candidate_dirs:
                base = os.path.join(drive, rel_dir)
                if not os.path.isdir(base):
                    continue
                search_roots = [base]
                try:
                    search_roots.extend(
                        os.path.join(base, entry)
                        for entry in os.listdir(base)
                        if os.path.isdir(os.path.join(base, entry))
                    )
                except OSError:
                    continue
                for root in search_roots:
                    for rel_exe in candidate_rel_exes:
                        exe_path = os.path.join(root, rel_exe)
                        if os.path.isfile(exe_path):
                            return exe_path
        return None

    def carla_enabled(self) -> bool:
        return not self.CARLA_SAFE_MODE and (
            self.ENABLE_CARLA_TEST_EARLY or self.ENABLE_CARLA_TEST_LATE
        )

    # -----------------------------------------------------------------
    # PIPELINE VERSIONING FOR SCIENTIFIC REPRODUCIBILITY
    # -----------------------------------------------------------------
    CARLA_BUILD_HASH: str = "0.9.16-win64"
    OSM_CONVERTER_VERSION: str = "2025-01-17"
    DEM_VERSION: str = "COP30_2024_R3"
    PIPELINE_VERSION: str = "2.0-beta"

    # -----------------------------------------------------------------
    # 0) DETERMINISM / REPRODUCIBILITY
    # -----------------------------------------------------------------
    DETERMINISTIC_MODE: bool = True
    DETERMINISTIC_SEED: int = 42
    DETERMINISM_SEED_TORCH: bool = False
    PIPELINE_START_TIME: float = field(default_factory=time.time)

    # -----------------------------------------------------------------
    # 2) INPUT / OUTPUT PATHS
    # -----------------------------------------------------------------
    # C11: default OFF. tools/preanchor_xodr.py is not present in this repo;
    # a default-True value makes a clean-checkout default run crash with
    # ImportError before stage 01 whenever GPS bounds are available.
    # Preanchoring re-frames off the Osm2Odr tmerc(0,0) frame that the DEM
    # contract needs, and no known working run used it. Explicit opt-in via
    # UP_PREANCHOR_INPUT_XODR=1 remains available.
    PREANCHOR_INPUT_XODR: bool = _env_bool("UP_PREANCHOR_INPUT_XODR", False)
    INPUT_XODR: str = str(
        resolve_path(
            os.getenv("UP_INPUT_XODR", None)
            or city_dir(CITY_NAME) / f"{CITY_NAME}_osm_auto.xodr",
            default=city_dir(CITY_NAME) / f"{CITY_NAME}_osm_auto.xodr",
        )
    )
    GENERATED_XODR: str = str(
        resolve_path(
            os.getenv("UP_GENERATED_XODR", None)
            or city_dir(CITY_NAME) / f"{CITY_NAME}.xodr",
            default=city_dir(CITY_NAME) / f"{CITY_NAME}.xodr",
        )
    )
    # Legacy compatibility alias for system_integrity_checker
    XODR_OUTPUT_FILE: str = INPUT_XODR

    # Keep commented manual-map path hints (for later domain-gap)
    # MANUAL_MAP_XODR: str = INPUT_XODR#(
    # Manual reference OpenDRIVE map (domain-gap / thesis strict).
    # Env precedence: UP_MANUAL_XODR_GRID0828, then UP_MANUAL_XODR (legacy).
    MANUAL_MAP_XODR: str = os.getenv("UP_MANUAL_XODR_GRID0828", "") or os.getenv("UP_MANUAL_XODR", "")
    # e.g. r"C:\path\to\manual_map.xodr"
    # Optional: directory containing manual reference tiles (.xodr per tile). Leave empty to skip per-tile gaps.
    # Split-root guard: override with UP_MANUAL_TILES_DIR to avoid loading from carla_-main
    MANUAL_TILES_DIR: str = _env_path(
        "UP_MANUAL_TILES_DIR",
        str(PROJECT_ROOT / "domain_gap_results" / "manual_tiles"),
    )
    # e.g. r"C:\path\to\manual_tiles"

    # Split-root guard: override with UP_BASE_OUTPUT_DIR to avoid writing to carla_-main
    BASE_OUTPUT_DIR: str = _env_path(
        "UP_BASE_OUTPUT_DIR",
        str(PROJECT_ROOT / "ultimate_pipeline_out"),
    )
    OUTPUT_DIR_OVERRIDE: str = ""

    timestamp: str = field(default_factory=_default_timestamp)

    # ------------------------------
    # Mesh Continuity Repair Settings
    # ------------------------------
    # Ingolstadt-tuned continuity parameters

    # "safe" | "moderate" | "aggressive"
    CONTINUITY_MODE: str = "moderate"
    CONTINUITY_SELECTIVE: bool = True

    # thresholds
    MAX_GAP_FOR_FIX: float = 3.0  # meters
    MAX_HEADING_JUMP_FIX: float = math.radians(10.0)  # radians
    MAX_SEGMENT_LENGTH_FIX: float = 1500.0  # meters

    # behavior
    STRICT_PASS_THROUGH: bool = True
    ENABLE_GAP_INTERPOLATION: bool = True
    ENABLE_HEADING_DAMPING: bool = True
    ENABLE_CURVATURE_SMOOTHING: bool = False
    CONT_SMOOTH_WEIGHT: float = 0.25

    # --- Geometry merge settings ---
    MIN_GEOM_MERGE_LENGTH: float = 2.0
    MAX_GEOM_MERGE_LENGTH: float = 300.0
    GEOMETRY_FROZEN = True
    # --- Unsafe geometry mutation containment flags (all disabled by default) ---
    ENABLE_UNSAFE_SHORT_SEGMENT_MERGE: bool = False
    ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE: bool = False
    ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING: bool = False
    ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP: bool = False
    ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE: bool = False
    ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK: bool = False
    # --- Curvature clamp for planView smoother ---
    CURVATURE_MAX_ALLOWED: float = 1.0  # used before continuity repair

    # -----------------------------------------------------------------
    # 3) DEM & GIS SETTINGS
    # -----------------------------------------------------------------
    OPENTOPO_API_KEY: str = os.getenv("OPENTOPO_API_KEY", "")
    DEM_PROVIDER: str = "COP30"
    ENABLE_DEM_AUTO_DOWNLOAD: bool = True

    DEM_DIR: str = str(
        resolve_path(
            os.getenv("UP_DEM_DIR", None) or city_dir(CITY_NAME) / "dem",
            default=city_dir(CITY_NAME) / "dem",
        )
    )
    DEM_FILENAME: str = "dem_ing.tif"
    DEM_EXPANDED_TIF_PATH: str = str(
        resolve_path(
            os.getenv("UP_DEM_EXPANDED_TIF_PATH", None)
            or city_dir(CITY_NAME) / "dem" / "dem_ing_expanded.tif",
            default=city_dir(CITY_NAME) / "dem" / "dem_ing_expanded.tif",
        )
    )

    @property
    def DEM_TIF(self) -> str:
        return os.path.join(self.DEM_DIR, self.DEM_FILENAME)

    # legacy compatibility alias
    DEM_FILE: str = ""

    # DEM smoothing (to remove spikes before ElevationSmoother)
    ENABLE_DEM_SMOOTHING: bool = True
    DEM_SMOOTHING_SIGMA: float = 1.0
    # DEM hardening controls (thesis-safe defaults)
    DEM_STRICT_MODE: bool = True
    FAIL_ON_FLAT_ELEVATION: bool = True
    ENABLE_DEM_CRS_TRANSFORM: bool = True
    DEM_FULL_COVERAGE_THRESHOLD: float = 0.6
    DEM_FULL_COVERAGE_STEP_M: float = 2.0
    DEM_FULL_COVERAGE_MAX_SAMPLES: int = 250000
    DEM_FULL_COVERAGE_STRICT: bool = True
    DEM_MIN_ELEVATION_VARIANCE: float = 0.0
    DEM_MIN_ELEVATION_STD: float = 0.0
    DEM_STRICT_MIN_ELEVATION_STD_DEFAULT: float = 0.01
    DEM_NODATA_RATIO_FAIL_THRESHOLD: float = 0.2
    DEM_SUSPICIOUS_RASTER_RANGE_THRESHOLD: float = 0.5
    DEM_FLAT_SAMPLE_RANGE_THRESHOLD: float = 0.05
    AUTO_REPROJECT_DEM_ON_QC_FAIL: bool = False
    DEM_SUSPICIOUS_SLOPE_THRESHOLD: float = 0.25
    DEM_SUSPICIOUS_JUMP_THRESHOLD_M: float = 0.5
    DEM_SUSPICIOUS_TOP_K: int = 10
    STRICT_DEM_SUSPICIOUS_FAIL: bool = False
    DEM_SUSPICIOUS_RATIO_FAIL_THRESHOLD: float = 0.25
    # 2-point linear grade: sample road start/end and compute b=(z_end - z_start)/length
    # Default OFF: keeps flat (b=0) elevation segments for CARLA stability.
    ELEVATION_LINEAR_GRADE: bool = _env_bool("UP_ELEVATION_LINEAR_GRADE", False)

    # Optional: schema for final XODR validation (if you provide XSD)
    XODR_XSD_PATH: str | None = None  # e.g. r"...\OpenDRIVE_1.5.xsd"

    # ----------------------------------------
    # OSM DOWNLOAD CONTROL (UPSTREAM DATA)
    # ----------------------------------------

    ENABLE_OSM_DOWNLOAD: bool = True  # 🔄 master switch

    # -----------------------------------------------------------------
    # 4) OSM / GPS BOUNDS / BUILDINGS
    # -----------------------------------------------------------------
    # Split-root guard: override with UP_COORDINATES_JSON to avoid reading from carla_-main
    COORDINATES_JSON: str = _env_path(
        "UP_COORDINATES_JSON",
        str(PROJECT_ROOT / "ultimate_pipeline" / "config" / "coordinates.json"),
    )

    # Default GPS bounds (used if coordinates.json is missing)
    DEFAULT_GPS_BOUNDS = {
        "lat_min": 48.74935649548228,
        "lon_min": 11.422268084715878,
        "lat_max": 48.77444431571603,
        "lon_max": 11.47882091528412,
    }

    OSM_FILE: str = str(
        resolve_path(
            os.getenv("UP_OSM_FILE", None)
            or city_dir(CITY_NAME) / "osm" / f"{CITY_NAME}.osm",
            default=city_dir(CITY_NAME) / "osm" / f"{CITY_NAME}.osm",
        )
    )
    # Alias used by older modules / system_integrity_checker
    OSM_INPUT_FILE: str = OSM_FILE

    OSM_BUILDINGS_GEOJSON: str = str(
        resolve_path(
            os.getenv("UP_OSM_BUILDINGS_GEOJSON", None)
            or city_dir(CITY_NAME) / "osm" / "buildings.geojson",
            default=city_dir(CITY_NAME) / "osm" / "buildings.geojson",
        )
    )
    ENRICHMENTS_RUNTIME_DIRNAME: str = str(
        os.getenv("UP_ENRICHMENTS_RUNTIME_DIRNAME", "enrichments") or "enrichments"
    ).strip() or "enrichments"
    ENRICHMENTS_RUNTIME_JSON_NAME: str = str(
        os.getenv("UP_ENRICHMENTS_RUNTIME_JSON_NAME", "enrichments_runtime.json")
        or "enrichments_runtime.json"
    ).strip() or "enrichments_runtime.json"
    ENRICHMENTS_GENERATOR_MIN_OBJECTS: int = max(
        10, int(os.getenv("UP_ENRICHMENTS_GENERATOR_MIN_OBJECTS", "12") or "12")
    )

    # -----------------------------------------------------------------
    # OSM → XODR generation (optional, thesis experiments)
    # -----------------------------------------------------------------
    # By default the pipeline starts from an existing INPUT_XODR.
    # Enable this if you want the repo itself to call an OSM→XODR tool.
    GENERATE_XODR_FROM_OSM: bool = False
    # Optional explicit path to an OSM→XODR converter (script or binary).
    # If empty, convert_osm_to_xodr() will try CARLA_ROOT tools.
    OSM_TO_XODR_TOOL: str = ""
    # Where to place generated XODRs (relative paths are resolved under BASE_OUTPUT_DIR)
    OSM_TO_XODR_OUT_DIR: str = "maps_generated"
    # If True, regenerate even if the output file already exists.
    OSM_TO_XODR_OVERWRITE: bool = True

    def load_gps_bounds(self) -> dict:
        import json

        # Prefer coordinates.json if it exists, otherwise fall back to DEFAULT_GPS_BOUNDS
        if os.path.exists(self.COORDINATES_JSON):
            with open(self.COORDINATES_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in ["lat_min", "lat_max", "lon_min", "lon_max"]:
                if k not in data:
                    raise KeyError(f"Missing {k} in coordinates.json")
            return data

        # Fallback: embedded bounds (thesis Ingolstadt cut)
        return dict(self.DEFAULT_GPS_BOUNDS)

    def lat0(self):
        return self.load_gps_bounds()["lat_min"]

    def lon0(self):
        return self.load_gps_bounds()["lon_min"]

    # -----------------------------------------------------------------
    # 5) SUMO
    # -----------------------------------------------------------------
    SUMO_NETCONVERT: str = (
        r"C:\Sumo\sumo-win64extra-1.24.0\sumo-1.24.0\bin\netconvert.exe"
    )

    # -----------------------------------------------------------------
    # 6) CORE PIPELINE TOGGLES
    # -----------------------------------------------------------------
    ENABLE_SUMO_REPAIR: bool = True
    SUMO_REPAIR_PRESERVE_FRAME: bool = True
    ENABLE_CARLA_TEST_EARLY: bool = False
    ENABLE_CARLA_TEST_LATE: bool = True
    ENABLE_AUTOPILOT_VALIDATION: bool = True

    # -----------------------------------------------------------------
    # EXTERNAL VALIDATION (libOpenDRIVE)
    # -----------------------------------------------------------------
    ENABLE_LIBOPENDRIVE_VALIDATION: bool = False
    LIBOPENDRIVE_VALIDATION_STRICT: bool = False
    LIBOPENDRIVE_VALIDATOR_EXE: str | None = None
    LIBOPENDRIVE_VALIDATOR_TIMEOUT_S: float = 20.0

    # -----------------------------------------------------------------
    # OSM2WORLD (optional 3D scene artifacts)
    # -----------------------------------------------------------------
    ENABLE_OSM2WORLD: bool = False
    OSM2WORLD_HOME: str = ""
    OSM2WORLD_CONFIG: str = ""
    OSM2WORLD_TIMEOUT_SEC: int = 300

    # -----------------------------------------------------------------
    # THESIS PERCEPTION CAPTURE (paired artifacts)
    # -----------------------------------------------------------------
    ENABLE_THESIS_PERCEPTION_CAPTURE: bool = False
    THESIS_PERCEPTION_FRAMES: int = 200
    THESIS_PERCEPTION_FPS: float = 10.0
    THESIS_PERCEPTION_TIMEOUT_S: int = 600
    ENABLE_SINGLE_ROAD_DEBUG: bool = True

    # OSM preprocessing (tag normalization etc.)
    ENABLE_OSM_PREPROCESSING: bool = True

    # LaneSection and s-offset normalization
    ENABLE_LANESECTION_FIX: bool = True
    ENABLE_S_OFFSET_NORMALIZATION: bool = True

    # XML uniqueness + integrity checks (IDs, structure)
    ENABLE_XML_UNIQUENESS_CHECK: bool = True
    # -----------------------------------------------------------------
    # GEOMETRY QA (Offline, Non-CARLA)
    # -----------------------------------------------------------------
    ENABLE_SHAPELY_GEOMETRY_QA: bool = True
    USE_SHAPELY: bool = True
    ENABLE_QUALITY_GATES_WRAPPER: bool = True
    STRICT_FAIL_ON_GEOMETRIC_CONTINUITY_GATE: bool = False
    # -----------------------------------------------------------------
    # 7) ENRICHMENT MODULES
    # -----------------------------------------------------------------
    ENABLE_ROUNDABOUT_RECONSTRUCTION: bool = False
    ENABLE_TRAFFIC_LIGHTS: bool = False
    # Thesis contract: buildings must be enabled so we can (a) quantify semantic enrichment
    # and (b) optionally visualize via proxy spawning (CARLA does not render XODR <object> meshes).
    ENABLE_BUILDINGS: bool = True
    ENABLE_SIDEWALKS: bool = True

    # Realism submodules
    ENABLE_REALISM: bool = True
    ENABLE_REALISM_RULES: bool = True
    ENABLE_GUARDRAILS: bool = True
    ENABLE_BENCHES: bool = True
    ENABLE_SMART_LAMPS: bool = True
    ENABLE_TRASH_BINS: bool = True

    # Traffic light → lane validation
    ENABLE_SIGNAL_VALIDATION: bool = True

    # -----------------------------------------------------------------
    # 8) PERCEPTION / SENSOR QA SETTINGS
    # -----------------------------------------------------------------
    ENABLE_LOCAL_PERCEPTION: bool = True
    ENABLE_HPC_PERCEPTION: bool = False
    ENABLE_SPAWN_BUILDING_PROXIES_DURING_PERCEPTION: bool = False
    LOW_MEMORY_PROFILE_ACTIVE: bool = _env_bool("UP_LOW_MEMORY_PROFILE", False)
    LOW_MEMORY_PROFILE_NPC_CAP: int = 10

    # Extra run artifacts / QA
    # Disable heavy seam artifacts while debugging Windows stability.
    ENABLE_SEAM_ARTIFACTS: bool = False
    ENABLE_AUTOPILOT_TEST: bool = False
    FORCE_VALIDATE_NON_DRIVABLE_TILES: bool = False

    # Offline-only mode (skip CARLA-dependent stages). Can be forced with env UP_OFFLINE_ONLY=1
    OFFLINE_ONLY: bool = False

    SENSOR_CALIB_JSON: str = os.getenv(
        "SENSOR_CALIB_JSON",
        str(
            (
                Path(__file__).resolve().parents[1] / "sensors" / "calib_data.json"
            ).as_posix()
        ),
    )

    # Sensor calibration conventions (real-vehicle -> CARLA)
    SENSOR_FLIP_VEHICLE_Y: bool = bool(int(os.getenv("SENSOR_FLIP_VEHICLE_Y", "1")))
    SENSOR_OPENCV_CAMERA_AXES: bool = bool(
        int(os.getenv("SENSOR_OPENCV_CAMERA_AXES", "1"))
    )
    # "auto" (default), "ros" if LiDAR axes are ROS-like (y left) and need conversion to CARLA (y right)
    SENSOR_LIDAR_AXES_MODE: str = (
        os.getenv("SENSOR_LIDAR_AXES_MODE", "auto").strip().lower()
    )

    MAX_NPCS_LOCAL: int = 20
    NPC_SPEED_PERCENT: float = 0.4
    EGO_AUTOPILOT: bool = True
    MAX_EGO_SPEED: float = 35.0
    # Safety: never load FULL map during STEP 8
    FORCE_LIGHT_LOAD_IN_STEP_8 = True
    # Thesis gate: repair missing road<->junction links before tiling/CARLA stages.
    ENABLE_JUNCTION_LINK_PATCH: bool = str(
        os.getenv("UP_ENABLE_JUNCTION_LINK_PATCH", "1")
    ).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
        "y",
    )
    # ===============================
    # CARLA LOAD POLICY
    # ===============================
    # Allow loading full final map in STEP 10 (before tile QA)
    # False by default = safer, deterministic, CARLA-friendly
    ALLOW_FULL_LOAD_IN_STEP_10 = False  # 👈 turn ON when you want to try full load
    FULL_LOAD_TIMEOUT_S = 300  # optional, safer than default 60
    # -----------------------------------------------------------------
    # 9) TILING & TILE STREAMING
    # -----------------------------------------------------------------
    # ---------------------------
    # TILE / STREAMING CONTROLS
    # ---------------------------
    ENABLE_TILING = True

    # streaming (visual/analysis)
    TILE_STREAM_RADIUS = 2
    ENABLE_FOV_FILTERING = True
    VIS_RANGE_M = 150.0
    FOV_DEGREES = 120.0

    # CARLA load policy

    ENABLE_MESH_STREAMING = True

    VALIDATE_TILES: bool = True
    # ----------------------------------------
    # TILING SETTINGS (BUFFERED TILING)
    # ----------------------------------------

    # For Ingolstadt: 500m tiles, radius 2 ≈ good balance
    TILE_SIZE: float = 500.0
    # Per-tile domain-gap gating: require bbox IoU >= threshold
    TILE_MATCH_MIN_IOU_FOR_GAP: float = 0.5
    # Overlap / buffered tiling (0 = off). Typical: 30–100m.
    # Smaller buffers reduce geometry complexity per tile (often improves CARLA stability).
    TILE_BUFFER_M: float = 20.0
    # Optional: safety clamp so buffer doesn't explode tiles
    TILE_BUFFER_MAX_M: float = 30.0

    # If True: keep "buffer geometry" in tiles for CARLA, but mark core bbox in metadata
    TILE_WRITE_CORE_BBOX: bool = True

    # Tile streaming system
    ENABLE_SIM_TILE_STREAMING: bool = True  # required by simulator
    ENABLE_TILE_STREAMING: bool = True  # backward compatibility
    TILE_STREAMER_UPDATE_RATE: float = 0.5
    # --- TILING SEMANTICS POLICY ---
    PRESERVE_GLOBAL_LANE_TYPES_IN_TILES: bool = True
    ALLOW_SUCCESSOR_OUTSIDE_TILE: bool = True
    # ============================================================
    # TILE GENERATION / TILING SEMANTICS
    # ============================================================
    AUTO_FIX_NEGATIVE_S = True
    NEGATIVE_S_EPS = 0.05
    AUTO_DOWNLOAD_OSM = False
    # ------------------------------------------------------------
    # Tile buffering (CRITICAL for CARLA lane preservation)
    # ------------------------------------------------------------

    # Base geometric buffer applied to every tile (meters)
    # Prevents lane truncation, waypoint loss, and spawn failures

    # Enable adaptive buffering for long highway segments
    # Highway-aware buffer can balloon tiles; keep it off while isolating crashes.
    ENABLE_HIGHWAY_AWARE_TILE_BUFFER: bool = False

    # Extra buffer = road_length * alpha (meters per meter)
    HIGHWAY_TILE_BUFFER_ALPHA: float = 0.15

    # FOV / Visibility settings
    UNLOAD_RANGE_M: float = 400.0

    # Streaming metadata (relative; main_pipeline prepends output_dir)
    TILE_ADJ_JSON: str = "tile_adjacency.json"
    TILE_METADATA_JSON: str | None = "tile_metadata.json"

    @property
    def TILES_DIR(self) -> str:
        p = os.path.join(self.output_dir(), "tiles")
        os.makedirs(p, exist_ok=True)
        return p

    @property
    def TILE_ADJ_JSON_FULL(self) -> str:
        return os.path.join(self.output_dir(), self.TILE_ADJ_JSON)

    @property
    def TILE_METADATA_JSON_FULL(self) -> str | None:
        if self.TILE_METADATA_JSON is None:
            return None
        return os.path.join(self.output_dir(), self.TILE_METADATA_JSON)

    # -----------------------------------------------------------------
    # 10) TILE SEAM VALIDATION (Step 10)
    # -----------------------------------------------------------------
    SEAM_MAX_LATERAL: float = 0.20  # meters
    SEAM_MAX_HEADING: float = 0.20  # radians
    SEAM_MAX_ELEV: float = 0.10  # meters

    ABORT_ON_SEAM_FAIL: bool = True
    ENABLE_SEAM_STATS_EXPORT: bool = True
    SEAM_STATS_JSON: str = "seam_statistics.json"
    ENABLE_PLANVIEW_SEAM_AUTO_REPAIR: bool = True
    PLANVIEW_SEAM_AUTO_REPAIR_MAX_M: float = 0.05

    ENABLE_FULL_MAP_LOAD_GATE = False
    ENABLE_TILE_ONLY_VALIDATION = True
    # --- TILE SAFETY POLICY ---
    # If True: crash immediately when tile loses driving lanes
    # If False: mark tile as non-drivable and continue

    STRICT_TILE_SEMANTICS = (
        False  # crash vs mark "Crash if any tile has roads but no driving lanes"
    )

    TILE_AUTO_FORENSICS_TRIGGER_N = 3  # observation threshold

    # ===============================
    # STEP 10 — TILE QA METRICS
    # ===============================

    # Write per-tile failure classification JSON
    ENABLE_TILE_FAILURE_TAXONOMY: bool = True
    TILE_FAILURE_TAXONOMY_JSON: str = "tile_failure_taxonomy.json"

    # Tile QA spawn robustness
    TILE_SPAWN_ATTEMPTS: int = 20  # try 20 different spawn points per tile
    TILE_SPAWN_Z_OFFSET_M: float = (
        0.75  # lift spawn above ground (DEM/elevation safety)
    )
    TILE_SPAWN_FORWARD_M: float = (
        0.0  # optionally 2.0 if you still see failures near edges
    )

    # Enable aggregate tile metrics (failure rate, counts)
    ENABLE_TILE_METRICS: bool = True

    # Where Step 10 metrics / figures are written (relative to output_dir)
    TILE_METRICS_DIR: str = "tile_metrics"
    # --------------------------------------------------
    # STEP 10 — CARLA / TILE QA
    # --------------------------------------------------
    # --------------------------------------------------
    #  ⚠️— TILING SEMANTICS POLICY
    # --------------------------------------------------
    # Enable tiling at all

    # Respect tile_metadata.json and skip non-drivable tiles
    USE_TILE_METADATA_GATE: bool = True

    # Enable automatic forensic re-tiling
    ENABLE_TILE_AUTO_FORENSICS: bool = True

    # ===============================
    # STEP 10 — TILE QA ISOLATION
    # ===============================

    # "batch" = restart CARLA once before tile loop
    # "per_tile" = restart CARLA before each tile (strongest isolation)
    # Use subprocess isolation on Windows to contain native crashes, but keep the
    # worker workload minimal while debugging stability.
    TILE_QA_ISOLATION_MODE: str = "subprocess"

    # If True, Step 10 runs a batch runner that spawns each tile validation in a *fresh* subprocess
    # (prevents native libcarla crashes from killing the main pipeline process on Windows).
    TILE_QA_RUN_SUBPROCESS_BATCH: bool = True

    # Restart CARLA periodically during tile QA to avoid long-run GPU/driver instability.
    # Reduce restart churn during debugging (restart churn can amplify native crashes).
    CARLA_RESTART_EVERY_N_TILES: int = 9999

    # Pause between tiles (helps Windows release sockets / file handles).
    TILE_QA_SLEEP_BETWEEN_TILES_S: float = 2.0

    # Subprocess timeout for a single tile worker (seconds).
    # 600s required for large maps like Grid0828 where generate_opendrive_world
    # can take >120s. Override via UP_TILE_WORKER_TIMEOUT_S env var.
    TILE_WORKER_TIMEOUT_S: float = 600.0

    # CARLA world generation timeout used by tile workers (seconds).
    CARLA_TILE_LOAD_TIMEOUT_S: float = 120.0

    # Retries for CARLA world generation inside a tile worker.
    CARLA_TILE_LOAD_RETRIES: int = 0

    # ===============================
    # STEP 10 — FIGURES (THESIS)
    # ===============================

    # Disable heavy artifacts while stabilizing; re-enable after crashes are gone.
    ENABLE_TILE_FIGURES: bool = False
    PLOT_SEAM_HISTOGRAMS: bool = True
    PLOT_SEAM_CDFS: bool = True
    PLOT_FAILURE_PIE: bool = True

    FIGURE_FORMAT: str = "png"  # or "pdf"
    FIGURE_DPI: int = 200

    # -----------------------------------------------------------------
    # 10C) TILE STRESS TEST
    # -----------------------------------------------------------------
    ENABLE_TILE_STRESS_TEST: bool = False
    TILE_STRESS_DURATION: float = 8.0
    TILE_STRESS_RESULTS_DIR: str = "tile_stress"

    # -----------------------------------------------------------------
    # 10C2) ROAD DEFECT SCAN
    # -----------------------------------------------------------------
    ENABLE_ROAD_DEFECT_SCAN: bool = False

    # -----------------------------------------------------------------
    # 10A2 + 10E SETTINGS (Spawn QA + Screenshots)
    # -----------------------------------------------------------------
    ENABLE_SPAWN_QA: bool = True
    ENABLE_SCREENSHOTS: bool = False

    # Spawn probe config
    TILE_SPAWN_PROBE_MAX_SPAWNS_PER_TILE: int = 25
    TILE_SPAWN_PROBE_OFFSET_M: float = 1.3

    # -----------------------------------------------------------------
    # 11) INTERACTIVE SIMULATION (Step 11)
    # -----------------------------------------------------------------
    ENABLE_SIMULATION_GATE: bool = False

    SIM_VIEWPORT_W: int = 1280
    SIM_VIEWPORT_H: int = 720

    # Scenario + Autopilot extras (required by CarlaSimulation)
    # Keep scenario/autopilot off during map stability checks.
    ENABLE_SCENARIO_MANAGER: bool = False
    ENABLE_AUTOPILOT: bool = False
    EGO_SPAWN_POINT: int | None = None
    SCENARIO_BATCH_SIZE: int = 20

    # Mesh streaming for unreal-based object loading
    ENABLE_MESH_STREAMING: bool = True

    # -----------------------------------------------------------------
    # 12) ACTOR STREAMING LIMITS
    # -----------------------------------------------------------------
    STREAM_MAX_VEHICLES: int = 15
    STREAM_MAX_WALKERS: int = 10

    # -----------------------------------------------------------------
    # 13) DOMAIN GAP ANALYSIS
    # -----------------------------------------------------------------
    # Master switch for STEP 12 in main_pipeline.py
    ENABLE_DOMAIN_GAP: bool = True  # set True once manual map is configured

    # Where domain gap results (full_report.json, heatmaps, etc.) are stored
    DOMAIN_GAP_OUT_DIR: str = "domain_gap"
    # --- DOMAIN GAP RUN MODE ---

    GEOMETRY_GAP = {
        "SAMPLE_STEP_M": 2.0,  # polyline resolution
        "MAX_GEOMS": None,  # cap for laptop runs
        "MAX_SAMPLES": 50_000,  # RMSE safety cap
        "PROGRESS_EVERY": 2_000,
        "ESTIMATE_AFTER": 5_000,
    }

    # duplicate removed: ENABLE_TILE_ONLY_VALIDATION = True

    # Optional perception metrics for sim-to-real comparison
    PERCEPTION_MANUAL_JSON: str | None = None
    PERCEPTION_AUTO_JSON: str | None = None

    # ============================================================
    # 13B) DOMAIN GAP → TILE HEATMAPS
    # ============================================================

    ENABLE_TILE_GAP_HEATMAP: bool = True

    TILE_GAP_HEATMAP_METRICS: list[str] = field(
        default_factory=lambda: [
            "geometry_rmse",  # RMSE from GeometryGap (meters)
            "curvature_kl",  # KL divergence from CurvatureGap
            # Future extensions (documented, not yet active):
            # "lane_width_gap",
            # "heading_gap",
            # "position_rmse",
        ]
    )

    # ============================================================
    # DOMAIN GAP – LEARNED / GNN-BASED (OPTIONAL EXTENSION)
    # ============================================================
    # OFF by default to avoid hard dependency on torch / torch_geometric.
    # Treated as exploratory, NOT a core metric.

    ENABLE_GNN_DOMAIN_GAP: bool = False

    # Path to trained MapEncoder checkpoint
    GNN_CHECKPOINT_PATH: str | None = None

    # Output directory for latent gap JSONs + heatmaps
    DOMAIN_GAP_GNN_OUT_DIR: str = "domain_gap_gnn"

    # If True → HARD FAIL when torch_geometric is missing
    # If False → skip gracefully (recommended)
    GNN_STRICT_MODE: bool = False

    # Tile pairing semantics for latent gap
    GNN_TILE_PAIRING: str = "spatial"  # alternatives: "filename"

    # Encoder normalization contract (documented assumptions)
    GNN_MAX_SPEED_KMH: float = 130.0
    GNN_MAX_LANE_WIDTH_M: float = 5.0
    GNN_MAX_CURVATURE: float = 0.2

    # ============================================================
    # DOMAIN GAP – ENABLE / ABLATION SWITCHES
    # ============================================================

    DOMAIN_GAP_ENABLE = {
        "geometry": True,
        "curvature": True,
        "intersection": True,
        "semantics": True,
        "road_classification": True,
        # per-tile
        "per_tile_geometry": True,
        "per_tile_curvature": True,
        # optional / advanced
        "perception": True,
        "aggregate": True,
        "latent_gnn": False,
    }

    # ============================================================
    # DOMAIN GAP – NORMALIZATION REFERENCES (EXPLICIT CONTRACT)
    # ============================================================

    DOMAIN_GAP_NORMALIZATION = {
        # Geometry
        "geometry_rmse_m": 1.0,  # 1 m RMSE ≈ strong geometric deviation
        "hausdorff_m": 5.0,
        # Curvature
        "curvature_kl": 0.5,
        # Structural / semantic (future use)
        "intersection_delta": 1.0,
        "semantic_delta": 1.0,
    }

    # ============================================================
    # DOMAIN GAP – COMPOSITE WEIGHTS (AGGREGATION)
    # ============================================================

    DOMAIN_GAP_WEIGHTS = {
        "geometry": 0.35,
        "curvature": 0.20,
        "intersection": 0.15,
        "semantics": 0.20,
        "road_classification": 0.10,
    }

    # ============================================================
    # DOMAIN GAP – SWEEP CONFIGURATION (HPC / STATISTICS)
    # ============================================================

    DOMAIN_GAP_SWEEP = {
        "seeds": [0, 1, 2, 3, 4],
        "min_runs": 3,
        "confidence": 0.95,
    }

    # ============================================================
    # CURVATURE GAP – PARAMETERS
    # ============================================================

    CURVATURE_BINS: int = 60
    CURVATURE_INCLUDE_LINES: bool = True
    CURVATURE_MAX_GEOMS: int | None = None

    # ============================================================
    # GEOMETRY GAP – PERFORMANCE / ABLATION
    # ============================================================

    GEOMETRY_GAP_MAX_SAMPLES: int = 50_000
    GEOMETRY_GAP_SKIP_HAUSDORFF: bool = False

    # -----------------------------------------------------------------
    # 14) HPC TRAINING SETTINGS
    # -----------------------------------------------------------------
    # Split-root guard: override with UP_HPC_DIR to avoid loading from carla_-main
    HPC_DIR: str = _env_path(
        "UP_HPC_DIR",
        str(PROJECT_ROOT / "hpc"),
    )
    HPC_CONFIGS_DIR: str = os.path.join(HPC_DIR, "configs")
    HPC_EXPERIMENT_LOG_DIR: str = os.path.join(HPC_DIR, "logs")

    # Enable/disable HPC dataset export from pipeline
    ENABLE_HPC_EXPORT: bool = True
    HPC_EXPORT_DIR: str = "hpc_dataset"

    # -----------------------------------------------------------------
    # 15) MODEL TRAINING SETTINGS (local or HPC)
    # -----------------------------------------------------------------
    TRAINING_BACKEND: str = "local"  # "local" | "hpc" | "auto"
    TRAINING_TASK: str = (
        "segmentation_fcn"  # future: "detector_yolo", "self_supervised"...
    )
    TRAINING_DATASET_DIR: str = (
        ""  # if empty, use latest recording under BASE_OUTPUT_DIR/recordings
    )
    TRAINING_CAMERA: str = "front_left_camera"
    TRAINING_OUT_DIR: str = "runs/train"  # relative to project root unless absolute
    TRAIN_EPOCHS: int = 3
    TRAIN_BATCH: int = 4
    TRAIN_LR: float = 1e-4
    TRAIN_NUM_CLASSES: int = _env_int("UP_TRAIN_NUM_CLASSES", CARLA_SEMANTIC_NUM_CLASSES)
    TRAIN_LIMIT: int = 0  # 0 = no limit
    TRAIN_DEVICE: str = "cuda"  # "cuda" or "cpu"
    TRAIN_NUM_WORKERS: int = 2
    TRAIN_USE_DDP: bool = False  # enable only when launching with torchrun/srun

    # --------------------------
    # LLM / Ollama integration
    # --------------------------
    ENABLE_LLM_REVIEW: bool = True
    ENABLE_LLM_XODR_CHECK: bool = True

    LLM_TEMP: float = 0.2
    LLM_MAX_TOKENS: int = 4096
    LLM_CONTEXT_LENGTH: int = 8192
    LLM_MODEL: str = "deepseek-r1:7b"

    AUTO_START_OLLAMA: bool = True
    OLLAMA_STARTUP_TIMEOUT: int = 12

    # -----------------------------------------------------------------
    # DIRECTORY UTILITIES
    # -----------------------------------------------------------------
    def output_dir(self) -> str:
        if self.OUTPUT_DIR_OVERRIDE:
            d = self.OUTPUT_DIR_OVERRIDE
            os.makedirs(d, exist_ok=True)
            return d
        d = os.path.join(self.BASE_OUTPUT_DIR, self.timestamp)
        os.makedirs(d, exist_ok=True)
        return d

    def logs_dir(self) -> str:
        p = os.path.join(self.output_dir(), "logs")
        os.makedirs(p, exist_ok=True)
        return p

    def stage_dir(self) -> str:
        p = os.path.join(self.output_dir(), "stages")
        os.makedirs(p, exist_ok=True)
        return p

    def stage_path(self, name: str) -> str:
        return os.path.join(self.output_dir(), f"{name}_{self.timestamp}.xodr")

    def domain_gap_dir(self) -> str:
        # ✅ minimal dedup: use configured output dir name
        p = os.path.join(self.output_dir(), self.DOMAIN_GAP_OUT_DIR)
        os.makedirs(p, exist_ok=True)
        return p

    def domain_gap_gnn_dir(self) -> str:
        p = os.path.join(self.output_dir(), self.DOMAIN_GAP_GNN_OUT_DIR)
        os.makedirs(p, exist_ok=True)
        return p

    # -----------------------------------------------------------------
    # POST-INIT AUTO-DETECTIONS
    # -----------------------------------------------------------------
    def __post_init__(self):
        # -----------------------------------------------------------------
        # 0) Path portability + environment overrides
        # -----------------------------------------------------------------
        # Highest priority: environment overrides (HPC-friendly)
        self.INPUT_XODR = _env_path("UP_INPUT_XODR", self.INPUT_XODR)
        self.OUTPUT_DIR_OVERRIDE = _env_path("UP_OUTPUT_DIR", self.OUTPUT_DIR_OVERRIDE)
        self.MANUAL_MAP_XODR = _env_path("UP_MANUAL_XODR", self.MANUAL_MAP_XODR)
        self.MANUAL_TILES_DIR = _env_path("UP_MANUAL_TILES_DIR", self.MANUAL_TILES_DIR)
        self.OSM_FILE = _env_path("UP_OSM_FILE", self.OSM_FILE)
        self.OSM_BUILDINGS_GEOJSON = _env_path(
            "UP_OSM_BUILDINGS_GEOJSON", self.OSM_BUILDINGS_GEOJSON
        )
        self.COORDINATES_JSON = _env_path("UP_COORDINATES_JSON", self.COORDINATES_JSON)
        self.DEM_MIN_ELEVATION_VARIANCE = _env_float(
            "UP_DEM_MIN_ELEVATION_VARIANCE", float(self.DEM_MIN_ELEVATION_VARIANCE)
        )
        self.DEM_MIN_ELEVATION_STD = _env_float(
            "UP_DEM_MIN_ELEVATION_STD", float(self.DEM_MIN_ELEVATION_STD)
        )
        self.DEM_STRICT_MIN_ELEVATION_STD_DEFAULT = _env_float(
            "UP_DEM_STRICT_MIN_ELEVATION_STD_DEFAULT",
            float(self.DEM_STRICT_MIN_ELEVATION_STD_DEFAULT),
        )
        self.DEM_NODATA_RATIO_FAIL_THRESHOLD = _env_float(
            "UP_DEM_NODATA_RATIO_FAIL_THRESHOLD",
            float(self.DEM_NODATA_RATIO_FAIL_THRESHOLD),
        )
        self.DEM_STRICT_MODE = _env_bool(
            "UP_DEM_STRICT_MODE", bool(self.DEM_STRICT_MODE)
        )
        self.DEM_FULL_COVERAGE_STRICT = _env_bool(
            "UP_DEM_FULL_COVERAGE_STRICT", bool(self.DEM_FULL_COVERAGE_STRICT)
        )
        self.FAIL_ON_FLAT_ELEVATION = _env_bool(
            "UP_FAIL_ON_FLAT_ELEVATION", bool(self.FAIL_ON_FLAT_ELEVATION)
        )
        self.DEM_SUSPICIOUS_RASTER_RANGE_THRESHOLD = _env_float(
            "UP_DEM_SUSPICIOUS_RASTER_RANGE_THRESHOLD",
            float(self.DEM_SUSPICIOUS_RASTER_RANGE_THRESHOLD),
        )
        self.DEM_FLAT_SAMPLE_RANGE_THRESHOLD = _env_float(
            "UP_DEM_FLAT_SAMPLE_RANGE_THRESHOLD",
            float(self.DEM_FLAT_SAMPLE_RANGE_THRESHOLD),
        )
        self.AUTO_REPROJECT_DEM_ON_QC_FAIL = _env_bool(
            "UP_AUTO_REPROJECT_DEM_ON_QC_FAIL",
            bool(self.AUTO_REPROJECT_DEM_ON_QC_FAIL),
        )
        self.STRICT_FAIL_ON_GEOMETRIC_CONTINUITY_GATE = _env_bool(
            "UP_STRICT_FAIL_ON_GEOMETRIC_CONTINUITY_GATE",
            bool(self.STRICT_FAIL_ON_GEOMETRIC_CONTINUITY_GATE),
        )
        self.DEM_SUSPICIOUS_SLOPE_THRESHOLD = _env_float(
            "UP_DEM_SUSPICIOUS_SLOPE_THRESHOLD",
            float(self.DEM_SUSPICIOUS_SLOPE_THRESHOLD),
        )
        self.DEM_SUSPICIOUS_JUMP_THRESHOLD_M = _env_float(
            "UP_DEM_SUSPICIOUS_JUMP_THRESHOLD_M",
            float(self.DEM_SUSPICIOUS_JUMP_THRESHOLD_M),
        )
        self.DEM_SUSPICIOUS_TOP_K = int(
            max(
                1,
                round(
                    _env_float(
                        "UP_DEM_SUSPICIOUS_TOP_K",
                        float(self.DEM_SUSPICIOUS_TOP_K),
                    )
                ),
            )
        )
        self.STRICT_DEM_SUSPICIOUS_FAIL = _env_bool(
            "UP_STRICT_DEM_SUSPICIOUS_FAIL",
            _env_bool(
                "STRICT_DEM_SUSPICIOUS_FAIL",
                bool(self.STRICT_DEM_SUSPICIOUS_FAIL),
            ),
        )
        self.DEM_SUSPICIOUS_RATIO_FAIL_THRESHOLD = _env_float(
            "UP_DEM_SUSPICIOUS_RATIO_FAIL_THRESHOLD",
            _env_float(
                "DEM_SUSPICIOUS_RATIO_FAIL_THRESHOLD",
                float(self.DEM_SUSPICIOUS_RATIO_FAIL_THRESHOLD),
            ),
        )
        self.STRICT_QUALITY_GATES = _env_bool(
            "UP_STRICT_QUALITY_GATES", self.STRICT_QUALITY_GATES
        )
        self.THESIS_STRICT = _env_bool("UP_THESIS_STRICT", self.THESIS_STRICT)
        self.REQUIRE_MANUAL_FOR_CRS = _env_bool(
            "UP_REQUIRE_MANUAL_FOR_CRS", self.REQUIRE_MANUAL_FOR_CRS
        )
        self.OFFLINE_ONLY = _env_bool("UP_OFFLINE_ONLY", self.OFFLINE_ONLY)
        self.SUMO_REPAIR_PRESERVE_FRAME = _env_bool(
            "UP_SUMO_REPAIR_PRESERVE_FRAME", self.SUMO_REPAIR_PRESERVE_FRAME
        )
        self.PREANCHOR_INPUT_XODR = _env_bool(
            "UP_PREANCHOR_INPUT_XODR", self.PREANCHOR_INPUT_XODR
        )
        self.RELEASE_PROFILE = os.getenv("UP_RELEASE_PROFILE", self.RELEASE_PROFILE).strip()
        self.ENABLE_UNSAFE_SHORT_SEGMENT_MERGE = _env_bool_strict(
            "UP_ENABLE_UNSAFE_SHORT_SEGMENT_MERGE",
            bool(self.ENABLE_UNSAFE_SHORT_SEGMENT_MERGE),
        )
        self.ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE = _env_bool_strict(
            "UP_ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE",
            bool(self.ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE),
        )
        self.ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING = _env_bool_strict(
            "UP_ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING",
            bool(self.ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING),
        )
        self.ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP = _env_bool_strict(
            "UP_ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP",
            bool(self.ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP),
        )
        self.ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE = _env_bool_strict(
            "UP_ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE",
            _env_bool_strict(
                "UP_ENABLE_GEOMETRY_START_RECOMPUTE",
                bool(self.ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE),
            ),
        )
        self.ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK = _env_bool_strict(
            "UP_ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK",
            bool(self.ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK),
        )
        self.ENABLE_ROUNDABOUT_RECONSTRUCTION = _env_bool(
            "UP_ENABLE_ROUNDABOUT_RECONSTRUCTION",
            bool(self.ENABLE_ROUNDABOUT_RECONSTRUCTION),
        )
        self.ENABLE_TRAFFIC_LIGHTS = _env_bool(
            "UP_ENABLE_TRAFFIC_LIGHTS",
            bool(self.ENABLE_TRAFFIC_LIGHTS),
        )
        self.CARLA_DEFAULT_MAP = str(
            os.getenv("UP_CARLA_DEFAULT_MAP", str(self.CARLA_DEFAULT_MAP))
        ).strip()
        self.LOW_MEMORY_PROFILE_ACTIVE = _env_bool(
            "UP_LOW_MEMORY_PROFILE", bool(self.LOW_MEMORY_PROFILE_ACTIVE)
        )
        if bool(self.LOW_MEMORY_PROFILE_ACTIVE):
            self.MAX_NPCS_LOCAL = int(
                min(
                    int(self.MAX_NPCS_LOCAL),
                    int(getattr(self, "LOW_MEMORY_PROFILE_NPC_CAP", 10)),
                )
            )

        # Thesis-strict evidence runs should not emit GPS-anchor override-like behavior
        # from optional debug crops. Users can still explicitly re-enable via env.
        if self.THESIS_STRICT:
            self.ENABLE_GPS_QA_CROP = False
        # Manual map names (comma-separated)
        manual_maps_env = os.getenv("UP_MANUAL_MAPS", "").strip()
        if manual_maps_env:
            self.MANUAL_CARLA_MAPS = tuple(
                m.strip() for m in manual_maps_env.split(",") if m.strip()
            )

        # One writable root is the easiest way to run on clusters.
        data_root = os.getenv("UP_DATA_ROOT", "").strip()
        if data_root:
            self.BASE_OUTPUT_DIR = str(Path(data_root) / "ultimate_pipeline_out")

            # When UP_DATA_ROOT is set but UP_INPUT_XODR is not, search for
            # newest 08_final*.xodr in the output directories (HPC fallback).
            if not os.getenv("UP_INPUT_XODR", "").strip():
                fallback = _resolve_input_xodr_with_fallback(self.BASE_OUTPUT_DIR)
                if fallback:
                    self.INPUT_XODR = fallback

        # Portable fallbacks if the current hard-coded paths do not exist.
        self.COORDINATES_JSON = _pick_existing(
            self.COORDINATES_JSON,
            str(PROJECT_ROOT / "ultimate_pipeline" / "config" / "coordinates.json"),
            str(PROJECT_ROOT / "config" / "coordinates.json"),
        )

        self.OSM_FILE = _pick_existing(
            self.OSM_FILE,
            str(city_dir(CITY_NAME) / "osm" / f"{CITY_NAME}.osm"),
        )

        if getattr(self, "OSM_TO_XODR_TOOL", ""):
            self.OSM_TO_XODR_TOOL = _pick_existing(self.OSM_TO_XODR_TOOL)

        self.INPUT_XODR = _pick_existing(
            self.INPUT_XODR,
            str(city_dir(CITY_NAME) / f"{CITY_NAME}_dominik.xodr"),
        )

        # Manual reference map autodetect (domain gap needs this)
        # Env UP_MANUAL_XODR still wins; we only auto-fill when missing.
        if not self.MANUAL_MAP_XODR:
            guess = self._auto_find_manual_xodr()
            if guess:
                self.MANUAL_MAP_XODR = guess
                _boot_log(f"[AUTO] MANUAL_MAP_XODR detected → {self.MANUAL_MAP_XODR}")

        manual_map_candidates = (
            self.MANUAL_MAP_XODR,
            str(PROJECT_ROOT / "cities" / CITY_NAME / "manual_grid0828.xodr"),
            str(PROJECT_ROOT / "cities" / CITY_NAME / "manual_grid0828_semantic.xodr"),
            str(PROJECT_ROOT / "manual_maps" / f"{CITY_NAME}_manual.xodr"),
            str(PROJECT_ROOT / "manual_maps" / "manual_ingolstadt_grid0828.xodr"),
            str(PROJECT_ROOT / "manual_maps" / "Grid0821.xodr"),
            str(PROJECT_ROOT / "manual_maps" / "Grid0828.xodr"),
        )
        self._manual_map_xodr_candidates = [
            str(candidate)
            for candidate in manual_map_candidates
            if str(candidate or "").strip()
        ]
        if self.MANUAL_MAP_XODR:
            self.MANUAL_MAP_XODR = _pick_existing(*manual_map_candidates)
            if self.MANUAL_MAP_XODR and not Path(self.MANUAL_MAP_XODR).is_file():
                tried = ", ".join(repr(candidate) for candidate in self._manual_map_xodr_candidates)
                msg = (
                    f"MANUAL_MAP_XODR resolved to missing file: {self.MANUAL_MAP_XODR!r}. "
                    f"Set UP_MANUAL_XODR to a valid .xodr file path. Tried: {tried}"
                )
                thesis_strict = bool(getattr(self, "THESIS_STRICT", False)) or _env_bool(
                    "UP_THESIS_STRICT", False
                )
                if thesis_strict:
                    raise RuntimeError(msg)
                _boot_log(f"[WARN] {msg}")

        self.BASE_OUTPUT_DIR = _pick_existing(
            self.BASE_OUTPUT_DIR,
            str(PROJECT_ROOT / "ultimate_pipeline_out"),
        )

        # 1. Load GPS bounds
        try:
            self.GPS_BOUNDS = self.load_gps_bounds()
            _boot_log(f"[OK] Loaded GPS bounds → {self.GPS_BOUNDS}")
        except Exception as e:
            _boot_log(f"[WARN] Could not load GPS bounds: {e}")
            self.GPS_BOUNDS = None

        if self.ENABLE_GNN_DOMAIN_GAP:
            if self.GNN_CHECKPOINT_PATH is None:
                _boot_log(
                    "[WARN] ENABLE_GNN_DOMAIN_GAP=True but no GNN_CHECKPOINT_PATH set"
                )
        if (
            self.ENABLE_TILING
            and not self.ENABLE_SIDEWALKS
            and not self.ENABLE_LANESECTION_FIX
        ):
            _boot_log(
                "[WARN] Tiling enabled without guaranteed lane semantics — tiles may be non-drivable by design."
            )

        # 2. Sync legacy DEM_FILE
        self.DEM_FILE = self.DEM_TIF

        # 3. Export map-fallback settings for core loader (used by load_opendrive_world)
        # Use ALLOW_FALLBACK_MAP as the authoritative source (release profiles control this)
        try:
            os.environ["UP_CARLA_FALLBACK_ENABLED"] = (
                "1" if self.ALLOW_FALLBACK_MAP else "0"
            )
            os.environ["UP_CARLA_FALLBACK_MAPS"] = ",".join(
                list(self.CARLA_FALLBACK_MAPS)
            )
        except Exception:
            pass

        # Keep CARLA_ENABLE_MAP_FALLBACK in sync for backward compatibility
        self.CARLA_ENABLE_MAP_FALLBACK = self.ALLOW_FALLBACK_MAP

        # 3b. CARLA streaming port defaults to RPC+1 unless explicitly configured.
        # This matters because the client library will connect to RPC+1 for streaming.
        if self.CARLA_STREAMING_PORT is None:
            try:
                self.CARLA_STREAMING_PORT = int(self.CARLA_PORT) + 1
            except Exception:
                self.CARLA_STREAMING_PORT = 2001

        # Export ports for subprocess-based CARLA startup helpers.
        os.environ.setdefault("UP_CARLA_RPC_PORT", str(self.CARLA_PORT))
        os.environ.setdefault("UP_CARLA_STREAMING_PORT", str(self.CARLA_STREAMING_PORT))

        # 3c. Windows: disable subprocess tile QA isolation to avoid native crashes
        # (exit code 0xC0000409 due to multiprocessing + CARLA/libcarla/GEOS/Shapely).
        # Tile QA still runs in-process; only subprocess isolation is disabled.
        if os.name == "nt":
            if getattr(self, "TILE_QA_ISOLATION_MODE", "") == "subprocess" or getattr(
                self, "TILE_QA_RUN_SUBPROCESS_BATCH", False
            ):
                self.TILE_QA_ISOLATION_MODE = "batch"
                self.TILE_QA_RUN_SUBPROCESS_BATCH = False
                _boot_log(
                    "[WARN] Windows detected: subprocess tile QA isolation disabled "
                    "(native crash 0xC0000409). Tile QA runs in-process instead."
                )

        # 3. DO NOT create output_dir() here — that would generate a new
        #    folder on every import. Directory creation happens in main_pipeline.

        # 4. Autodetect SUMO if missing
        if not os.path.isfile(self.SUMO_NETCONVERT):
            for base in ["C:\\Sumo", "D:\\Sumo", "E:\\Sumo"]:
                for root, dirs, files in os.walk(base):
                    if "netconvert.exe" in files:
                        self.SUMO_NETCONVERT = os.path.join(root, "netconvert.exe")
                        _boot_log(f"[AUTO] SUMO detected → {self.SUMO_NETCONVERT}")
                        break

        # 5. DEM autodetect
        full_dem_path = self.DEM_TIF
        if not os.path.exists(full_dem_path):
            _boot_log(f"[WARN] DEM not found: {full_dem_path}")
            if os.path.isdir(self.DEM_DIR):
                for f in os.listdir(self.DEM_DIR):
                    if f.lower().endswith(".tif"):
                        self.DEM_FILENAME = f
                        _boot_log(f"[AUTO] DEM detected → {self.DEM_TIF}")

        # 6. Manual tiles autodetect (helps per-tile domain-gap if the default path is stale)
        try:
            has_tiles = False
            if self.MANUAL_TILES_DIR and os.path.isdir(self.MANUAL_TILES_DIR):
                # quick check: any .xodr files inside?
                for _f in os.listdir(self.MANUAL_TILES_DIR):
                    if _f.lower().endswith(".xodr"):
                        has_tiles = True
                        break
            if not has_tiles:
                guess = self._auto_find_manual_tiles_dir()
                if guess:
                    _boot_log(f"[AUTO] MANUAL_TILES_DIR detected → {guess}")
                    self.MANUAL_TILES_DIR = guess
        except Exception as e:
            _boot_log(f"[WARN] MANUAL_TILES_DIR autodetect failed: {e}")

        # 7. Validate key path settings and emit explicit override hints.
        _warn_missing_setting_path(
            "MANUAL_TILES_DIR",
            self.MANUAL_TILES_DIR,
            env_var="UP_MANUAL_TILES_DIR",
            expect="dir",
        )
        _warn_missing_setting_path(
            "BASE_OUTPUT_DIR",
            self.BASE_OUTPUT_DIR,
            env_var="UP_BASE_OUTPUT_DIR",
            expect="dir",
        )
        _warn_missing_setting_path(
            "COORDINATES_JSON",
            self.COORDINATES_JSON,
            env_var="UP_COORDINATES_JSON",
            expect="file",
        )
        _warn_missing_setting_path(
            "HPC_DIR",
            self.HPC_DIR,
            env_var="UP_HPC_DIR",
            expect="dir",
        )
        _warn_missing_setting_path(
            "PIPELINE_OUT_DIR",
            self.PIPELINE_OUT_DIR,
            env_var="UP_PIPELINE_OUT_DIR",
            expect="dir",
        )

        # Apply release profile (must be last to enforce immutability)
        self._apply_release_profile()

    def _auto_find_manual_tiles_dir(self) -> str:
        """Best-effort discovery of tiles for the manual reference map.

        This exists because a stale MANUAL_TILES_DIR silently breaks per-tile gap
        (whole-map can look perfect while per-tile RMSE explodes).
        Returns a directory path or an empty string.
        """
        try:
            manual_xodr = Path(self.MANUAL_MAP_XODR) if self.MANUAL_MAP_XODR else None
            candidates = []

            # 1) sibling 'tiles' next to the manual map
            if manual_xodr and manual_xodr.exists():
                sib = manual_xodr.parent / "tiles"
                candidates.append((10, sib))

            # 2) default location under repo (manual_maps/tiles) relative to this file
            here = Path(__file__).resolve()
            repo_root = here.parents[2] if len(here.parents) >= 3 else here.parent
            candidates.append((8, repo_root / "domain_gap_results" / "manual_tiles"))
            candidates.append((5, repo_root / "manual_maps" / "tiles"))

            # 3) search recent pipeline outputs for a plausible tiles directory
            out_root = Path(self.BASE_OUTPUT_DIR) if self.BASE_OUTPUT_DIR else None
            if out_root and out_root.exists():
                # scan only first-level run dirs (keeps it fast on Windows)
                for run_dir in sorted(
                    out_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
                )[:50]:
                    if not run_dir.is_dir():
                        continue
                    tiles_dir = run_dir / "tiles"
                    if tiles_dir.is_dir():
                        score = 1
                        # bump score if run dir contains an xodr that looks like the manual map
                        if manual_xodr:
                            base = manual_xodr.name
                            if (run_dir / base).exists():
                                score += 10
                            else:
                                # any file containing the manual stem?
                                stem = manual_xodr.stem
                                for f in run_dir.glob("*.xodr"):
                                    if stem in f.stem:
                                        score += 6
                                        break
                        # prefer richer tiles dirs
                        xodr_count = 0
                        try:
                            for f in tiles_dir.iterdir():
                                if f.suffix.lower() == ".xodr":
                                    xodr_count += 1
                                    if xodr_count >= 50:
                                        break
                        except Exception:
                            pass
                        score += min(5, xodr_count // 10)
                        candidates.append((score, tiles_dir))

            # pick best existing tiles dir with at least one xodr
            best = ""
            best_score = -1
            for score, p in candidates:
                try:
                    if p and p.is_dir():
                        has_xodr = any(f.suffix.lower() == ".xodr" for f in p.iterdir())
                        if has_xodr and score > best_score:
                            best = str(p)
                            best_score = score
                except Exception:
                    continue
            return best
        except Exception:
            return ""

    def _auto_find_manual_xodr(self) -> str:
        """
        Best-effort discovery of the manual reference XODR for domain gap.
        Env UP_MANUAL_XODR still wins; this only fills when MANUAL_MAP_XODR is empty.
        """
        try:
            repo = _repo_root()
            city_dir_candidate = repo / "cities" / CITY_NAME
            strong_city = [
                city_dir_candidate / "manual_grid0828.xodr",
                city_dir_candidate / "manual_grid0828_semantic.xodr",
            ]
            for p in strong_city:
                try:
                    if p.is_file():
                        return str(p)
                except Exception:
                    continue

            manual_dir = repo / "manual_maps"
            if not manual_dir.is_dir():
                return ""

            city = (str(CITY_NAME) if CITY_NAME else "ingolstadt").strip().lower()

            strong = [
                manual_dir / "manual_ingolstadt_grid0828.xodr",
                manual_dir / "manual_ingolstadt_grid0828_semantic.xodr",
                manual_dir / "Grid0828.xodr",
                manual_dir / f"{city}_manual.xodr",
            ]
            for p in strong:
                try:
                    if p.is_file():
                        return str(p)
                except Exception:
                    continue

            best_path = ""
            best_score = -10_000
            best_mtime = 0.0

            for p in manual_dir.glob("*.xodr"):
                name = p.name.lower()
                score = 0
                if "grid0828" in name:
                    score += 50
                if "manual" in name:
                    score += 25
                if "ingolstadt" in name or city in name:
                    score += 15
                if "semantic" in name:
                    score -= 5

                try:
                    mtime = float(p.stat().st_mtime)
                except Exception:
                    mtime = 0.0

                if (score > best_score) or (score == best_score and mtime > best_mtime):
                    best_score = score
                    best_mtime = mtime
                    best_path = str(p)

            return best_path
        except Exception:
            return ""

    # -------------------------------------------------------------
    # Automatic post-pipeline summaries
    # -------------------------------------------------------------
    ENABLE_LANE_STATS_SUMMARY: bool = True
    ENABLE_CONTINUITY_SUMMARY: bool = True

    # Default lane width used by LaneGenerator for roads without lanes
    DEFAULT_LANE_WIDTH: float = 3.5

    # QA / thesis figures / auto-visualization
    ENABLE_QUALITY_GATES_WRAPPER: bool = True
    ENABLE_THESIS_FIGURES: bool = True
    QA_AUTOVIS: bool = True
    ENABLE_QA_CROP = True
    ENABLE_GPS_QA_CROP = True
    STRICT_QUALITY_GATES: bool = False
    THESIS_STRICT: bool = True
    # C11: decouples Phase-1 auto-map GENERATION from the Phase-2 manual-map
    # COMPARISON. THESIS_STRICT alone must no longer force
    # _write_crs_comparability() to raise when no manual map is present --
    # that coupled ordinary generation runs to an input they don't need.
    # Default False: generation writes a status="manual_deferred" record
    # instead of raising. Set True (or UP_REQUIRE_MANUAL_FOR_CRS=1) to
    # restore the old hard-fail-without-manual-map behavior for callers that
    # specifically need the manual-vs-auto CRS comparison to be mandatory.
    REQUIRE_MANUAL_FOR_CRS: bool = _env_bool("UP_REQUIRE_MANUAL_FOR_CRS", False)
    # C11: default OFF — see the declaration above (~line 708) for rationale.
    # This second field of the same name (both live in the one Settings
    # dataclass body) is the one that actually wins as the dataclass default.
    PREANCHOR_INPUT_XODR: bool = _env_bool("UP_PREANCHOR_INPUT_XODR", False)

    # -----------------------------
    # PIPELINE OUTPUT DIRECTORIES
    # (legacy / some tools still use these)
    # -----------------------------
    # Split-root guard: override with UP_PIPELINE_OUT_DIR to avoid writing to carla_-main
    PIPELINE_OUT_DIR: str = _env_path(
        "UP_PIPELINE_OUT_DIR",
        str(PROJECT_ROOT / "ultimate_pipeline_out"),
    )

    TILE_DIR: str = os.path.join(PIPELINE_OUT_DIR, "tiles")

    # -----------------------------
    # DATASET DIRECTORIES (YOLO)
    # -----------------------------
    DATASET_ROOT: str = "datasets"
    MANUAL_DATASET_NAME: str = "manual"
    AUTO_DATASET_NAME: str = "auto"
    # =====================================================
    # CARLA SAFETY MODE (CRITICAL)
    # =====================================================
    CARLA_SAFE_MODE = False  # 🚨 master kill-switch
    CARLA_ENABLE_QA = True  # disables QA crop loading
    CARLA_ENABLE_PREVIEWS = True
    CARLA_ENABLE_SPAWN_TESTS = True
    CARLA_ENABLE_AUTO_RESTART = True

    ALLOW_EARLY_CARLA_LOADS = False

    # -----------------------------
    # AUGMENTATION SETTINGS
    # -----------------------------
    ENABLE_AUGMENTATION: bool = True
    AUGMENTATION_MULTIPLIER: int = 2  # augmented imgs per raw img
    AUGMENTATION_SEED: int = 42  # for reproducibility

    AUG_PROB_NOISE: float = 0.6
    AUG_PROB_MOTION_BLUR: float = 0.4
    AUG_PROB_BRIGHTNESS: float = 0.7
    AUG_PROB_COLOR_SHIFT: float = 0.5
    ENABLE_GEOMETRY_START_RECOMPUTE = False

    # --- ML Refiners ---
    ENABLE_LANE_GNN_REFINER = False
    LANE_GNN_WEIGHTS_PATH = r"C:\path\to\lane_gnn_weights.pt"
    LANE_GNN_DEVICE = "cuda"  # or "cpu"

    # -------------------------------------------------------------
    # DEBUG / QUICK MODE
    # -------------------------------------------------------------
    DEBUG_QUICK_MODE: bool = True
    DEBUG_RADIUS: float = 800.0

    # -----------------------------
    # DATABASE / ARTIFACT STORAGE
    # -----------------------------
    @staticmethod
    def resolve_data_root() -> Path:
        """Pick a writable data root across Windows/Linux/HPC.

        Priority:
          1) env UP_DATA_ROOT (recommended on HPC)
          2) D:\\ or H:\\ (lab Windows machines)
          3) /mnt/data (containers / many HPC mounts)
          4) <cwd>/carla_database
          5) ~/.carla_database
        """
        env = os.environ.get("UP_DATA_ROOT", "").strip()
        if env:
            base = Path(env).expanduser()
            if base.name != "carla_database":
                base = base / "carla_database"
            base.mkdir(parents=True, exist_ok=True)
            return base

        for drive in ("D:\\", "H:\\"):
            p = Path(drive)
            if p.exists():
                candidate = p / "carla_database"
                try:
                    candidate.mkdir(parents=True, exist_ok=True)
                    return candidate
                except PermissionError:
                    continue  # drive visible but access-denied (e.g. CI / restricted lab)

        candidates = [Path("/mnt/data"), Path.cwd(), Path.home()]
        for cand in candidates:
            try:
                base = (
                    cand if cand.name == "carla_database" else cand / "carla_database"
                )
                base.mkdir(parents=True, exist_ok=True)
                # quick write test
                test = base / ".write_test"
                test.write_text("ok", encoding="utf-8")
                test.unlink(missing_ok=True)
                return base
            except Exception:
                continue

        base = Path.cwd() / "carla_database"
        base.mkdir(parents=True, exist_ok=True)
        return base

    KEEP_LAST_RUNS: int = 10
    DB_ROOT: Path = resolve_data_root()
    DB_FILE: Path = DB_ROOT / "carla_pipeline.db"

    def latest_output_dir(self) -> str:
        """Returns the most recent folder inside BASE_OUTPUT_DIR."""
        base = self.BASE_OUTPUT_DIR
        if not os.path.isdir(base):
            raise FileNotFoundError(f"No pipeline_output directory: {base}")

        subdirs = sorted(
            (os.path.join(base, d) for d in os.listdir(base)),
            key=os.path.getmtime,
            reverse=True,
        )
        return subdirs[0]


# ------------------------------------------------------------
# GPU / RENDER SAFETY
# ------------------------------------------------------------
CARLA_QUALITY_LEVEL = "Low"

MAX_ACTIVE_CAMERAS = 2  # instead of 6
ENABLE_TOPDOWN_SCREENSHOTS = True
ENABLE_DEBUG_CAMERAS = True

LOCAL_PERCEPTION_MAX_NPCS = 10  # instead of 20


# ---------------------------------------------------------------------
# SINGLETON
# ---------------------------------------------------------------------
SETTINGS = Settings()
