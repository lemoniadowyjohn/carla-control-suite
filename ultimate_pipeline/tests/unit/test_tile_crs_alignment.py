from __future__ import annotations

import logging
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.core.georef_utils import canonical_manual_georeference
from ultimate_pipeline.run_full_domain_gap import (
    _attach_auto_georef_metadata,
    _auto_generate_tiles_from_xodr,
    _raise_on_invalid_auto_georef_alignment,
    _read_tiles_dir_proj4,
    _write_inferred_tile_origin_meta,
)


def _write_source_xodr(path: Path, georef: str) -> None:
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header", revMajor="1", revMinor="4", name="auto")
    geo = ET.SubElement(header, "geoReference")
    geo.text = georef

    road = ET.SubElement(root, "road", id="1", length="20", junction="-1", type="town")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10")
    ET.SubElement(plan, "geometry", s="10", x="10", y="10", hdg="0", length="10")

    lanes = ET.SubElement(road, "lanes")
    lane_section = ET.SubElement(lanes, "laneSection", s="0")
    ET.SubElement(ET.SubElement(lane_section, "center"), "lane", id="0", type="none", level="false")
    right = ET.SubElement(lane_section, "right")
    lane = ET.SubElement(right, "lane", id="-1", type="driving", level="false")
    ET.SubElement(lane, "width", sOffset="0", a="3", b="0", c="0", d="0")

    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_auto_generated_tiles_can_be_rewritten_to_manual_crs(tmp_path: Path) -> None:
    source_xodr = tmp_path / "aligned_auto.xodr"
    output_root = tmp_path / "auto_tiles"
    local_tm = (
        "+proj=tmerc +lat_0=48.74935649548228 +lon_0=11.422268084715878 +k=1 "
        "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )
    _write_source_xodr(source_xodr, local_tm)

    out = _auto_generate_tiles_from_xodr(
        str(source_xodr),
        output_root,
        logging.getLogger("test"),
        proj4_override=canonical_manual_georeference(),
    )

    assert out is not None
    tile_path = Path(out) / "tiles" / "tile_0_0.xodr"
    manifest_path = Path(out) / "tile_manifest.json"
    root = ET.parse(tile_path).getroot()
    header = root.find("header")
    geo = header.find("geoReference") if header is not None else None
    text = (geo.text or "").strip() if geo is not None else ""

    assert text == canonical_manual_georeference()
    assert manifest_path.read_text(encoding="utf-8").find(canonical_manual_georeference()) >= 0
    assert _read_tiles_dir_proj4(str(Path(out) / "tiles")) == canonical_manual_georeference()


def test_write_inferred_tile_origin_meta_recovers_manual_grid_origin(tmp_path: Path) -> None:
    tiles_dir = tmp_path / "manual_tiles"
    tiles_dir.mkdir()
    metadata = {
        "_settings_snapshot": {
            "TILE_BUFFER_M": 50.0,
        },
        "tile_62_23.xodr": {
            "i": 62,
            "j": 23,
            "bounds": [677584.6762795, 5402767.21326809, 678084.6762795, 5403267.21326809],
        },
    }
    (tiles_dir / "tile_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    inferred = _write_inferred_tile_origin_meta(str(tiles_dir), tmp_path / "manual_tiles_origin_inferred.json")
    payload = json.loads(Path(inferred).read_text(encoding="utf-8"))

    assert inferred is not None
    assert payload["origin_x"] == 646584.6762795
    assert payload["origin_y"] == 5391267.21326809
    assert payload["tile_size_m"] == 500.0
    assert payload["buffer_m"] == 50.0


def test_auto_georef_alignment_guard_raises_on_near_zero_bbox_overlap() -> None:
    transform = {"crs_reprojection": {"bbox_iou_after_reprojection": 0.0}}
    override = {"auto_georeference_injected": True}

    with pytest.raises(RuntimeError, match="near-zero bbox overlap"):
        _raise_on_invalid_auto_georef_alignment(transform, override)


def test_attach_auto_georef_metadata_adds_full_report_fields() -> None:
    full_report = {}
    run_meta = {
        "auto_georeference_injected": True,
        "auto_georeference_warning": "Coordinates may be in local frame; verify alignment quality",
    }

    _attach_auto_georef_metadata(full_report, run_meta)

    assert full_report["auto_georeference_injected"] is True
    assert "local frame" in full_report["auto_georeference_warning"]
