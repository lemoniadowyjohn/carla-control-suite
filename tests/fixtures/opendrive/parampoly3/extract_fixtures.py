"""Build immutable fixtures using frozen pre-migration production outputs."""
from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from opendrive_geometry.parampoly3_legacy_baseline import (
    BASELINE_COMMIT,
    BASELINE_CURVATURE_SOURCE,
    BASELINE_POSE_SOURCE,
    legacy_curvatures,
    legacy_pose,
)

SOURCES = (REPO / "auto_master.xodr", REPO / "manual_grid0828.xodr")
COEFFICIENT_NAMES = ("aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV")
STATION_FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _production_outputs(record: dict) -> list[dict]:
    curvatures = legacy_curvatures(record, n_samples=len(STATION_FRACTIONS))
    if len(curvatures) != len(STATION_FRACTIONS):
        raise ValueError("production curvature consumer rejected fixture")
    outputs = []
    for index, fraction in enumerate(STATION_FRACTIONS):
        station = record["length"] * fraction
        pose = legacy_pose(record, station)
        outputs.append(
            {
                "station_fraction": fraction,
                "station": station,
                "x": pose.x,
                "y": pose.y,
                "heading": pose.hdg,
                "curvature_abs": curvatures[index],
            }
        )
    return outputs


def _records(source: Path) -> list[tuple[dict, ET.Element]]:
    root = ET.parse(source).getroot()
    records: list[tuple[dict, ET.Element]] = []
    for road in root.findall(".//road"):
        plan = road.find("planView")
        if plan is None:
            continue
        for index, geometry in enumerate(plan.findall("geometry")):
            param_poly3 = geometry.find("paramPoly3")
            if param_poly3 is None:
                continue
            record = {
                "road_id": road.get("id", ""),
                "geometry_index": index,
                "s0": float(geometry.attrib["s"]),
                "x0": float(geometry.attrib["x"]),
                "y0": float(geometry.attrib["y"]),
                "hdg0": float(geometry.attrib["hdg"]),
                "length": float(geometry.attrib["length"]),
                "pRange": param_poly3.attrib["pRange"],
            }
            record.update(
                {name: float(param_poly3.attrib[name]) for name in COEFFICIENT_NAMES}
            )
            records.append((record, param_poly3))
    return records


def _select_diverse(
    records: list[tuple[dict, ET.Element]], count: int
) -> list[tuple[dict, ET.Element]]:
    if len(records) <= count:
        return records
    indices = {
        round(index * (len(records) - 1) / (count - 1))
        for index in range(count)
    }
    return [records[index] for index in sorted(indices)]


def main() -> None:
    sources = []
    for source in SOURCES:
        parent_sha256 = _sha256(source)
        fixtures = []
        for record, _param_poly3 in _select_diverse(_records(source), 6):
            record["parent_xodr_sha256"] = parent_sha256
            record["expected_production_output"] = _production_outputs(record)
            fixtures.append(record)
        sources.append(
            {
                "file": source.name,
                "sha256": parent_sha256,
                "selection": "six evenly distributed ParamPoly3 records",
                "fixtures": fixtures,
            }
        )

    output = Path(__file__).with_name("manifest.json")
    output.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "production_baseline": {
                    "commit": BASELINE_COMMIT,
                    "pose_source": BASELINE_POSE_SOURCE,
                    "curvature_source": BASELINE_CURVATURE_SOURCE,
                },
                "sources": sources,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {sum(len(source['fixtures']) for source in sources)} fixtures")


if __name__ == "__main__":
    main()
