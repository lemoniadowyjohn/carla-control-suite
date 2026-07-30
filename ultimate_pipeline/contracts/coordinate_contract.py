from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ultimate_pipeline.core.georef_utils import normalize_georeference, parse_georeference


REPORT_ID = "C44V01_coordinate_contract"
ALIGNMENT_ID = "C44V01_alignment_results"
DEFAULT_CONTROL_POINT_LIMIT = 20

RUN11_ALIGNMENT_RELATIVE = Path("submission/results/structural_gap_run11/alignment.json")
RUN11_XODR_RELATIVE = Path("submission/results/structural_gap_run11/auto_aligned_rigid.xodr")
AG04_RELATIVE = Path("reports/architecture_gate/AG04_coordinate_contract.json")
COORDINATE_REPORT_RELATIVE = Path("reports/visual_structural_reconciliation/C44V01_coordinate_contract.json")
ALIGNMENT_REPORT_RELATIVE = Path("reports/visual_structural_reconciliation/C44V01_alignment_results.json")
MARKDOWN_REPORT_RELATIVE = Path("reports/visual_structural_reconciliation/C44V01_coordinate_contract.md")


@dataclass(frozen=True)
class C44V01Verification:
    verdict: str
    missing_metadata: list[str]
    coordinate_contract: dict[str, Any]
    alignment_results: dict[str, Any]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report": REPORT_ID,
            "verdict": self.verdict,
            "missing_metadata": list(self.missing_metadata),
            "coordinate_contract": self.coordinate_contract,
            "alignment_results": self.alignment_results,
            "evidence": self.evidence,
        }


def build_c44v01_verification(repo_root: Path) -> C44V01Verification:
    repo_root = repo_root.resolve()
    ag04 = _load_json(repo_root / AG04_RELATIVE)
    alignment = _load_json(repo_root / RUN11_ALIGNMENT_RELATIVE)

    xodr_path = repo_root / RUN11_XODR_RELATIVE
    xodr_sha256 = _sha256(xodr_path) if xodr_path.exists() else None
    xodr_header = _parse_xodr_header(xodr_path) if xodr_path.exists() else {}
    xodr_geo_reference = xodr_header.get("geo_reference")
    xodr_offset = xodr_header.get("offset")
    control_points = _extract_control_points(xodr_path) if xodr_path.exists() else []

    bbox = ag04.get("bbox_wgs84") or {}
    source_osm = {
        "sha256": None,
        "bounds_wgs84": {
            "lat_min": bbox.get("lat_min"),
            "lat_max": bbox.get("lat_max"),
            "lon_min": bbox.get("lon_min"),
            "lon_max": bbox.get("lon_max"),
            "region": bbox.get("region", "Ingolstadt"),
        },
        "crs": "EPSG:4326" if bbox else None,
    }

    projected_map = {
        "crs_definition": xodr_geo_reference,
        "datum": _extract_proj_param(xodr_geo_reference, "+datum"),
        "units": _extract_proj_param(xodr_geo_reference, "+units") or "m" if xodr_geo_reference else None,
        "axis_order": "E/N" if xodr_geo_reference else None,
    }

    coordinate_contract = {
        "schema_version": 1,
        "source_osm": source_osm,
        "projected_map": projected_map,
        "xodr": {
            "sha256": xodr_sha256,
            "geo_reference": xodr_geo_reference,
            "header_offset": xodr_offset,
            "local_units": "metres" if xodr_geo_reference else None,
        },
        "osm2world": {
            "version": None,
            "source_osm_sha256": None,
            "projection": None,
            "origin": None,
            "units": None,
            "axes": None,
        },
        "blender": {
            "version": None,
            "import_units": None,
            "scene_units": None,
            "axes": None,
            "applied_transform": None,
        },
        "fbx": {
            "sha256": None,
            "export_version": None,
            "units": None,
            "axes": None,
            "global_transform": None,
        },
        "unreal": {
            "engine_version": "UE4.26",
            "import_scale": "centimetres",
            "axes": "left-handed X-forward Y-right Z-up",
            "map_origin": None,
        },
        "vertical": {
            "datum": None,
            "source": None,
            "offset": None,
            "confidence": "unknown",
        },
        "control_points": control_points,
        "control_point_count": len(control_points),
    }

    missing_metadata = _missing_metadata(coordinate_contract)
    verdict = "BLOCKED_MISSING_METADATA"
    if not missing_metadata:
        verdict = "CRS_CONTRACT_READY"

    return C44V01Verification(
        verdict=verdict,
        missing_metadata=missing_metadata,
        coordinate_contract=coordinate_contract,
        alignment_results=_alignment_results(alignment, xodr_sha256, xodr_geo_reference, xodr_offset),
        evidence={
            "repo_root": str(repo_root),
            "ag04_path": str(repo_root / AG04_RELATIVE),
            "alignment_path": str(repo_root / RUN11_ALIGNMENT_RELATIVE),
            "xodr_path": str(xodr_path),
        },
    )


def write_c44v01_reports(repo_root: Path) -> C44V01Verification:
    verification = build_c44v01_verification(repo_root)
    out_dir = repo_root / "reports" / "visual_structural_reconciliation"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / MARKDOWN_REPORT_RELATIVE.name).write_text(
        _render_coordinate_markdown(verification),
        encoding="utf-8",
    )
    (out_dir / COORDINATE_REPORT_RELATIVE.name).write_text(
        json.dumps(verification.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / ALIGNMENT_REPORT_RELATIVE.name).write_text(
        json.dumps(verification.alignment_results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return verification


def _alignment_results(
    alignment: dict[str, Any],
    xodr_sha256: str | None,
    xodr_geo_reference: str | None,
    xodr_offset: dict[str, Any] | None,
) -> dict[str, Any]:
    transform = alignment.get("transform") if isinstance(alignment.get("transform"), dict) else {}
    reprojection = alignment.get("crs_reprojection") if isinstance(alignment.get("crs_reprojection"), dict) else {}
    diagnostics = alignment.get("diagnostics") if isinstance(alignment.get("diagnostics"), dict) else {}
    return {
        "report": ALIGNMENT_ID,
        "source_xodr_sha256": xodr_sha256,
        "source_xodr_geo_reference": xodr_geo_reference,
        "source_xodr_header_offset": xodr_offset,
        "transform": transform,
        "crs_reprojection": reprojection,
        "diagnostics": diagnostics,
        "verdict": "BLOCKED_MISSING_METADATA",
    }


def _missing_metadata(contract: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    source_osm = contract.get("source_osm", {})
    xodr = contract.get("xodr", {})
    projected_map = contract.get("projected_map", {})
    osm2world = contract.get("osm2world", {})
    blender = contract.get("blender", {})
    fbx = contract.get("fbx", {})
    vertical = contract.get("vertical", {})

    if not source_osm.get("sha256"):
        missing.append("source_osm.sha256")
    if not projected_map.get("crs_definition"):
        missing.append("projected_map.crs_definition")
    if not xodr.get("sha256"):
        missing.append("xodr.sha256")
    if not xodr.get("geo_reference"):
        missing.append("xodr.geo_reference")
    if not osmbounds_present(source_osm):
        missing.append("source_osm.bounds_wgs84")
    if not osm2world.get("version"):
        missing.append("osm2world.version")
    if not blender.get("version"):
        missing.append("blender.version")
    if not fbx.get("sha256"):
        missing.append("fbx.sha256")
    if not vertical.get("datum"):
        missing.append("vertical.datum")
    return missing


def osmbounds_present(source_osm: dict[str, Any]) -> bool:
    bounds = source_osm.get("bounds_wgs84") or {}
    required = ("lat_min", "lat_max", "lon_min", "lon_max")
    return all(bounds.get(key) is not None for key in required)


def _parse_xodr_header(path: Path) -> dict[str, Any]:
    tree = ET.parse(path)
    root = tree.getroot()
    header = root.find("header")
    if header is None:
        return {}
    geo_el = header.find("geoReference")
    geo_reference = normalize_georeference(geo_el.text if geo_el is not None else None)
    valid, complete, normalized = parse_georeference(geo_reference)
    if valid:
        geo_reference = normalized
    offset_el = header.find("offset")
    offset = None
    if offset_el is not None:
        offset = {
            key: _maybe_float(offset_el.get(key))
            for key in ("x", "y", "z", "hdg")
        }
    if not complete:
        geo_reference = geo_reference or None
    return {"geo_reference": geo_reference, "offset": offset}


def _extract_control_points(path: Path, limit: int = DEFAULT_CONTROL_POINT_LIMIT) -> list[dict[str, Any]]:
    try:
        tree = ET.parse(path)
    except Exception:
        return []
    root = tree.getroot()
    points: list[dict[str, Any]] = []
    for geometry in root.findall(".//road/planView/geometry"):
        x = _maybe_float(geometry.get("x"))
        y = _maybe_float(geometry.get("y"))
        points.append({"x": x, "y": y, "source": "planView.geometry.start"})
    if not points:
        return []
    if len(points) <= limit:
        sampled = points
    else:
        step = max(1, len(points) // limit)
        sampled = points[::step][:limit]
    for idx, point in enumerate(sampled):
        point["index"] = idx
    return sampled


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_proj_param(text: str | None, key: str) -> str | None:
    if not text:
        return None
    for token in text.split():
        if token.startswith(f"{key}="):
            return token.split("=", 1)[1]
    return None


def _maybe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        parsed = float(value)
        if not (parsed == parsed):  # NaN check without math import
            return None
        return parsed
    except Exception:
        return None


def _render_coordinate_markdown(verification: C44V01Verification) -> str:
    contract = verification.coordinate_contract
    xodr = contract["xodr"]
    projected = contract["projected_map"]
    source_osm = contract["source_osm"]
    vertical = contract["vertical"]
    lines = [
        "# C44V01 Coordinate Contract",
        "",
        f"Verdict: `{verification.verdict}`",
        "",
        "## Parsed Contract",
        "",
        f"- Source OSM sha256: `{source_osm['sha256']}`",
        f"- Source OSM bounds: `{source_osm['bounds_wgs84']}`",
        f"- Projected CRS: `{projected['crs_definition']}`",
        f"- XODR sha256: `{xodr['sha256']}`",
        f"- XODR geoReference: `{xodr['geo_reference']}`",
        f"- XODR header offset: `{xodr['header_offset']}`",
        f"- Vertical datum: `{vertical['datum']}`",
        "",
        "## Missing Metadata",
        "",
    ]
    if verification.missing_metadata:
        lines.extend(f"- {item}" for item in verification.missing_metadata)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Alignment",
            "",
            f"- Control points sampled: {contract['control_point_count']}",
            f"- Alignment verdict: `{verification.alignment_results['verdict']}`",
        ]
    )
    return "\n".join(lines) + "\n"
