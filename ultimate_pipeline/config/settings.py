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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ultimate_pipeline.utils.paths import repo_root, city_dir, resolve_path


PROJECT_ROOT = repo_root()
CITY_NAME = os.getenv("UP_CITY", "ingolstadt")


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


def _pick_existing(*candidates: str) -> str:
    """Pick the first candidate that exists on disk; otherwise return the first."""
    for c in candidates:
        try:
            if c and Path(c).exists():
                return c
        except Exception:
            continue
    return candidates[0] if candidates else ""


# =====================================================================
# MAIN SETTINGS CLASS
# =====================================================================
@dataclass
class Settings:
    SETTINGS_SCHEMA_VERSION = "1.0"

    REQUIRED_SNAPSHOT_KEYS = {
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

        # --- Domain Gap ---
        "ENABLE_DOMAIN_GAP",
        "MANUAL_MAP_XODR",
        "MANUAL_TILES_DIR",
        "DOMAIN_GAP_OUT_DIR",
        "PERCEPTION_MANUAL_JSON",
        "PERCEPTION_AUTO_JSON",

    }

    def to_dict(self) -> dict:
        data = {
            # --- Meta ---
            "_schema_version": self.SETTINGS_SCHEMA_VERSION,
            "_exported_at_utc": datetime.utcnow().isoformat() + "Z",

            # --- Core paths ---
            "INPUT_XODR": self.INPUT_XODR,
            "OSM_FILE": self.OSM_FILE,

            # --- Tile / QA ---
            "ENABLE_TILING": self.ENABLE_TILING,
            "USE_TILE_METADATA_GATE": self.USE_TILE_METADATA_GATE,
            "STRICT_TILE_SEMANTICS": self.STRICT_TILE_SEMANTICS,
            "TILE_SIZE": self.TILE_SIZE,
            "TILE_MATCH_MIN_IOU_FOR_GAP": getattr(self, "TILE_MATCH_MIN_IOU_FOR_GAP", 0.9),
            "TILE_AUTO_FORENSICS_TRIGGER_N": self.TILE_AUTO_FORENSICS_TRIGGER_N,
            "TILE_SPAWN_ATTEMPTS": self.TILE_SPAWN_ATTEMPTS,
            "TILE_SPAWN_Z_OFFSET_M": self.TILE_SPAWN_Z_OFFSET_M,
            "TILE_SPAWN_FORWARD_M": self.TILE_SPAWN_FORWARD_M,
            "ENABLE_SPAWN_QA": self.ENABLE_SPAWN_QA,
            "ENABLE_TILE_STRESS_TEST": self.ENABLE_TILE_STRESS_TEST,
            # --- Geometry / Semantics ---
            "ENABLE_SIDEWALKS": self.ENABLE_SIDEWALKS,
            "ENABLE_TRAFFIC_LIGHTS": self.ENABLE_TRAFFIC_LIGHTS,
            "ENABLE_BUILDINGS": self.ENABLE_BUILDINGS,
            "ENABLE_REALISM": self.ENABLE_REALISM,

            # --- Geometry tuning ---
            "CURVATURE_MAX_ALLOWED": self.CURVATURE_MAX_ALLOWED,
            "MIN_GEOM_MERGE_LENGTH": self.MIN_GEOM_MERGE_LENGTH,
            "CONTINUITY_MODE": self.CONTINUITY_MODE,

            # --- Domain-gap / metric performance ---
            "GEOMETRY_GAP_MAX_SAMPLES": getattr(self, "GEOMETRY_GAP_MAX_SAMPLES", None),
            "GEOMETRY_GAP_SKIP_HAUSDORFF": getattr(self, "GEOMETRY_GAP_SKIP_HAUSDORFF", None),

            # --- Perception ---
            "ENABLE_LOCAL_PERCEPTION": self.ENABLE_LOCAL_PERCEPTION,
            "ENABLE_SCREENSHOTS": self.ENABLE_SCREENSHOTS,

            # --- CARLA ---
            "ALLOW_FULL_LOAD_IN_STEP_10": self.ALLOW_FULL_LOAD_IN_STEP_10,
            "CARLA_HOST": self.CARLA_HOST,
            "CARLA_PORT": self.CARLA_PORT,
            "CARLA_STREAMING_PORT": self.CARLA_STREAMING_PORT,

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

            # --- Domain Gap ---
            "ENABLE_DOMAIN_GAP": self.ENABLE_DOMAIN_GAP,
            "MANUAL_MAP_XODR": self.MANUAL_MAP_XODR,
            "MANUAL_TILES_DIR": self.MANUAL_TILES_DIR,
            "DOMAIN_GAP_OUT_DIR": self.DOMAIN_GAP_OUT_DIR,
            "PERCEPTION_MANUAL_JSON": self.PERCEPTION_MANUAL_JSON,
            "PERCEPTION_AUTO_JSON": self.PERCEPTION_AUTO_JSON,

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
    CARLA_POST_LOAD_TICK_TIMEOUT: float = 5.0  # seconds: wait_for_tick after world (re)load/import
    CARLA_READY_TICK_TIMEOUT: float = 2.0  # seconds: wait_for_tick during readiness check
    CARLA_TIMEOUT: float = 20.0
    CARLA_EXE: str = r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
    CARLA_STARTUP_MODE = "windows_safe"  # or "hpc"

    # -----------------------------------------------------------------
    # Map load policy + fallback (for perception capture)
    # -----------------------------------------------------------------
    CARLA_ENABLE_MAP_FALLBACK: bool = False
    # Try these in order if OpenDRIVE generation fails
    CARLA_FALLBACK_MAPS = ("Town10HD_Opt", "Town05", "Town03", "Town01")
    # If True, skip OpenDRIVE entirely and use the built-in map below
    CARLA_FORCE_BUILTIN_MAP: bool = False
    CARLA_BUILTIN_MAP: str = "Town10HD_Opt"


    # -----------------------------------------------------------------
    # CARLA startup / recovery tuning
    # -----------------------------------------------------------------
    CARLA_STARTUP_WAIT: float = 25.0  # seconds (Windows-safe)
    CARLA_CONNECT_RETRIES: int = 10
    CARLA_KILL_ON_FAIL: bool = True  # can be disabled for debugging

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
        for drive in ["C:\\", "D:\\", "E:\\"]:
            for root, dirs, files in os.walk(drive):
                if "CarlaUE4.exe" in files:
                    return os.path.join(root, "CarlaUE4.exe")
                if "CarlaUE4-Win64-Shipping.exe" in files:
                    return os.path.join(root, "CarlaUE4-Win64-Shipping.exe")
        return None

    def carla_enabled(self) -> bool:
        return (
                not self.CARLA_SAFE_MODE
                and (self.ENABLE_CARLA_TEST_EARLY or self.ENABLE_CARLA_TEST_LATE)
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
    INPUT_XODR: str = str(
        resolve_path(
            os.getenv("UP_INPUT_XODR", None) or city_dir(CITY_NAME) / f"{CITY_NAME}_dominik.xodr",
            default=city_dir(CITY_NAME) / f"{CITY_NAME}_dominik.xodr",
        )
    )
    GENERATED_XODR: str = str(
        resolve_path(
            os.getenv("UP_GENERATED_XODR", None) or city_dir(CITY_NAME) / f"{CITY_NAME}.xodr",
            default=city_dir(CITY_NAME) / f"{CITY_NAME}.xodr",
        )
    )
    # Legacy compatibility alias for system_integrity_checker
    XODR_OUTPUT_FILE: str = INPUT_XODR

    # Keep commented manual-map path hints (for later domain-gap)
    #MANUAL_MAP_XODR: str = INPUT_XODR#(
    # Manual reference OpenDRIVE map (set this to Dominik's manual Ingolstadt .xodr)
    MANUAL_MAP_XODR: str = os.getenv("UP_MANUAL_XODR", "")
    # e.g. r"C:\path\to\manual_map.xodr"
    # Optional: directory containing manual reference tiles (.xodr per tile). Leave empty to skip per-tile gaps.
    MANUAL_TILES_DIR: str = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\manual_maps\tiles"
    # e.g. r"C:\path\to\manual_tiles"

    BASE_OUTPUT_DIR: str = (
        r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
        r"\ultimate_pipeline_out"
    )

    timestamp: str = field(default_factory=_default_timestamp)

    # ------------------------------
    # Mesh Continuity Repair Settings
    # ------------------------------
    # Ingolstadt-tuned continuity parameters

    # "safe" | "moderate" | "aggressive"
    CONTINUITY_MODE: str = "moderate"
    CONTINUITY_SELECTIVE: bool = True

    # thresholds
    MAX_GAP_FOR_FIX: float = 3.0                     # meters
    MAX_HEADING_JUMP_FIX: float = math.radians(10.0) # radians
    MAX_SEGMENT_LENGTH_FIX: float = 1500.0           # meters

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

    @property
    def DEM_TIF(self) -> str:
        return os.path.join(self.DEM_DIR, self.DEM_FILENAME)

    # legacy compatibility alias
    DEM_FILE: str = ""

    # DEM smoothing (to remove spikes before ElevationSmoother)
    ENABLE_DEM_SMOOTHING: bool = True
    DEM_SMOOTHING_SIGMA: float = 1.0

    # Optional: schema for final XODR validation (if you provide XSD)
    XODR_XSD_PATH: str | None = None  # e.g. r"...\OpenDRIVE_1.5.xsd"

    # ----------------------------------------
    # OSM DOWNLOAD CONTROL (UPSTREAM DATA)
    # ----------------------------------------

    ENABLE_OSM_DOWNLOAD: bool = True  # 🔁 master switch


    # -----------------------------------------------------------------
    # 4) OSM / GPS BOUNDS / BUILDINGS
    # -----------------------------------------------------------------
    COORDINATES_JSON: str = (
        r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
        r"\ultimate_pipeline\config\coordinates.json"
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
    ENABLE_CARLA_TEST_EARLY: bool = False
    ENABLE_CARLA_TEST_LATE: bool = False
    ENABLE_AUTOPILOT_VALIDATION: bool = True
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
    # -----------------------------------------------------------------
    # 7) ENRICHMENT MODULES
    # -----------------------------------------------------------------
    ENABLE_ROUNDABOUT_RECONSTRUCTION: bool = True
    ENABLE_TRAFFIC_LIGHTS: bool = False
    ENABLE_BUILDINGS: bool = False
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

    # Extra run artifacts / QA
    ENABLE_SEAM_ARTIFACTS: bool = True
    ENABLE_AUTOPILOT_TEST: bool = False
    FORCE_VALIDATE_NON_DRIVABLE_TILES: bool = False

    # Offline-only mode (skip CARLA-dependent stages). Can be forced with env UP_OFFLINE_ONLY=1
    OFFLINE_ONLY: bool = False

    SENSOR_CALIB_JSON: str = os.getenv(
        "SENSOR_CALIB_JSON",
        str((Path(__file__).resolve().parents[1] / "sensors" / "calib_data.json").as_posix()),
    )

    # Sensor calibration conventions (real-vehicle -> CARLA)
    SENSOR_FLIP_VEHICLE_Y: bool = bool(int(os.getenv("SENSOR_FLIP_VEHICLE_Y", "1")))
    SENSOR_OPENCV_CAMERA_AXES: bool = bool(int(os.getenv("SENSOR_OPENCV_CAMERA_AXES", "1")))
    # "auto" (default), "ros" if LiDAR axes are ROS-like (y left) and need conversion to CARLA (y right)
    SENSOR_LIDAR_AXES_MODE: str = os.getenv("SENSOR_LIDAR_AXES_MODE", "auto").strip().lower()


    MAX_NPCS_LOCAL: int = 20
    NPC_SPEED_PERCENT: float = 0.4
    EGO_AUTOPILOT: bool = True
    MAX_EGO_SPEED: float = 35.0
    # Safety: never load FULL map during STEP 8
    FORCE_LIGHT_LOAD_IN_STEP_8 = True
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
    TILE_BUFFER_M: float = 50.0
    # Optional: safety clamp so buffer doesn't explode tiles
    TILE_BUFFER_MAX_M: float = 80.0

    # If True: keep "buffer geometry" in tiles for CARLA, but mark core bbox in metadata
    TILE_WRITE_CORE_BBOX: bool = True

    # Tile streaming system
    ENABLE_SIM_TILE_STREAMING: bool = True   # required by simulator
    ENABLE_TILE_STREAMING: bool = True       # backward compatibility
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
    ENABLE_HIGHWAY_AWARE_TILE_BUFFER: bool = True

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
    SEAM_MAX_ELEV: float = 0.10     # meters

    ABORT_ON_SEAM_FAIL: bool = True
    ENABLE_SEAM_STATS_EXPORT: bool = True
    SEAM_STATS_JSON: str = "seam_statistics.json"

    ENABLE_FULL_MAP_LOAD_GATE = False
    ENABLE_TILE_ONLY_VALIDATION = True
    # --- TILE SAFETY POLICY ---
    # If True: crash immediately when tile loses driving lanes
    # If False: mark tile as non-drivable and continue

    STRICT_TILE_SEMANTICS = False  # crash vs mark “Crash if any tile has roads but no driving lanes”

    TILE_AUTO_FORENSICS_TRIGGER_N = 3  # observation threshold

    # ===============================
    # STEP 10 — TILE QA METRICS
    # ===============================

    # Write per-tile failure classification JSON
    ENABLE_TILE_FAILURE_TAXONOMY: bool = True
    TILE_FAILURE_TAXONOMY_JSON: str = "tile_failure_taxonomy.json"

    # Tile QA spawn robustness
    TILE_SPAWN_ATTEMPTS: int = 20        # try 20 different spawn points per tile
    TILE_SPAWN_Z_OFFSET_M: float = 0.75    # lift spawn above ground (DEM/elevation safety)
    TILE_SPAWN_FORWARD_M: float = 0.0      # optionally 2.0 if you still see failures near edges

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
    TILE_QA_ISOLATION_MODE: str = "subprocess"


    # If True, Step 10 runs a batch runner that spawns each tile validation in a *fresh* subprocess
    # (prevents native libcarla crashes from killing the main pipeline process on Windows).
    TILE_QA_RUN_SUBPROCESS_BATCH: bool = True

    # Restart CARLA periodically during tile QA to avoid long-run GPU/driver instability.
    CARLA_RESTART_EVERY_N_TILES: int = 5

    # Pause between tiles (helps Windows release sockets / file handles).
    TILE_QA_SLEEP_BETWEEN_TILES_S: float = 2.0

    # Subprocess timeout for a single tile worker (seconds).
    TILE_WORKER_TIMEOUT_S: float = 420.0

    # CARLA world generation timeout used by tile workers (seconds).
    CARLA_TILE_LOAD_TIMEOUT_S: float = 360.0

    # Retries for CARLA world generation inside a tile worker.
    CARLA_TILE_LOAD_RETRIES: int = 2

    # ===============================
    # STEP 10 — FIGURES (THESIS)
    # ===============================

    ENABLE_TILE_FIGURES: bool = True
    PLOT_SEAM_HISTOGRAMS: bool = True
    PLOT_SEAM_CDFS: bool = True
    PLOT_FAILURE_PIE: bool = True

    FIGURE_FORMAT: str = "png"  # or "pdf"
    FIGURE_DPI: int = 200

    # -----------------------------------------------------------------
    # 10C) TILE STRESS TEST
    # -----------------------------------------------------------------
    ENABLE_TILE_STRESS_TEST: bool = True
    TILE_STRESS_DURATION: float = 8.0
    TILE_STRESS_RESULTS_DIR: str = "tile_stress"

    # -----------------------------------------------------------------
    # 10C2) ROAD DEFECT SCAN
    # -----------------------------------------------------------------
    ENABLE_ROAD_DEFECT_SCAN: bool = True

    # -----------------------------------------------------------------
    # 10A2 + 10E SETTINGS (Spawn QA + Screenshots)
    # -----------------------------------------------------------------
    ENABLE_SPAWN_QA: bool = True
    ENABLE_SCREENSHOTS: bool = True

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
    ENABLE_SCENARIO_MANAGER: bool = True
    ENABLE_AUTOPILOT: bool = True
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
    ENABLE_DOMAIN_GAP: bool = True   # set True once manual map is configured

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

    TILE_GAP_HEATMAP_METRICS: list[str] = field(default_factory=lambda: [
        "geometry_rmse",  # RMSE from GeometryGap (meters)
        "curvature_kl",  # KL divergence from CurvatureGap
        # Future extensions (documented, not yet active):
        # "lane_width_gap",
        # "heading_gap",
        # "position_rmse",
    ])

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
    GEOMETRY_GAP_SKIP_HAUSDORFF: bool = True

    # -----------------------------------------------------------------
    # 14) HPC TRAINING SETTINGS
    # -----------------------------------------------------------------
    HPC_DIR: str = (
        r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\hpc"
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
    TRAINING_TASK: str = "segmentation_fcn"  # future: "detector_yolo", "self_supervised"...
    TRAINING_DATASET_DIR: str = ""  # if empty, use latest recording under BASE_OUTPUT_DIR/recordings
    TRAINING_CAMERA: str = "front_left_camera"
    TRAINING_OUT_DIR: str = "runs/train"  # relative to project root unless absolute
    TRAIN_EPOCHS: int = 3
    TRAIN_BATCH: int = 4
    TRAIN_LR: float = 1e-4
    TRAIN_NUM_CLASSES: int = 256
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
    LLM_MODEL: str = "deepseek-coder:6.7b"

    AUTO_START_OLLAMA: bool = True
    OLLAMA_STARTUP_TIMEOUT: int = 12

    # -----------------------------------------------------------------
    # DIRECTORY UTILITIES
    # -----------------------------------------------------------------
    def output_dir(self) -> str:
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
        self.MANUAL_MAP_XODR = _env_path("UP_MANUAL_XODR", self.MANUAL_MAP_XODR)
        self.MANUAL_TILES_DIR = _env_path("UP_MANUAL_TILES_DIR", self.MANUAL_TILES_DIR)
        self.OSM_FILE = _env_path("UP_OSM_FILE", self.OSM_FILE)
        self.OSM_BUILDINGS_GEOJSON = _env_path("UP_OSM_BUILDINGS_GEOJSON", self.OSM_BUILDINGS_GEOJSON)
        self.COORDINATES_JSON = _env_path("UP_COORDINATES_JSON", self.COORDINATES_JSON)

        # One writable root is the easiest way to run on clusters.
        data_root = os.getenv("UP_DATA_ROOT", "").strip()
        if data_root:
            self.BASE_OUTPUT_DIR = str(Path(data_root) / "ultimate_pipeline_out")

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

        if self.MANUAL_MAP_XODR:
                self.MANUAL_MAP_XODR = _pick_existing(
                    self.MANUAL_MAP_XODR,
                    str(PROJECT_ROOT / "manual_maps" / f"{CITY_NAME}_manual.xodr"),
                )

        self.BASE_OUTPUT_DIR = _pick_existing(
            self.BASE_OUTPUT_DIR,
            str(PROJECT_ROOT / "ultimate_pipeline_out"),
        )

        # 1. Load GPS bounds
        try:
            self.GPS_BOUNDS = self.load_gps_bounds()
            print(f"[OK] Loaded GPS bounds → {self.GPS_BOUNDS}")
        except Exception as e:
            print(f"[WARN] Could not load GPS bounds: {e}")
            self.GPS_BOUNDS = None

        if self.ENABLE_GNN_DOMAIN_GAP:
            if self.GNN_CHECKPOINT_PATH is None:
                print("[WARN] ENABLE_GNN_DOMAIN_GAP=True but no GNN_CHECKPOINT_PATH set")
        if self.ENABLE_TILING and not self.ENABLE_SIDEWALKS and not self.ENABLE_LANESECTION_FIX:
            print("[WARN] Tiling enabled without guaranteed lane semantics — tiles may be non-drivable by design.")

        # 2. Sync legacy DEM_FILE
        self.DEM_FILE = self.DEM_TIF

        # 3. Export map-fallback settings for core loader (used by load_opendrive_world)
        try:
            os.environ["UP_CARLA_FALLBACK_ENABLED"] = "1" if self.CARLA_ENABLE_MAP_FALLBACK else "0"
            os.environ["UP_CARLA_FALLBACK_MAPS"] = ",".join(list(self.CARLA_FALLBACK_MAPS))
        except Exception:
            pass

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

        # 3. DO NOT create output_dir() here — that would generate a new
        #    folder on every import. Directory creation happens in main_pipeline.

        # 4. Autodetect SUMO if missing
        if not os.path.isfile(self.SUMO_NETCONVERT):
            for base in ["C:\\Sumo", "D:\\Sumo", "E:\\Sumo"]:
                for root, dirs, files in os.walk(base):
                    if "netconvert.exe" in files:
                        self.SUMO_NETCONVERT = os.path.join(root, "netconvert.exe")
                        print(f"[AUTO] SUMO detected → {self.SUMO_NETCONVERT}")
                        break

        # 5. DEM autodetect
        full_dem_path = self.DEM_TIF
        if not os.path.exists(full_dem_path):
            print(f"[WARN] DEM not found: {full_dem_path}")
            if os.path.isdir(self.DEM_DIR):
                for f in os.listdir(self.DEM_DIR):
                    if f.lower().endswith(".tif"):
                        self.DEM_FILENAME = f
                        print(f"[AUTO] DEM detected → {self.DEM_TIF}")


        # 6. Manual tiles autodetect (helps per-tile domain-gap if the default path is stale)
        try:
            has_tiles = False
            if self.MANUAL_TILES_DIR and os.path.isdir(self.MANUAL_TILES_DIR):
                # quick check: any .xodr files inside?
                for _f in os.listdir(self.MANUAL_TILES_DIR):
                    if _f.lower().endswith(".xodr"):
                        has_tiles = True
                        break
            if (not has_tiles):
                guess = self._auto_find_manual_tiles_dir()
                if guess:
                    print(f"[AUTO] MANUAL_TILES_DIR detected → {guess}")
                    self.MANUAL_TILES_DIR = guess
        except Exception as e:
            print(f"[WARN] MANUAL_TILES_DIR autodetect failed: {e}")
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
            candidates.append((5, repo_root / "manual_maps" / "tiles"))

            # 3) search recent pipeline outputs for a plausible tiles directory
            out_root = Path(self.BASE_OUTPUT_DIR) if self.BASE_OUTPUT_DIR else None
            if out_root and out_root.exists():
                # scan only first-level run dirs (keeps it fast on Windows)
                for run_dir in sorted(out_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
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
                        has_xodr = any(f.suffix.lower()==".xodr" for f in p.iterdir())
                        if has_xodr and score > best_score:
                            best = str(p)
                            best_score = score
                except Exception:
                    continue
            return best
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

    # -----------------------------
    # PIPELINE OUTPUT DIRECTORIES
    # (legacy / some tools still use these)
    # -----------------------------
    PIPELINE_OUT_DIR: str = (
        r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3"
        r"\carla_-main\ultimate_pipeline_out"
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
    CARLA_SAFE_MODE = True  # 🚨 master kill-switch
    CARLA_ENABLE_QA = True  # disables QA crop loading
    CARLA_ENABLE_PREVIEWS = True
    CARLA_ENABLE_SPAWN_TESTS = True
    CARLA_ENABLE_AUTO_RESTART = True

    ALLOW_EARLY_CARLA_LOADS = False

    # -----------------------------
    # AUGMENTATION SETTINGS
    # -----------------------------
    ENABLE_AUGMENTATION: bool = True
    AUGMENTATION_MULTIPLIER: int = 2      # augmented imgs per raw img
    AUGMENTATION_SEED: int = 42          # for reproducibility

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
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate

        candidates = [Path("/mnt/data"), Path.cwd(), Path.home()]
        for cand in candidates:
            try:
                base = cand if cand.name == "carla_database" else cand / "carla_database"
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
            reverse=True
        )
        return subdirs[0]
# ------------------------------------------------------------
# GPU / RENDER SAFETY
# ------------------------------------------------------------
CARLA_QUALITY_LEVEL = "Low"

MAX_ACTIVE_CAMERAS = 2          # instead of 6
ENABLE_TOPDOWN_SCREENSHOTS = True
ENABLE_DEBUG_CAMERAS = True

LOCAL_PERCEPTION_MAX_NPCS = 10  # instead of 20


# ---------------------------------------------------------------------
# SINGLETON
# ---------------------------------------------------------------------
SETTINGS = Settings()
