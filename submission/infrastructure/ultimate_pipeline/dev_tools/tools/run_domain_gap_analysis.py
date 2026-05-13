#!/usr/bin/env python3
"""
Run structural domain-gap checks on manual CARLA maps (e.g., Grid0821/Grid0828) and optional auto XODR.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.carla_tools.carla_server import (
    DEFAULT_FLAGS,
    ensure_carla_server,
    ensure_maps_available,
    load_map_with_timeout,
    enable_no_rendering,
    _lazy_carla,
)
from ultimate_pipeline.domain_gap.structural_gap import StructuralGapAnalyzer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Manual-map domain-gap structural metrics.")
    p.add_argument(
        "--manual-maps",
        nargs="+",
        default=list(getattr(SETTINGS, "MANUAL_CARLA_MAPS", ("Grid0821", "Grid0828"))),
        help="Manual CARLA map names (e.g., Grid0821 Grid0828).",
    )
    p.add_argument(
        "--auto-xodr",
        default=getattr(SETTINGS, "GENERATED_XODR", None),
        help="Optional auto-generated XODR path to compare (defaults to SETTINGS.GENERATED_XODR).",
    )
    p.add_argument(
        "--host", default=SETTINGS.CARLA_HOST, help="CARLA host (default from settings)"
    )
    p.add_argument(
        "--port", type=int, default=SETTINGS.CARLA_PORT, help="CARLA port (default from settings)"
    )
    p.add_argument(
        "--carla-exe",
        default=SETTINGS.CARLA_EXE,
        help="Path to CarlaUE4.exe (0.9.16).",
    )
    p.add_argument(
        "--out",
        default=str(Path(SETTINGS.BASE_OUTPUT_DIR) / "domain_gap_manual"),
        help="Output directory for JSON metrics.",
    )
    p.add_argument(
        "--no-start",
        action="store_true",
        help="Assume CARLA already running; skip restart.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Timeout seconds for map loads.",
    )
    p.add_argument(
        "--kill-stale",
        action="store_true",
        help="Kill stale CarlaUE4 processes before start (opt-in).",
    )
    return p.parse_args()


def analyze_manual_maps(
    maps: Sequence[str],
    host: str,
    port: int,
    carla_exe: str,
    output_dir: Path,
    skip_start: bool = False,
    timeout_s: float = 300.0,
    kill_stale: bool = False,
) -> list[dict]:
    if not skip_start:
        ensure_carla_server(
            host=host,
            port=port,
            carla_exe=carla_exe,
            extra_flags=DEFAULT_FLAGS,
            timeout_s=120.0,
            kill_stale=kill_stale,
        )

    carla = _lazy_carla()
    client = carla.Client(host, port)
    client.set_timeout(float(timeout_s))

    ensure_maps_available(client, maps)
    analyzer = StructuralGapAnalyzer(host=host, port=port, timeout=300.0)

    results = []
    for m in maps:
        world = load_map_with_timeout(client, m, timeout_s=timeout_s)
        enable_no_rendering(world)
        metrics = analyzer.analyze_world(world, source=m)
        results.append(metrics)
    (output_dir / "manual_maps.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    manual_results = analyze_manual_maps(
        args.manual_maps,
        host=args.host,
        port=args.port,
        carla_exe=args.carla_exe,
        output_dir=out_dir,
        skip_start=bool(args.no_start),
        timeout_s=float(args.timeout),
        kill_stale=bool(args.kill_stale),
    )

    if args.auto_xodr:
        analyzer = StructuralGapAnalyzer(host=args.host, port=args.port, timeout=300.0)
        auto_metrics = analyzer.analyze_xodr(args.auto_xodr)
        (out_dir / "auto_xodr.json").write_text(json.dumps(auto_metrics, indent=2), encoding="utf-8")

    print(f"[DONE] Results written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
