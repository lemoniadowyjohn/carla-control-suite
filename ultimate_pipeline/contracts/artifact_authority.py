# ultimate_pipeline/contracts/artifact_authority.py
# -*- coding: utf-8 -*-

"""Final-artifact authority: structural fingerprints + a runtime capability ledger.

Why this module exists (P0 work package C, 2026-09-18)
------------------------------------------------------
``MainPipeline._run_internal()`` used to build its pipeline-level acceptance
and fingerprint evidence *before* the last two stages that are still allowed
to mutate the map:

- ``map_acceptance.json``            (main_pipeline.py, pre-fix lines 2315-2326)
- ``map_content_fingerprint.json``   (pre-fix line 2336)
- ``_step8d_preflight_validation``   (pre-fix line 2343)
- ``_write_determinism_fingerprint`` (pre-fix line 2344)

...all ran BEFORE:

- ``_mark_stage("junction_link_integrity")`` + ``run_junction_link_integrity_gate``
  (pre-fix lines 2347-2356), which can PATCH junction/lane links and even
  select a different output file (``final_out = gate_result["final_xodr"]``), and
- ``_mark_stage("map_hygiene")`` + ``_step8h_map_hygiene`` (pre-fix lines
  2389-2390), which can quarantine/DELETE whole roads, repair degenerate
  lanes, repair lane-width discontinuities and re-chain z-seams, again
  returning a different output file.

So the acceptance receipt and both fingerprints could certify a PRE-FINAL
XODR: a different byte stream, a different structure, and sometimes literally
a different path than the file the run publishes as "final".

What this module provides
-------------------------
1. :func:`compute_structure_fingerprint` -- a deterministic, aspect-wise
   digest of exactly the structural material that must not move after the
   structural freeze: road identity, planView, road links, junction
   connections, laneSection identities, lane links, lane widths, lane offsets
   and road elevations.
2. :class:`ArtifactAuthorityLedger` -- a *runtime* capability ledger that
   records which lifecycle capabilities currently hold, which evidence
   artifact was computed against which exact bytes, and which capabilities
   have been INVALIDATED. Evidence recorded against bytes that no longer
   match is detected as STALE, fail-closed, instead of being silently
   treated as current.
3. :meth:`ArtifactAuthorityLedger.build_receipt` -- the final acceptance
   receipt, which refuses to be produced at all while any evidence is stale
   or any required capability has been revoked.

This is deliberately I/O-light and offline: parse + hash only. No CARLA, no
Unreal, no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ultimate_pipeline.contracts.stage_capabilities import (
    FINAL_ARTIFACT_PUBLISHED,
    STRUCTURE_FROZEN,
)


class ArtifactAuthorityError(RuntimeError):
    """Raised when final-artifact authority is violated.

    Two distinct violations share this type on purpose -- both mean "the
    receipt you are about to write does not describe the file on disk":

    * evidence recorded against content that has since changed (STALE), and
    * a capability that was revoked and never re-established.
    """


# ---------------------------------------------------------------------------
# Structural fingerprint
# ---------------------------------------------------------------------------

#: The structural aspects that must be immutable after ``STRUCTURE_FROZEN``.
#: This tuple is the machine-readable form of the P0-C rule "nothing after
#: STRUCTURE_FROZEN may mutate road identity, planView, road links, junction
#: connections, laneSection identities, lane links, lane widths, lane offsets
#: or road elevations".
STRUCTURAL_ASPECTS: Tuple[str, ...] = (
    "road_identity",
    "plan_view",
    "road_links",
    "junction_connections",
    "lane_section_identities",
    "lane_links",
    "lane_widths",
    "lane_offsets",
    "road_elevations",
)


def _attrs(el: Any, keys: Sequence[str]) -> str:
    """Render selected attributes as literal text.

    The raw XML attribute *strings* are used rather than parsed floats so the
    digest can never drift because of float formatting/round-tripping -- a
    byte-level change to a coordinate is a structural change.
    """
    return "|".join(f"{k}={el.get(k)!r}" for k in keys)


def _link_text(link_el: Any) -> str:
    if link_el is None:
        return ""
    parts: List[str] = []
    for tag in ("predecessor", "successor"):
        child = link_el.find(f"./{tag}")
        if child is None:
            continue
        rendered = ";".join(f"{k}={v!r}" for k, v in sorted(child.attrib.items()))
        parts.append(f"{tag}({rendered})")
    return ",".join(parts)


def _sorted_roads(root: Any) -> List[Any]:
    # Sort by road id so a pure re-ordering of <road> elements in the file is
    # not reported as a structural mutation (it is not one), while any change
    # to the road set itself is.
    return sorted(root.findall(".//road"), key=lambda r: str(r.get("id")))


def _aspect_lines(root: Any) -> Dict[str, List[str]]:
    """Build the canonical per-aspect line lists for one OpenDRIVE root."""
    lines: Dict[str, List[str]] = {name: [] for name in STRUCTURAL_ASPECTS}

    for road in _sorted_roads(root):
        rid = str(road.get("id"))

        lines["road_identity"].append(
            f"{rid}::{_attrs(road, ('id', 'name', 'length', 'junction', 'rule'))}"
        )

        plan_view = road.find("./planView")
        if plan_view is not None:
            for gi, geom in enumerate(plan_view.findall("./geometry")):
                shape = ""
                for child in list(geom):
                    rendered = ";".join(
                        f"{k}={v!r}" for k, v in sorted(child.attrib.items())
                    )
                    shape += f"<{child.tag} {rendered}>"
                lines["plan_view"].append(
                    f"{rid}#{gi}::"
                    f"{_attrs(geom, ('s', 'x', 'y', 'hdg', 'length'))}::{shape}"
                )

        lines["road_links"].append(f"{rid}::{_link_text(road.find('./link'))}")

        elevation_profile = road.find("./elevationProfile")
        if elevation_profile is not None:
            for ei, elev in enumerate(elevation_profile.findall("./elevation")):
                lines["road_elevations"].append(
                    f"{rid}#{ei}::{_attrs(elev, ('s', 'a', 'b', 'c', 'd'))}"
                )

        lanes_el = road.find("./lanes")
        if lanes_el is None:
            continue

        for oi, offset in enumerate(lanes_el.findall("./laneOffset")):
            lines["lane_offsets"].append(
                f"{rid}#{oi}::{_attrs(offset, ('s', 'a', 'b', 'c', 'd'))}"
            )

        for si, section in enumerate(lanes_el.findall("./laneSection")):
            section_lane_ids: List[str] = []
            for side in ("left", "center", "right"):
                side_el = section.find(f"./{side}")
                if side_el is None:
                    continue
                for lane in side_el.findall("./lane"):
                    lid = str(lane.get("id"))
                    section_lane_ids.append(f"{side}:{lid}:{lane.get('type')}")
                    key = f"{rid}#{si}#{side}#{lid}"
                    lines["lane_links"].append(
                        f"{key}::{_link_text(lane.find('./link'))}"
                    )
                    for wi, width in enumerate(lane.findall("./width")):
                        lines["lane_widths"].append(
                            f"{key}#{wi}::"
                            f"{_attrs(width, ('sOffset', 'a', 'b', 'c', 'd'))}"
                        )
            lines["lane_section_identities"].append(
                f"{rid}#{si}::s={section.get('s')!r}::"
                + ",".join(section_lane_ids)
            )

    for junction in sorted(root.findall(".//junction"), key=lambda j: str(j.get("id"))):
        jid = str(junction.get("id"))
        for ci, conn in enumerate(junction.findall("./connection")):
            lane_links = ",".join(
                _attrs(ll, ("from", "to")) for ll in conn.findall("./laneLink")
            )
            lines["junction_connections"].append(
                f"{jid}#{ci}::"
                f"{_attrs(conn, ('id', 'incomingRoad', 'connectingRoad', 'contactPoint'))}"
                f"::{lane_links}"
            )

    return lines


def _digest(lines: Iterable[str]) -> str:
    h = hashlib.sha256()
    for line in lines:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def structure_counts(root: Any) -> Dict[str, int]:
    """Road / junction / lane counts for the acceptance receipt.

    ``lane_count`` counts every ``<lane>`` element in every lane section,
    including the centre lane, so it is a literal element count and not a
    filtered, policy-dependent number.
    """
    road_count = len(root.findall(".//road"))
    junction_count = len(root.findall(".//junction"))
    lane_count = len(root.findall(".//laneSection//lane"))
    return {
        "road_count": road_count,
        "junction_count": junction_count,
        "lane_count": lane_count,
    }


def compute_structure_fingerprint(source: Any) -> Dict[str, Any]:
    """Fingerprint the structural content of an OpenDRIVE artifact.

    ``source`` may be a path (``str``/``os.PathLike``) or an already-parsed
    ``Element`` root.

    Returns a dict with a per-aspect digest map, a combined ``sha256`` over
    all aspects, and literal road/junction/lane counts. Two files with the
    same combined digest have byte-identical structural material in every
    aspect listed in :data:`STRUCTURAL_ASPECTS`.
    """
    if isinstance(source, (str, os.PathLike)):
        root = ET.parse(os.fspath(source)).getroot()
    else:
        root = source

    lines = _aspect_lines(root)
    aspects = {name: _digest(lines[name]) for name in STRUCTURAL_ASPECTS}
    combined = hashlib.sha256()
    for name in STRUCTURAL_ASPECTS:
        combined.update(f"{name}={aspects[name]}\n".encode("utf-8"))

    return {
        "aspects": aspects,
        "aspect_line_counts": {name: len(lines[name]) for name in STRUCTURAL_ASPECTS},
        "sha256": combined.hexdigest(),
        "counts": structure_counts(root),
    }


def diff_structure_fingerprints(
    before: Dict[str, Any], after: Dict[str, Any]
) -> List[str]:
    """Return the names of structural aspects that differ between two prints."""
    before_aspects = (before or {}).get("aspects", {}) or {}
    after_aspects = (after or {}).get("aspects", {}) or {}
    return [
        name
        for name in STRUCTURAL_ASPECTS
        if before_aspects.get(name) != after_aspects.get(name)
    ]


def sha256_file(path: str) -> Optional[str]:
    """SHA-256 of a file's exact bytes, or ``None`` if it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Runtime capability ledger
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EvidenceRecord:
    """One piece of derived evidence and the exact content it describes."""

    name: str
    artifact_path: str
    artifact_sha256: Optional[str]
    structure_sha256: Optional[str]
    stage: str
    depends_on: Tuple[str, ...]
    recorded_at_utc: str
    stale_reason: Optional[str] = None

    @property
    def stale(self) -> bool:
        return self.stale_reason is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "structure_sha256": self.structure_sha256,
            "stage": self.stage,
            "depends_on": list(self.depends_on),
            "recorded_at_utc": self.recorded_at_utc,
            "stale": self.stale,
            "stale_reason": self.stale_reason,
        }


class ArtifactAuthorityLedger:
    """Tracks lifecycle capabilities and evidence freshness during one run.

    The ledger is the runtime half of
    ``ultimate_pipeline.contracts.stage_capabilities`` (which validates a
    *declared* stage order statically). Where the static contract says "this
    order is legal", the ledger says "and here is what actually happened, and
    whether the evidence we are about to publish still describes the artifact
    we are about to publish".
    """

    def __init__(self) -> None:
        self._held: Dict[str, Dict[str, Any]] = {}
        self._revoked: Dict[str, Dict[str, Any]] = {}
        self._evidence: Dict[str, EvidenceRecord] = {}
        self._structure_baseline: Optional[Dict[str, Any]] = None
        self._structure_baseline_path: Optional[str] = None
        self.history: List[Dict[str, Any]] = []

    # -- capabilities ------------------------------------------------------

    def provide(
        self, capability: str, stage: str, *, evidence: Optional[str] = None
    ) -> None:
        """Declare that *capability* now holds, as of *stage*."""
        self._held[capability] = {
            "capability": capability,
            "stage": stage,
            "evidence": evidence,
            "at_utc": _utc_now(),
        }
        self._revoked.pop(capability, None)
        self.history.append(
            {"event": "provide", "capability": capability, "stage": stage}
        )

    def invalidate(self, capability: str, stage: str, *, reason: str) -> None:
        """Revoke *capability* and mark every piece of evidence that depended
        on it as stale.

        This is the primitive the old contract explicitly lacked ("this model
        has no 'revokes' primitive"). Without it, a capability could remain
        silently "provided" after the thing it asserted stopped being true.
        """
        self._held.pop(capability, None)
        self._revoked[capability] = {
            "capability": capability,
            "stage": stage,
            "reason": reason,
            "at_utc": _utc_now(),
        }
        for record in self._evidence.values():
            if capability in record.depends_on and not record.stale:
                record.stale_reason = (
                    f"capability {capability!r} was invalidated by stage "
                    f"{stage!r} after this evidence was recorded ({reason})"
                )
        self.history.append(
            {
                "event": "invalidate",
                "capability": capability,
                "stage": stage,
                "reason": reason,
            }
        )

    def holds(self, capability: str) -> bool:
        return capability in self._held

    def require(self, capability: str, stage: str) -> None:
        """Fail closed unless *capability* currently holds."""
        if capability in self._held:
            return
        revoked = self._revoked.get(capability)
        if revoked is not None:
            raise ArtifactAuthorityError(
                f"stage {stage!r} requires capability {capability!r}, which was "
                f"INVALIDATED by stage {revoked['stage']!r} "
                f"({revoked['reason']}) and never re-established"
            )
        raise ArtifactAuthorityError(
            f"stage {stage!r} requires capability {capability!r}, which has "
            "not been provided by any earlier stage in this run"
        )

    # -- structural freeze -------------------------------------------------

    def freeze_structure(self, artifact_path: str, *, stage: str) -> Dict[str, Any]:
        """Take the authoritative structural baseline and provide
        ``STRUCTURE_FROZEN``.

        Must be called only after every permitted road/lane/topology/hygiene
        mutation is complete.
        """
        fingerprint = compute_structure_fingerprint(artifact_path)
        self._structure_baseline = fingerprint
        self._structure_baseline_path = artifact_path
        self.provide(STRUCTURE_FROZEN, stage, evidence=fingerprint["sha256"])
        return fingerprint

    @property
    def structure_baseline(self) -> Optional[Dict[str, Any]]:
        return self._structure_baseline

    def assert_structure_unchanged(self, artifact_path: str, *, where: str) -> None:
        """Fail closed if structural material changed since the freeze.

        This is the enforcement behind "nothing after ``STRUCTURE_FROZEN``
        may mutate road identity, planView, road links, junction connections,
        laneSection identities, lane links, lane widths, lane offsets or road
        elevations" -- it is a measurement, not a naming convention.
        """
        if self._structure_baseline is None:
            raise ArtifactAuthorityError(
                f"assert_structure_unchanged({where!r}) called before "
                "freeze_structure(); there is no baseline to compare against"
            )
        self.require(STRUCTURE_FROZEN, where)
        current = compute_structure_fingerprint(artifact_path)
        if current["sha256"] == self._structure_baseline["sha256"]:
            return
        changed = diff_structure_fingerprints(self._structure_baseline, current)
        raise ArtifactAuthorityError(
            f"STRUCTURE_FROZEN violated at {where!r}: structural aspects "
            f"{sorted(changed)} changed after the structural freeze "
            f"(baseline {self._structure_baseline['sha256'][:16]}... from "
            f"{self._structure_baseline_path!r}, now "
            f"{current['sha256'][:16]}... from {artifact_path!r}). A stage "
            "that must mutate structure has to invalidate STRUCTURE_FROZEN "
            "and force every derived artifact to be regenerated."
        )

    # -- evidence ----------------------------------------------------------

    def record_evidence(
        self,
        name: str,
        artifact_path: str,
        *,
        stage: str,
        depends_on: Sequence[str] = (),
    ) -> EvidenceRecord:
        """Record that evidence *name* was computed against *artifact_path*.

        The file's exact bytes and its structural fingerprint are captured, so
        a later mutation of that file (or a switch to a different final file)
        is detectable rather than assumed away.
        """
        for capability in depends_on:
            self.require(capability, f"{stage}:{name}")
        try:
            structure_sha = compute_structure_fingerprint(artifact_path)["sha256"]
        except Exception:
            structure_sha = None
        record = EvidenceRecord(
            name=name,
            artifact_path=artifact_path,
            artifact_sha256=sha256_file(artifact_path),
            structure_sha256=structure_sha,
            stage=stage,
            depends_on=tuple(depends_on),
            recorded_at_utc=_utc_now(),
        )
        self._evidence[name] = record
        self.history.append({"event": "evidence", "name": name, "stage": stage})
        return record

    @property
    def evidence(self) -> Dict[str, EvidenceRecord]:
        return dict(self._evidence)

    def stale_evidence(self, final_artifact_path: str) -> List[str]:
        """Re-measure every evidence record against the real final artifact.

        Returns human-readable descriptions of every record that no longer
        describes ``final_artifact_path``. An empty list means every receipt
        this run is about to publish genuinely describes the published file.
        """
        problems: List[str] = []
        final_sha = sha256_file(final_artifact_path)
        try:
            final_structure = compute_structure_fingerprint(final_artifact_path)[
                "sha256"
            ]
        except Exception:
            final_structure = None

        for name in sorted(self._evidence):
            record = self._evidence[name]
            if record.stale:
                problems.append(f"{name}: {record.stale_reason}")
                continue
            if os.path.normcase(os.path.abspath(record.artifact_path)) != os.path.normcase(
                os.path.abspath(final_artifact_path)
            ):
                problems.append(
                    f"{name}: computed against {record.artifact_path!r}, but the "
                    f"published final artifact is {final_artifact_path!r}"
                )
                continue
            if record.artifact_sha256 != final_sha:
                problems.append(
                    f"{name}: computed against sha256 "
                    f"{(record.artifact_sha256 or 'unreadable')[:16]}..., but the "
                    f"published final artifact is now "
                    f"{(final_sha or 'unreadable')[:16]}... (content changed after "
                    "the evidence was produced)"
                )
                continue
            if record.structure_sha256 != final_structure:
                problems.append(
                    f"{name}: structural fingerprint changed after the evidence "
                    f"was produced ({(record.structure_sha256 or 'n/a')[:16]}... -> "
                    f"{(final_structure or 'n/a')[:16]}...)"
                )
        return problems

    def assert_evidence_current(self, final_artifact_path: str) -> None:
        """Fail closed if any recorded evidence is stale."""
        problems = self.stale_evidence(final_artifact_path)
        if problems:
            raise ArtifactAuthorityError(
                "Final acceptance evidence does not describe the published "
                f"artifact {final_artifact_path!r}:\n  - " + "\n  - ".join(problems)
            )

    # -- receipt -----------------------------------------------------------

    def build_receipt(
        self,
        *,
        final_artifact_path: str,
        map_acceptance: Optional[Dict[str, Any]] = None,
        topology_certification: Optional[Dict[str, Any]] = None,
        semantic_authority_profile: Optional[Dict[str, Any]] = None,
        source_manifest_identity: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
        stage: str = "final_artifact_authority",
    ) -> Dict[str, Any]:
        """Build the final acceptance receipt for the published artifact.

        Fails closed (``ArtifactAuthorityError``) if any recorded evidence is
        stale or if ``STRUCTURE_FROZEN`` is not currently held -- i.e. a run
        that mutated structure after producing acceptance evidence cannot
        emit a valid final acceptance packet at all.
        """
        self.require(STRUCTURE_FROZEN, stage)
        self.assert_structure_unchanged(final_artifact_path, where=stage)
        self.assert_evidence_current(final_artifact_path)

        fingerprint = compute_structure_fingerprint(final_artifact_path)
        acceptance = map_acceptance or {}
        certification = topology_certification or {}

        receipt: Dict[str, Any] = {
            "schema": "final_artifact_authority/v1",
            "generated_at_utc": _utc_now(),
            "final_artifact_path": final_artifact_path,
            "final_artifact_sha256": sha256_file(final_artifact_path),
            "road_count": fingerprint["counts"]["road_count"],
            "junction_count": fingerprint["counts"]["junction_count"],
            "lane_count": fingerprint["counts"]["lane_count"],
            "structure_fingerprint": fingerprint,
            "map_acceptance_status": {
                "valid_for_experiments": acceptance.get("valid_for_experiments"),
                "failed_gates": acceptance.get("failed_gates", []),
                "hard_fail_reasons": acceptance.get("hard_fail_reasons", []),
                "soft_warnings": acceptance.get("soft_warnings", []),
                "acceptance_artifact": acceptance.get("acceptance_artifact"),
            },
            "topology_certification": certification,
            "semantic_authority_profile": semantic_authority_profile,
            "source_manifest_identity": source_manifest_identity,
            "capabilities_held": sorted(self._held),
            "capabilities_invalidated": {
                name: dict(info) for name, info in sorted(self._revoked.items())
            },
            "evidence": {
                name: record.to_dict() for name, record in sorted(self._evidence.items())
            },
            "history": list(self.history),
        }
        if extra:
            receipt.update(extra)

        self.provide(FINAL_ARTIFACT_PUBLISHED, stage, evidence=receipt["final_artifact_sha256"])
        receipt["capabilities_held"] = sorted(self._held)
        return receipt


def write_receipt(out_dir: str, receipt: Dict[str, Any]) -> str:
    """Persist a receipt as ``<out_dir>/final_artifact_authority.json``."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "final_artifact_authority.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2, sort_keys=True, default=str, ensure_ascii=True)
    return path
