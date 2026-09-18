#!/usr/bin/env python3
"""ultimate_pipeline.experiments.thesis.run_thesis_oneweek

[EXPERIMENTAL/STALE] A single entrypoint intended for the final-week thesis sprint.
NOTE: This script is preserved for historical reference but may not reflect 
the latest stable evidence-pack requirements. Use run_thesis_experiments.py
for canonical thesis runs.
This repository accumulated many scripts (map generation, preflight, perception,
domain-gap, QA). Examiners mainly care that you can produce a small set of
reproducible artifacts that directly support the thesis claims.

This runner focuses on three thesis-critical outputs:
1) Structural gap (manual vs auto) computed from XODR (no CARLA required)
2) Perceptual gap (manual vs auto) computed from either:
   - task metrics (mIoU/mAP JSON), OR
   - feature-proxy metrics exported from run image folders
3) Natural variability (optional): run domain-gap N times if you provide multiple
   auto-map XODRs, and summarize mean+/-std.

It does NOT record new CARLA datasets by default. Use:
  python -m ultimate_pipeline.perception.record_route
and then point this script to the resulting run folders.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import List, Optional

from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap
from ultimate_pipeline.domain_gap.domain_gap_prep import DomainGapPrep
from ultimate_pipeline.utils.run_provenance import collect_provenance, write_provenance

INGOLSTADT_BBOX = {
    "lat_min": 48.74935649548228,
    "lon_min": 11.422268084715878,
    "lat_max": 48.77444431571603,
    "lon_max": 11.47882091528412,
}


def _resolve_calib_path(explicit_path: Optional[str]) -> str:
    """Resolve calibration JSON path with standardized fallback order.

    Resolution order:
    1. If explicit_path is provided and exists, use it
    2. Try ultimate_pipeline/sensors/calib_data.json
    3. Fall back to previous default (calib_data.json in CWD)

    Returns the resolved path and logs which was chosen.
    """
    # Standard location
    standard_path = Path(__file__).parents[2] / "sensors" / "calib_data.json"

    # Previous default (CWD)
    legacy_path = Path("calib_data.json")

    if explicit_path:
        p = Path(explicit_path).expanduser()
        if p.is_file():
            print(f"Using explicit calib path: {p}")
            return str(p)
        # Explicit path given but doesn't exist - warn and continue
        print(f"Warning: Explicit calib path not found: {p}, trying fallbacks")

    if standard_path.is_file():
        print(f"Using standard calib path: {standard_path}")
        return str(standard_path)

    if legacy_path.is_file():
        print(f"Using legacy calib path (CWD): {legacy_path.resolve()}")
        return str(legacy_path)

    # Return the standard path even if it doesn't exist; downstream will error
    print(f"Calib path not found, using default: {standard_path}")
    return str(standard_path)


def _load_and_validate_protocol(protocol_path: str) -> dict:
    """Load and validate a protocol file, raising on error."""
    from ultimate_pipeline.experiments.thesis.protocol import (
        load_protocol,
        validate_protocol,
    )
    protocol = load_protocol(protocol_path)
    protocol["_source_path"] = str(Path(protocol_path).resolve())
    validate_protocol(protocol)
    return protocol


def _write_protocol_snapshot_with_provenance(
    out_dir: Path,
    protocol: dict,
    calib_path: str,
) -> None:
    """Write protocol snapshot and provenance to output directory."""
    from ultimate_pipeline.experiments.thesis.protocol import write_protocol_snapshot

    provenance = collect_provenance(extra={
        "calib_path": calib_path,
        "run_type": "thesis_oneweek",
    })
    write_protocol_snapshot(str(out_dir), protocol, provenance)


def _parse_multi_paths(value: str) -> List[str]:
    value = (value or "").strip()
    if not value:
        return []
    return [v.strip() for v in value.split(',') if v.strip()]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--manual-xodr', required=True)
    ap.add_argument('--auto-xodr', required=True, help='Comma-separated list allowed for variability study')
    ap.add_argument('--out-dir', default='ultimate_pipeline_out/thesis_oneweek')

    # Optional tiles
    ap.add_argument('--manual-tiles', default='')
    ap.add_argument('--auto-tiles', default='')

    # Optional perception inputs (either metrics JSON or run directory)
    ap.add_argument('--perception-manual', default='', help='Path to metrics JSON OR a run directory')
    ap.add_argument('--perception-auto', default='', help='Path to metrics JSON OR a run directory')

    ap.add_argument('--calib-json', default='', help='Calibration JSON path (defaults to ultimate_pipeline/sensors/calib_data.json)')
    ap.add_argument('--variability', action='store_true', help='If set, treat --auto-xodr as list and summarize variance')

    # Protocol support for thesis reproducibility
    ap.add_argument('--protocol', default='', help='Path to thesis protocol YAML for snapshot + validation')

    return ap.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve calibration path with standardized fallback
    calib_path = _resolve_calib_path(args.calib_json if args.calib_json else None)

    # Handle protocol if provided
    protocol = None
    if args.protocol:
        print(f"Loading thesis protocol: {args.protocol}")
        protocol = _load_and_validate_protocol(args.protocol)
        _write_protocol_snapshot_with_provenance(out_dir, protocol, calib_path)
        print(f"Protocol snapshot written to: {out_dir}")

    prep = DomainGapPrep(calib_json=calib_path)
    auto_xodrs = _parse_multi_paths(args.auto_xodr) or [args.auto_xodr]

    # Resolve/ensure perception metrics JSONs (supports feature-proxy export)
    manual_metrics_json = prep.ensure_feature_metrics_json(args.perception_manual, out_name='perception_metrics_manual.json')
    auto_metrics_json = prep.ensure_feature_metrics_json(args.perception_auto, out_name='perception_metrics_auto.json')

    results = []
    for i, ax in enumerate(auto_xodrs, start=1):
        run_out = out_dir / (f'run_{i:02d}' if len(auto_xodrs) > 1 else 'run')
        run_out.mkdir(parents=True, exist_ok=True)

        combined = run_full_domain_gap(
            manual_xodr=str(Path(args.manual_xodr)),
            auto_xodr=str(Path(ax)),
            manual_tiles=args.manual_tiles or '',
            auto_tiles=args.auto_tiles or '',
            perception_manual_json=manual_metrics_json,
            perception_auto_json=auto_metrics_json,
            output_dir=str(run_out),
        )

        # Write a small meta file for thesis writing
        meta = {
            "bbox_ingolstadt": INGOLSTADT_BBOX,
            "manual_xodr": str(Path(args.manual_xodr).resolve()),
            "auto_xodr": str(Path(ax).resolve()),
            "perception_manual_json": manual_metrics_json,
            "perception_auto_json": auto_metrics_json,
            "calib_path": calib_path,
            "protocol_used": args.protocol if args.protocol else None,
        }
        (run_out / 'thesis_meta.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
        results.append(combined if isinstance(combined, dict) else {"combined": str(type(combined))})

    # Variability summary (mean±std) for a simple structural scalar if available
    if args.variability and len(results) > 1:
        # Try to summarize geometric RMSE if present
        import numpy as np
        vals = []
        for r in results:
            try:
                vals.append(float(r.get('structural', {}).get('geometric_gap', {}).get('rmse', 0.0)))
            except Exception:
                continue
        if vals:
            arr = np.asarray(vals, dtype=float)
            summary = {
                "metric": "geometric_gap.rmse",
                "n": int(arr.size),
                "mean": float(arr.mean()),
                "std": float(arr.std()),
                "values": [float(x) for x in arr.tolist()],
            }
            (out_dir / 'variability_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')

    print(f"Wrote thesis outputs to: {out_dir}")


if __name__ == '__main__':
    main()
