# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/contracts/artifact_authority.py (P0-C).

The defect these tests exist for
--------------------------------
``MainPipeline._run_internal()`` used to build ``map_acceptance.json``,
``map_content_fingerprint.json``, the preflight report and the determinism
fingerprint BEFORE ``junction_link_integrity`` (which patches junction/lane
links and may select a different output file) and BEFORE ``map_hygiene``
(which can quarantine/DELETE whole roads, repair degenerate lanes, repair
lane-width discontinuities and re-chain z-seams, also returning a different
output file). The acceptance receipt therefore did not necessarily describe
the file that ended up on disk as "final".

``ArtifactAuthorityLedger`` is the runtime mechanism that makes that
undetectable-no-more: evidence is recorded together with the exact bytes and
structural fingerprint it was computed against, and a receipt refuses to be
built while any of it is stale.

Test groups
-----------
1. ``TestStructureFingerprint`` -- each of the nine structural aspects that
   must be immutable after ``STRUCTURE_FROZEN`` is genuinely measured: a
   targeted mutation of that aspect (and only that aspect) changes exactly
   that aspect's digest and the combined digest.
2. ``TestCapabilityInvalidation`` -- the revoke primitive the original
   contract explicitly lacked.
3. ``TestStructureFreezeEnforcement`` -- "nothing after STRUCTURE_FROZEN may
   mutate structure" is enforced by measurement, not by naming convention.
4. ``TestLateMutationInvalidatesAcceptance`` -- THE regression: producing
   acceptance evidence and then mutating structure afterwards must not leave
   a valid final acceptance packet.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.contracts.artifact_authority import (
    STRUCTURAL_ASPECTS,
    ArtifactAuthorityError,
    ArtifactAuthorityLedger,
    compute_structure_fingerprint,
    diff_structure_fingerprints,
    sha256_file,
    write_receipt,
)
from ultimate_pipeline.contracts.stage_capabilities import (
    FINAL_ARTIFACT_PUBLISHED,
    GEOMETRY_FROZEN,
    HYGIENE_COMPLETE,
    LANES_FINAL,
    STRUCTURE_FROZEN,
)


# ---------------------------------------------------------------------------
# Fixture: a tiny but structurally complete OpenDRIVE map
# ---------------------------------------------------------------------------

BASE_XODR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="p0c" geometryFrozen="true"/>
  <road name="R1" length="100.0" id="1" junction="-1">
    <link>
      <successor elementType="road" elementId="2" contactPoint="start"/>
    </link>
    <planView>
      <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="100.0">
        <line/>
      </geometry>
    </planView>
    <elevationProfile>
      <elevation s="0.0" a="1.0" b="0.0" c="0.0" d="0.0"/>
    </elevationProfile>
    <lanes>
      <laneOffset s="0.0" a="0.0" b="0.0" c="0.0" d="0.0"/>
      <laneSection s="0.0">
        <left>
          <lane id="1" type="driving" level="false">
            <link><successor id="1"/></link>
            <width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/>
          </lane>
        </left>
        <center>
          <lane id="0" type="none" level="false"/>
        </center>
        <right>
          <lane id="-1" type="driving" level="false">
            <link><successor id="-1"/></link>
            <width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
  <road name="R2" length="50.0" id="2" junction="100">
    <link>
      <predecessor elementType="road" elementId="1" contactPoint="end"/>
    </link>
    <planView>
      <geometry s="0.0" x="100.0" y="0.0" hdg="0.0" length="50.0">
        <line/>
      </geometry>
    </planView>
    <elevationProfile>
      <elevation s="0.0" a="1.0" b="0.0" c="0.0" d="0.0"/>
    </elevationProfile>
    <lanes>
      <laneOffset s="0.0" a="0.0" b="0.0" c="0.0" d="0.0"/>
      <laneSection s="0.0">
        <center>
          <lane id="0" type="none" level="false"/>
        </center>
        <right>
          <lane id="-1" type="driving" level="false">
            <link><predecessor id="-1"/></link>
            <width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
  <junction id="100" name="J100">
    <connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start">
      <laneLink from="-1" to="-1"/>
    </connection>
  </junction>
</OpenDRIVE>
"""


def _write_xodr(tmp_path, text=BASE_XODR, name="final.xodr"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


class TestStructureFingerprint:
    """Every listed structural aspect is actually measured."""

    def test_fingerprint_is_stable_for_identical_content(self, tmp_path):
        a = _write_xodr(tmp_path, name="a.xodr")
        b = _write_xodr(tmp_path, name="b.xodr")
        assert (
            compute_structure_fingerprint(a)["sha256"]
            == compute_structure_fingerprint(b)["sha256"]
        )

    def test_counts_are_literal_element_counts(self, tmp_path):
        counts = compute_structure_fingerprint(_write_xodr(tmp_path))["counts"]
        assert counts["road_count"] == 2
        assert counts["junction_count"] == 1
        # 3 lanes in road 1's single section + 2 lanes in road 2's.
        assert counts["lane_count"] == 5

    def test_whitespace_only_change_is_not_a_structural_change(self, tmp_path):
        """Reformatting is not a structural mutation -- the fingerprint must
        track structure, not bytes, or it would fire on every pretty-print."""
        base = _write_xodr(tmp_path, name="base.xodr")
        reformatted = _write_xodr(
            tmp_path, text=BASE_XODR.replace("\n  <road", "\n\n\n    <road"),
            name="reformatted.xodr",
        )
        assert sha256_file(base) != sha256_file(reformatted)
        assert (
            compute_structure_fingerprint(base)["sha256"]
            == compute_structure_fingerprint(reformatted)["sha256"]
        )

    @pytest.mark.parametrize(
        "aspect,old,new",
        [
            # road identity: the declared length of road 1
            ("road_identity", 'name="R1" length="100.0"', 'name="R1" length="101.0"'),
            # planView: the geometry's x
            ("plan_view", 'x="100.0" y="0.0"', 'x="100.5" y="0.0"'),
            # road links: the successor's contactPoint
            (
                "road_links",
                '<successor elementType="road" elementId="2" contactPoint="start"/>',
                '<successor elementType="road" elementId="2" contactPoint="end"/>',
            ),
            # junction connections: the laneLink mapping
            ("junction_connections", '<laneLink from="-1" to="-1"/>',
             '<laneLink from="-1" to="-2"/>'),
            # laneSection identities: a lane's declared type
            ("lane_section_identities", 'id="1" type="driving"',
             'id="1" type="sidewalk"'),
            # lane links: a lane-level successor id
            ("lane_links", "<link><successor id=\"1\"/></link>",
             "<link><successor id=\"2\"/></link>"),
            # lane widths: a width polynomial coefficient
            ("lane_widths", 'sOffset="0.0" a="3.5"', 'sOffset="0.0" a="3.25"'),
            # lane offsets: a laneOffset polynomial coefficient
            ("lane_offsets", '<laneOffset s="0.0" a="0.0"',
             '<laneOffset s="0.0" a="0.25"'),
            # road elevations: an elevation polynomial coefficient
            ("road_elevations", '<elevation s="0.0" a="1.0"',
             '<elevation s="0.0" a="2.0"'),
        ],
    )
    def test_each_structural_aspect_is_measured(self, tmp_path, aspect, old, new):
        assert old in BASE_XODR, f"fixture no longer contains {old!r}"
        before_path = _write_xodr(tmp_path, name="before.xodr")
        after_path = _write_xodr(
            tmp_path, text=BASE_XODR.replace(old, new, 1), name="after.xodr"
        )

        before = compute_structure_fingerprint(before_path)
        after = compute_structure_fingerprint(after_path)

        assert before["sha256"] != after["sha256"]
        changed = diff_structure_fingerprints(before, after)
        assert aspect in changed, (
            f"mutating {aspect} did not change its own digest; changed={changed}"
        )

    def test_all_declared_aspects_are_present_in_the_fingerprint(self, tmp_path):
        aspects = compute_structure_fingerprint(_write_xodr(tmp_path))["aspects"]
        assert set(aspects) == set(STRUCTURAL_ASPECTS)


class TestCapabilityInvalidation:
    """The revoke primitive the original contract explicitly lacked."""

    def test_provide_then_require_succeeds(self):
        ledger = ArtifactAuthorityLedger()
        ledger.provide(GEOMETRY_FROZEN, "geometry")
        ledger.require(GEOMETRY_FROZEN, "lanes")  # must not raise

    def test_require_unprovided_capability_fails_closed(self):
        ledger = ArtifactAuthorityLedger()
        with pytest.raises(ArtifactAuthorityError) as exc:
            ledger.require(GEOMETRY_FROZEN, "lanes")
        assert "has not been provided" in str(exc.value)

    def test_invalidated_capability_does_not_remain_silently_provided(self):
        ledger = ArtifactAuthorityLedger()
        ledger.provide(STRUCTURE_FROZEN, "final_artifact_authority")
        assert ledger.holds(STRUCTURE_FROZEN)

        ledger.invalidate(
            STRUCTURE_FROZEN, "map_hygiene", reason="island quarantine deleted roads"
        )
        assert not ledger.holds(STRUCTURE_FROZEN)

        with pytest.raises(ArtifactAuthorityError) as exc:
            ledger.require(STRUCTURE_FROZEN, "tiling")
        message = str(exc.value)
        assert "INVALIDATED" in message
        assert "map_hygiene" in message
        assert "island quarantine deleted roads" in message

    def test_invalidation_marks_dependent_evidence_stale(self, tmp_path):
        path = _write_xodr(tmp_path)
        ledger = ArtifactAuthorityLedger()
        ledger.freeze_structure(path, stage="final_artifact_authority")
        ledger.record_evidence(
            "map_acceptance",
            path,
            stage="final_artifact_authority",
            depends_on=(STRUCTURE_FROZEN,),
        )
        assert ledger.evidence["map_acceptance"].stale is False

        ledger.invalidate(STRUCTURE_FROZEN, "late_repair", reason="patched lane links")

        assert ledger.evidence["map_acceptance"].stale is True
        problems = ledger.stale_evidence(path)
        assert any("map_acceptance" in p for p in problems)

    def test_re_providing_a_capability_clears_the_revocation(self):
        ledger = ArtifactAuthorityLedger()
        ledger.provide(STRUCTURE_FROZEN, "first_freeze")
        ledger.invalidate(STRUCTURE_FROZEN, "late_repair", reason="mutated")
        ledger.provide(STRUCTURE_FROZEN, "second_freeze")
        ledger.require(STRUCTURE_FROZEN, "tiling")  # must not raise


class TestStructureFreezeEnforcement:
    """Enforced by measurement, not by naming convention."""

    def test_unchanged_artifact_passes(self, tmp_path):
        path = _write_xodr(tmp_path)
        ledger = ArtifactAuthorityLedger()
        ledger.freeze_structure(path, stage="final_artifact_authority")
        ledger.assert_structure_unchanged(path, where="tiling")

    def test_post_freeze_structural_mutation_is_caught(self, tmp_path):
        path = _write_xodr(tmp_path)
        ledger = ArtifactAuthorityLedger()
        ledger.freeze_structure(path, stage="final_artifact_authority")

        # A late "repair" deletes a road -- exactly what map hygiene's island
        # quarantine does, and exactly what must never happen after the freeze.
        root = ET.fromstring(BASE_XODR)
        doomed = next(r for r in root.findall("./road") if r.get("id") == "2")
        root.remove(doomed)
        (tmp_path / "final.xodr").write_bytes(ET.tostring(root, encoding="utf-8"))

        with pytest.raises(ArtifactAuthorityError) as exc:
            ledger.assert_structure_unchanged(path, where="tiling")
        assert "STRUCTURE_FROZEN violated" in str(exc.value)
        assert "road_identity" in str(exc.value)

    def test_assert_before_freeze_is_an_error_not_a_silent_pass(self, tmp_path):
        path = _write_xodr(tmp_path)
        ledger = ArtifactAuthorityLedger()
        with pytest.raises(ArtifactAuthorityError) as exc:
            ledger.assert_structure_unchanged(path, where="tiling")
        assert "before freeze_structure()" in str(exc.value)


class TestLateMutationInvalidatesAcceptance:
    """THE regression for the P0-C defect.

    Each test simulates the real bug shape -- acceptance evidence produced
    against one artifact, structure mutated afterwards -- and asserts the
    system reports the evidence as stale/invalid instead of silently treating
    it as still current.
    """

    def _frozen_ledger_with_acceptance(self, tmp_path):
        path = _write_xodr(tmp_path)
        ledger = ArtifactAuthorityLedger()
        ledger.provide(GEOMETRY_FROZEN, "geometry")
        ledger.provide(LANES_FINAL, "map_hygiene")
        ledger.provide(HYGIENE_COMPLETE, "map_hygiene")
        ledger.freeze_structure(path, stage="final_artifact_authority")
        ledger.record_evidence(
            "map_acceptance",
            path,
            stage="final_artifact_authority",
            depends_on=(STRUCTURE_FROZEN,),
        )
        ledger.record_evidence(
            "map_content_fingerprint",
            path,
            stage="final_artifact_authority",
            depends_on=(STRUCTURE_FROZEN,),
        )
        return ledger, path

    def test_clean_run_produces_a_complete_receipt(self, tmp_path):
        ledger, path = self._frozen_ledger_with_acceptance(tmp_path)
        acceptance_path = tmp_path / "map_acceptance.json"
        acceptance_path.write_text("{}", encoding="utf-8")
        source_manifest = tmp_path / "inputs_manifest.json"
        source_manifest.write_text('{"inputs": {}}', encoding="utf-8")
        source_manifest_identity = {
            "inputs_manifest_path": str(source_manifest),
            "inputs_manifest_sha256": sha256_file(str(source_manifest)),
        }
        receipt = ledger.build_receipt(
            final_artifact_path=path,
            map_acceptance={"valid_for_experiments": True, "failed_gates": []},
            topology_certification={"SPEC_TOPOLOGY": "COMPLETE"},
            semantic_authority_profile={"release_profile": "structural_release"},
            source_manifest_identity=source_manifest_identity,
            receipt_root=str(tmp_path),
            acceptance_receipt_path=str(acceptance_path),
        )

        # Every field the P0-C receipt schema is required to carry.
        assert receipt["final_artifact_path"] == path
        assert receipt["final_artifact_sha256"] == sha256_file(path)
        assert receipt["road_count"] == 2
        assert receipt["junction_count"] == 1
        assert receipt["lane_count"] == 5
        assert receipt["structure_fingerprint"]["sha256"]
        assert receipt["map_acceptance_status"]["valid_for_experiments"] is True
        assert receipt["topology_certification"] == {"SPEC_TOPOLOGY": "COMPLETE"}
        assert receipt["semantic_authority_profile"] == {
            "release_profile": "structural_release"
        }
        assert receipt["source_manifest_identity"] == source_manifest_identity
        assert receipt["source_manifest"]["sha256"] == source_manifest_identity["inputs_manifest_sha256"]
        assert receipt["schema_version"] == 1
        assert receipt["final_xodr"]["path"] == "final.xodr"
        assert receipt["acceptance_receipt"]["path"] == "map_acceptance.json"
        assert FINAL_ARTIFACT_PUBLISHED in receipt["capabilities_held"]
        assert STRUCTURE_FROZEN in receipt["capabilities_held"]

        out = write_receipt(str(tmp_path / "run"), receipt)
        assert json.loads(open(out, encoding="utf-8").read())["road_count"] == 2

    def test_late_structural_mutation_blocks_the_receipt(self, tmp_path):
        """Acceptance evidence first, structural mutation after: the packet
        must not build."""
        ledger, path = self._frozen_ledger_with_acceptance(tmp_path)

        # A late lane-link patch -- the junction-link-integrity stage's own
        # behavior, which used to run AFTER acceptance was written.
        (tmp_path / "final.xodr").write_text(
            BASE_XODR.replace('<laneLink from="-1" to="-1"/>',
                              '<laneLink from="-1" to="-2"/>'),
            encoding="utf-8",
        )

        with pytest.raises(ArtifactAuthorityError) as exc:
            ledger.build_receipt(final_artifact_path=path)
        assert "STRUCTURE_FROZEN violated" in str(exc.value)
        assert "junction_connections" in str(exc.value)

    def test_evidence_computed_against_a_superseded_file_is_detected(self, tmp_path):
        """The literal original bug: hygiene returns a DIFFERENT output path,
        so the acceptance receipt describes a file that is not the published
        final artifact."""
        pre_hygiene = _write_xodr(tmp_path, name="08_final.xodr")
        ledger = ArtifactAuthorityLedger()
        ledger.provide(GEOMETRY_FROZEN, "geometry")
        ledger.provide(LANES_FINAL, "map_hygiene")
        ledger.provide(HYGIENE_COMPLETE, "map_hygiene")
        ledger.freeze_structure(pre_hygiene, stage="final_artifact_authority")
        ledger.record_evidence(
            "map_acceptance",
            pre_hygiene,
            stage="final_artifact_authority",
            depends_on=(STRUCTURE_FROZEN,),
        )

        # Island quarantine writes a new artifact with one road removed.
        post_hygiene = _write_xodr(
            tmp_path,
            text=BASE_XODR.replace('<laneOffset s="0.0" a="0.0"',
                                   '<laneOffset s="0.0" a="0.75"'),
            name="08h1_island_quarantined.xodr",
        )

        problems = ledger.stale_evidence(post_hygiene)
        assert problems, (
            "acceptance evidence computed against the pre-hygiene artifact must "
            "not be reported as current for the post-hygiene published artifact"
        )
        assert any("08_final.xodr" in p for p in problems)

        with pytest.raises(ArtifactAuthorityError):
            ledger.assert_evidence_current(post_hygiene)

    def test_receipt_refuses_to_build_without_structure_frozen(self, tmp_path):
        path = _write_xodr(tmp_path)
        ledger = ArtifactAuthorityLedger()
        with pytest.raises(ArtifactAuthorityError) as exc:
            ledger.build_receipt(final_artifact_path=path)
        assert STRUCTURE_FROZEN in str(exc.value)

    def test_receipt_refuses_to_build_after_structure_frozen_is_invalidated(
        self, tmp_path
    ):
        ledger, path = self._frozen_ledger_with_acceptance(tmp_path)
        ledger.invalidate(
            STRUCTURE_FROZEN,
            "late_hygiene_rerun",
            reason="quarantined 30 more roads",
        )
        with pytest.raises(ArtifactAuthorityError) as exc:
            ledger.build_receipt(final_artifact_path=path)
        assert "INVALIDATED" in str(exc.value)
        assert "late_hygiene_rerun" in str(exc.value)

    def test_byte_level_mutation_without_structural_change_is_still_caught(
        self, tmp_path
    ):
        """Even a non-structural edit (a header attribute) must invalidate the
        fingerprint/determinism evidence, which is byte-level by definition."""
        ledger, path = self._frozen_ledger_with_acceptance(tmp_path)
        (tmp_path / "final.xodr").write_text(
            BASE_XODR.replace('name="p0c"', 'name="p0c-edited"'), encoding="utf-8"
        )
        # Structure is unchanged...
        ledger.assert_structure_unchanged(path, where="check")
        # ...but the bytes are not, so the receipt still must not build.
        with pytest.raises(ArtifactAuthorityError) as exc:
            ledger.build_receipt(final_artifact_path=path)
        assert "content changed after the evidence was produced" in str(exc.value)
