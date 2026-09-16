#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared artifact locator helpers (OSM/XODR/run dir).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple


def output_root_from_settings() -> Path:
    try:
        from ultimate_pipeline.config.settings import SETTINGS

        return Path(getattr(SETTINGS, "PIPELINE_OUTPUT_ROOT", "ultimate_pipeline_out"))
    except Exception:
        return Path("ultimate_pipeline_out")


def resolve_run_dir(
    run_dir_arg: Optional[str],
    *,
    env_var: str = "UP_HEALTH_RUN_DIR",
    output_root: Optional[Path] = None,
) -> Path:
    env = os.environ.get(env_var, "").strip()
    if env:
        return Path(env)
    if run_dir_arg:
        return Path(run_dir_arg)
    root = output_root or output_root_from_settings()
    # FIX: Do not fallback to newest by mtime (stale selection). Require explicit run_dir_arg or env var.
    # If neither provided, return Path(".") but caller must verify existence and provenance explicitly
    # Previously: candidates.sort by mtime and return newest - now removed to enforce explicit identity
    return Path(".")


def find_osm_artifact(run_dir: Path) -> Tuple[Optional[Path], str]:
    candidates = [
        run_dir / "osm" / "extract.osm",
        run_dir / "osm" / "extract.osm.pbf",
        run_dir / "osm_extract.osm",
        run_dir / "osm_extract.osm.pbf",
        run_dir / "artifacts" / "osm_extract.osm",
        run_dir / "artifacts" / "osm_extract.osm.pbf",
    ]
    for p in candidates:
        if p.exists():
            return p, "run_dir"
    osm_files = sorted(run_dir.rglob("*.osm")) + sorted(run_dir.rglob("*.osm.pbf"))
    if osm_files:
        return osm_files[0], "run_dir_glob"
    return None, "not_found"


def _repaired_sibling_exists(path: Path) -> bool:
    """True if ``path`` (a ``08_final*_semantic.xodr`` file) has a same-run
    ``*_laneSectionFixed*.xodr`` sibling on disk.

    stage_08_integrity.py writes 08_final_<ts>_semantic.xodr TWICE for a
    single run: once as a plain copy of the pre-repair file, and again
    ("AUTHORITATIVE MAP SWITCH") after repair_and_assert_lane_section_successors()
    produces 08_final_<ts>_laneSectionFixed.xodr. Both copies share the exact
    same filename (the run's <ts> is fixed at run start and reused), so within
    a single well-formed run there is only ever one 08_final*_semantic.xodr
    path and its mtime alone already reflects "was it (re-)written after
    repair". This sibling check is a second, independent, content-shape
    signal for the *same* property -- it does not depend on mtime at all --
    so a semantic file whose run never reached the repair step (no
    laneSectionFixed sibling) never outranks one that did, even if its mtime
    was bumped afterward by an unrelated copy/touch/restore operation.
    """
    name = path.name
    if "_semantic" not in name:
        return False
    prefix = name.split("_semantic", 1)[0]
    return any(path.parent.glob(f"{prefix}*_laneSectionFixed*.xodr"))


def _newest_final_xodr(run_dir: Path) -> Optional[Path]:
    """Pick the authoritative final XODR among any 08_final*.xodr variants.

    A real pipeline run writes several 08_final*.xodr files in sequence:
    the plain 08_final_<ts>.xodr (pre-repair), then 08_final_<ts>_semantic.xodr
    (a copy), then 08_final_<ts>_laneSectionFixed.xodr (the repaired map --
    "AUTHORITATIVE MAP SWITCH" per stage_08_integrity.py), and finally
    08_final_<ts>_semantic.xodr is re-copied from the repaired file. Naive
    lexicographic sorting (plain sorted(glob(...))) picks the plain
    pre-repair file first ("." < "_" in ASCII) -- the exact file the
    laneSection-successor repair exists to supersede, since loading it can
    trip CARLA's MapBuilder.cpp asserts. This is not hypothetical: it is
    directly reproduced and regression-tested in
    ultimate_pipeline/tests/unit/test_artifact_locator_final_xodr.py, and the
    same mtime-newest convention is independently used (and tested) in three
    other places in this codebase: export_thesis_tables.py::_latest_final_xodr,
    run_determinism_audit.py::_find_final_xodr, and
    scripts/regen_map_of_record.py::_find_final_xodr.

    Within each candidate pool (semantic, then the any-suffix fallback) we
    first prefer files that are structurally verified to be post-repair (see
    _repaired_sibling_exists / the "laneSectionFixed" name check below) --
    this does not depend on trusting filesystem mtime at all, so a stale or
    adversarially-touched file cannot win purely by having a newer mtime
    without also having the repair artifacts to back it up. mtime-newest is
    then used only as the tie-breaker among files that are equally
    legitimate by that structural check (or when no candidate has repair
    evidence at all, e.g. ENABLE_LANE_SECTION_REPAIR=0 runs) -- matching the
    established, tested convention above.
    """
    semantic = list(run_dir.glob("08_final*_semantic.xodr"))
    if semantic:
        repaired = [p for p in semantic if _repaired_sibling_exists(p)]
        pool = repaired or semantic
        pool.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return pool[0]
    any_final = list(run_dir.glob("08_final*.xodr"))
    if not any_final:
        return None
    repaired_any = [p for p in any_final if "laneSectionFixed" in p.name]
    pool = repaired_any or any_final
    pool.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return pool[0]


def find_xodr_artifact(run_dir: Path) -> Tuple[Optional[Path], str]:
    tile = run_dir / "tiles" / "tile_0_0.xodr"
    if tile.exists():
        return tile, "run_dir"
    final = _newest_final_xodr(run_dir)
    if final is not None:
        return final, "run_dir"
    candidates = sorted(run_dir.rglob("*.xodr"))
    for p in candidates:
        if p.exists():
            return p, "run_dir"
    return None, "not_found"


def find_final_xodr(run_dir: Path) -> Tuple[Optional[Path], str]:
    final = _newest_final_xodr(run_dir)
    if final is not None:
        return final, "08_final"
    return find_xodr_artifact(run_dir)
