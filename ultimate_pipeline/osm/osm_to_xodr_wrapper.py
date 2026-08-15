#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ultimate_pipeline/osm/osm_to_xodr_wrapper.py

OSM → OpenDRIVE (.xodr) wrapper with *best-effort fallbacks*.

Why this exists:
 - Your thesis requires evaluating variability when converting the *same* OSM
   cutout into CARLA/OpenDRIVE.
 - CARLA's OSM→OpenDRIVE tooling differs across versions and installs.

This module therefore:
 1) Tries CARLA's Python API converter if available.
 2) Tries to locate and run CARLA's utility scripts/binaries if present.
 3) If nothing is available, it raises a clear error — and calling code may
    fall back to an already-existing XODR or even a built-in CARLA map.

It is intentionally conservative: it never silently fabricates an XODR.

Usage:
    from ultimate_pipeline.osm.osm_to_xodr_wrapper import convert_osm_to_xodr
    convert_osm_to_xodr("ingolstadt.osm", "out/ingolstadt.xodr")
"""

from __future__ import annotations

import os
import sys
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


@dataclass
class OSMToXODRConfig:
    carla_root: Optional[str] = None
    # Optional explicit tool/script path.
    tool_path: Optional[str] = None
    overwrite: bool = True
    timeout_s: int = 600
    extra_args: tuple[str, ...] = ()

    # --- CARLA PythonAPI settings (used when available) ---
    lane_width: float = 3.5
    generate_traffic_lights: bool = False
    all_junctions_with_traffic_lights: bool = False
    center_map: bool = False
    osm_way_types: tuple[str, ...] = (
        "motorway", "motorway_link",
        "trunk", "trunk_link",
        "primary", "primary_link",
        "secondary", "secondary_link",
        "tertiary", "tertiary_link",
        "unclassified", "residential",
    )

    def __post_init__(self):
        """Allow environment override for way types."""
        env_types = os.getenv("UP_OSM_FILTER_TYPES")
        if env_types:
            # Parse comma-separated list, trim whitespace, ignore empty
            tokens = [t.strip() for t in env_types.split(",") if t.strip()]
            if tokens:
                self.osm_way_types = tuple(tokens)



def _auto_detect_carla_root() -> Optional[Path]:
    """Best-effort CARLA_ROOT detection (no env var needed).

    Looks for a folder that contains: PythonAPI/carla/dist
    We check:
      - this file's parent directories
      - the current working directory's parents
    """
    here = Path(__file__).resolve()
    for base in [here] + list(here.parents):
        if (base / "PythonAPI" / "carla" / "dist").exists():
            return base
    cwd = Path.cwd().resolve()
    for base in [cwd] + list(cwd.parents):
        if (base / "PythonAPI" / "carla" / "dist").exists():
            return base
    return None


def _ensure_carla_importable(carla_root: Optional[Path]) -> None:
    """Try to make `import carla` work by adding CARLA PythonAPI paths to sys.path."""
    try:
        import carla  # type: ignore  # noqa: F401
        return
    except Exception:
        pass

    # Explicit egg/wheel path (optional)
    explicit = os.getenv("CARLA_PYTHONAPI_EGG") or os.getenv("CARLA_EGG")
    if explicit:
        p = Path(explicit)
        if p.exists():
            sp = str(p)
            if sp not in sys.path:
                sys.path.insert(0, sp)

    if not carla_root:
        return

    dist = carla_root / "PythonAPI" / "carla" / "dist"
    if dist.exists():
        # Add all candidates; Python will pick the matching one
        for p in sorted(dist.glob("carla-*")):
            sp = str(p)
            if sp not in sys.path:
                sys.path.insert(0, sp)

    carla_pkg = carla_root / "PythonAPI" / "carla"
    if carla_pkg.exists():
        sp = str(carla_pkg)
        if sp not in sys.path:
            sys.path.insert(0, sp)

def _find_carla_root(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    env = os.getenv("CARLA_ROOT") or os.getenv("CARLA_HOME")
    if env:
        p = Path(env)
        return p if p.exists() else None
    return _auto_detect_carla_root()


def _try_carla_pythonapi(osm_path: Path, cfg: OSMToXODRConfig) -> Optional[str]:
    """
    Try converting via CARLA PythonAPI if it exposes Osm2Odr.

    Important: in many CARLA builds, carla.Osm2Odr is a class with a *static*
    convert() method (not an instantiable converter). Older code that tries
    Osm2Odr() will fail even when the feature exists.
    """
    carla_root = _find_carla_root(cfg.carla_root)
    _ensure_carla_importable(carla_root)
    try:
        import carla  # type: ignore
    except Exception:
        return None

    # Preferred: the official API surface (common in 0.9.14+ forks).
    try:
        if hasattr(carla, "Osm2Odr") and hasattr(carla, "Osm2OdrSettings"):
            osm_data = osm_path.read_text(encoding="utf-8")
            settings = carla.Osm2OdrSettings()

            # Configure settings defensively (API differs between versions).
            if hasattr(settings, "set_osm_way_types"):
                try:
                    settings.set_osm_way_types(list(cfg.osm_way_types))
                except Exception:
                    pass

            if hasattr(settings, "default_lane_width"):
                try:
                    settings.default_lane_width = float(cfg.lane_width)
                except Exception:
                    pass

            for attr, val in (
                ("generate_traffic_lights", cfg.generate_traffic_lights),
                ("all_junctions_with_traffic_lights", cfg.all_junctions_with_traffic_lights),
                ("center_map", cfg.center_map),
            ):
                if hasattr(settings, attr):
                    try:
                        setattr(settings, attr, bool(val))
                    except Exception:
                        pass

            # carla.Osm2Odr.convert(osm_xml, settings) -> OpenDRIVE XML string
            out = carla.Osm2Odr.convert(osm_data, settings)
            if isinstance(out, str) and "<OpenDRIVE" in out:
                return out
    except Exception:
        pass

    # Fallback: try to discover converter-like objects in some forks.
    try:
        candidates: Sequence[str] = ("Osm2Odr", "Osm2OdrConverter", "OSM2ODR")
        for name in candidates:
            conv = getattr(carla, name, None)
            if conv is None:
                continue

            # If it looks like a class with a static convert(), call it.
            method = getattr(conv, "convert", None)
            if callable(method):
                try:
                    out = method(osm_path.read_text(encoding="utf-8"))
                    if isinstance(out, str) and "<OpenDRIVE" in out:
                        return out
                except Exception:
                    pass
    except Exception:
        pass

    return None


def _candidate_tools(carla_root: Optional[Path]) -> list[Path]:
    tools: list[Path] = []

    # Always consider a converter bundled with this repo (if present).
    here = Path(__file__).resolve().parent
    for rel in ["osm_to_xodr.py", "osm_to_xodr.pyd"]:
        p = here / rel
        if p.exists():
            tools.append(p)
    if carla_root is None:
        return tools

    # Known-ish utility scripts in many CARLA installs.
    for rel in [
        "PythonAPI/util/osm_to_xodr.py",
        "PythonAPI/util/osm_to_opendrive.py",
        "PythonAPI/util/osm_to_xodr.pyc",
    ]:
        p = carla_root / rel
        if p.exists():
            tools.append(p)

    # Potential binaries.
    for rel in [
        "osm2odr",
        "osm2odr.exe",
        "Tools/osm2odr",
        "Tools/osm2odr.exe",
    ]:
        p = carla_root / rel
        if p.exists():
            tools.append(p)

    return tools


def _run_subprocess(cmd: list[str], timeout_s: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)


def _try_tool(tool: Path, osm_path: Path, xodr_path: Path, cfg: OSMToXODRConfig) -> bool:
    """Try running a discovered tool with several common arg patterns."""

    # If it's a python script, call with the current interpreter.
    is_py = tool.suffix.lower() in (".py", ".pyc")
    base_cmd = [sys.executable, str(tool)] if is_py else [str(tool)]

    arg_patterns = [
        # pattern A: positional in/out
        [str(osm_path), str(xodr_path)],
        # pattern B: named args (common)
        ["--osm", str(osm_path), "--xodr", str(xodr_path)],
        ["--osm-path", str(osm_path), "--output", str(xodr_path)],
        ["--input", str(osm_path), "--output", str(xodr_path)],
        ["-i", str(osm_path), "-o", str(xodr_path)],
    ]

    for args in arg_patterns:
        cmd = base_cmd + args + list(cfg.extra_args)
        try:
            p = _run_subprocess(cmd, timeout_s=cfg.timeout_s)
        except Exception:
            continue

        # Success cases:
        #  - tool wrote the xodr file
        #  - tool printed xodr to stdout
        if xodr_path.exists() and xodr_path.stat().st_size > 200:
            return True
        if p.returncode == 0 and p.stdout and "<OpenDRIVE" in p.stdout:
            xodr_path.write_text(p.stdout, encoding="utf-8")
            return True

    return False


def convert_osm_to_xodr(
    osm_path: str | Path,
    xodr_path: str | Path,
    cfg: Optional[OSMToXODRConfig] = None,
) -> Path:
    """Convert an OSM extract into an OpenDRIVE (.xodr) file.

    Raises RuntimeError if no conversion method is available.
    """
    cfg = cfg or OSMToXODRConfig()

    osm_path = Path(osm_path)
    xodr_path = Path(xodr_path)

    if not osm_path.exists():
        raise FileNotFoundError(f"OSM file not found: {osm_path}")

    if xodr_path.exists() and not cfg.overwrite:
        return xodr_path

    xodr_path.parent.mkdir(parents=True, exist_ok=True)

    # 1) Try CARLA Python API converter, if present.
    xodr_text = _try_carla_pythonapi(osm_path, cfg)
    if xodr_text:
        xodr_path.write_text(xodr_text, encoding="utf-8")
        return xodr_path

    # 2) Try external tools (scripts/binaries) under CARLA_ROOT.
    carla_root = _find_carla_root(cfg.carla_root)

    explicit_tool = Path(cfg.tool_path) if cfg.tool_path else None
    tools: list[Path] = []
    if explicit_tool and explicit_tool.exists():
        tools.append(explicit_tool)
    tools += _candidate_tools(carla_root)

    for tool in tools:
        if _try_tool(tool, osm_path, xodr_path, cfg):
            return xodr_path

    attempted_tools = "\n".join(f"  - {p}" for p in tools) if tools else "  - (none)"
    raise RuntimeError(
        "No OSM→XODR conversion tool was found.\n"
        "Tried: CARLA PythonAPI converter + tool/script discovery.\n\n"
        "Tools considered:\n" + attempted_tools + "\n\n"
        "Fix options:\n"
        "  - Set CARLA_ROOT (or CARLA_HOME) to your CARLA install.\n"
        "  - Or set CARLA_PYTHONAPI_EGG to the exact carla-*.egg path.\n"
        "  - Or set UP_OSM_TO_XODR_TOOL to an explicit converter path.\n"
        "  - Or generate the .xodr externally and set UP_INPUT_XODR."
    )


__all__ = ["OSMToXODRConfig", "convert_osm_to_xodr"]
