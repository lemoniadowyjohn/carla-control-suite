#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ultimate_pipeline/perception/perception_api.py  (FIXED + compatible)

Goal
----
Make the perception API compatible with BOTH call styles that currently exist in your codebase:

A) Old / strict style:
    run_local_perception(client, map_name="Town10HD_Opt", out_dir="...")

B) New / config-driven style (what your run_training.py was trying to do):
    run_local_perception(config_path="configs/perception.json")

This module:
✅ accepts either style (and errors clearly if neither is provided)
✅ creates CARLA client from config when needed
✅ passes only supported kwargs to LocalPerceptionRunner (signature-safe)
✅ tries hard to discover the produced metrics JSON path
✅ returns a PerceptionRunResult with summary + metrics_json_path

Expected config JSON example
----------------------------
{
  "host": "127.0.0.1",
  "port": 2000,
  "timeout": 30.0,
  "map_name": "Town10HD_Opt",
  "out_dir": "ultimate_pipeline_out/perception_run",
  "seed": 42,
  "runner_kwargs": {
    "radius": 2
  }
}
"""

from __future__ import annotations

import os
import json
import glob
import inspect
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

import carla


# ----------------------------
# Public return type
# ----------------------------

@dataclass
class PerceptionRunResult:
    metrics_json_path: Optional[str]
    summary: Dict[str, Any]


# ----------------------------
# Helpers
# ----------------------------

def _ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def _load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        # assume JSON (simple + robust)
        return json.load(f)


def _make_client_from_cfg(cfg: Dict[str, Any]) -> carla.Client:
    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", 2000))
    timeout = float(cfg.get("timeout", 30.0))
    client = carla.Client(host, port)
    client.set_timeout(timeout)
    return client


def _pick_latest_json(out_dir: str) -> Optional[str]:
    """
    Best-effort: find the most recent JSON file under out_dir that *looks* like metrics.
    This is a fallback when the runner doesn't explicitly return a path.
    """
    if not out_dir or not os.path.isdir(out_dir):
        return None

    # Prefer common filenames if they exist
    preferred = [
        "metrics.json",
        "perception_metrics.json",
        "defects.json",
        "validation_metrics.json",
        "perception_gap.json",
    ]
    for name in preferred:
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            return p

    # Else: pick newest json anywhere under out_dir
    candidates = glob.glob(os.path.join(out_dir, "**", "*.json"), recursive=True)
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def _safe_call_with_supported_kwargs(fn, **kwargs):
    """
    Call fn(**kwargs) but only pass parameters that exist in fn signature.
    This avoids breakage if LocalPerceptionRunner signature changes.
    """
    sig = inspect.signature(fn)
    allowed = {}
    for k, v in kwargs.items():
        if k in sig.parameters and v is not None:
            allowed[k] = v
    return fn(**allowed)


# ----------------------------
# Main API
# ----------------------------

def run_local_perception(
    client: Optional[carla.Client] = None,
    map_name: Optional[str] = None,
    out_dir: Optional[str] = None,
    *,
    config_path: Optional[str] = None,
) -> PerceptionRunResult:
    """
    Compatible entrypoint.

    You may call either:
      - run_local_perception(client, map_name, out_dir)
      - run_local_perception(config_path="...")

    Returns:
      PerceptionRunResult(metrics_json_path=..., summary={...})
    """
    # 1) Load config if provided (and override missing args)
    cfg: Dict[str, Any] = {}
    if config_path:
        cfg = _load_config(config_path)

        if client is None:
            client = _make_client_from_cfg(cfg)

        if map_name is None:
            map_name = cfg.get("map_name")

        if out_dir is None:
            out_dir = cfg.get("out_dir")

    if client is None or not map_name:
        raise ValueError(
            "run_local_perception requires either:\n"
            "  (1) client + map_name (+ out_dir), or\n"
            "  (2) config_path with host/port + map_name (+ out_dir)\n"
            f"Got: client={client is not None}, map_name={map_name}, out_dir={out_dir}, config_path={config_path}"
        )

    out_dir = _ensure_dir(out_dir or os.path.join(os.getcwd(), "perception_out"))

    # Optional runner kwargs from config
    runner_kwargs = {}
    if isinstance(cfg.get("runner_kwargs"), dict):
        runner_kwargs = cfg["runner_kwargs"]

    seed = cfg.get("seed", None)

    # 2) Import runner lazily (so importing this module doesn't drag CARLA-dependent stuff too early)
    from ultimate_pipeline.carla_tools.local_perception_runner import LocalPerceptionRunner

    # 3) Construct runner in a signature-safe way
    # Different codebases use different param names; we try common ones.
    # If your LocalPerceptionRunner only accepts (client, map_name), we won't pass extra.
    runner = _safe_call_with_supported_kwargs(
        LocalPerceptionRunner,
        client=client,
        map_name=map_name,
        out_dir=out_dir,
        output_dir=out_dir,   # alternate name some people use
        seed=seed,
        **runner_kwargs,
    )

    # 4) Run (also signature-safe)
    # Some runners accept out_dir / output_dir on run(); others don't.
    result = _safe_call_with_supported_kwargs(
        runner.run,
        out_dir=out_dir,
        output_dir=out_dir,
    )

    # 5) Determine metrics path (best-effort)
    metrics_path = None

    # If runner returned a dict with a path, prefer it
    if isinstance(result, dict):
        for key in ("metrics_json_path", "metrics_path", "out_json", "output_json", "defects_json", "path"):
            if key in result and isinstance(result[key], str) and os.path.exists(result[key]):
                metrics_path = result[key]
                break

    # If runner object exposes something useful
    if metrics_path is None:
        for attr in ("metrics_json_path", "metrics_path", "out_json", "output_json"):
            p = getattr(runner, attr, None)
            if isinstance(p, str) and os.path.exists(p):
                metrics_path = p
                break

    # Fallback: search out_dir
    if metrics_path is None:
        metrics_path = _pick_latest_json(out_dir)

    summary = {
        "status": "ok",
        "map_name": map_name,
        "out_dir": out_dir,
        "config_path": config_path,
        "seed": seed,
        "runner_kwargs": runner_kwargs,
        "result_type": type(result).__name__,
    }

    # Attach small result preview (don’t blow up JSON if it’s huge)
    if isinstance(result, dict):
        summary["result_keys"] = sorted(list(result.keys()))[:50]
    else:
        summary["result_repr"] = repr(result)[:500]

    # Include whether we actually found a metrics file
    summary["metrics_found"] = bool(metrics_path and os.path.exists(metrics_path))

    return PerceptionRunResult(metrics_json_path=metrics_path, summary=summary)
