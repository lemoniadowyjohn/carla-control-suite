# ultimate_pipeline/artifacts/map_event_record.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import time
import hashlib
from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass
class MapEventRecord:
    run_id: str
    map_hash: Optional[str]
    stage_name: Optional[str]
    gate_name: Optional[str]
    event_type: str
    road_id: Optional[str]
    lane_section_id: Optional[str]
    lane_id: Optional[str]
    junction_id: Optional[str]
    s_from: Optional[float]
    s_to: Optional[float]
    removed_length_m: Optional[float]
    removed_length_pct: Optional[float]
    tile_id: Optional[str]
    carla_failed_before_masking: Optional[bool]
    carla_failed_after_masking: Optional[bool]
    timestamp: str


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _run_id_from_out_dir(out_dir: str) -> str:
    base = os.path.basename(os.path.normpath(out_dir or ""))
    return base or "unknown"


def _artifacts_dir(out_dir: str) -> str:
    run_id = _run_id_from_out_dir(out_dir)
    return os.path.join(out_dir, "artifacts", run_id)


def _events_path(out_dir: str) -> str:
    return os.path.join(_artifacts_dir(out_dir), "map_events.jsonl")


def _map_hash_path(out_dir: str) -> str:
    return os.path.join(_artifacts_dir(out_dir), "map_hash.sha256")


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get_map_hash(out_dir: str, final_xodr_path: str) -> Optional[str]:
    if not out_dir or not final_xodr_path:
        return None
    cache_path = _map_hash_path(out_dir)
    if os.path.exists(cache_path):
        try:
            return open(cache_path, "r", encoding="utf-8").read().strip() or None
        except Exception:
            pass
    try:
        with open(final_xodr_path, "r", encoding="utf-8", errors="replace") as f:
            text = _normalize_text(f.read())
        digest = _sha256_text(text)
    except Exception:
        return None
    try:
        os.makedirs(_artifacts_dir(out_dir), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(digest + "\n")
    except Exception:
        pass
    return digest


def append_event(out_dir: str, record: MapEventRecord) -> None:
    try:
        os.makedirs(_artifacts_dir(out_dir), exist_ok=True)
        path = _events_path(out_dir)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=True) + "\n")
    except Exception:
        pass


def build_record(
    *,
    out_dir: str,
    final_xodr_path: str,
    stage_name: Optional[str],
    gate_name: Optional[str],
    event_type: str,
    road_id: Optional[str],
    lane_section_id: Optional[str],
    lane_id: Optional[str],
    junction_id: Optional[str],
    s_from: Optional[float],
    s_to: Optional[float],
    removed_length_m: Optional[float],
    removed_length_pct: Optional[float],
    tile_id: Optional[str] = None,
    carla_failed_before_masking: Optional[bool] = None,
    carla_failed_after_masking: Optional[bool] = None,
) -> MapEventRecord:
    run_id = _run_id_from_out_dir(out_dir)
    map_hash = get_map_hash(out_dir, final_xodr_path)
    return MapEventRecord(
        run_id=run_id,
        map_hash=map_hash,
        stage_name=stage_name,
        gate_name=gate_name,
        event_type=event_type,
        road_id=road_id,
        lane_section_id=lane_section_id,
        lane_id=lane_id,
        junction_id=junction_id,
        s_from=s_from,
        s_to=s_to,
        removed_length_m=removed_length_m,
        removed_length_pct=removed_length_pct,
        tile_id=tile_id,
        carla_failed_before_masking=carla_failed_before_masking,
        carla_failed_after_masking=carla_failed_after_masking,
        timestamp=_utc_timestamp(),
    )
