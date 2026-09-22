# -*- coding: utf-8 -*-
"""P0-C: the final acceptance receipt must describe the FINAL artifact.

The defect, as it stood on integration/production-large-map-20260918 @234e1ef1
------------------------------------------------------------------------------
In ``MainPipeline._run_internal()``:

    line 2315-2326  build_map_acceptance(...) -> map_acceptance.json
    line 2336       write_map_content_fingerprint(...) -> map_content_fingerprint.json
    line 2343       self._step8d_preflight_validation(final_out)
    line 2344       self._write_determinism_fingerprint(final_out)
    ---------------------------------------------------------------------
    line 2347      self._mark_stage("junction_link_integrity")
    line 2349-2356 run_junction_link_integrity_gate(...)   # PATCHES links and
                                                           # reassigns final_out
    line 2389      self._mark_stage("map_hygiene")
    line 2390      final_out = self._step8h_map_hygiene(final_out)  # quarantines /
                                                           # DELETES roads, repairs
                                                           # lanes, lane widths and
                                                           # z-seams; reassigns
                                                           # final_out again

Every acceptance/fingerprint artifact was therefore produced against a
PRE-FINAL XODR -- different content, and frequently a literally different
path, from the file published as "final".

What this module tests
----------------------
1. ``TestSourceOrdering`` -- the reproduction. Every evidence producer now
   lives behind ``_publish_final_artifact_authority``, which ``_run_internal``
   calls only AFTER both mutating stages. Run against the pre-fix source these
   assertions fail.
2. ``TestDeclaredContractCatchesTheOldOrder`` -- moving the freeze stage back
   to where the evidence used to be produced makes the declared stage
   capability contract fail, fail-closed.
3. ``TestPublishedEvidenceIsAuthoritative`` -- a functional exercise of the
   relocated code: evidence is recorded against the exact final artifact, and
   a late mutation cannot leave a valid acceptance packet behind.
"""

from __future__ import annotations

import inspect
import json
import re
import types

import pytest

import ultimate_pipeline.main_pipeline as main_pipeline_mod
from ultimate_pipeline.contracts.artifact_authority import (
    ArtifactAuthorityError,
    compute_structure_fingerprint,
    sha256_file,
)
from ultimate_pipeline.contracts.stage_capabilities import (
    CURRENT_PIPELINE_STAGE_SEQUENCE,
    FINAL_ARTIFACT_PUBLISHED,
    GEOMETRY_FROZEN,
    HYGIENE_COMPLETE,
    LANES_FINAL,
    LANES_GENERATED,
    STRUCTURE_FROZEN,
    StageCapabilitySpec,
    moved_stage,
    validate_stage_sequence,
    with_stage_requirements,
)

from ultimate_pipeline.tests.unit.test_final_artifact_authority import BASE_XODR


#: The four pipeline-level evidence producers that used to run too early.
EVIDENCE_PRODUCERS = (
    "build_map_acceptance",
    "write_map_content_fingerprint",
    "_step8d_preflight_validation",
    "_write_determinism_fingerprint",
)


class TestSourceOrdering:
    """Source-level reproduction of the original ordering defect."""

    @staticmethod
    def _run_internal_source() -> str:
        return inspect.getsource(main_pipeline_mod.MainPipeline._run_internal)

    def test_no_evidence_producer_is_called_inside_run_internal(self):
        """All four moved into ``_publish_final_artifact_authority``.

        On the pre-fix code every one of them appears in ``_run_internal``
        itself, ahead of the mutating stages -- which is the defect.
        """
        source = self._run_internal_source()
        for producer in EVIDENCE_PRODUCERS:
            assert producer not in source, (
                f"{producer!r} is still called directly from _run_internal; "
                "pipeline-level acceptance/fingerprint evidence must be "
                "produced only by _publish_final_artifact_authority, after "
                "junction_link_integrity and map_hygiene"
            )

    def test_publish_runs_after_both_mutating_stages(self):
        source = self._run_internal_source()
        junction_idx = source.index('self._mark_stage("junction_link_integrity")')
        hygiene_idx = source.index('self._mark_stage("map_hygiene")')
        publish_idx = source.index("self._publish_final_artifact_authority(")
        assert junction_idx < publish_idx, (
            "acceptance evidence must be produced after the junction-link "
            "integrity gate, which patches links and can select a different "
            "output file"
        )
        assert hygiene_idx < publish_idx, (
            "acceptance evidence must be produced after map hygiene, which can "
            "quarantine/delete roads and repair lanes, lane widths and z-seams"
        )

    def test_publish_runs_before_every_consumer_stage(self):
        source = self._run_internal_source()
        publish_idx = source.index("self._publish_final_artifact_authority(")
        for consumer in ("drivable_surface_scan", "tiling", "tile_qa", "run_summary"):
            assert publish_idx < source.index(f'self._mark_stage("{consumer}")'), (
                f"stage {consumer!r} consumes the frozen artifact and must run "
                "after the structural freeze"
            )

    def test_publish_method_contains_every_evidence_producer(self):
        source = inspect.getsource(
            main_pipeline_mod.MainPipeline._publish_final_artifact_authority
        )
        for producer in EVIDENCE_PRODUCERS:
            assert producer in source, (
                f"{producer!r} was removed from _run_internal but is not "
                "produced by _publish_final_artifact_authority either -- a "
                "check must be relocated, never dropped"
            )

    def test_release_gate_evidence_already_runs_against_the_final_artifact(self):
        """Release-gate evidence needed no relocation -- and this proves it.

        The quality-gate wrapper, the cumulative gate tally and the
        post-hygiene geometric-continuity gate all already ran after
        ``map_hygiene``, so unlike acceptance/fingerprints they were never
        computed against a pre-final artifact. This test pins that, so the
        claim cannot silently stop being true.
        """
        source = self._run_internal_source()
        hygiene_idx = source.index('self._mark_stage("map_hygiene")')
        for marker in (
            'self._run_geometric_continuity_gate(final_out, "after_map_hygiene")',
            'self._mark_stage("quality_gates")',
            "self._run_quality_gates_wrapper(final_out)",
            'self._mark_stage("cumulative_gates")',
            "self._finalize_gates()",
        ):
            assert hygiene_idx < source.index(marker), (
                f"{marker!r} must run after map_hygiene so release-gate "
                "evidence describes the published artifact"
            )

    def test_structure_freeze_is_re_verified_after_the_freeze(self):
        """The 'nothing may mutate structure after STRUCTURE_FROZEN' rule is
        enforced by measurement at least once after the freeze."""
        source = self._run_internal_source()
        publish_idx = source.index("self._publish_final_artifact_authority(")
        guard_idx = source.index("self._assert_structure_frozen_unchanged(")
        assert publish_idx < guard_idx

    def test_declared_sequence_still_mirrors_the_real_mark_stage_order(self):
        """``CURRENT_PIPELINE_STAGE_SEQUENCE`` must stay a literal mirror of
        the real ``_mark_stage(...)`` call order, or the static contract is
        validating a fiction."""
        source = self._run_internal_source()
        real = ["start"] + re.findall(r'_mark_stage\(\s*"([a-z0-9_]+)"', source)
        declared = [stage.name for stage in CURRENT_PIPELINE_STAGE_SEQUENCE]
        assert declared == real, (
            "declared stage sequence drifted from main_pipeline.py's real "
            f"_mark_stage order.\n  declared={declared}\n  real    ={real}"
        )


class TestDeclaredContractCatchesTheOldOrder:
    """The static contract now fails on the pre-fix ordering."""

    def test_freezing_before_hygiene_fails_its_own_prerequisites(self):
        """First line of defence: the freeze stage cannot even start before
        hygiene has completed, because it declares that dependency."""
        broken = moved_stage(
            CURRENT_PIPELINE_STAGE_SEQUENCE,
            stage_name="final_artifact_authority",
            before="junction_link_integrity",
        )
        report = validate_stage_sequence(broken)

        assert not report.ok, (
            "producing the acceptance/freeze packet before "
            "junction_link_integrity and map_hygiene must violate the stage "
            "capability contract"
        )
        joined = "\n".join(report.violations)
        assert "final_artifact_authority" in joined
        assert LANES_FINAL in joined and HYGIENE_COMPLETE in joined

    def test_old_order_with_pre_fix_prerequisites_is_still_caught(self):
        """Second line of defence, and the closest model of the ACTUAL pre-fix
        code.

        Before the fix, acceptance/fingerprint evidence was produced with only
        geometry+lanes established -- it declared no dependency on hygiene at
        all. Reproduce exactly that (freeze moved early AND its prerequisites
        relaxed to what the old code effectively required) and the contract
        must still fail: both remaining mutating stages now run after the
        freeze, and every downstream consumer depends on a capability they
        revoke.
        """
        relaxed = with_stage_requirements(
            CURRENT_PIPELINE_STAGE_SEQUENCE,
            stage_name="final_artifact_authority",
            requires=frozenset({GEOMETRY_FROZEN, LANES_GENERATED}),
        )
        broken = moved_stage(
            relaxed,
            stage_name="final_artifact_authority",
            before="junction_link_integrity",
        )
        report = validate_stage_sequence(broken)

        assert not report.ok
        joined = "\n".join(report.violations)

        # junction_link_integrity and map_hygiene both declare that they revoke
        # STRUCTURE_FROZEN, so scheduling them after the freeze leaves every
        # downstream consumer depending on a capability that no longer holds.
        assert "INVALIDATED" in joined
        assert "map_hygiene" in joined
        assert STRUCTURE_FROZEN in joined

        # Every stage that consumes the frozen artifact is named.
        for consumer in (
            "drivable_surface_scan",
            "tiling",
            "tile_qa",
            "quality_gates",
            "run_summary",
        ):
            assert consumer in joined, f"{consumer!r} not reported as depending on a revoked capability"

    def test_undeclared_structural_mutation_after_the_freeze_is_caught(self):
        """The other half of the rule: a stage that mutates structure after the
        freeze WITHOUT declaring that it revokes STRUCTURE_FROZEN.

        junction_link_integrity/map_hygiene honestly declare their revocation,
        so they are caught by the requires path above. A future stage added
        after the freeze that quietly edits lanes would not be -- unless the
        validator checks the declared mutation flag itself, which it does.
        """
        sneaky = list(CURRENT_PIPELINE_STAGE_SEQUENCE)
        insert_at = next(
            i for i, s in enumerate(sneaky) if s.name == "drivable_surface_scan"
        )
        sneaky.insert(
            insert_at,
            StageCapabilitySpec("late_lane_touchup", mutates_structure=True),
        )
        report = validate_stage_sequence(sneaky)

        assert not report.ok, (
            "a stage declared as mutating structure after STRUCTURE_FROZEN, "
            "without invalidating it, must be a contract violation"
        )
        joined = "\n".join(report.violations)
        assert "late_lane_touchup" in joined
        assert "mutates_structure=True" in joined

        # Declaring the revocation makes it a legal (if drastic) mutation --
        # which then trips the downstream consumers, never a silent pass.
        honest = list(CURRENT_PIPELINE_STAGE_SEQUENCE)
        honest.insert(
            insert_at,
            StageCapabilitySpec(
                "late_lane_touchup",
                invalidates=frozenset({STRUCTURE_FROZEN}),
                mutates_structure=True,
            ),
        )
        honest_report = validate_stage_sequence(honest)
        assert not honest_report.ok
        assert all("INVALIDATED" in v for v in honest_report.violations)

    def test_real_declared_sequence_is_clean(self):
        report = validate_stage_sequence(CURRENT_PIPELINE_STAGE_SEQUENCE)
        assert report.ok, report.violations

    def test_freeze_stage_requires_hygiene_to_have_completed(self):
        by_name = {s.name: s for s in CURRENT_PIPELINE_STAGE_SEQUENCE}
        freeze = by_name["final_artifact_authority"]
        assert LANES_FINAL in freeze.requires
        assert HYGIENE_COMPLETE in freeze.requires
        assert STRUCTURE_FROZEN in freeze.provides
        assert FINAL_ARTIFACT_PUBLISHED in freeze.provides
        # And the two mutating stages declare that they would revoke it.
        assert STRUCTURE_FROZEN in by_name["junction_link_integrity"].invalidates
        assert STRUCTURE_FROZEN in by_name["map_hygiene"].invalidates


# ---------------------------------------------------------------------------
# Functional exercise of the relocated code
# ---------------------------------------------------------------------------


class _StubQualityGate:
    def gate_origin_sanity(self, path):
        return {"ok": True, "centroid_distance_m": 1.5}


class _StubPipeline:
    """Minimal stand-in carrying the real, unbound methods under test.

    A full ``MainPipeline`` needs live settings/CARLA infrastructure this
    suite does not have, but the methods under test only touch ``settings``,
    ``out_dir``, ``qgate``, ``_mark_stage`` and the ledger -- so binding the
    real implementations to a stub exercises the real code, not a copy.
    """

    authority_ledger = main_pipeline_mod.MainPipeline.authority_ledger
    _authority_mark_geometry_frozen = (
        main_pipeline_mod.MainPipeline._authority_mark_geometry_frozen
    )
    _authority_mark_lanes_generated = (
        main_pipeline_mod.MainPipeline._authority_mark_lanes_generated
    )
    _authority_mark_structure_mutated = (
        main_pipeline_mod.MainPipeline._authority_mark_structure_mutated
    )
    _authority_mark_hygiene_complete = (
        main_pipeline_mod.MainPipeline._authority_mark_hygiene_complete
    )
    _semantic_authority_profile = (
        main_pipeline_mod.MainPipeline._semantic_authority_profile
    )
    _source_manifest_identity = main_pipeline_mod.MainPipeline._source_manifest_identity
    _publish_final_artifact_authority = (
        main_pipeline_mod.MainPipeline._publish_final_artifact_authority
    )
    _assert_structure_frozen_unchanged = (
        main_pipeline_mod.MainPipeline._assert_structure_frozen_unchanged
    )

    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        self.settings = types.SimpleNamespace(
            RELEASE_PROFILE="structural_release",
            ENABLE_BUILDINGS=False,
            ENABLE_TRAFFIC_LIGHTS=False,
            ENABLE_CROSSWALKS=False,
            ENABLE_MAP_HYGIENE=True,
            ENABLE_JUNCTION_LINK_PATCH=True,
            DETERMINISTIC_SEED=1234,
            INPUTS_MANIFEST="",
            OSM_FILE="",
        )
        self.qgate = _StubQualityGate()
        self._authority_ledger = None
        self.marks = []
        self.preflight_calls = []
        self.determinism_calls = []

    def _mark_stage(self, stage, *, message=None):
        self.marks.append(stage)

    def _resolve_strict_quality_gates(self):
        return True

    def _resolve_experimental_unsafe(self):
        return False

    def _step8d_preflight_validation(self, final_out):
        self.preflight_calls.append(final_out)

    def _write_determinism_fingerprint(self, final_out):
        self.determinism_calls.append(final_out)


@pytest.fixture()
def staged(tmp_path):
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    xodr = out_dir / "08h1_island_quarantined.xodr"
    xodr.write_text(BASE_XODR, encoding="utf-8")
    manifest = out_dir / "inputs_manifest.json"
    manifest.write_text('{"inputs": {}}', encoding="utf-8")

    pipe = _StubPipeline(str(out_dir))
    pipe.settings.INPUTS_MANIFEST = str(manifest)
    pipe._authority_mark_geometry_frozen(str(xodr))
    pipe._authority_mark_lanes_generated(str(xodr))
    pipe._authority_mark_structure_mutated(
        "junction_link_integrity", "patched junction lane links"
    )
    pipe._authority_mark_structure_mutated(
        "map_hygiene", "island quarantine + lane repair"
    )
    pipe._authority_mark_hygiene_complete(str(xodr))
    # P0-L: positional semantics materialization complete
    from ultimate_pipeline.contracts.stage_capabilities import SEMANTICS_FINAL
    pipe.authority_ledger.provide(SEMANTICS_FINAL, "positional_semantics", evidence=str(xodr))
    return pipe, str(xodr), out_dir


class TestPublishedEvidenceIsAuthoritative:
    def test_receipt_describes_the_exact_final_artifact(self, staged):
        pipe, xodr, out_dir = staged
        receipt = pipe._publish_final_artifact_authority(
            xodr, seam_report={"ok": True, "seam_stats": {}}
        )

        assert receipt["final_artifact_path"] == xodr
        assert receipt["final_artifact_sha256"] == sha256_file(xodr)
        assert receipt["road_count"] == 2
        assert receipt["junction_count"] == 1
        assert receipt["lane_count"] == 5
        assert (
            receipt["structure_fingerprint"]["sha256"]
            == compute_structure_fingerprint(xodr)["sha256"]
        )
        assert receipt["map_acceptance_status"]["valid_for_experiments"] is not None
        assert receipt["topology_certification"], "literal topology certification missing"
        assert "SPEC_TOPOLOGY" in receipt["topology_certification"]
        assert receipt["semantic_authority_profile"]["release_profile"] == (
            "structural_release"
        )
        assert "inputs_manifest_path" in receipt["source_manifest_identity"]
        assert FINAL_ARTIFACT_PUBLISHED in receipt["capabilities_held"]

        on_disk = json.loads(
            (out_dir / "final_artifact_receipt.json").read_text(encoding="utf-8")
        )
        assert on_disk["final_artifact_sha256"] == receipt["final_artifact_sha256"]

    def test_every_moved_artifact_is_produced_against_the_final_path(self, staged):
        pipe, xodr, out_dir = staged
        pipe._publish_final_artifact_authority(xodr, seam_report={"ok": True})

        assert (out_dir / "map_acceptance.json").is_file()
        assert (out_dir / "map_content_fingerprint.json").is_file()
        assert pipe.preflight_calls == [xodr]
        assert pipe.determinism_calls == [xodr]

        acceptance = json.loads(
            (out_dir / "map_acceptance.json").read_text(encoding="utf-8")
        )
        assert acceptance["final_xodr_path"] == xodr
        assert acceptance["final_xodr_sha256"] == sha256_file(xodr)

        content_fp = json.loads(
            (out_dir / "map_content_fingerprint.json").read_text(encoding="utf-8")
        )
        assert content_fp["final_xodr_path"] == xodr
        assert content_fp["final_xodr_sha256"] == sha256_file(xodr)

    def test_stage_is_marked_so_the_declared_contract_stays_traceable(self, staged):
        pipe, xodr, _ = staged
        pipe._publish_final_artifact_authority(xodr, seam_report={"ok": True})
        # _run_internal marks the stage; the method itself must not double-mark.
        assert "final_artifact_authority" not in pipe.marks

    def test_publish_fails_closed_when_hygiene_never_completed(self, tmp_path):
        out_dir = tmp_path / "run"
        out_dir.mkdir()
        xodr = out_dir / "final.xodr"
        xodr.write_text(BASE_XODR, encoding="utf-8")

        pipe = _StubPipeline(str(out_dir))
        pipe._authority_mark_geometry_frozen(str(xodr))
        pipe._authority_mark_lanes_generated(str(xodr))
        # deliberately no _authority_mark_hygiene_complete

        with pytest.raises(ArtifactAuthorityError) as exc:
            pipe._publish_final_artifact_authority(str(xodr))
        assert LANES_FINAL in str(exc.value) or HYGIENE_COMPLETE in str(exc.value)

    def test_late_structural_mutation_after_publish_is_caught(self, staged):
        """THE regression: acceptance evidence exists, then something mutates
        structure. The run must fail closed instead of shipping a receipt that
        describes content that no longer exists."""
        pipe, xodr, _ = staged
        pipe._publish_final_artifact_authority(xodr, seam_report={"ok": True})

        # A late lane-width "repair" -- the shape of thing map hygiene does,
        # which used to be able to run after the evidence was written.
        with open(xodr, "w", encoding="utf-8") as fh:
            fh.write(BASE_XODR.replace('a="3.5"', 'a="2.9"'))

        with pytest.raises(ArtifactAuthorityError) as exc:
            pipe._assert_structure_frozen_unchanged(xodr, "after_tiling")
        message = str(exc.value)
        assert "STRUCTURE_FROZEN violated" in message
        assert "lane_widths" in message

    def test_late_mutation_also_makes_the_recorded_evidence_stale(self, staged):
        pipe, xodr, _ = staged
        pipe._publish_final_artifact_authority(xodr, seam_report={"ok": True})
        ledger = pipe.authority_ledger
        assert ledger.stale_evidence(xodr) == []

        with open(xodr, "w", encoding="utf-8") as fh:
            fh.write(BASE_XODR.replace('<laneLink from="-1" to="-1"/>',
                                       '<laneLink from="-1" to="-2"/>'))

        problems = ledger.stale_evidence(xodr)
        assert problems, "mutated final artifact left all evidence 'current'"
        assert any("map_acceptance" in p for p in problems)
        assert any("map_content_fingerprint" in p for p in problems)
        assert any("determinism_fingerprint" in p for p in problems)

    def test_a_second_publish_after_mutation_cannot_succeed_silently(self, staged):
        """Re-publishing without re-freezing must not paper over the mutation."""
        pipe, xodr, _ = staged
        pipe._publish_final_artifact_authority(xodr, seam_report={"ok": True})
        pipe.authority_ledger.invalidate(
            STRUCTURE_FROZEN, "late_repair", reason="re-ran hygiene"
        )
        with pytest.raises(ArtifactAuthorityError) as exc:
            pipe.authority_ledger.build_receipt(final_artifact_path=xodr)
        assert "INVALIDATED" in str(exc.value)
