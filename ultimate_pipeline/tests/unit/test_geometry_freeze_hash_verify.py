# MainPipeline._verify_geometry_freeze_hash() previously hashed the SAME file
# whose header carried the embedded geometryFreezeHash attribute. That hash
# was computed by stage_05_geometry.py from cont_out's raw disk bytes (a
# DIFFERENT, pre-freeze file) *before* the geometryFreezeHash/geometryFrozen
# attributes existed, then embedded into frozen_before_elev's header and that
# file was saved. Re-hashing frozen_before_elev's own bytes at verify time can
# therefore never match the embedded value: the file's serialized content
# necessarily differs (it now contains the two new header attributes), so the
# comparison was guaranteed to report MISMATCH on every real run regardless of
# whether the geometry actually drifted, and the sole call site
# (stage_05_geometry.py::_step5_dem_and_geometry) discards the return value
# entirely -- so it was inert as both a diagnostic and a gate.
#
# Fix: stage_05_geometry.py now hashes frozen_before_elev's own serialized
# bytes (via a first save before the hash attribute is set, then a second
# save after), and _verify_geometry_freeze_hash reproduces that exact
# procedure by stripping geometryFreezeHash back out and re-serializing
# through save_xodr (not a raw tree.write to a buffer -- ElementTree applies
# platform newline translation when writing to a path but not a file-like
# buffer, so the two serialization paths must match) before re-hashing.
#
# This freeze-hash check is a secondary, diagnostic-only mechanism embedded in
# the XODR header itself; the pipeline's real geometry-freeze safety net is
# the semantically-meaningful opendrive_geometry.freeze module (see
# tests/opendrive_geometry/test_geometry_freeze.py), which is unaffected by
# this bug and was already working correctly.
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.core.odr_io import load_xodr, save_xodr
from ultimate_pipeline.main_pipeline import MainPipeline


def _write_frozen_file(cont_out: str, frozen_out: str) -> None:
    """Mirrors stage_05_geometry.py's freeze block exactly."""
    import hashlib

    tree, root = load_xodr(cont_out)
    header = root.find("header")
    if header is None:
        header = ET.SubElement(root, "header")
    header.set("geometryFrozen", "true")

    save_xodr(tree, frozen_out)
    freeze_hash = hashlib.sha256()
    with open(frozen_out, "rb") as f:
        freeze_hash.update(f.read())
    freeze_hex = freeze_hash.hexdigest()
    header.set("geometryFreezeHash", freeze_hex)
    save_xodr(tree, frozen_out)


@pytest.fixture
def pipeline():
    return MainPipeline.__new__(MainPipeline)


def _write_source(path: str, road_id: str = "1") -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "<?xml version='1.0'?><OpenDRIVE>"
            "<header revMajor='1' revMinor='4'/>"
            f"<road id='{road_id}' length='10'/>"
            "</OpenDRIVE>"
        )


def test_verify_matches_freshly_frozen_file(pipeline, tmp_path):
    cont_out = str(tmp_path / "cont.xodr")
    frozen_out = str(tmp_path / "frozen.xodr")
    _write_source(cont_out)
    _write_frozen_file(cont_out, frozen_out)

    result = pipeline._verify_geometry_freeze_hash(frozen_out)

    assert result is not None
    assert len(result) == 64  # sha256 hex digest


def test_verify_detects_real_post_freeze_drift(pipeline, tmp_path):
    cont_out = str(tmp_path / "cont.xodr")
    frozen_out = str(tmp_path / "frozen.xodr")
    _write_source(cont_out)
    _write_frozen_file(cont_out, frozen_out)

    # Simulate a downstream mutation to the frozen file's geometry-bearing
    # content after the freeze checkpoint.
    tree, root = load_xodr(frozen_out)
    road = root.find("road")
    road.set("length", "999")
    save_xodr(tree, frozen_out)

    assert pipeline._verify_geometry_freeze_hash(frozen_out) is None


def test_verify_missing_header_returns_none(pipeline, tmp_path):
    p = tmp_path / "no_header.xodr"
    p.write_text("<?xml version='1.0'?><OpenDRIVE></OpenDRIVE>", encoding="utf-8")

    assert pipeline._verify_geometry_freeze_hash(str(p)) is None


def test_verify_missing_hash_attribute_returns_none(pipeline, tmp_path):
    p = tmp_path / "no_hash_attr.xodr"
    p.write_text(
        "<?xml version='1.0'?><OpenDRIVE><header geometryFrozen='true'/></OpenDRIVE>",
        encoding="utf-8",
    )

    assert pipeline._verify_geometry_freeze_hash(str(p)) is None


def test_verify_unparseable_file_returns_none(pipeline, tmp_path):
    p = tmp_path / "garbage.xodr"
    p.write_text("not xml at all", encoding="utf-8")

    assert pipeline._verify_geometry_freeze_hash(str(p)) is None
