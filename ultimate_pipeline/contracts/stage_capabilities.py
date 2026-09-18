# ultimate_pipeline/contracts/stage_capabilities.py
# -*- coding: utf-8 -*-

"""
Stage capability contract (P0-K/P0-L follow-on, additive-only slice).

Background
----------
The 2026-09-15 comprehensive gap audit
(reports/production_readiness/20260915T203000Z_COMPREHENSIVE_GAP_AUDIT/
PIPELINE_DEPENDENCY_AUDIT.json, packets P0-K/P0-L) found:

    "Position-dependent semantics (signals, crosswalks, signs) are written
    before structural geometry freeze. No explicit STRUCTURAL_FREEZE gate
    exists. Stages lack capability prerequisites."

Re-verified against the current code (2026-09-17, 69 commits after the
audit): the finding still reproduces. Concretely:

- ``MainPipeline.run()`` calls ``self._step4_enrichment(...)`` (marked
  ``_mark_stage("enrichment")``) BEFORE ``self._step5_geometry_elevation_
  continuity(...)`` (marked ``_mark_stage("geometry")``) --
  ultimate_pipeline/main_pipeline.py lines 2170-2175.
- Stage 4 (ultimate_pipeline/pipeline_stages/stage_04_enrichment.py)
  inserts traffic lights with lane references (line 180), OSM-matched
  regulatory signs / turn markings (lines 285-304), and geometrically
  projected crosswalks (lines 364-389) -- all position-dependent semantic
  placements keyed to road s/t coordinates.
- The horizontal-geometry freeze (header ``geometryFrozen="true"``) is not
  set until stage_05_geometry.py line 261, i.e. one full stage *after*
  those placements already happened.
- Stage 4 itself already documents the general hazard for a *different*
  artifact it explicitly defers for this exact reason (see stage_04_
  enrichment.py lines 429-438, "OSM2World cannot run here: Stage 04 is
  explicitly pre-lane and later geometry stages can still change the
  structural map" / "OSM2World deferred until final structural freeze")
  -- but crosswalks/signals/signs are NOT deferred; they mutate the XODR
  immediately in Stage 4.
- Further downstream, map hygiene (ultimate_pipeline/pipeline_stages/
  stage_08_hygiene.py, "08H") runs island quarantine -- which can *delete
  entire roads* (see scripts/regen_map_of_record.py's _find_final_xodr()
  docstring: a real regen's 08h1_island_quarantined.xodr had 30 fewer
  roads than its pre-hygiene input) -- plus degenerate-lane and z-seam
  repair, all well after Stage 4's semantic placements.
- ``MainPipeline._assert_geometry_frozen()`` (main_pipeline.py line 2831)
  IS already called from stage_07_lanes.py:73 and stage_08_integrity.py:
  513 -- i.e. an ad hoc version of exactly this prerequisite check already
  exists for lanes/final-integrity, but was never extended to Stage 4's
  semantic placements.

This module does NOT perform the full P0-L "gradual migration with frozen
gates" reorder (that is an explicitly separate, larger follow-on packet).
It adds only:

1. A small, generic capability-contract data model (``StageCapabilitySpec``)
   any stage can declare ``requires``/``provides`` capabilities against.
2. A fail-closed validator (``validate_stage_sequence`` /
   ``assert_stage_sequence_valid``) that checks a declared stage order
   against those capabilities.
3. ``CURRENT_PIPELINE_STAGE_SEQUENCE``: an honest, traceable mirror of
   ``MainPipeline.run()``'s real ``_mark_stage(...)`` call order, with
   capabilities declared to match what is TRUE of the code today (not
   aspirational). This sequence validates cleanly today -- it does not
   yet declare that Stage 4 *requires* frozen/hygiene-complete geometry,
   because it genuinely does not check for that today, and turning that
   requirement on without also doing the P0-L reorder would hard-fail
   every pipeline run. See ``ultimate_pipeline/tests/unit/
   test_stage_capability_contract.py`` for a test that patches Stage 4's
   declared requirements to what the audit finding says they SHOULD be,
   and proves ``validate_stage_sequence`` catches the real misordering
   against this same real stage order -- i.e. the mechanism this module
   adds would have caught the audit's finding, and will catch it (or any
   future regression like it) for any stage that opts in.

Whether/when to flip Stage 4's declared ``requires`` to the honest
aspirational set (and thus make this a live, enforced gate) is the P0-L
reorder work, intentionally out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, List, Sequence

# ---------------------------------------------------------------------------
# Capability vocabulary (additive; extend as more stages adopt the contract)
# ---------------------------------------------------------------------------

#: Set once horizontal (s/t-relevant) road geometry is fixed and will not be
#: further mutated except by an explicit, declared repair stage. Mirrors the
#: existing ad hoc ``header.get("geometryFrozen") == "true"`` runtime check
#: in ``MainPipeline._assert_geometry_frozen``.
GEOMETRY_FROZEN = "geometry_frozen"

#: Set once lane generation (stage 7) has produced the lane structure that
#: position-dependent semantics (which lane a sign/signal refers to) depend
#: on.
LANES_GENERATED = "lanes_generated"

#: Set once map hygiene (stage 08H: island quarantine, degenerate-lane
#: floor-repair, z-seam repair) has completed. Island quarantine can delete
#: whole roads, so anything keyed to a road id/s-coordinate placed before
#: this point may reference geometry that no longer exists or has shifted.
HYGIENE_COMPLETE = "hygiene_complete"

#: Provided (not required) by stages that write position-dependent semantic
#: content (signals, crosswalks, regulatory signs) keyed to road s/t
#: coordinates. Exists so downstream consumers/audits can query "did this
#: sequence ever place position-dependent semantics" without needing to
#: know the specific stage name.
SEMANTIC_POSITIONS_PLACED = "semantic_positions_placed"


@dataclass(frozen=True)
class StageCapabilitySpec:
    """One pipeline stage's declared capability contract.

    ``name`` should match (or closely mirror) the ``_mark_stage(...)``
    label used in ``MainPipeline.run()`` so a real-sequence audit and this
    declared contract stay traceable to each other.

    ``requires``: capabilities that MUST already have been provided by a
    strictly earlier stage in the sequence for this stage to be safe to run.

    ``provides``: capabilities this stage guarantees hold true for every
    stage that runs after it (until/unless something explicitly says
    otherwise -- this model has no "revokes" primitive; a stage that
    invalidates an earlier guarantee should not re-declare that capability
    as provided by anything after it).
    """

    name: str
    requires: FrozenSet[str] = field(default_factory=frozenset)
    provides: FrozenSet[str] = field(default_factory=frozenset)


class StageDependencyViolation(RuntimeError):
    """Raised when a declared stage sequence violates its own capability contract."""


@dataclass(frozen=True)
class StageDependencyReport:
    ok: bool
    violations: List[str]


def validate_stage_sequence(
    stages: Sequence[StageCapabilitySpec],
) -> StageDependencyReport:
    """Fail-closed check of a declared stage order against its own contract.

    For every stage, in order, its ``requires`` must already be satisfied
    by the union of ``provides`` from all STRICTLY EARLIER stages in the
    sequence. A stage's own ``provides`` only become visible to stages
    after it (a stage cannot satisfy its own requirement, and ordering
    ties are not a substitute for an explicit prerequisite).

    Returns a report rather than raising, so a caller can decide how to
    surface accumulated violations (see ``assert_stage_sequence_valid``
    for the fail-closed convenience wrapper).
    """
    provided_so_far: set[str] = set()
    violations: List[str] = []

    for index, stage in enumerate(stages):
        missing = set(stage.requires) - provided_so_far
        if missing:
            violations.append(
                f"stage[{index}] {stage.name!r} requires "
                f"{sorted(missing)} but no earlier stage in the declared "
                "sequence provides it"
            )
        provided_so_far |= set(stage.provides)

    return StageDependencyReport(ok=not violations, violations=violations)


def assert_stage_sequence_valid(
    stages: Sequence[StageCapabilitySpec],
) -> StageDependencyReport:
    """Fail-closed wrapper: raise ``StageDependencyViolation`` on any violation."""
    report = validate_stage_sequence(stages)
    if not report.ok:
        raise StageDependencyViolation(
            "Stage capability contract violated by the declared stage "
            "sequence:\n  - " + "\n  - ".join(report.violations)
        )
    return report


# ---------------------------------------------------------------------------
# Current, real MainPipeline.run() stage order (honest, non-aspirational).
# ---------------------------------------------------------------------------
#
# Names below are exactly the ``_mark_stage(...)`` labels passed in
# ultimate_pipeline/main_pipeline.py's ``run()`` method, in call order, so
# this sequence stays directly auditable against the real code (grep for
# ``_mark_stage(`` in main_pipeline.py to re-verify).
#
# Only the handful of stages relevant to the STRUCTURAL_FREEZE finding
# declare non-empty requires/provides; the rest are included with empty
# contracts purely so the sequence is a complete, literal mirror of the
# real run() order (a partial mirror would silently under-audit anything
# inserted between two capability-bearing stages in the future).
CURRENT_PIPELINE_STAGE_SEQUENCE: List[StageCapabilitySpec] = [
    StageCapabilitySpec("start"),
    StageCapabilitySpec("sanitize"),
    StageCapabilitySpec("topology_semantics"),
    StageCapabilitySpec("topology_repair"),
    # Honest as of today: Stage 4 does not declare a requirement on frozen
    # geometry (it doesn't check for one), even though it writes
    # position-dependent semantics. It DOES provide
    # SEMANTIC_POSITIONS_PLACED, since that's true of what it does.
    StageCapabilitySpec(
        "enrichment", provides=frozenset({SEMANTIC_POSITIONS_PLACED})
    ),
    StageCapabilitySpec("geometry", provides=frozenset({GEOMETRY_FROZEN})),
    StageCapabilitySpec(
        "lanes",
        requires=frozenset({GEOMETRY_FROZEN}),
        provides=frozenset({LANES_GENERATED}),
    ),
    StageCapabilitySpec(
        "final_integrity",
        requires=frozenset({GEOMETRY_FROZEN, LANES_GENERATED}),
    ),
    StageCapabilitySpec("junction_link_integrity"),
    StageCapabilitySpec("map_hygiene", provides=frozenset({HYGIENE_COMPLETE})),
    StageCapabilitySpec("drivable_surface_scan"),
    StageCapabilitySpec("full_map_metrics"),
    StageCapabilitySpec("osm2world_visual"),
    StageCapabilitySpec("tiling"),
    StageCapabilitySpec("tile_qa"),
    StageCapabilitySpec("perception_screenshots"),
    StageCapabilitySpec("interactive_sim"),
    StageCapabilitySpec("domain_gap"),
    StageCapabilitySpec("quality_gates"),
    StageCapabilitySpec("cumulative_gates"),
    StageCapabilitySpec("final_summary"),
    StageCapabilitySpec("run_summary"),
]


def with_stage_requirements(
    stages: Sequence[StageCapabilitySpec],
    *,
    stage_name: str,
    requires: FrozenSet[str],
) -> List[StageCapabilitySpec]:
    """Return a copy of ``stages`` with ``stage_name``'s ``requires`` replaced.

    Convenience for building the "what should this stage honestly require"
    variant of a sequence (e.g. in tests / audits) without mutating the
    shared module-level constant.
    """
    updated: List[StageCapabilitySpec] = []
    found = False
    for stage in stages:
        if stage.name == stage_name:
            found = True
            updated.append(
                StageCapabilitySpec(
                    stage.name, requires=frozenset(requires), provides=stage.provides
                )
            )
        else:
            updated.append(stage)
    if not found:
        raise KeyError(f"no stage named {stage_name!r} in the given sequence")
    return updated
