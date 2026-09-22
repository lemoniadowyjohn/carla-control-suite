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
    LANES_GENERATED,
    SEMANTIC_POSITIONS_PLACED,
    StageCapabilitySpec,
    StageDependencyViolation,
    XODR_VALIDATED,
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

    def test_real_stage_order_fails_once_enrichment_declares_its_true_dependency(
        self,
    ):
        """This is the reproduction of the audit's actual finding.

        Stage 4 ("enrichment") genuinely writes position-dependent
        semantics (traffic lights with lane references, OSM-matched
        regulatory signs, geometrically-projected crosswalks --
        pipeline_stages/stage_04_enrichment.py lines 180, 285-304,
        364-389) before the horizontal geometry freeze
        (pipeline_stages/stage_05_geometry.py:261) and before map hygiene
        (pipeline_stages/stage_08_hygiene.py, which can delete whole
        roads via island quarantine) have run.

        If "enrichment" honestly declared that dependency (what it SHOULD
        declare per the audit finding), validating the REAL current stage
        order (unchanged) now fails -- proving this mechanism would have
        caught the real misordering, using the actual pipeline order
        found in main_pipeline.py, not a synthetic stand-in.
        """
        audit_target_sequence = with_stage_requirements(
            CURRENT_PIPELINE_STAGE_SEQUENCE,
            stage_name="enrichment",
            requires=frozenset({GEOMETRY_FROZEN, HYGIENE_COMPLETE}),
        )

        report = validate_stage_sequence(audit_target_sequence)

        assert not report.ok, (
            "expected the real stage order to violate the contract once "
            "'enrichment' honestly declares its dependency on frozen + "
            "hygiene-complete geometry -- if this now passes, either the "
            "real stage order changed (re-verify against main_pipeline.py "
            "_mark_stage(...) call order) or the audit finding no longer "
            "reproduces and this test should be updated to say so"
        )
        assert any("enrichment" in v for v in report.violations)
        assert any(
            GEOMETRY_FROZEN in v or HYGIENE_COMPLETE in v for v in report.violations
        )

        with pytest.raises(StageDependencyViolation):
            assert_stage_sequence_valid(audit_target_sequence)

    def test_corrected_ordering_with_same_aspirational_requirement_passes(self):
        """Positive-case counterpart: if semantic placement is moved to run
        after both geometry-freeze and hygiene-complete (the shape of fix
        the full P0-L reorder would produce), the same aspirational
        requirement on 'enrichment' validates clean. This is not an
        implementation of the reorder -- it only proves the validator
        recognizes a corrected order as valid, so it can be trusted as the
        acceptance check for that future work."""
        reordered = [
            stage
            for stage in CURRENT_PIPELINE_STAGE_SEQUENCE
            if stage.name != "enrichment"
        ]
        # Re-insert "enrichment" (with its true requirement) immediately
        # after "map_hygiene", which provides HYGIENE_COMPLETE and runs
        # after "geometry" (which provides GEOMETRY_FROZEN).
        hygiene_index = next(
            i for i, stage in enumerate(reordered) if stage.name == "map_hygiene"
        )
        moved_enrichment = StageCapabilitySpec(
            "enrichment",
            requires=frozenset({GEOMETRY_FROZEN, HYGIENE_COMPLETE}),
            provides=frozenset({SEMANTIC_POSITIONS_PLACED}),
        )
        reordered.insert(hygiene_index + 1, moved_enrichment)

        report = validate_stage_sequence(reordered)
        assert report.ok, (
            f"corrected ordering should validate clean; violations: {report.violations}"
        )

    def test_lanes_and_final_integrity_already_require_geometry_frozen(self):
        """Sanity check that this module's declarations for 'lanes' and
        'final_integrity' match the ad hoc runtime check that already
        exists (MainPipeline._assert_geometry_frozen, called from
        stage_07_lanes.py:73 and stage_08_integrity.py:513) -- i.e. this
        module formalizes a prerequisite that was already partially
        enforced for those two stages, just never extended to
        'enrichment'."""
        by_name = {s.name: s for s in CURRENT_PIPELINE_STAGE_SEQUENCE}
        assert GEOMETRY_FROZEN in by_name["lanes"].requires
        assert GEOMETRY_FROZEN in by_name["final_integrity"].requires
        assert LANES_GENERATED in by_name["final_integrity"].requires
        # "enrichment" (stage 4) is the one NOT yet declaring a requirement
        # on frozen/hygiene-complete geometry, which is exactly the audit's
        # finding. It DOES now require XODR_VALIDATED (added when the
        # xodr_validator stage was wired in ahead of it) -- that is a
        # different, narrower dependency than the audit finding covers.
        assert by_name["enrichment"].requires == frozenset({XODR_VALIDATED})
