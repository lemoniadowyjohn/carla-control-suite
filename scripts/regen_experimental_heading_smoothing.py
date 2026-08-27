#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-off experimental regen: RELEASE_PROFILE=EXPERIMENTAL_UNSAFE with ONLY
ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING opted in (all other individual unsafe-mutator flags
left at their own default False), to test whether PlanViewSmoother.smooth_heading_jumps
(threshold_deg=12.0) resolves the 48-road position-continuous heading-kink defect class
found in C30 (reports/post_audit_hardening/C30_VISUAL_GEOMETRY_AUDIT_AND_HEADING_KINK_FINDING.md).

NOT run through scripts/regen_map_of_record.py's own CLI: that script's --profile argparse
choices deliberately excludes EXPERIMENTAL_UNSAFE (canonical map-of-record candidates must
never be generated under a profile that also relaxes STRICT_QUALITY_GATES/STRICT_TILE_SEMANTICS/
ALLOW_FALLBACK_MAP/ALLOW_TILE_QA_SKIP -- ultimate_pipeline/config/settings.py's own
RELEASE_PROFILES table bundles those together with EXPERIMENTAL_UNSAFE by design). This script
reuses the SAME internal functions regen_map_of_record.py itself uses (_run_pipeline,
_find_final_xodr, _rebase_to_local, _sha256_file) rather than re-implementing them, and reuses
the EXACT SAME pinned seed XODR that produced the current map of record
(campaigns/.../regen/20260819T142310Z/seed_from_osm.xodr) so the ONLY variable between this
run and the current pin is heading-only smoothing on/off -- Osm2Odr's own conversion step is
not re-run.

Deliberately does NOT call _measure_acceptance here: that call would run in THIS process,
which has UP_THESIS_STRICT=0 / UP_RELEASE_PROFILE=EXPERIMENTAL_UNSAFE set (required for the
subprocess to permit the unsafe mutation), so an acceptance check made here would silently
inherit the relaxed settings instead of giving genuine independent verification. Strict,
independent verification is done afterward via `regen_map_of_record.py --verify-only` in a
fresh process with a clean environment (see the report for the exact command run).

Output: a candidate file with an unmistakably experimental name (not the normal
map_of_record_<timestamp> pattern), so it can never be confused with a governed candidate.
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

    # This process's OWN Settings instantiation must ALSO see RELEASE_PROFILE=EXPERIMENTAL_UNSAFE
    # -- not just the subprocess _run_pipeline() launches. Settings._apply_release_profile()
    # fail-closed-checks every individual ENABLE_UNSAFE_* flag against the CURRENT profile at
    # init time (raises RuntimeError if an unsafe flag is set under a profile that forbids it,
    # e.g. the DEVELOPMENT default); leaving this process's own profile at its default while
    # only passing "EXPERIMENTAL_UNSAFE" as _run_pipeline's `profile` argument (for the
    # subprocess's env only) triggers that guard in THIS process, and the resulting exception
    # was observed to be silently swallowed by _sumo_status()'s broad except-pass, surfacing
    # only as a confusing unrelated "SUMO not found" error.
    os.environ["UP_RELEASE_PROFILE"] = "EXPERIMENTAL_UNSAFE"
    # Required for _apply_release_profile to permit ENABLE_UNSAFE_* under EXPERIMENTAL_UNSAFE
    # (ultimate_pipeline/config/settings.py: unsafe_allowed = profile==EXPERIMENTAL_UNSAFE and
    # not THESIS_STRICT; THESIS_STRICT defaults True).
    os.environ["UP_THESIS_STRICT"] = "0"
    # Master switch for the whole "unsafe planview mutations" family (release_profile.py).
    os.environ["UP_ENABLE_UNSAFE_PLANVIEW_MUTATIONS"] = "1"
    # The ONE specific feature under test. Every other individual unsafe-mutator flag
    # (short-segment-merge, small-geometry-merge, curvature-only-clamp, geometry-start-
    # recompute) is deliberately left unset -- their own default is False regardless of
    # profile, so they stay off.
    os.environ["UP_ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING"] = "1"

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
        / f"{datetime.now().strftime('%Y%m%dT%H%M%SZ')}_EXPERIMENTAL_heading_smoothing"
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

    name = f"EXPERIMENTAL_heading_smoothing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xodr"
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
