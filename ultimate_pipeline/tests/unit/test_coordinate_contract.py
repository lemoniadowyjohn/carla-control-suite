from __future__ import annotations

import hashlib
from pathlib import Path

from ultimate_pipeline.contracts.coordinate_contract import build_c44v01_verification


REPO_ROOT = Path(__file__).resolve().parents[3]
RUN11_XODR = REPO_ROOT / "submission" / "results" / "structural_gap_run11" / "auto_aligned_rigid.xodr"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_c44v01_verifier_blocks_on_missing_metadata() -> None:
    verification = build_c44v01_verification(REPO_ROOT)

    assert verification.verdict == "BLOCKED_MISSING_METADATA"
    assert "source_osm.sha256" in verification.missing_metadata
    assert "fbx.sha256" in verification.missing_metadata
    assert verification.coordinate_contract["projected_map"]["crs_definition"]


def test_c44v01_verifier_parses_run11_xodr_contract() -> None:
    verification = build_c44v01_verification(REPO_ROOT)

    assert verification.coordinate_contract["xodr"]["sha256"] == _sha256(RUN11_XODR)
    assert verification.coordinate_contract["xodr"]["geo_reference"].startswith("+proj=tmerc")
    assert verification.coordinate_contract["xodr"]["header_offset"]["x"] == -838640.8
    assert 1 <= verification.coordinate_contract["control_point_count"] <= 20


def test_c44v01_alignment_results_preserve_rigid_scale_lock() -> None:
    verification = build_c44v01_verification(REPO_ROOT)
    alignment = verification.alignment_results

    assert alignment["transform"]["scale"] == 1.0
    assert alignment["crs_reprojection"]["applied"] is True
    assert alignment["diagnostics"]["rigid_only"] is True
    assert alignment["verdict"] == "BLOCKED_MISSING_METADATA"
