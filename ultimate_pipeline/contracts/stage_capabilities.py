# ultimate_pipeline/contracts/stage_capabilities.py
# -*- coding: utf-8 -*-

"""Stage capability contract (P0-K/P0-L, extended by P0-C on 2026-09-18).

Background
----------
The 2026-09-15 comprehensive gap audit
(reports/production_readiness/20260915T203000Z_COMPREHENSIVE_GAP_AUDIT/
PIPELINE_DEPENDENCY_AUDIT.json, packets P0-K/P0-L) found:

    "Position-dependent semantics (signals, crosswalks, signs) are written
    before structural geometry freeze. No explicit STRUCTURAL_FREEZE gate
    exists. Stages lack capability prerequisites."

The first slice of this module (2026-09-17) added an additive-only capability
model (``requires``/``provides``) plus a fail-closed validator, and an honest
mirror of ``MainPipeline.run()``'s real ``_mark_stage(...)`` order.

P0-C (2026-09-18) extends it for the *final-artifact authority* defect
--------------------------------------------------------------------
``MainPipeline._run_internal()`` produced ``map_acceptance.json``,
``map_content_fingerprint.json``, preflight validation and the determinism
fingerprint BEFORE the ``junction_link_integrity`` and ``map_hygiene`` stages,
both of which can still mutate the map (link patching; road quarantine /
deletion, lane repair, lane-width repair, z-seam repair) and both of which can
even return a DIFFERENT output path. The acceptance receipt therefore did not
necessarily describe the file published as "final".

Two things were missing from the model to express (and enforce) that:

1. There was no ``STRUCTURE_FROZEN`` capability marking "every permitted
   road/lane/topology/hygiene mutation is now complete".
2. The model had no way for a stage to INVALIDATE a capability. The original
   docstring said so explicitly: "this model has no 'revokes' primitive". So a
   capability could stay silently "provided" after the thing it asserted had
   stopped being true.

This revision adds both, plus a declared ``mutates_structure`` flag so the
validator can catch a structural mutation scheduled after ``STRUCTURE_FROZEN``
without an explicit invalidation -- real validation rather than a naming
convention. The runtime half (evidence freshness, structural fingerprints, the
final receipt) lives in ``ultimate_pipeline.contracts.artifact_authority``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, List, Sequence

# ---------------------------------------------------------------------------
# Capability vocabulary
# ---------------------------------------------------------------------------

#: Set once horizontal (s/t-relevant) road geometry is fixed and will not be
#: further mutated except by an explicit, declared repair stage. Mirrors the
#: existing ad hoc ``header.get("geometryFrozen") == "true"`` runtime check
#: in ``MainPipeline._assert_geometry_frozen``.
GEOMETRY_FROZEN = "geometry_frozen"

#: Set once lane generation (stage 7) has produced the lane structure that
#: position-dependent semantics (which lane a sign/signal refers to) depend
#: on. NOTE: lanes can still be repaired after this point -- see LANES_FINAL.
LANES_GENERATED = "lanes_generated"

#: Set once no further lane mutation is permitted: lane links, lane widths and
#: lane offsets are final. Map hygiene (08H) is the last stage allowed to
#: touch them (degenerate-lane flooring, lane-width discontinuity repair, G6
#: lane links), so this is provided there -- NOT at stage 7.
LANES_FINAL = "lanes_final"

#: Set once map hygiene (stage 08H: island quarantine, degenerate-lane
#: floor-repair, lane-width repair, z-seam repair) has completed. Island
#: quarantine can delete whole roads, so anything keyed to a road id/s
#: coordinate placed before this point may reference geometry that no longer
#: exists or has shifted.
HYGIENE_COMPLETE = "hygiene_complete"

#: Provided (not required) by stages that write position-dependent semantic
#: content (signals, crosswalks, regulatory signs) keyed to road s/t
#: coordinates.
SEMANTIC_POSITIONS_PLACED = "semantic_positions_placed"

#: THE final-artifact authority gate. Set only after EVERY permitted
#: road/lane/topology/hygiene mutation is complete. Nothing after this point
#: may mutate road identity, planView, road links, junction connections,
#: laneSection identities, lane links, lane widths, lane offsets or road
#: elevations -- unless it explicitly invalidates this capability, which
#: forces every derived artifact (acceptance, fingerprints, preflight,
#: determinism, release evidence) to be regenerated.
STRUCTURE_FROZEN = "structure_frozen"

#: Set once supplemental visual/collision material (OSM2World meshes) is
#: final. Visual material never feeds back into the OpenDRIVE authority.
VISUAL_FROZEN = "visual_frozen"

#: Set once the final acceptance receipt has been published against the exact
#: frozen artifact (see ``artifact_authority.ArtifactAuthorityLedger``).
FINAL_ARTIFACT_PUBLISHED = "final_artifact_published"


@dataclass(frozen=True)
class StageCapabilitySpec:
    """One pipeline stage's declared capability contract.

    ``name`` should match (or closely mirror) the ``_mark_stage(...)`` label
    used in ``MainPipeline.run()`` so a real-sequence audit and this declared
    contract stay traceable to each other.

    ``requires``: capabilities that MUST already hold (provided by a strictly
    earlier stage and not subsequently invalidated) for this stage to be safe
    to run.

    ``provides``: capabilities this stage guarantees hold for every stage
    that runs after it, until something explicitly invalidates them.

    ``invalidates``: capabilities this stage REVOKES. Applied before
    ``provides``, so a stage may legally declare both -- that is the
    "mutate, then re-establish and force regeneration" pattern. Invalidating
    a capability that was never provided is a legal no-op (it is how a stage
    declares "I would break this if it were held").

    ``mutates_structure``: True for any stage permitted to change road
    identity, planView, road links, junction connections, laneSection
    identities, lane links, lane widths, lane offsets or road elevations.
    Such a stage scheduled AFTER ``STRUCTURE_FROZEN`` is a contract violation
    unless it also invalidates ``STRUCTURE_FROZEN``.
    """

    name: str
    requires: FrozenSet[str] = field(default_factory=frozenset)
    provides: FrozenSet[str] = field(default_factory=frozenset)
    invalidates: FrozenSet[str] = field(default_factory=frozenset)
    mutates_structure: bool = False


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

    For every stage, in order:

    1. its ``requires`` must be satisfied by capabilities that are CURRENTLY
       held -- i.e. provided by a strictly earlier stage and not invalidated
       since. A capability that was invalidated and never re-provided is
       reported with its invalidating stage, not silently treated as still
       provided;
    2. if it declares ``mutates_structure`` while ``STRUCTURE_FROZEN`` is
       currently held, it must also invalidate ``STRUCTURE_FROZEN``;
    3. its ``invalidates`` are then applied, and finally its ``provides``
       (so a stage that declares both ends up net-providing).

    A stage's own ``provides`` only become visible to stages after it.

    Returns a report rather than raising, so a caller can decide how to
    surface accumulated violations (see ``assert_stage_sequence_valid``).
    """
    provided_so_far: set[str] = set()
    revoked_by: dict[str, str] = {}
    violations: List[str] = []

    for index, stage in enumerate(stages):
        missing = set(stage.requires) - provided_so_far
        # Never-provided and invalidated are reported separately: "nobody
        # produces this" and "somebody revoked this" are different defects
        # and need different fixes. The never-provided message keeps the
        # original (pre-P0-C) aggregated wording so existing callers/tests
        # that parse it are unaffected.
        never_provided = sorted(c for c in missing if c not in revoked_by)
        if never_provided:
            violations.append(
                f"stage[{index}] {stage.name!r} requires "
                f"{never_provided} but no earlier stage in the declared "
                "sequence provides it"
            )
        for capability in sorted(c for c in missing if c in revoked_by):
            violations.append(
                f"stage[{index}] {stage.name!r} requires {capability!r}, "
                f"which was INVALIDATED by stage {revoked_by[capability]!r} "
                "and never re-provided"
            )

        if (
            stage.mutates_structure
            and STRUCTURE_FROZEN in provided_so_far
            and STRUCTURE_FROZEN not in stage.invalidates
        ):
            violations.append(
                f"stage[{index}] {stage.name!r} is declared mutates_structure=True "
                f"but runs after {STRUCTURE_FROZEN!r} was provided without "
                f"invalidating it; a stage that must mutate road identity, "
                "planView, road links, junction connections, laneSection "
                "identities, lane links, lane widths, lane offsets or road "
                "elevations after the structural freeze has to invalidate "
                f"{STRUCTURE_FROZEN!r} and force every derived artifact to be "
                "regenerated"
            )

        for capability in stage.invalidates:
            provided_so_far.discard(capability)
            revoked_by[capability] = stage.name
        for capability in stage.provides:
            provided_so_far.add(capability)
            revoked_by.pop(capability, None)

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
# ultimate_pipeline/main_pipeline.py's ``_run_internal()`` method, in call
# order, so this sequence stays directly auditable against the real code
# (grep for ``_mark_stage(`` in main_pipeline.py to re-verify).
CURRENT_PIPELINE_STAGE_SEQUENCE: List[StageCapabilitySpec] = [
    StageCapabilitySpec("start"),
    StageCapabilitySpec("sanitize", mutates_structure=True),
    StageCapabilitySpec("topology_semantics", mutates_structure=True),
    StageCapabilitySpec("topology_repair", mutates_structure=True),
    # Honest as of today: Stage 4 does not declare a requirement on frozen
    # geometry (it doesn't check for one), even though it writes
    # position-dependent semantics. It DOES provide
    # SEMANTIC_POSITIONS_PLACED, since that's true of what it does.
    StageCapabilitySpec(
        "enrichment",
        provides=frozenset({SEMANTIC_POSITIONS_PLACED}),
        mutates_structure=True,
    ),
    StageCapabilitySpec(
        "geometry", provides=frozenset({GEOMETRY_FROZEN}), mutates_structure=True
    ),
    StageCapabilitySpec(
        "lanes",
        requires=frozenset({GEOMETRY_FROZEN}),
        provides=frozenset({LANES_GENERATED}),
        mutates_structure=True,
    ),
    StageCapabilitySpec(
        "final_integrity",
        requires=frozenset({GEOMETRY_FROZEN, LANES_GENERATED}),
        mutates_structure=True,
    ),
    # Patches junction/lane links and may select a different output file
    # (main_pipeline.py: ``final_out = gate_result["final_xodr"]``).
    StageCapabilitySpec(
        "junction_link_integrity",
        requires=frozenset({GEOMETRY_FROZEN, LANES_GENERATED}),
        invalidates=frozenset({STRUCTURE_FROZEN}),
        mutates_structure=True,
    ),
    # Island quarantine can DELETE whole roads; degenerate-lane flooring,
    # lane-width repair, z-seam repair and G6 lane links all mutate lanes.
    # This is the last stage permitted to change structure, so LANES_FINAL
    # is provided here -- not at "lanes".
    StageCapabilitySpec(
        "map_hygiene",
        requires=frozenset({GEOMETRY_FROZEN, LANES_GENERATED}),
        provides=frozenset({LANES_FINAL, HYGIENE_COMPLETE}),
        invalidates=frozenset({STRUCTURE_FROZEN}),
        mutates_structure=True,
    ),
    # P0-C: the structural freeze + all pipeline-level acceptance/fingerprint
    # /preflight/determinism evidence, recomputed against the EXACT
    # post-hygiene, post-junction-integrity artifact.
    StageCapabilitySpec(
        "final_artifact_authority",
        requires=frozenset({GEOMETRY_FROZEN, LANES_FINAL, HYGIENE_COMPLETE}),
        provides=frozenset({STRUCTURE_FROZEN, FINAL_ARTIFACT_PUBLISHED}),
    ),
    StageCapabilitySpec(
        "drivable_surface_scan", requires=frozenset({STRUCTURE_FROZEN})
    ),
    StageCapabilitySpec("full_map_metrics", requires=frozenset({STRUCTURE_FROZEN})),
    StageCapabilitySpec(
        "osm2world_visual",
        requires=frozenset({STRUCTURE_FROZEN}),
        provides=frozenset({VISUAL_FROZEN}),
    ),
    StageCapabilitySpec("tiling", requires=frozenset({STRUCTURE_FROZEN})),
    StageCapabilitySpec("tile_qa", requires=frozenset({STRUCTURE_FROZEN})),
    StageCapabilitySpec(
        "perception_screenshots",
        requires=frozenset({STRUCTURE_FROZEN, VISUAL_FROZEN}),
    ),
    StageCapabilitySpec("interactive_sim", requires=frozenset({STRUCTURE_FROZEN})),
    StageCapabilitySpec("domain_gap", requires=frozenset({STRUCTURE_FROZEN})),
    StageCapabilitySpec("quality_gates", requires=frozenset({STRUCTURE_FROZEN})),
    StageCapabilitySpec("cumulative_gates", requires=frozenset({STRUCTURE_FROZEN})),
    StageCapabilitySpec(
        "final_summary",
        requires=frozenset({STRUCTURE_FROZEN, FINAL_ARTIFACT_PUBLISHED}),
    ),
    StageCapabilitySpec(
        "run_summary",
        requires=frozenset({STRUCTURE_FROZEN, FINAL_ARTIFACT_PUBLISHED}),
    ),
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
                    stage.name,
                    requires=frozenset(requires),
                    provides=stage.provides,
                    invalidates=stage.invalidates,
                    mutates_structure=stage.mutates_structure,
                )
            )
        else:
            updated.append(stage)
    if not found:
        raise KeyError(f"no stage named {stage_name!r} in the given sequence")
    return updated


def moved_stage(
    stages: Sequence[StageCapabilitySpec],
    *,
    stage_name: str,
    before: str,
) -> List[StageCapabilitySpec]:
    """Return a copy of ``stages`` with ``stage_name`` relocated immediately
    before ``before``.

    Used by the P0-C regression tests to reproduce the original defect against
    the REAL declared sequence: moving ``final_artifact_authority`` back before
    ``junction_link_integrity`` (where the acceptance/fingerprint evidence used
    to be produced) must make the contract fail, not pass.
    """
    remaining = [s for s in stages if s.name != stage_name]
    if len(remaining) == len(stages):
        raise KeyError(f"no stage named {stage_name!r} in the given sequence")
    try:
        target = next(i for i, s in enumerate(remaining) if s.name == before)
    except StopIteration:
        raise KeyError(f"no stage named {before!r} in the given sequence") from None
    moved = next(s for s in stages if s.name == stage_name)
    return remaining[:target] + [moved] + remaining[target:]
