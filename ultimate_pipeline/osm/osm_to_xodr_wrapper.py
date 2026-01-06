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


def _find_carla_root(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    env = os.getenv("CARLA_ROOT") or os.getenv("CARLA_HOME")
    if env:
        p = Path(env)
        return p if p.exists() else None
    return None


def _try_carla_pythonapi(osm_path: Path) -> Optional[str]:
    """Try converting via CARLA PythonAPI if it exposes an OSM converter.

We intentionally use a very defensive approach because the exact API surface
varies between CARLA versions and forks.
"""
    try:
        import carla  # type: ignore
    except Exception:
        return None

    # Common candidate names seen in some builds/forks.
    candidates: Sequence[str] = ("Osm2Odr", "Osm2OdrConverter", "OSM2ODR")
    for name in candidates:
        conv = getattr(carla, name, None)
        if conv is None:
            continue
        try:
            obj = conv() if callable(conv) else conv
            # Try the most likely method names.
            for method_name in ("convert", "Convert", "run"):
                method = getattr(obj, method_name, None)
                if method is None:
                    continue
                try:
                    out = method(str(osm_path))
                except TypeError:
                    # Some variants take raw XML.
                    out = method(osm_path.read_text(encoding="utf-8"))
                if isinstance(out, str) and "<OpenDRIVE" in out:
                    return out
        except Exception:
            continue
    return None


def _candidate_tools(carla_root: Optional[Path]) -> list[Path]:
    tools: list[Path] = []
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
    xodr_text = _try_carla_pythonapi(osm_path)
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

    raise RuntimeError(
        "No OSM→XODR conversion tool was found.\n"
        "Tried: CARLA PythonAPI converter + CARLA_ROOT utility scripts/binaries.\n"
        "Fix options:\n"
        "  - Set CARLA_ROOT to your CARLA install.\n"
        "  - Set SETTINGS.OSM_TO_XODR_TOOL to an explicit converter path.\n"
        "  - Or generate the .xodr externally and set SETTINGS.INPUT_XODR."  # noqa: E501
    )


__all__ = ["OSMToXODRConfig", "convert_osm_to_xodr"]
