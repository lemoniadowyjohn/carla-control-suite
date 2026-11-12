"""``RunStatus`` normalisation across the eleven source vocabularies.

The repository speaks eleven mutually incompatible status languages.  Phase 1
defines ONE normalised enum.  The mapping below is **table-driven and data**,
never hand-written into widgets, and is bidirectional where the source label is
unambiguous.

Lossiness is explicit: :data:`LOSSY_SOURCES` records every source where the
normalisation is many-to-one and therefore not reversible without the original
label.  The original raw label and its evidence timestamp are always preserved
on :class:`NormalizedStatus` so nothing is destroyed by normalising.

``UNKNOWN`` and ``NOT_EVALUATED`` are never passes.  A label this module cannot
classify resolves to ``UNKNOWN`` -- it is never guessed into ``FAIL``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping

__all__ = [
    "RunStatus", "SOURCE_VOCABULARIES", "SourceMapping", "NormalizedStatus",
    "normalize", "to_source_label", "is_lossy", "raw_status", "is_pass",
    "LOSSY_SOURCES", "NON_RUN_STATUS_SOURCES",
]


class RunStatus(str, Enum):
    """The single normalised run vocabulary."""

    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    NOT_EVALUATED = "NOT_EVALUATED"
    INCONCLUSIVE = "INCONCLUSIVE"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SourceMapping:
    """One source vocabulary and its label -> :class:`RunStatus` table."""

    source: str
    reference: str
    table: Mapping[str, RunStatus]
    #: ``True`` when the table is many-to-one, so the original label cannot be
    #: recovered from the normalised status alone.
    lossy: bool = False
    #: ``True`` when the source vocabulary is a *different kind* of thing
    #: (lease lifecycle, sensor verdicts) and must be surfaced separately
    #: instead of being forced into ``RunStatus``.
    not_a_run_status: bool = False


def _m(**kw: str) -> dict[str, RunStatus]:
    return {k: RunStatus(v) for k, v in kw.items()}


#: The eleven source vocabularies, in the order documented by
#: ``07_GUI_SPEC/GLOBAL_STATES.md`` section 3 and
#: ``02_MODULE_CATALOG/perception_and_experiments/PERCEPTION_AND_EXPERIMENTS.md`` MOD-79.
SOURCE_VOCABULARIES: tuple[SourceMapping, ...] = (
    SourceMapping(
        source="signals_verdict",
        reference="ultimate_pipeline/signals/verdict.py:70",
        table=_m(PASS="PASS", FAIL="FAIL", BLOCKED_EXTERNAL="BLOCKED_EXTERNAL",
                 NOT_EVALUATED="NOT_EVALUATED"),
    ),
    SourceMapping(
        source="cli_up_health",
        reference="ultimate_pipeline/cli.py (up health)",
        table=_m(PASS="PASS", FAIL="FAIL", INCOMPLETE="INCONCLUSIVE",
                 NOT_RUN="NOT_EVALUATED", BLOCKED_EXTERNAL="BLOCKED_EXTERNAL"),
        lossy=True,
    ),
    SourceMapping(
        source="carla_0916_import_process_contract",
        reference="ultimate_pipeline/**/carla_0916_import_process_contract.py:39",
        table=_m(PASS="PASS", FAIL="FAIL", TIMEOUT="TIMEOUT",
                 CANCELLED="CANCELLED", SPAWN_ERROR="FAIL", OUTPUT_MISSING="FAIL"),
        lossy=True,
    ),
    SourceMapping(
        source="carla_0916_large_map_contract",
        reference="ultimate_pipeline/**/carla_0916_large_map_contract.py:31-34",
        # FAIL_* family, e.g. FAIL_SPAWN / FAIL_HASH / FAIL_TOPOLOGY
        table={"FAIL": RunStatus.FAIL},
        lossy=True,
    ),
    SourceMapping(
        source="lease_store",
        reference="ultimate_pipeline/governance/single_writer/lease_store.py",
        table=_m(ACQUIRED="UNKNOWN", RUNNING="UNKNOWN", RELEASING="UNKNOWN",
                 RELEASED="UNKNOWN", STALE_RECONCILIATION_REQUIRED="UNKNOWN"),
        not_a_run_status=True,
    ),
    SourceMapping(
        source="sensor_recorder",
        reference="ultimate_pipeline/sensors/recorder.py:23-29",
        table=_m(CAPTURE_FRAME_DROP="FAIL", ARTIFACT_MISMATCH="FAIL",
                 FRAME_ID_INVALID="FAIL"),
        not_a_run_status=True,
    ),
    SourceMapping(
        source="stage_contracts_quality_status",
        reference="ultimate_pipeline/contracts/stage_contracts.py QualityStatus",
        table=_m(SKIPPED="SKIPPED", BLOCKED_EXTERNAL="BLOCKED_EXTERNAL",
                 UNKNOWN="UNKNOWN", PASS="PASS", FAIL="FAIL"),
        lossy=True,
    ),
    SourceMapping(
        source="ue426_qualification",
        reference="UE426_QUALIFICATION.json",
        table=_m(UE426_BLOCKED_OPERATOR_INSTALL="BLOCKED_EXTERNAL"),
    ),
    SourceMapping(
        source="runtime_map_identity_auto",
        reference="RUNTIME_MAP_IDENTITY_AUTO.json",
        table=_m(BLOCKED_COOK_REQUIRED="BLOCKED_EXTERNAL"),
    ),
    SourceMapping(
        source="current_map_static_release_matrix",
        reference="CURRENT_MAP_STATIC_RELEASE_MATRIX.json",
        table=_m(STALE_OR_UNBOUND="STALE"),
    ),
    SourceMapping(
        source="production_readiness_matrix",
        reference="PRODUCTION_READINESS_MATRIX.json",
        # Reported stale by the foundation audit. It must never be presented as
        # a live measurement, so anything read from it is STALE by construction.
        table=_m(STALE_OR_UNBOUND="STALE", STALE="STALE", PASS="STALE", FAIL="STALE"),
        lossy=True,
    ),
)

LOSSY_SOURCES = frozenset(m.source for m in SOURCE_VOCABULARIES if m.lossy)
NON_RUN_STATUS_SOURCES = frozenset(
    m.source for m in SOURCE_VOCABULARIES if m.not_a_run_status
)

_BY_SOURCE = {m.source: m for m in SOURCE_VOCABULARIES}


@dataclass(frozen=True)
class NormalizedStatus:
    """A normalised status that never loses the original evidence."""

    status: RunStatus
    raw: str
    source: str
    evidence_at: str = ""
    lossy: bool = False
    #: ``True`` when the source vocabulary is not a run status at all and the
    #: caller must surface it in its own panel.
    not_a_run_status: bool = False

    @property
    def is_pass(self) -> bool:
        return self.status is RunStatus.PASS

    def as_dict(self) -> dict:
        return {
            "status": self.status.value,
            "raw": self.raw,
            "source": self.source,
            "evidence_at": self.evidence_at,
            "lossy": self.lossy,
            "not_a_run_status": self.not_a_run_status,
        }


def normalize(source: str, raw: str, evidence_at: str = "") -> NormalizedStatus:
    """Normalise ``raw`` from ``source``.

    An unknown *source* or an unclassified *label* resolves to
    ``RunStatus.UNKNOWN``.  A source label is never invented and never guessed
    into a failure.
    """
    mapping = _BY_SOURCE.get(source)
    if mapping is None:
        return NormalizedStatus(RunStatus.UNKNOWN, raw, source, evidence_at, False, False)

    label = (raw or "").strip()

    if mapping.not_a_run_status and label not in mapping.table:
        # Lease lifecycle / sensor verdict vocabularies are not run statuses.
        # They stay separate rather than being forced into the enum.
        return NormalizedStatus(RunStatus.UNKNOWN, raw, source, evidence_at,
                                mapping.lossy, True)

    status = mapping.table.get(label)
    if status is None:
        status = RunStatus.UNKNOWN
    return NormalizedStatus(status, raw, source, evidence_at, mapping.lossy,
                            mapping.not_a_run_status)


def raw_status(label: str, source: str) -> str:
    """Return the canonical raw label for ``label`` within ``source``."""
    mapping = _BY_SOURCE.get(source)
    if mapping is None:
        raise KeyError(f"unknown status source: {source!r}")
    for raw, status in mapping.table.items():
        if status is RunStatus(label):
            return raw
    raise KeyError(f"{label!r} has no raw label in source {source!r}")


def to_source_label(status: RunStatus, source: str) -> str | None:
    """Bidirectional half: normalised -> raw, or ``None`` when not representable."""
    try:
        return raw_status(status, source)
    except KeyError:
        return None


def is_lossy(source: str) -> bool:
    mapping = _BY_SOURCE.get(source)
    return bool(mapping and mapping.lossy)


def is_pass(status: RunStatus) -> bool:
    """Only an explicit, source-backed PASS is a pass."""
    return status is RunStatus.PASS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")