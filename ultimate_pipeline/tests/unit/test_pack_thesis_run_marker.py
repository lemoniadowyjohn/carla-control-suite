# -*- coding: utf-8 -*-
"""ultimate_pipeline/tools/pack_thesis_run.py's own completion marker.

V93 round 2 (F5): this module previously wrote a literal ``SUCCESS.txt``,
confusable with the governed pipeline SUCCESS_MARKER invariant
(signals/registry.py), even though it has no live consumers and a different
(narrower, post-hoc-audit) claim shape. Renamed to ``AUDIT_PACK_VERIFIED.txt``.

NOTE: this module (``ultimate_pipeline.tools.pack_thesis_run``) is distinct
from the unrelated top-level ``tools/pack_thesis_run.py`` already covered by
``tests/unit/test_pack_thesis_run.py`` -- they are different files with the
same basename and different purposes (see the module docstring for detail).
"""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.tools.pack_thesis_run import (
    AUDIT_PACK_VERIFIED_FILENAME,
    pack_run,
)


def test_pack_run_writes_the_renamed_marker_not_success_txt(tmp_path: Path):
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()

    # Minimal domain_gap artifact set, all present -> a clean pack.
    for name in (
        "full_report.json",
        "summary.csv",
        "reproducibility_hash.json",
        "tile_pairing_report.json",
        "domain_gap_status.json",
    ):
        (src / name).write_text("{}", encoding="utf-8")

    rc = pack_run(src, out, "domain_gap")
    assert rc == 0
    assert (out / AUDIT_PACK_VERIFIED_FILENAME).is_file()
    assert not (out / "SUCCESS.txt").exists()
    assert not (out / "FAIL.txt").exists()


def test_pack_run_with_missing_artifact_writes_fail_not_the_marker(tmp_path: Path):
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    # Only one of the five required domain_gap artifacts.
    (src / "full_report.json").write_text("{}", encoding="utf-8")

    rc = pack_run(src, out, "domain_gap")
    assert rc == 1
    assert (out / "FAIL.txt").is_file()
    assert not (out / AUDIT_PACK_VERIFIED_FILENAME).exists()
    assert not (out / "SUCCESS.txt").exists()


def test_pack_run_revokes_a_stale_marker_on_a_later_failing_run(tmp_path: Path):
    """A stale AUDIT_PACK_VERIFIED.txt from a previous clean run must not
    survive a later run against the same out_dir that now fails."""
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    for name in (
        "full_report.json",
        "summary.csv",
        "reproducibility_hash.json",
        "tile_pairing_report.json",
        "domain_gap_status.json",
    ):
        (src / name).write_text("{}", encoding="utf-8")
    assert pack_run(src, out, "domain_gap") == 0
    assert (out / AUDIT_PACK_VERIFIED_FILENAME).is_file()

    # Remove one required artifact from src and re-pack into the SAME out_dir.
    (src / "summary.csv").unlink()
    rc = pack_run(src, out, "domain_gap")
    assert rc == 1
    assert not (out / AUDIT_PACK_VERIFIED_FILENAME).exists()
