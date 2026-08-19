#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from phase_q.common import PROJECT_ROOT
from tools.verify_candidate_digest import sha256_file

from .runtime_config import DEFAULT_CANDIDATE_XODR, resolve_cert_runtime_config

OUT = PROJECT_ROOT / "_p4_runtime_evidence.json"
SRC = (
    PROJECT_ROOT
    / "campaigns"
    / "ingolstadt_cooked_perception_v1"
    / "candidate"
    / "raw_xodr_run_1_epsg32632_header_pinned.xodr"
)


def log(msg: str) -> None:
    print(msg, flush=True)


def _server_pid():
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq CarlaUE4-Win64-Shipping.exe", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = [l for l in out.stdout.strip().splitlines() if "CarlaUE4" in l]
        if lines:
            parts = lines[0].replace('"', "").split(",")
            if len(parts) > 1:
                return parts[1]
    except Exception:
        pass
    return None


def collect_runtime_evidence(
    *,
    source_xodr: Path | str = SRC,
    repaired_xodr: Path | str = DEFAULT_CANDIDATE_XODR,
    client: Any = None,
    load_world_fn: Optional[Callable[..., Any]] = None,
    client_timeout_s: float = 90.0,
    load_timeout_s: float = 600.0,
    log_fn: Callable[[str], None] = log,
) -> dict[str, Any]:
    source_xodr = Path(source_xodr)
    repaired_xodr = Path(repaired_xodr)

    src_sha = sha256_file(source_xodr)
    rep_sha = sha256_file(repaired_xodr)
    log_fn(f"Source SHA-256: {src_sha}")
    log_fn(f"Repaired SHA-256: {rep_sha}")

    payload_text = repaired_xodr.read_text(encoding="utf-8", errors="ignore")
    payload_sha = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    log_fn(f"Load-payload SHA-256 (file text): {payload_sha}")

    if load_world_fn is None:
        import carla

        from ultimate_pipeline.core.carla_opendrive_loader import (
            CarlaOpendrivePreflightError,
            load_opendrive_world_from_file,
        )

        load_world_fn = load_opendrive_world_from_file
        if client is None:
            client = carla.Client("127.0.0.1", 2000)
            client.set_timeout(client_timeout_s)
    else:
        CarlaOpendrivePreflightError = RuntimeError  # type: ignore[assignment]
        if client is None:
            raise ValueError("client is required when injecting a custom load_world_fn")

    t0 = time.time()
    try:
        world = load_world_fn(
            client,
            repaired_xodr,
            timeout_s=load_timeout_s,
            retries=1,
            do_reload=True,
            fallback_enabled=False,
            source_sha256=rep_sha,
        )
        load_time_s = time.time() - t0
    except CarlaOpendrivePreflightError as exc:  # type: ignore[misc]
        return {
            "status": "PREFLIGHT_FAILED",
            "error": str(exc),
            "src_sha256": src_sha,
            "rep_sha256": rep_sha,
            "payload_sha256": payload_sha,
            "server_pid": _server_pid(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            "status": "LOAD_FAILED",
            "error": f"{type(exc).__name__}: {exc}",
            "load_time_s": round(time.time() - t0, 1),
            "src_sha256": src_sha,
            "rep_sha256": rep_sha,
            "payload_sha256": payload_sha,
            "server_pid": _server_pid(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    m = world.get_map()
    map_name = str(getattr(m, "name", "") or "")
    log_fn(f"Map loaded in {load_time_s:.1f}s, name={map_name}")

    runtime_xodr = m.to_opendrive()
    runtime_sha = hashlib.sha256(runtime_xodr.encode("utf-8")).hexdigest()
    log_fn(f"Runtime to_opendrive SHA-256: {runtime_sha}")

    src_root = ET.parse(source_xodr).getroot()
    rep_root = ET.parse(repaired_xodr).getroot()
    rt_root = ET.fromstring(runtime_xodr)

    def count_ids(root, tag):
        xml_count = len(root.findall(tag))
        ids = set()
        for el in root.findall(tag):
            i = el.get("id")
            if i is not None:
                ids.add(i)
        return xml_count, len(ids), ids

    src_road_xml, src_road_unique, src_road_ids = count_ids(src_root, "road")
    rep_road_xml, rep_road_unique, rep_road_ids = count_ids(rep_root, "road")
    rt_road_xml, rt_road_unique, rt_road_ids = count_ids(rt_root, "road")

    src_junc_xml, src_junc_unique, src_junc_ids = count_ids(src_root, "junction")
    rep_junc_xml, rep_junc_unique, rep_junc_ids = count_ids(rep_root, "junction")
    rt_junc_xml, rt_junc_unique, rt_junc_ids = count_ids(rt_root, "junction")

    missing_roads = sorted(src_road_ids - rt_road_ids)
    unexpected_roads = sorted(rt_road_ids - src_road_ids)
    missing_juncs = sorted(src_junc_ids - rt_junc_ids)
    unexpected_juncs = sorted(rt_junc_ids - src_junc_ids)

    def count_lanes_and_sections(root):
        lane_sections = 0
        driving_lanes = 0
        for road in root.findall("road"):
            lanes = road.find("lanes")
            if lanes is None:
                continue
            lane_sections += len(lanes.findall("laneSection"))
            for sec in lanes.findall("laneSection"):
                for ln in sec.findall(".//lane"):
                    if ln.get("type") == "driving":
                        driving_lanes += 1
        return lane_sections, driving_lanes

    src_ls, src_dl = count_lanes_and_sections(src_root)
    rt_ls, rt_dl = count_lanes_and_sections(rt_root)

    log_fn(f"SOURCE roads(xml/unique): {src_road_xml}/{src_road_unique}")
    log_fn(f"REPAIRED roads(xml/unique): {rep_road_xml}/{rep_road_unique}")
    log_fn(f"RUNTIME roads(xml/unique): {rt_road_xml}/{rt_road_unique}")
    log_fn(f"SOURCE junctions(xml/unique): {src_junc_xml}/{src_junc_unique}")
    log_fn(f"RUNTIME junctions(xml/unique): {rt_junc_xml}/{rt_junc_unique}")
    log_fn(f"Missing runtime roads: {len(missing_roads)}")
    log_fn(f"Unexpected runtime roads: {len(unexpected_roads)}")
    log_fn(f"Missing runtime junction IDs: {len(missing_juncs)}")
    log_fn(f"Unexpected runtime junction IDs: {len(unexpected_juncs)}")
    log_fn(f"Lane sections source/runtime: {src_ls}/{rt_ls}")
    log_fn(f"Driving lanes source/runtime: {src_dl}/{rt_dl}")

    return {
        "status": "OK",
        "map_name": map_name,
        "load_time_s": round(load_time_s, 1),
        "src_sha256": src_sha,
        "rep_sha256": rep_sha,
        "payload_sha256": payload_sha,
        "runtime_to_opendrive_sha256": runtime_sha,
        "inventory": {
            "source": {
                "road_xml": src_road_xml,
                "road_unique": src_road_unique,
                "junction_xml": src_junc_xml,
                "junction_unique": src_junc_unique,
                "lane_sections": src_ls,
                "driving_lanes": src_dl,
            },
            "repaired": {
                "road_xml": rep_road_xml,
                "road_unique": rep_road_unique,
                "junction_xml": rep_junc_xml,
                "junction_unique": rep_junc_unique,
            },
            "runtime": {
                "road_xml": rt_road_xml,
                "road_unique": rt_road_unique,
                "junction_xml": rt_junc_xml,
                "junction_unique": rt_junc_unique,
                "lane_sections": rt_ls,
                "driving_lanes": rt_dl,
            },
            "missing_roads": missing_roads[:200],
            "unexpected_roads": unexpected_roads[:200],
            "missing_junctions": missing_juncs[:100],
            "unexpected_junctions": unexpected_juncs[:100],
            "missing_road_count": len(missing_roads),
            "unexpected_road_count": len(unexpected_roads),
            "missing_junction_count": len(missing_juncs),
            "unexpected_junction_count": len(unexpected_juncs),
        },
        "server_pid": _server_pid(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def write_runtime_evidence(payload: dict[str, Any], out_path: Path | str = OUT) -> Path:
    out_path = Path(out_path)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-xodr", default=str(SRC))
    parser.add_argument("--candidate-xodr", default=str(DEFAULT_CANDIDATE_XODR))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--phase-l-dir", default=None)
    parser.add_argument("--p4-dir", default=None)
    parser.add_argument("--out", default=str(OUT))
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    runtime = resolve_cert_runtime_config(
        candidate_xodr=args.candidate_xodr,
        run_id=args.run_id,
        phase_l_dir=args.phase_l_dir,
        p4_dir=args.p4_dir,
    )
    payload = collect_runtime_evidence(
        source_xodr=args.source_xodr,
        repaired_xodr=runtime.candidate_xodr,
    )
    write_runtime_evidence(payload, args.out)
    log(f"\nEvidence written to {args.out}")
    return 0 if payload.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
