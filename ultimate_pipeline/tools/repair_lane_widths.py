from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Optional

from ultimate_pipeline.enrichment.lane_width_policy import apply_lane_width_policy


def _load_osm_meta(osm_path: str | Path | None) -> Optional[dict[str, dict[str, Any]]]:
    if not osm_path:
        return None
    from ultimate_pipeline.enrichment.osm_meta_index import build_osm_meta_index

    return build_osm_meta_index(str(osm_path))


def _add_missing_non_center_widths(
    root: ET.Element,
    *,
    default_width: float,
) -> int:
    added = 0
    for lane in root.findall(".//lane"):
        lane_id = lane.get("id")
        try:
            if int(lane_id or "0") == 0:
                continue
        except Exception:
            pass
        if lane.find("width") is not None:
            continue
        ET.SubElement(
            lane,
            "width",
            sOffset="0",
            a=f"{float(default_width):.3f}",
            b="0",
            c="0",
            d="0",
        )
        added += 1
    return added


def repair(
    xodr_in: str | Path,
    xodr_out: str | Path,
    default_width: float = 3.5,
    *,
    osm_meta: Optional[Mapping[str, Mapping[str, Any]]] = None,
    osm_path: str | Path | None = None,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply the governed lane-width policy to an XODR file and write a new file."""
    tree = ET.parse(str(xodr_in))
    root = tree.getroot()
    meta = osm_meta if osm_meta is not None else _load_osm_meta(osm_path)

    report = apply_lane_width_policy(
        root,
        osm_meta=meta,
        fallback_width_m=float(default_width),
    )
    report["totals"]["legacy_missing_non_center_widths_added"] = (
        _add_missing_non_center_widths(root, default_width=float(default_width))
    )
    report["input_xodr"] = str(xodr_in)
    report["output_xodr"] = str(xodr_out)
    if osm_path:
        report["osm_path"] = str(osm_path)

    out = Path(xodr_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(out), encoding="utf-8", xml_declaration=True)

    if report_path:
        report_out = Path(report_path)
        report_out.parent.mkdir(parents=True, exist_ok=True)
        report_out.write_text(
            json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True),
            encoding="utf-8",
        )

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply governed lane-width policy to XODR.")
    parser.add_argument("input_xodr")
    parser.add_argument("output_xodr")
    parser.add_argument("--osm-path", default=None)
    parser.add_argument("--report-path", default=None)
    parser.add_argument("--default-width", type=float, default=3.5)
    args = parser.parse_args(argv)

    report = repair(
        args.input_xodr,
        args.output_xodr,
        default_width=args.default_width,
        osm_path=args.osm_path,
        report_path=args.report_path,
    )
    print(json.dumps(report["totals"], indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
