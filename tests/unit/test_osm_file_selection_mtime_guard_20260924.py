"""Coordinate/OSM consistency audit (20260924).

``ultimate_pipeline/tools/osm_stats.py::_find_osm_in_run`` and
``ultimate_pipeline/tools/check_osm_to_carla_determinism.py::_find_source_osm_file``
both fell back to::

    osm_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return osm_files[0]

across *every* ``*.osm``/``*.osm.pbf`` found anywhere under a run directory
(``run_dir.rglob("*.osm")``) whenever none of the hardcoded conventional
paths existed -- an unguarded mtime-as-authority pattern, the exact class of
bug already fixed for XODR candidate selection elsewhere in this repo
(GAP-012, GAP-023), but neither file was covered by
``ultimate_pipeline/tests/unit/test_mtime_audit.py``'s protected-module list.

Fix: prefer the candidate closest to ``run_dir`` (fewest path parts) --
a nested probe/tile artifact is by construction deeper than a top-level
extract -- and use mtime only as a tiebreaker among equally-shallow
candidates. Both functions also now report whether the result was an exact
conventional-path match or an ambiguous glob+mtime fallback (more than one
equally-shallow candidate), so a downstream report reader is not misled into
treating a guess with the same confidence as a verified path.

These tests reproduce the bug directly: build a run directory with a deep,
newer-mtime decoy ``.osm`` file and a shallow, older-mtime real one, and
confirm the shallow file wins (pre-fix, the decoy would have won on raw
mtime).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ultimate_pipeline.tools.osm_stats import _find_osm_in_run
from ultimate_pipeline.tools.check_osm_to_carla_determinism import (
    _find_source_osm_file,
)

_OSM_MIN = (
    '<?xml version="1.0"?><osm version="0.6">'
    '<node id="1" lat="48.75" lon="11.43"/></osm>'
)


def _touch_older(path: Path, text: str, *, seconds_ago: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    ts = time.time() - seconds_ago
    os.utime(path, (ts, ts))


def test_osm_stats_prefers_shallow_over_newer_deep_decoy(tmp_path: Path) -> None:
    run_dir = tmp_path / "run1"
    real = run_dir / "top_level_extract.osm"
    decoy = run_dir / "artifacts" / "tile_probe" / "nested" / "decoy.osm"

    # decoy is NEWER (smaller seconds_ago) but deeply nested; real is OLDER
    # but shallow. Pre-fix, raw mtime sort would pick the decoy.
    _touch_older(real, _OSM_MIN, seconds_ago=100)
    _touch_older(decoy, _OSM_MIN, seconds_ago=1)

    chosen, reason = _find_osm_in_run(run_dir)
    assert chosen == real, (
        f"expected the shallow top-level extract to win over a newer, "
        f"deeply-nested decoy; got {chosen}"
    )
    assert "ambiguous" not in reason  # only one file at the shallowest depth


def test_osm_stats_flags_ambiguity_when_two_files_tie_on_depth(tmp_path: Path) -> None:
    run_dir = tmp_path / "run2"
    a = run_dir / "extract_a.osm"
    b = run_dir / "extract_b.osm"
    _touch_older(a, _OSM_MIN, seconds_ago=50)
    _touch_older(b, _OSM_MIN, seconds_ago=10)

    chosen, reason = _find_osm_in_run(run_dir)
    # Both at the same depth -> mtime tiebreak picks the newer one (b), but
    # the result must be honestly flagged as ambiguous (more than one
    # equally-plausible candidate existed).
    assert chosen == b
    assert "ambiguous" in reason


def test_check_osm_determinism_prefers_shallow_over_newer_deep_decoy(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run3"
    real = run_dir / "top_level_extract.osm"
    decoy = run_dir / "artifacts" / "tile_probe" / "nested" / "decoy.osm"

    _touch_older(real, _OSM_MIN, seconds_ago=100)
    _touch_older(decoy, _OSM_MIN, seconds_ago=1)

    chosen, ambiguous = _find_source_osm_file(run_dir, hint="")
    assert chosen == real, (
        f"expected the shallow top-level extract to win over a newer, "
        f"deeply-nested decoy; got {chosen}"
    )
    assert ambiguous is False


def test_check_osm_determinism_flags_ambiguity_when_two_files_tie_on_depth(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run4"
    a = run_dir / "extract_a.osm"
    b = run_dir / "extract_b.osm"
    _touch_older(a, _OSM_MIN, seconds_ago=50)
    _touch_older(b, _OSM_MIN, seconds_ago=10)

    chosen, ambiguous = _find_source_osm_file(run_dir, hint="")
    assert chosen == b
    assert ambiguous is True


def test_check_osm_determinism_exact_conventional_path_is_never_ambiguous(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run5"
    conventional = run_dir / "osm" / "extract.osm"
    decoy = run_dir / "artifacts" / "tile_probe" / "decoy.osm"
    _touch_older(conventional, _OSM_MIN, seconds_ago=100)
    _touch_older(decoy, _OSM_MIN, seconds_ago=1)

    chosen, ambiguous = _find_source_osm_file(run_dir, hint="")
    assert chosen == conventional
    assert ambiguous is False
