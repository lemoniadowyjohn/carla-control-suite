# -*- coding: utf-8 -*-
"""
Tests for the stage capability contract (ultimate_pipeline/contracts/
stage_capabilities.py).

Covers the 2026-09-15 comprehensive gap audit's STRUCTURAL_FREEZE finding
(packets P0-K/P0-L): "Position-dependent semantics (signals, crosswalks,
signs) are written before structural geometry freeze. No explicit
STRUCTURAL_FREEZE gate exists. Stages lack capability prerequisites."

Test groups:

1. ``TestValidatorMechanics`` -- generic, synthetic-stage unit tests of the
   validator itself (nothing pipeline-specific): a deliberately-misordered
   sequence is caught, a correctly-ordered one passes, a stage cannot
   satisfy its own requirement, etc. These establish that BEFORE this
   module existed, nothing in the codebase could express or check this
   kind of cross-stage prerequisite at all (the gap the audit found).

2. ``TestRealPipelineOrderingFinding`` -- uses
   ``CURRENT_PIPELINE_STAGE_SEQUENCE`` (an honest, literal mirror of
   ``MainPipeline.run()``'s real ``_mark_stage(...)`` order) to prove two
   things:
     a) the sequence as declared TODAY (Stage 4 does not yet declare a
        requirement on frozen/hygiene-complete geometry) validates clean
        -- this module does not retroactively break existing behavior.
     b) if Stage 4's requirements are patched to what the audit finding
        says they honestly SHOULD be (it does write position-dependent
        semantics keyed to road geometry), validating that same real
        stage order now fails, with a violation naming stage 'enrichment'
        -- i.e. this mechanism would have caught the real ordering issue
        the audit found, using the real stage order, not a synthetic one.
     c) a corrected ordering (semantic placement moved to run after both
        geometry freeze and hygiene) validates clean under the same
        aspirational requirements -- confirming the validator's positive
        case, not just its negative case.
"""

from __future__ import annotations

import pytest

from ultimate_pipeline.contracts.stage_capabilities import (
    CURRENT_PIPELINE_STAGE_SEQUENCE,
    GEOMETRY_FROZEN,
    HYGIENE_COMPLETE,
    LANES_FINAL,
    LANES_GENERATED,
    SEMANTIC_POSITIONS_PLACED,
    SEMANTIC_SOURCE_READY,
    SEMANTICS_FINAL,
    StageCapabilitySpec,
    StageDependencyViolation,
    assert_stage_sequence_valid,
    validate_stage_sequence,
    with_stage_requirements,
)


class TestValidatorMechanics:
    """Generic validator behavior, independent of the real pipeline."""

    def test_empty_sequence_is_trivially_valid(self):
        report = validate_stage_sequence([])
        assert report.ok
        assert report.violations == []

    def test_simple_satisfied_requirement_passes(self):
        stages = [
            StageCapabilitySpec("produce", provides=frozenset({"x"})),
            StageCapabilitySpec("consume", requires=frozenset({"x"})),
        ]
        report = validate_stage_sequence(stages)
        assert report.ok
        assert report.violations == []

    def test_deliberately_misordered_sequence_is_caught(self):
        """The exact shape of bug the audit found: a consumer runs BEFORE
        its producer in the declared sequence."""
        stages = [
            StageCapabilitySpec("consume", requires=frozenset({"x"})),
            StageCapabilitySpec("produce", provides=frozenset({"x"})),
        ]
        report = validate_stage_sequence(stages)
        assert not report.ok
        assert len(report.violations) == 1
        assert "consume" in report.violations[0]
        assert "x" in report.violations[0]

    def test_stage_cannot_satisfy_its_own_requirement(self):
        """A single stage that both requires and provides the same
        capability must still fail -- provides only become visible to
        LATER stages, not to itself."""
        stages = [
            StageCapabilitySpec(
                "self_referential",
                requires=frozenset({"x"}),
                provides=frozenset({"x"}),
            )
        ]
        report = validate_stage_sequence(stages)
        assert not report.ok

    def test_assert_variant_raises_on_violation(self):
        stages = [
            StageCapabilitySpec("consume", requires=frozenset({"x"})),
            StageCapabilitySpec("produce", provides=frozenset({"x"})),
        ]
        with pytest.raises(StageDependencyViolation) as exc_info:
            assert_stage_sequence_valid(stages)
        assert "consume" in str(exc_info.value)

    def test_assert_variant_returns_report_on_success(self):
        stages = [
            StageCapabilitySpec("produce", provides=frozenset({"x"})),
            StageCapabilitySpec("consume", requires=frozenset({"x"})),
        ]
        report = assert_stage_sequence_valid(stages)
        assert report.ok

    def test_multiple_missing_requirements_all_reported(self):
        stages = [
            StageCapabilitySpec("consume", requires=frozenset({"x", "y"})),
        ]
        report = validate_stage_sequence(stages)
        assert not report.ok
        # Both missing capabilities named in the single violation entry for
        # this stage.
        assert "x" in report.violations[0] and "y" in report.violations[0]


class TestRealPipelineOrderingFinding:
    """Validates the real MainPipeline.run() stage order, per the audit."""

    def test_current_honest_sequence_validates_clean(self):
        """The sequence as declared TODAY (before any P0-L reorder) must
        validate clean: Stage 4 doesn't yet declare a requirement it
        doesn't actually check for, so wiring this validator into the live
        pipeline today would not spuriously break existing runs."""
        report = validate_stage_sequence(CURRENT_PIPELINE_STAGE_SEQUENCE)
        assert report.ok, (
            "current, non-aspirational stage sequence should validate "
            f"clean; unexpected violations: {report.violations}"
        )

    def test_p0l_reorder_validates_clean(self):
        """P0-L reorder: the new stage order (semantic_source_preparation early,
        positional_semantics after map_hygiene) validates clean.

        This replaces the old test that proved the mechanism would have caught
        the misordering. Now that the reorder is implemented, the real stage
        order with the new split stages validates clean.
        """
        report = validate_stage_sequence(CURRENT_PIPELINE_STAGE_SEQUENCE)
        assert report.ok, (
            f"P0-L reorder should validate clean; violations: {report.violations}"
        )

        # Verify the new stages exist in the correct order
        stage_names = [s.name for s in CURRENT_PIPELINE_STAGE_SEQUENCE]
        assert "semantic_source_preparation" in stage_names
        assert "positional_semantics" in stage_names
        assert "enrichment" not in stage_names  # old stage removed

        # Verify positional_semantics requires the right capabilities
        pos_sem_stage = next(s for s in CURRENT_PIPELINE_STAGE_SEQUENCE if s.name == "positional_semantics")
        assert GEOMETRY_FROZEN in pos_sem_stage.requires
        assert LANES_FINAL in pos_sem_stage.requires
        assert HYGIENE_COMPLETE in pos_sem_stage.requires
        assert SEMANTIC_POSITIONS_PLACED in pos_sem_stage.provides
        assert SEMANTICS_FINAL in pos_sem_stage.provides

        # Verify semantic_source_preparation provides SEMANTIC_SOURCE_READY
        src_prep_stage = next(s for s in CURRENT_PIPELINE_STAGE_SEQUENCE if s.name == "semantic_source_preparation")
        assert SEMANTIC_SOURCE_READY in src_prep_stage.provides
        assert not src_prep_stage.mutates_structure

    def test_old_enrichment_with_true_dependency_would_fail(self):
        """Legacy test: if the old 'enrichment' stage (with its true dependency
        on frozen + hygiene-complete geometry) were still in the sequence,
        it would fail -- proving the validator catches the original misordering."""
        # Build a sequence with the old enrichment stage inserted at its old position
        old_sequence = []
        for stage in CURRENT_PIPELINE_STAGE_SEQUENCE:
            if stage.name == "geometry":
                # Insert old enrichment before geometry (its old position)
                old_sequence.append(StageCapabilitySpec(
                    "enrichment",
                    requires=frozenset({GEOMETRY_FROZEN, HYGIENE_COMPLETE}),
                    provides=frozenset({SEMANTIC_POSITIONS_PLACED}),
                    mutates_structure=True,
                ))
            old_sequence.append(stage)

        report = validate_stage_sequence(old_sequence)
        assert not report.ok, (
            "Old enrichment with true dependency should fail in old position"
        )
        assert any("enrichment" in v for v in report.violations)
        assert any(GEOMETRY_FROZEN in v or HYGIENE_COMPLETE in v for v in report.violations)

        with pytest.raises(StageDependencyViolation):
            assert_stage_sequence_valid(old_sequence)

    def test_lanes_and_final_integrity_already_require_geometry_frozen(self):
        """Sanity check that this module's declarations for 'lanes' and
        'final_integrity' match the ad hoc runtime check that already
        exists (MainPipeline._assert_geometry_frozen, called from
        stage_07_lanes.py:73 and stage_08_integrity.py:513) -- i.e. this
        module formalizes a prerequisite that was already partially
        enforced for those two stages, just never extended to
        'enrichment' (now split into semantic_source_preparation + positional_semantics)."""
        by_name = {s.name: s for s in CURRENT_PIPELINE_STAGE_SEQUENCE}
        assert GEOMETRY_FROZEN in by_name["lanes"].requires
        assert GEOMETRY_FROZEN in by_name["final_integrity"].requires
        assert LANES_GENERATED in by_name["final_integrity"].requires
        # "semantic_source_preparation" (early, non-structural) does NOT
        # require frozen geometry -- it only prepares sources.
        assert by_name["semantic_source_preparation"].requires == frozenset()
        # "positional_semantics" (late, post-freeze) DOES require
        # GEOMETRY_FROZEN + LANES_FINAL + HYGIENE_COMPLETE.
        assert GEOMETRY_FROZEN in by_name["positional_semantics"].requires
        assert LANES_FINAL in by_name["positional_semantics"].requires
        assert HYGIENE_COMPLETE in by_name["positional_semantics"].requires
        # Old "enrichment" stage no longer exists.
        assert "enrichment" not in by_name
