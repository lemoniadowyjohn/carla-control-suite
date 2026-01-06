# ultimate_pipeline/tests/test_pipeline_health.py
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.diagnostics.system_integrity_checker import (
    osm_integrity_ok,
    xodr_integrity_ok,
    dem_integrity_ok,
    domain_gap_ready,
)
from ultimate_pipeline.database.db_manager import Database


def test_osm_integrity():
    ok, detail = osm_integrity_ok()
    assert ok, f"OSM integrity failed: {detail}"


def test_xodr_integrity():
    ok, detail = xodr_integrity_ok()
    assert ok, f"XODR integrity failed: {detail}"


def test_dem_integrity():
    ok, detail = dem_integrity_ok()
    assert ok, f"DEM integrity failed: {detail}"


def test_domain_gap_ready():
    ok, detail = domain_gap_ready()
    assert ok, f"Domain gap not ready: {detail}"


def test_dataset_structure_auto():
    root = Path(SETTINGS.DATASET_ROOT) / SETTINGS.AUTO_DATASET_NAME
    images = root / "images"
    labels = root / "labels"

    assert images.exists(), f"Missing images dir: {images}"
    assert labels.exists(), f"Missing labels dir: {labels}"

    image_files = sorted(images.glob("*.jpg"))
    assert len(image_files) > 0, "No images found for auto dataset"

    for img in image_files[:50]:  # sample
        label = labels / (img.stem + ".txt")
        assert label.exists(), f"Missing label for {img.name}"


def test_dataset_structure_manual():
    root = Path(SETTINGS.DATASET_ROOT) / SETTINGS.MANUAL_DATASET_NAME
    if not root.exists():
        # Manual dataset may not exist yet; this is a soft expectation
        return

    images = root / "images"
    labels = root / "labels"

    assert images.exists(), f"Missing images dir: {images}"
    assert labels.exists(), f"Missing labels dir: {labels}"

    image_files = sorted(images.glob("*.jpg"))
    assert len(image_files) > 0, "No images found for manual dataset"

    for img in image_files[:50]:
        label = labels / (img.stem + ".txt")
        assert label.exists(), f"Missing label for {img.name}"


def test_db_connection_and_tables():
    db = Database()
    conn = db._get_connection()  # or an exposed method
    cur = conn.cursor()
    # Check that key tables exist
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    expected = {"dataset_entries", "perception_results"}
    missing = expected - tables
    assert not missing, f"Missing DB tables: {missing}"
