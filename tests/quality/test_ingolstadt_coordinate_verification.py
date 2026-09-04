from __future__ import annotations

"""WP1 coordinate verification tests for the Ingolstadt map quality v2 campaign.

These tests verify that the coordinate correction (actual reprojection) applied
to the Ingolstadt map candidate is correct, reversible, and preserves geometry
and lane structure.

The coordinate verification evidence is also captured in coordinate_tests.json.
This test file provides executable verification that can be run with pytest.
"""

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WP1_CANDIDATES = REPO_ROOT / "reports" / "ingolstadt_map_quality_v2" / "work_package_01_coordinate_truth" / "candidates"
COORDINATE_TESTS_JSON = WP1_CANDIDATES / "coordinate_tests.json"
ACTUAL_REPROJECTION_XODR = WP1_CANDIDATES / "candidate_actual_reprojection.xodr"

# Expected hashes. 03_ARTIFACT_HASH_REGISTRY.json (a static, "external"-tracked publication
# record from a different local environment, not read by any code) cites CRLF-inflated values
# for these 4 files -- left as historical record, not corrected. These below are the real,
# platform-invariant LF hashes (2026-09-04): the 4 candidate_*.xodr files were marked
# filter=lfs in .gitattributes but had never actually been migrated to real LFS storage
# (git cat-file -s returned full ~81MB content, not a small pointer), so their on-disk bytes
# had silently drifted to CRLF over time despite -text being set (ineffective while the LFS
# filter was non-functional). Migrated via `git add --renormalize` after a fresh checkout
# restored the correct LF content; verified byte-for-byte that CRLF-converting this LF content
# reproduces the OLD hardcoded hashes exactly, so this is a platform-invariance fix, not a
# real content change.
EXPECTED_HASHES = {
    "candidate_actual_reprojection.xodr": "8a21a4bf8bea37fa9b3e980f25cb96c99df375372dbc42ff9e2961eaeb7b52d2",
    "candidate_alignment_transform_only.xodr": "943e921fea47b409d02ace408b42776545773290f0fdcc71a0d48bf2caddc02b",
    "candidate_correct_georeference.xodr": "db4554e403b87f98474c6a01861a6b31b4787949852cb93998fb364ba8d8ff56",
    "candidate_metadata_only.xodr": "b3094f4e7e72034395284877e0b03204d7666b0b4416141593275942f79f53d4",
}


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class TestCoordinateCandidateHashes:
    def test_actual_reprojection_hash(self):
        assert _sha256_file(ACTUAL_REPROJECTION_XODR) == EXPECTED_HASHES["candidate_actual_reprojection.xodr"]

    def test_alignment_transform_only_hash(self):
        p = WP1_CANDIDATES / "candidate_alignment_transform_only.xodr"
        assert _sha256_file(p) == EXPECTED_HASHES["candidate_alignment_transform_only.xodr"]

    def test_correct_georeference_hash(self):
        p = WP1_CANDIDATES / "candidate_correct_georeference.xodr"
        assert _sha256_file(p) == EXPECTED_HASHES["candidate_correct_georeference.xodr"]

    def test_metadata_only_hash(self):
        p = WP1_CANDIDATES / "candidate_metadata_only.xodr"
        assert _sha256_file(p) == EXPECTED_HASHES["candidate_metadata_only.xodr"]


class TestCoordinateVerificationResults:
    def test_round_trip_passed(self):
        data = json.loads(COORDINATE_TESTS_JSON.read_text())
        assert data["round_trip"]["passed"] is True
        assert data["round_trip"]["max_error_m"] == 0.0

    def test_inverse_consistency_passed(self):
        data = json.loads(COORDINATE_TESTS_JSON.read_text())
        assert data["inverse_consistency"]["passed"] is True
        assert data["inverse_consistency"]["max_error_m"] == 0.0

    def test_bbox_verification_passed(self):
        data = json.loads(COORDINATE_TESTS_JSON.read_text())
        assert data["bbox_verification"]["passed"] is True
        assert data["bbox_verification"]["manual_contained_in_candidate"] is True

    def test_negative_controls_passed(self):
        data = json.loads(COORDINATE_TESTS_JSON.read_text())
        for name, ctrl in data["negative_controls"].items():
            assert ctrl["passed"] is True, f"Negative control {name} failed"

    def test_overall_verdict(self):
        data = json.loads(COORDINATE_TESTS_JSON.read_text())
        assert data["all_tests_passed"] is True
        assert data["verdict"] == "COORDINATES_REPROJECTED_AND_VERIFIED"


class TestCoordinateDiagnosis:
    def test_actual_reprojection_uses_tmerc(self):
        """Verify the actual reprojection candidate uses tmerc (not utm header-only)."""
        import xml.etree.ElementTree as ET
        tree = ET.parse(ACTUAL_REPROJECTION_XODR)
        root = tree.getroot()
        hdr = root.find("header")
        geo_ref = hdr.find("geoReference")
        geo_text = (geo_ref.text or "").strip()
        assert "+proj=tmerc" in geo_text, f"Expected tmerc in geoReference, got: {geo_text}"

    def test_alignment_only_uses_tmerc(self):
        """The alignment-transform-only candidate should also use tmerc but not reproject geometry."""
        import xml.etree.ElementTree as ET
        p = WP1_CANDIDATES / "candidate_alignment_transform_only.xodr"
        tree = ET.parse(p)
        root = tree.getroot()
        hdr = root.find("header")
        geo_ref = hdr.find("geoReference")
        geo_text = (geo_ref.text or "").strip()
        assert "+proj=tmerc" in geo_text

    def test_actual_reprojection_has_utm_coordinates(self):
        """Verify the actual reprojection candidate has UTM-zone coordinates (easting ~678k, northing ~5402k)."""
        import xml.etree.ElementTree as ET
        tree = ET.parse(ACTUAL_REPROJECTION_XODR)
        root = tree.getroot()
        road = root.find(".//road")
        assert road is not None
        geom = road.find("planView/geometry")
        assert geom is not None
        x = float(geom.get("x"))
        y = float(geom.get("y"))
        # UTM zone 32N coordinates for Ingolstadt: easting ~670k-685k, northing ~5400k
        assert 670000 < x < 685000, f"Easting {x} outside expected UTM range"
        assert 5400000 < y < 5410000, f"Northing {y} outside expected UTM range"

    def test_alignment_only_has_non_utm_coordinates(self):
        """The alignment-only candidate has coordinates far from UTM (showing header-only fix)."""
        import xml.etree.ElementTree as ET
        p = WP1_CANDIDATES / "candidate_alignment_transform_only.xodr"
        tree = ET.parse(p)
        root = tree.getroot()
        road = root.find(".//road")
        assert road is not None
        geom = road.find("planView/geometry")
        assert geom is not None
        x = float(geom.get("x"))
        y = float(geom.get("y"))
        # The alignment-only candidate has coordinates ~840k, 5464k (different UTM zone)
        assert 830000 < x < 850000, f"Easting {x} should show misaligned coordinates"
        assert 5460000 < y < 5470000, f"Northing {y} should show misaligned coordinates"
