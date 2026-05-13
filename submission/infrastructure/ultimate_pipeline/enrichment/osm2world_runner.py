#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSM2World Runner Module (Robust, Cacheable, Windows-First)

Generates 3D scene geometry artifacts (OBJ/PNG/GLB) from OSM data for visual QA
and thesis figures. This is a strictly optional stage that does NOT affect
OpenDRIVE generation or CARLA loadability.

OSM2World is used for perceptual clutter (buildings/vegetation), NOT for road truth.
Roads are owned by CARLA/OpenDRIVE.

Environment Variables:
    ENABLE_OSM2WORLD: Set to "1" to enable this stage (default: off)
    OSM2WORLD_HOME: Path to OSM2World binary folder (default: see DEFAULT_OSM2WORLD_HOME)
    OSM2WORLD_JAR: Explicit path to OSM2World JAR file (optional)
    OSM2WORLD_CONFIG: Path to external properties file (optional override)
    OSM2WORLD_OUTPUTS: Comma-separated outputs to generate (default: obj). Options: obj,png,glb
    OSM2WORLD_TIMEOUT_SEC: Timeout in seconds (default: 1800)

Usage:
    from ultimate_pipeline.enrichment.osm2world_runner import OSM2WorldRunner

    runner = OSM2WorldRunner(osm_path="/path/to/file.osm", output_dir="/path/to/output")
    result = runner.run()
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Default path on Windows - can be overridden via OSM2WORLD_HOME env var
DEFAULT_OSM2WORLD_HOME = Path(
    r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\OSM2World-latest-bin"
)

# Default Blender path for GLB validation
DEFAULT_BLENDER_EXE = Path(r"E:\Program Files\Blender Foundation\Blender 4.3\blender.exe")


@dataclass
class OSM2WorldResult:
    """Result of an OSM2World run."""
    status: str  # "ok" | "skipped" | "failed" | "cached"
    reason: str = ""
    command_lines: List[List[str]] = field(default_factory=list)
    java_version: str = ""
    osm2world_version: str = ""
    osm2world_jar: str = ""
    outputs: Dict[str, str] = field(default_factory=dict)  # type -> path
    hashes: Dict[str, str] = field(default_factory=dict)   # file -> sha256
    config_path: str = ""
    config_hash: str = ""
    input_osm_hash: str = ""
    cache_key: str = ""
    start_time: str = ""
    end_time: str = ""
    duration_sec: float = 0.0
    exit_codes: Dict[str, int] = field(default_factory=dict)
    exception: str = ""
    stdout_log: str = ""
    stderr_log: str = ""
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    glb_valid: Optional[bool] = None
    glb_validation_reason: str = ""
    # Debug fields
    config_header_hex: str = ""  # First 8 bytes of config as hex for debugging
    abs_osm_path: str = ""       # Resolved absolute OSM path
    abs_config_path: str = ""    # Resolved absolute config path
    working_dir: str = ""        # cwd used for subprocess
    successful_variant: int = 0  # Which CLI variant succeeded (1-4), 0 if none

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "command_lines": self.command_lines,
            "java_version": self.java_version,
            "osm2world_version": self.osm2world_version,
            "osm2world_jar": self.osm2world_jar,
            "outputs": self.outputs,
            "hashes": self.hashes,
            "config_path": self.config_path,
            "config_hash": self.config_hash,
            "input_osm_hash": self.input_osm_hash,
            "cache_key": self.cache_key,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_sec": self.duration_sec,
            "exit_codes": self.exit_codes,
            "exception": self.exception,
            "stdout_log": self.stdout_log,
            "stderr_log": self.stderr_log,
            "attempts": self.attempts,
            "glb_valid": self.glb_valid,
            "glb_validation_reason": self.glb_validation_reason,
            "config_header_hex": self.config_header_hex,
            "abs_osm_path": self.abs_osm_path,
            "abs_config_path": self.abs_config_path,
            "working_dir": self.working_dir,
            "successful_variant": self.successful_variant,
        }


class OSM2WorldRunner:
    """
    Runs OSM2World to generate 3D scene geometry artifacts.

    This is an optional enrichment stage for visual QA and thesis figures.
    It does NOT affect the main pipeline's OpenDRIVE output.

    Features:
    - Robust CLI invocation with multiple fallback argument styles
    - Config validation: fails if "could not read config" appears in stderr
    - Deterministic caching by input OSM + config hash
    - OBJ as primary output (more reliable than GLB)
    - Optional GLB with header validation and Blender import test
    - Full logging of stdout/stderr
    """

    # Default safe config that excludes roads (CARLA/OpenDRIVE owns roads)
    DEFAULT_CONFIG = """\
# OSM2World configuration for thesis pipeline
# Generated by osm2world_runner.py
# Conservative defaults: buildings/vegetation only, no roads/terrain

# Terrain settings (disabled for speed and stability)
createTerrain=false
renderUnderground=false

# Buildings
useBuildingColors=true
implicitWindowImplementation=NONE
explicitWindowImplementation=NONE

# Exclude road-related modules (CARLA/OpenDRIVE owns roads)
excludeWorldModule=RoadModule;RailwayModule;AerowayModule;ParkingModule

# Trees / vegetation (modest density to avoid memory issues)
treesPerSquareMeter=0.02
defaultTreeHeight=8
defaultTreeHeightForest=12

# Level of detail
lodDistances=100,500,2000
"""

    def __init__(
        self,
        osm_path: str,
        output_dir: str,
        osm2world_home: Optional[str] = None,
        timeout_sec: Optional[int] = None,
        config_path: Optional[str] = None,
    ):
        """
        Initialize OSM2World runner.

        Args:
            osm_path: Path to input OSM file (.osm, .osm.xml, or .pbf)
            output_dir: Directory to write outputs
            osm2world_home: Path to OSM2World binary folder (uses env/default if None)
            timeout_sec: Timeout for OSM2World execution (default from env or 1800)
            config_path: Path to external properties file (optional)
        """
        self.osm_path = Path(osm_path)
        self.output_dir = Path(output_dir)

        # Timeout: env > arg > default 1800
        default_timeout = 1800
        env_timeout = os.getenv("OSM2WORLD_TIMEOUT_SEC", "").strip()
        if env_timeout.isdigit():
            default_timeout = int(env_timeout)
        self.timeout_sec = timeout_sec if timeout_sec is not None else default_timeout

        # OSM2World home: arg > env > default
        if osm2world_home:
            self.osm2world_home = Path(osm2world_home)
        else:
            env_home = os.getenv("OSM2WORLD_HOME", "").strip()
            self.osm2world_home = Path(env_home) if env_home else DEFAULT_OSM2WORLD_HOME

        # Config path: arg > env > None (will generate default)
        if config_path:
            self.external_config = Path(config_path)
        else:
            env_config = os.getenv("OSM2WORLD_CONFIG", "").strip()
            self.external_config = Path(env_config) if env_config else None

        # Blender path for GLB validation
        env_blender = os.getenv("BLENDER_EXE", "").strip()
        self.blender_exe = Path(env_blender) if env_blender else DEFAULT_BLENDER_EXE

    def _hash_file(self, path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        if not path.exists():
            return ""
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    def _check_java(self) -> Tuple[bool, str]:
        """
        Check if Java is available.

        Returns:
            Tuple of (available, version_string)
        """
        try:
            result = subprocess.run(
                ["java", "-version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Java version goes to stderr
            output = result.stderr or result.stdout or ""
            # Parse version from output like: openjdk version "17.0.1" 2021-10-19
            for line in output.strip().split("\n"):
                if "version" in line.lower():
                    return True, line.strip()
            return True, output.split("\n")[0].strip() if output else "unknown"
        except FileNotFoundError:
            return False, "Java not found in PATH"
        except subprocess.TimeoutExpired:
            return False, "Java check timed out"
        except Exception as e:
            return False, f"Java check failed: {e}"

    def _find_osm2world_entrypoint(self) -> Tuple[Optional[List[str]], str, str]:
        """
        Find the OSM2World executable/script.

        Priority:
        1. .bat/.cmd/.exe wrapper (if exists)
        2. java -jar with explicit OSM2WORLD_JAR
        3. java -jar with first OSM2World*.jar in home

        Returns:
            Tuple of (command_prefix, jar_path, version_hint)
        """
        home = self.osm2world_home

        if not home.exists():
            return None, "", f"OSM2World home not found: {home}"

        # Check for explicit JAR path from env
        explicit_jar = os.getenv("OSM2WORLD_JAR", "").strip()
        if explicit_jar and Path(explicit_jar).exists():
            jar_path = explicit_jar
        else:
            # Look for JAR file in home
            jar_files = list(home.glob("OSM2World*.jar"))
            if not jar_files:
                jar_files = list(home.glob("*.jar"))

            jar_path = ""
            if jar_files:
                # Prefer the main jar with "OSM2World" in name
                for jar in jar_files:
                    if "OSM2World" in jar.name:
                        jar_path = str(jar)
                        break
                if not jar_path:
                    jar_path = str(jar_files[0])

        # Check for platform-specific scripts (preferred if they exist)
        is_windows = sys.platform.startswith("win")

        if is_windows:
            # Try batch files / exe
            for script_name in ["osm2world.exe", "osm2world-windows.bat", "osm2world.bat", "osm2world.cmd"]:
                script = home / script_name
                if script.exists():
                    script_path = str(script.resolve())
                    # .bat/.cmd files must be invoked via cmd.exe /c on Windows
                    if script_name.endswith((".bat", ".cmd")):
                        return ["cmd.exe", "/c", script_path], jar_path, script.name
                    else:
                        return [script_path], jar_path, script.name
        else:
            # Try shell scripts
            for script_name in ["osm2world.sh", "osm2world"]:
                script = home / script_name
                if script.exists():
                    return [str(script)], jar_path, script.name

        # Fall back to java -jar
        if jar_path:
            return ["java", "-jar", jar_path], jar_path, Path(jar_path).name

        return None, "", "No OSM2World entrypoint found"

    def _write_config(self) -> Path:
        """
        Write config file to output directory.

        Uses external config if specified, otherwise writes default.
        Config is written as ASCII/UTF-8 without BOM to avoid Java issues.
        """
        config_path = self.output_dir / "osm2world.properties"

        if self.external_config and self.external_config.exists():
            # Copy external config
            content = self.external_config.read_text(encoding="utf-8")
        else:
            content = self.DEFAULT_CONFIG

        # Write without BOM (critical for Java properties loader)
        with open(config_path, "w", encoding="ascii", errors="replace", newline="\n") as f:
            f.write(content)

        return config_path

    def _validate_osm_input(self) -> Tuple[bool, str]:
        """Validate the input OSM file."""
        if not self.osm_path.exists():
            return False, f"OSM file not found: {self.osm_path}"

        suffix = self.osm_path.suffix.lower()
        if suffix not in [".osm", ".xml", ".pbf"]:
            # Check for .osm.xml
            if str(self.osm_path).lower().endswith(".osm.xml"):
                return True, ""
            return False, f"Unsupported OSM format: {suffix} (expected .osm, .osm.xml, or .pbf)"

        # Basic size check
        size_mb = self.osm_path.stat().st_size / (1024 * 1024)
        if size_mb > 500:
            return False, f"OSM file too large ({size_mb:.1f} MB) - may cause memory issues"

        return True, ""

    def _compute_cache_key(self, osm_hash: str, config_hash: str) -> str:
        """Compute a cache key from OSM + config hashes."""
        combined = f"{osm_hash}:{config_hash}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _check_cache(self, cache_key: str) -> Optional[OSM2WorldResult]:
        """
        Check if valid cached outputs exist for this cache key.

        Returns cached result if valid, None otherwise.
        """
        status_path = self.output_dir / "osm2world_status.json"
        if not status_path.exists():
            return None

        try:
            with open(status_path, "r", encoding="utf-8") as f:
                cached = json.load(f)

            if cached.get("cache_key") != cache_key:
                return None

            if cached.get("status") not in ("ok", "cached"):
                return None

            # Verify outputs still exist
            outputs = cached.get("outputs", {})
            for name, path in outputs.items():
                if not Path(path).exists():
                    return None

            # Return cached result
            result = OSM2WorldResult(
                status="cached",
                reason=f"Using cached outputs (cache_key={cache_key})",
            )
            for key, value in cached.items():
                if hasattr(result, key):
                    setattr(result, key, value)
            result.status = "cached"
            return result

        except Exception:
            return None

    def _validate_glb(self, glb_path: Path) -> Tuple[bool, str]:
        """
        Validate a GLB file.

        1. Check header begins with 'glTF'
        2. Optionally test Blender import if Blender is available

        Returns (valid, reason)
        """
        if not glb_path.exists():
            return False, "GLB file does not exist"

        if glb_path.stat().st_size == 0:
            return False, "GLB file is empty"

        # Check GLB header magic bytes: 'glTF' (0x676C5446)
        try:
            with open(glb_path, "rb") as f:
                header = f.read(4)
            if header != b"glTF":
                return False, f"Invalid GLB header: expected 'glTF', got {header!r}"
        except Exception as e:
            return False, f"Failed to read GLB header: {e}"

        # Optional Blender validation
        if self.blender_exe.exists():
            try:
                valid, reason = self._validate_glb_with_blender(glb_path)
                if not valid:
                    return False, f"Blender validation failed: {reason}"
            except Exception as e:
                # Blender validation is optional - don't fail on errors
                pass

        return True, "GLB header valid"

    def _validate_glb_with_blender(self, glb_path: Path) -> Tuple[bool, str]:
        """
        Validate GLB by attempting Blender import.

        Returns (valid, reason)
        """
        # Create validation script
        script_content = f'''
import bpy
import sys

try:
    bpy.ops.import_scene.gltf(filepath=r"{glb_path}")
    print("BLENDER_IMPORT_OK")
    sys.exit(0)
except Exception as e:
    print(f"BLENDER_IMPORT_FAILED: {{e}}")
    sys.exit(1)
'''

        script_path = self.output_dir / "_validate_glb.py"
        script_path.write_text(script_content, encoding="utf-8")

        try:
            result = subprocess.run(
                [str(self.blender_exe), "--background", "--python-exit-code", "1",
                 "--python", str(script_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if "BLENDER_IMPORT_OK" in result.stdout:
                return True, "Blender import successful"

            # Extract error from output
            for line in result.stdout.split("\n"):
                if "BLENDER_IMPORT_FAILED" in line:
                    return False, line
            for line in result.stderr.split("\n"):
                if "error" in line.lower() or "failed" in line.lower():
                    return False, line

            return False, f"Blender exit code {result.returncode}"

        except subprocess.TimeoutExpired:
            return False, "Blender validation timed out"
        except Exception as e:
            return False, str(e)
        finally:
            try:
                script_path.unlink()
            except Exception:
                pass

    def _run_osm2world_for_output(
        self,
        cmd_prefix: List[str],
        config_path: Path,
        output_path: Path,
        attempts_list: List[Dict[str, Any]],
    ) -> Tuple[bool, Optional[subprocess.CompletedProcess], List[str], bool, int]:
        """
        Run OSM2World to produce a single output file, trying multiple CLI variants.

        Returns:
            Tuple of (success, last_process, command_used, config_failed, successful_variant)
            config_failed is True if "could not read config" was detected in ALL variants
            successful_variant is 1-4 if success, 0 if none
        """
        # CRITICAL: Use absolute paths because we run with cwd=osm2world_home
        # Relative paths would be resolved relative to OSM2World home, not caller's cwd
        abs_osm = str(self.osm_path.resolve())
        abs_out = str(output_path.resolve())
        abs_cfg = str(config_path.resolve())

        # CLI argument variants (OSM2World CLI evolved; keep it robust)
        # Prefer picocli style with --config AFTER subcommand (verified working)
        candidates: List[List[str]] = [
            # Picocli: --config AFTER subcommand args (PREFERRED - verified working)
            ["convert", "-i", abs_osm, "-o", abs_out, "--config", abs_cfg],
            # Picocli: --config BEFORE subcommand (global option)
            ["--config", abs_cfg, "convert", "-i", abs_osm, "-o", abs_out],
            # Legacy style: config first, no subcommand
            ["--config", abs_cfg, "-i", abs_osm, "-o", abs_out],
            # Alternative with long flags
            ["--config", abs_cfg, "--input", abs_osm, "--output", abs_out],
        ]

        last_proc: Optional[subprocess.CompletedProcess] = None
        last_cmd: List[str] = []
        config_failed_count = 0

        for variant_idx, args in enumerate(candidates, start=1):
            cmd = cmd_prefix + args
            last_cmd = cmd

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_sec,
                    cwd=str(self.osm2world_home),
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired as e:
                attempts_list.append({
                    "output": abs_out,
                    "variant": variant_idx,
                    "command_line": cmd,
                    "timeout": True,
                    "timeout_sec": self.timeout_sec,
                })
                continue
            except Exception as e:
                attempts_list.append({
                    "output": abs_out,
                    "variant": variant_idx,
                    "command_line": cmd,
                    "exception": str(e),
                })
                continue

            stderr_text = proc.stderr or ""
            stdout_text = proc.stdout or ""

            attempts_list.append({
                "output": abs_out,
                "variant": variant_idx,
                "command_line": cmd,
                "exit_code": proc.returncode,
                "stderr_head": stderr_text[:2000],
                "stdout_head": stdout_text[:2000],
            })

            # Check for config loading issue
            if "could not read config" in stderr_text.lower():
                config_failed_count += 1
                last_proc = proc
                # Try next variant - config path/ordering might be wrong
                continue

            # Check success: exit code 0 + output exists + no config warning
            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return True, proc, cmd, False, variant_idx

            last_proc = proc

        # All variants failed; config_failed is True only if ALL tried variants had config issues
        all_config_failed = config_failed_count == len(candidates)
        return False, last_proc, last_cmd, all_config_failed, 0

    def run(self) -> OSM2WorldResult:
        """
        Execute OSM2World and generate artifacts.

        Returns:
            OSM2WorldResult with status and artifact paths
        """
        result = OSM2WorldResult(status="failed")
        result.start_time = datetime.now().isoformat()
        start_ts = time.time()

        try:
            # Ensure output directory exists
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # Validate input
            valid, msg = self._validate_osm_input()
            if not valid:
                result.status = "skipped"
                result.reason = msg
                return self._finalize(result, start_ts)

            # Check Java
            java_ok, java_ver = self._check_java()
            result.java_version = java_ver
            if not java_ok:
                result.status = "skipped"
                result.reason = f"Java not available: {java_ver}"
                return self._finalize(result, start_ts)

            # Find OSM2World
            cmd_prefix, jar_path, version_hint = self._find_osm2world_entrypoint()
            result.osm2world_jar = jar_path
            result.osm2world_version = version_hint

            if cmd_prefix is None:
                result.status = "skipped"
                result.reason = version_hint  # Contains error message
                return self._finalize(result, start_ts)

            # Write config
            config_path = self._write_config()
            result.config_path = str(config_path)

            # Populate debug fields
            result.abs_osm_path = str(self.osm_path.resolve())
            result.abs_config_path = str(config_path.resolve())
            result.working_dir = str(self.osm2world_home)

            # Read config header for debugging (detect BOM/encoding issues)
            try:
                with open(config_path, "rb") as f:
                    header_bytes = f.read(8)
                result.config_header_hex = header_bytes.hex()
            except Exception:
                result.config_header_hex = "read_error"

            # Compute hashes for caching
            result.input_osm_hash = self._hash_file(self.osm_path)
            result.config_hash = self._hash_file(config_path)
            result.cache_key = self._compute_cache_key(result.input_osm_hash, result.config_hash)
            result.hashes["input_osm"] = result.input_osm_hash
            result.hashes["config"] = result.config_hash

            # Check cache
            cached_result = self._check_cache(result.cache_key)
            if cached_result is not None:
                return cached_result

            # Determine requested outputs (default: obj)
            outputs_env = os.getenv("OSM2WORLD_OUTPUTS", "obj").strip().lower()
            requested = [o.strip() for o in outputs_env.split(",") if o.strip()]
            allowed = {"glb", "gltf", "obj", "png"}
            requested = [o for o in requested if o in allowed]
            if not requested:
                requested = ["obj"]

            # Map output types to file paths
            out_files: Dict[str, Path] = {}
            if "obj" in requested:
                out_files["scene.obj"] = self.output_dir / "scene.obj"
            if "png" in requested:
                out_files["preview.png"] = self.output_dir / "preview.png"
            if "glb" in requested:
                out_files["scene.glb"] = self.output_dir / "scene.glb"
            if "gltf" in requested:
                out_files["scene.gltf"] = self.output_dir / "scene.gltf"

            attempts: List[Dict[str, Any]] = []
            any_success = False
            failures: List[str] = []
            config_not_loaded = False

            # Run OSM2World for each requested output
            for out_name, out_path in out_files.items():
                ok_out, proc, cmd_used, cfg_failed, variant_idx = self._run_osm2world_for_output(
                    cmd_prefix, config_path, out_path, attempts
                )

                # Save logs
                safe_tag = out_name.replace(".", "_")
                stdout_log = self.output_dir / f"osm2world_{safe_tag}_stdout.log"
                stderr_log = self.output_dir / f"osm2world_{safe_tag}_stderr.log"

                if proc:
                    stdout_log.write_text(proc.stdout or "", encoding="utf-8", errors="replace")
                    stderr_log.write_text(proc.stderr or "", encoding="utf-8", errors="replace")
                    result.exit_codes[out_name] = proc.returncode

                    if not result.stdout_log:
                        result.stdout_log = str(stdout_log)
                    if not result.stderr_log:
                        result.stderr_log = str(stderr_log)

                if cfg_failed:
                    config_not_loaded = True

                if not result.command_lines:
                    result.command_lines = [cmd_used]
                else:
                    result.command_lines.append(cmd_used)

                if ok_out:
                    any_success = True
                    result.outputs[out_name] = str(out_path)
                    result.hashes[out_name] = self._hash_file(out_path)
                    if result.successful_variant == 0:
                        result.successful_variant = variant_idx
                else:
                    failures.append(out_name)

            result.attempts = attempts

            # Check for config failure (HARD FAILURE even if files exist)
            if config_not_loaded:
                result.status = "failed"
                result.reason = "config_not_loaded: OSM2World reported 'could not read config'"
                return self._finalize(result, start_ts)

            if not any_success:
                result.status = "failed"
                result.reason = "OSM2World did not produce any requested outputs"
                return self._finalize(result, start_ts)

            # Validate GLB if produced
            if "scene.glb" in result.outputs:
                glb_path = Path(result.outputs["scene.glb"])
                glb_valid, glb_reason = self._validate_glb(glb_path)
                result.glb_valid = glb_valid
                result.glb_validation_reason = glb_reason
                if not glb_valid:
                    # Mark GLB as invalid but don't fail the whole stage
                    del result.outputs["scene.glb"]
                    failures.append("scene.glb (invalid)")

            # Validate OBJ
            if "scene.obj" in result.outputs:
                obj_path = Path(result.outputs["scene.obj"])
                if not obj_path.exists() or obj_path.stat().st_size == 0:
                    del result.outputs["scene.obj"]
                    failures.append("scene.obj (empty)")

            # Validate PNG
            if "preview.png" in result.outputs:
                png_path = Path(result.outputs["preview.png"])
                if not png_path.exists() or png_path.stat().st_size == 0:
                    del result.outputs["preview.png"]
                    failures.append("preview.png (empty)")

            # Final status
            if result.outputs:
                result.status = "ok"
                if failures:
                    result.reason = f"Generated {len(result.outputs)} outputs; failed: {', '.join(failures)}"
                else:
                    result.reason = f"Generated {len(result.outputs)} outputs: {', '.join(result.outputs.keys())}"
            else:
                result.status = "failed"
                result.reason = "No valid output files were generated"

        except subprocess.TimeoutExpired:
            result.status = "failed"
            result.reason = f"OSM2World timed out after {self.timeout_sec}s"
            result.exception = "TimeoutExpired"
        except Exception as e:
            result.status = "failed"
            result.reason = str(e)
            result.exception = f"{type(e).__name__}: {e}"

        return self._finalize(result, start_ts)

    def _finalize(self, result: OSM2WorldResult, start_ts: float) -> OSM2WorldResult:
        """Finalize result with timing and save status JSON."""
        result.end_time = datetime.now().isoformat()
        result.duration_sec = round(time.time() - start_ts, 3)

        # Write status JSON
        status_path = self.output_dir / "osm2world_status.json"
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, indent=2)
        except Exception as e:
            print(f"  Warning: could not write osm2world_status.json: {e}")

        return result


def run_osm2world_stage(
    osm_path: str,
    output_dir: str,
    osm2world_home: Optional[str] = None,
) -> OSM2WorldResult:
    """
    Convenience function to run OSM2World as a pipeline stage.

    Args:
        osm_path: Path to input OSM file
        output_dir: Directory for outputs
        osm2world_home: Optional override for OSM2World home

    Returns:
        OSM2WorldResult with status and paths
    """
    runner = OSM2WorldRunner(
        osm_path=osm_path,
        output_dir=output_dir,
        osm2world_home=osm2world_home,
    )
    return runner.run()


def is_osm2world_enabled() -> bool:
    """Check if OSM2World stage is enabled via environment.

    Supported toggles:
      - ENABLE_OSM2WORLD (legacy)
      - UP_ENABLE_OSM2WORLD (settings-driven)
    """
    for key in ("ENABLE_OSM2WORLD", "UP_ENABLE_OSM2WORLD"):
        val = os.getenv(key, "").strip().lower()
        if val in ("1", "true", "yes", "on"):
            return True
    return False


# ---------------------------------------------------------------------------
# CLI entry point for direct testing
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run OSM2World to generate 3D scene artifacts"
    )
    parser.add_argument("--osm", required=True, help="Path to OSM file")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--home", help="OSM2World home directory")
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds")
    parser.add_argument("--config", help="Path to external config file")

    args = parser.parse_args()

    runner = OSM2WorldRunner(
        osm_path=args.osm,
        output_dir=args.out,
        osm2world_home=args.home,
        timeout_sec=args.timeout,
        config_path=args.config,
    )
    result = runner.run()

    print(f"\nStatus: {result.status}")
    print(f"Reason: {result.reason}")
    print(f"Duration: {result.duration_sec:.1f}s")
    print(f"Cache key: {result.cache_key}")
    if result.outputs:
        print("Outputs:")
        for name, path in result.outputs.items():
            print(f"  {name}: {path}")
    if result.glb_valid is not None:
        print(f"GLB Valid: {result.glb_valid} ({result.glb_validation_reason})")

    sys.exit(0 if result.status in ("ok", "skipped", "cached") else 1)
