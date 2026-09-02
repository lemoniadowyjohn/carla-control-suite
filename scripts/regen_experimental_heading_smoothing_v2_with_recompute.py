#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-off experimental regen, v2 (WS1.3, map-quality hardening plan, 2026-09-02).

Follow-up to scripts/regen_experimental_heading_smoothing.py, whose 2026-08-27
run (campaigns/.../candidate/EXPERIMENTAL_heading_smoothing_20260827_142533.xodr)
was re-verified this session and found UNSAFE: check_planview_internal_seams
showed num_heading_only_discontinuities going from 82 (baseline pin) to 1334,
and num_seams (real position gaps) going from 0 to 6024.

Root cause traced to PlanViewSmoother.smooth_heading_jumps
(ultimate_pipeline/geometry/planview_smoother.py): it mutates a geometry's
`hdg` attribute in place WITHOUT recomputing that geometry's or any
downstream geometry's `x`/`y` start position. Since OpenDRIVE <geometry>
elements each declare their own absolute x/y/hdg (not derived from the
previous element), changing only hdg silently displaces where the geometry
actually ends up walking from -- corrupting continuity for every geometry
after it in the same road, unless something re-chains positions afterward.

stage_06_links.py already has exactly that re-chaining step
(PlanViewSmoother.recompute_geometry_starts, wired behind its OWN
independent unsafe flag ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE) -- but v1's
docstring explicitly left it OFF, deliberately, to isolate "the ONE specific
feature under test". That isolation was the methodological gap: heading
smoothing structurally REQUIRES the recompute step to be safe; they are not
independent features in practice, only independently *flagged*.

This v2 run tests the hypothesis directly: same pinned seed, same
EXPERIMENTAL_UNSAFE profile, but with BOTH
ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING=1 AND
ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE=1. If that combination is what
resolves the 82 heading-only-discontinuity findings WITHOUT introducing new
position seams, the earlier "too risky" caution was about an incomplete
mutation, not the underlying idea. If it still isn't clean, that's real
signal the underlying fix needs more work regardless of flag combination.

Reuses the exact same pinned seed XODR as v1 and the map-of-record pin, so
the only variable between this run and the current governed pin is these
two flags. Same governance as v1: NOT run through regen_map_of_record.py's
own CLI (EXPERIMENTAL_UNSAFE is deliberately excluded from --profile
choices); emits an unmistakably-experimental candidate name.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

EXISTING_SEED = (
    REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "regen"
    / "20260819T142310Z" / "seed_from_osm.xodr"
)


def main() -> int:
    if not EXISTING_SEED.is_file():
        print(f"ERROR: expected existing seed not found: {EXISTING_SEED}", file=sys.stderr)
        return 2

    os.environ["UP_RELEASE_PROFILE"] = "EXPERIMENTAL_UNSAFE"
    os.environ["UP_THESIS_STRICT"] = "0"
    os.environ["UP_ENABLE_UNSAFE_PLANVIEW_MUTATIONS"] = "1"
    os.environ["UP_ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING"] = "1"
    # The ONE change from v1: also recompute downstream geometry start poses
    # after heading smoothing mutates headings, so consecutive geometries
    # stay chained instead of leaving stale x/y behind a moved heading.
    os.environ["UP_ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE"] = "1"

    from scripts.regen_map_of_record import (
        _run_pipeline,
        _find_final_xodr,
        _rebase_to_local,
        _sha256_file,
        _write_json,
        _check_sumo,
        _git_dirty,
        CANDIDATE_DIR,
    )

    dirty = _git_dirty()
    if dirty:
        print(f"[git] NOTE: worktree has {len(dirty)} uncommitted changes (informational only "
              f"-- this is an experimental, non-canonical run, not gated on a clean worktree).")

    _check_sumo()

    out_dir = (
        REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "regen"
        / f"{datetime.now().strftime('%Y%m%dT%H%M%SZ')}_EXPERIMENTAL_heading_smoothing_v2_recompute"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    seed_copy = out_dir / "seed_from_osm.xodr"
    shutil.copy2(EXISTING_SEED, seed_copy)
    print(f"[seed] reusing existing pinned seed (not re-converting OSM): {EXISTING_SEED}")
    print(f"[seed] sha256={_sha256_file(seed_copy)}")

    _run_pipeline(seed_copy, out_dir / "pipeline_out", "EXPERIMENTAL_UNSAFE", disable_carla=True)
    final = _find_final_xodr(out_dir / "pipeline_out")
    print(f"[final] {final} sha256={_sha256_file(final)}")

    rebased = out_dir / "final_rebased.xodr"
    rebase_report = _rebase_to_local(final, rebased)
    measured = rebased if rebase_report.get("shifted") else final
    _write_json(out_dir / "rebase_report.json", rebase_report)
    if rebase_report.get("shifted"):
        print(f"[frame] re-based global -> local: dx={rebase_report['dx']} dy={rebase_report['dy']}")
    else:
        print(f"[frame] already local ({rebase_report.get('reason')}); no re-base needed")

    name = f"EXPERIMENTAL_heading_smoothing_v2_recompute_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xodr"
    target = CANDIDATE_DIR / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(measured, target)
    print(f"[emit] EXPERIMENTAL candidate (NOT a governed map-of-record candidate) -> {target}")
    print(f"[emit] sha256={_sha256_file(target)}")
    print(f"[emit] out_dir={out_dir}")
    print()
    print("Next step (run separately, clean env, for genuine independent verification):")
    print(f"  python scripts/regen_map_of_record.py --verify-only {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
