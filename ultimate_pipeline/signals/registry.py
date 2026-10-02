#!/usr/bin/env python3
"""
Canonical signal-policy registry for the governed CARLA pipeline.

Addresses NEW-334 through NEW-349 by defining, for every governed signal:
  - signal_id
  - producer (module.function)
  - artifact (JSON filename or env var)
  - class (HARD_GATE | REQUIRED_WHEN_ENABLED | ADVISORY | INFORMATIONAL | EXTERNAL_BLOCKER)
  - enabled_by (list of config keys / env vars that activate the signal)
  - required_release_profiles (list of release profiles where this signal MUST be present)
  - consumer (function / stage that consumes the signal)
  - consumer_action (FAIL | ADVISORY | RECORD)
  - pass_states / failure_states / missing_states
  - skip_policy (when and how a signal may be skipped)
  - missing_policy (PASS | FAIL | BLOCKED_EXTERNAL | RECORD)

The registry is the single source of truth for "what signals are governed".
The static auditor (tools/audit_pipeline_signal_graph.py) and the final-run-verdict
computer both load from this module.
"""
from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any


class SignalClass(str, Enum):
    """Classification of a governed pipeline signal.

    HARD_GATE            -- must be PASS for final verdict to be PASS; missing or FAIL => final FAIL
    REQUIRED_WHEN_ENABLED-- required when its enabled_by predicate is True; missing => final FAIL
    ADVISORY             -- recorded but does not block final PASS; always logged
    INFORMATIONAL        -- no blocking consumer by design
    EXTERNAL_BLOCKER     -- represents external dependency; when triggered, verdict = BLOCKED_EXTERNAL
    """

    HARD_GATE = "HARD_GATE"
    REQUIRED_WHEN_ENABLED = "REQUIRED_WHEN_ENABLED"
    ADVISORY = "ADVISORY"
    INFORMATIONAL = "INFORMATIONAL"
    EXTERNAL_BLOCKER = "EXTERNAL_BLOCKER"


PROFILE_STRUCTURAL = "structural_release"
PROFILE_VISUAL = "visual_build"
PROFILE_RESEARCH = "perception_research"
PROFILE_DEBUG = "debug"


def _release_profiles(*names: str) -> list[str]:
    return list(names)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SIGNAL_REGISTRY: dict[str, dict[str, Any]] = {
    "MAP_ACCEPTANCE": {
        "signal_id": "MAP_ACCEPTANCE",
        "producer": "ultimate_pipeline.main_pipeline._publish_final_artifact_authority",
        "artifact": "map_acceptance.json",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH, PROFILE_DEBUG),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_INVALID",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": ["schema", "valid_for_experiments", "sha256", "num_roads", "num_junctions", "reason"],
    },
    "FINAL_ARTIFACT_RECEIPT": {
        "signal_id": "FINAL_ARTIFACT_RECEIPT",
        "producer": "ultimate_pipeline.main_pipeline._publish_final_artifact_authority",
        "artifact": "final_artifact_receipt.json",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_INVALID",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": ["schema", "sha256", "final_xodr", "map_acceptance_sha256", "stage_ledger_sha256"],
    },
    "CUMULATIVE_GATES": {
        "signal_id": "CUMULATIVE_GATES",
        "producer": "ultimate_pipeline.main_pipeline._final_summary_and_llm",
        "artifact": "gate_failures.json",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH, PROFILE_DEBUG),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_NONEMPTY",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": ["gate_name", "status", "reason"],
    },
    "PIPELINE_HEALTH": {
        "signal_id": "PIPELINE_HEALTH",
        "producer": "ultimate_pipeline.quality.pipeline_health_summary.write_pipeline_health_summary",
        "artifact": "pipeline_health_summary.json",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH, PROFILE_DEBUG),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_OVERALL_NOT_OK",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": ["overall_ok", "gates", "missing_required_gates", "skipped_required_gates", "malformed_gates"],
    },
    "RUN_SUMMARY": {
        "signal_id": "RUN_SUMMARY",
        "producer": "ultimate_pipeline.main_pipeline._write_run_summary",
        "artifact": "run_summary.json",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH, PROFILE_DEBUG),
        "consumer": "final_run_verdict",
        "consumer_action": "INDEX_RECORD",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": ["signals", "preflight", "tile_qa", "map_acceptance", "final_artifact_receipt"],
    },
    "ENVIRONMENT_SNAPSHOT": {
        "signal_id": "ENVIRONMENT_SNAPSHOT",
        "producer": "ultimate_pipeline.utils.environment_snapshot.write_environment_snapshot",
        "artifact": "environment_snapshot.json",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "RECORD",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": ["schema", "git_sha", "python_version", "settings"],
    },
    "VALIDATION_REPORT": {
        "signal_id": "VALIDATION_REPORT",
        "producer": "ultimate_pipeline.quality.quality_gates.run_quality_gates",
        "artifact": "validation_report_full.json",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_INVALID",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": ["schema", "summary", "domain_gap_summary"],
    },
    "FINAL_RUN_VERDICT": {
        "signal_id": "FINAL_RUN_VERDICT",
        "producer": "ultimate_pipeline.signals.verdict.write_final_run_verdict",
        "artifact": "final_run_verdict.json",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH, PROFILE_DEBUG),
        "consumer": "run_status_and_success_marker",
        "consumer_action": "FAIL_ON_NONPASS",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "BLOCKED_EXTERNAL"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": ["schema", "release_profile", "status", "blocking_failures", "blocked_external", "advisories", "required_signals"],
    },
    "SUCCESS_MARKER": {
        "signal_id": "SUCCESS_MARKER",
        "producer": "ultimate_pipeline.utils.finalize_run_pack.finalize_run_pack",
        "artifact": "SUCCESS.txt",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH),
        "consumer": "external_callers",
        "consumer_action": "RECORD",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": [],
        "invariant": "SUCCESS.txt present IFF final_run_verdict.status == PASS AND run_status == ok AND pack verifies",
    },
    "CARLA_PREFLIGHT": {
        "signal_id": "CARLA_PREFLIGHT",
        "producer": "ultimate_pipeline.pipeline_stages.stage_08_integrity._step8d_preflight_validation",
        "artifact": "carla_loadability_status.json (written only when UP_RUN_PREFLIGHT)",
        "class": SignalClass.REQUIRED_WHEN_ENABLED.value,
        "enabled_by": ["UP_RUN_PREFLIGHT"],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_INVALID_OR_BLOCKED",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "BLOCKED_EXTERNAL_IF_NO_CARLA",
        "missing_policy": "FAIL",
        "fields": ["schema", "ok", "server_version", "client_version"],
    },
    "TILE_QA": {
        "signal_id": "TILE_QA",
        "producer": "ultimate_pipeline.pipeline_stages.stage_10_tile_qa._step10_tile_qa",
        "artifact": "step10_tile_qa_status.json",
        "class": SignalClass.REQUIRED_WHEN_ENABLED.value,
        "enabled_by": ["ENABLE_SIMULATION_GATE"],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_INVALID",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "RECORD_IF_DISABLED",
        "missing_policy": "FAIL",
        "fields": ["schema", "ok", "status", "reason", "tile_count", "failures"],
    },
    "ROAD_DEFECTS": {
        "signal_id": "ROAD_DEFECTS",
        "producer": "ultimate_pipeline.pipeline_stages.stage_10_tile_qa._step10c_road_perception_screenshots",
        "artifact": "step10c_road_defects_status.json",
        "class": SignalClass.REQUIRED_WHEN_ENABLED.value,
        "enabled_by": ["ENABLE_ROAD_DEFECT_SCAN"],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_INVALID",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "RECORD_IF_DISABLED",
        "missing_policy": "FAIL",
        "fields": ["schema", "ok", "defect_count"],
    },
    "LOCAL_PERCEPTION": {
        "signal_id": "LOCAL_PERCEPTION",
        "producer": "ultimate_pipeline.pipeline_stages.stage_10_tile_qa._step10c_road_perception_screenshots",
        "artifact": "step10c_local_perception_status.json",
        "class": SignalClass.ADVISORY.value,
        "enabled_by": ["ENABLE_LOCAL_PERCEPTION"],
        "required_release_profiles": _release_profiles(PROFILE_DEBUG, PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "RECORD_ADVISE",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "RECORD_IF_DISABLED",
        "missing_policy": "RECORD",
        "fields": ["schema", "ok", "frame_count"],
    },
    "THESIS_PERCEPTION": {
        "signal_id": "THESIS_PERCEPTION",
        "producer": "ultimate_pipeline.pipeline_stages.stage_10_tile_qa._step10c_road_perception_screenshots",
        "artifact": "step10d2_thesis_perception_status.json",
        "class": SignalClass.REQUIRED_WHEN_ENABLED.value,
        "enabled_by": ["ENABLE_THESIS_PERCEPTION_CAPTURE", "UP_ENABLE_THESIS_PERCEPTION_CAPTURE"],
        "required_release_profiles": _release_profiles(PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_INVALID",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "BLOCKED_EXTERNAL_IF_NO_CARLA",
        "missing_policy": "FAIL",
        "fields": ["schema", "ok", "pair_count"],
    },
    "SCENARIORUNNER": {
        "signal_id": "SCENARIORUNNER",
        "producer": "ultimate_pipeline.pipeline_stages.stage_10_tile_qa._step10c_road_perception_screenshots",
        "artifact": "step10d3_scenariorunner_status.json",
        "class": SignalClass.REQUIRED_WHEN_ENABLED.value,
        "enabled_by": ["UP_ENABLE_SCENARIORUNNER"],
        "required_release_profiles": _release_profiles(PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_INVALID",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "BLOCKED_EXTERNAL_IF_NO_CARLA",
        "missing_policy": "FAIL",
        "fields": ["schema", "ok", "scenario_count"],
    },
    "DOMAIN_GAP": {
        "signal_id": "DOMAIN_GAP",
        "producer": "ultimate_pipeline.main_pipeline._step12_domain_gap",
        "artifact": "domain_gap_stage_status.json",
        "class": SignalClass.EXTERNAL_BLOCKER.value,
        "enabled_by": ["ENABLE_DOMAIN_GAP", "UP_ENABLE_DOMAIN_GAP"],
        "required_release_profiles": _release_profiles(PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_OR_BLOCKED_EXTERNAL",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "RECORD_IF_DISABLED",
        "missing_policy": "BLOCKED_EXTERNAL_IF_NO_MANUAL_XODR",
        "fields": ["schema", "ok", "manual_xodr_present", "domain_gap_score"],
    },
    "RQ1_DETERMINISM": {
        "signal_id": "RQ1_DETERMINISM",
        "producer": "tools.rq1_trial_run.main",
        "artifact": "rq1_run_receipt/v1 (receipt_run_XX.json)",
        "class": SignalClass.REQUIRED_WHEN_ENABLED.value,
        "enabled_by": ["UP_ENABLE_RQ1_DETERMINISM"],
        "required_release_profiles": _release_profiles(PROFILE_RESEARCH),
        "consumer": "rq1_five_run_matrix",
        "consumer_action": "FAIL_ON_SCHEMA_MISMATCH",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "RECORD_IF_DISABLED",
        "missing_policy": "FAIL",
        "fields": ["run", "status", "input_sha256", "out_dir", "xodr_sha256", "normalized_xodr_sha256", "structural_signature", "feature_counts", "topology_counts", "output_path", "tileset_digest", "map_acceptance_digest", "final_receipt_digest", "schema"],
    },
    "DETERMINISM_FINGERPRINT": {
        "signal_id": "DETERMINISM_FINGERPRINT",
        "producer": "ultimate_pipeline.main_pipeline._write_determinism_fingerprint",
        "artifact": "determinism_fingerprint.json",
        "class": SignalClass.REQUIRED_WHEN_ENABLED.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_RESEARCH, PROFILE_STRUCTURAL),
        "consumer": "final_run_verdict",
        "consumer_action": "RECORD_FAIL_ON_PERSISTENCE",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "RECORD_IF_DISABLED",
        # The producer is fail-closed since NEW-348, so absence means the run
        # never completed its fingerprint step -- not "nothing to report".
        "missing_policy": "FAIL",
        "fields": [
            "schema",
            "final_xodr",
            "final_xodr_path",
            "final_out_sha256",
            "map_sha256",
            "settings_snapshot",
            "seeds",
        ],
    },
    "EXPERIMENT_READINESS": {
        "signal_id": "EXPERIMENT_READINESS",
        "producer": "ultimate_pipeline.main_pipeline._publish_final_artifact_authority",
        "artifact": "map_acceptance.json (field: valid_for_experiments)",
        "class": SignalClass.REQUIRED_WHEN_ENABLED.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_RESEARCH),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_INVALID_FOR_EXPERIMENT",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "RECORD_IF_PROFILE_NOT_RESEARCH",
        "missing_policy": "FAIL",
        "fields": ["valid_for_experiments", "reason"],
    },
    "G6_HYGIENE": {
        "signal_id": "G6_HYGIENE",
        "producer": "ultimate_pipeline.pipeline_stages.stage_08_hygiene._step8h_map_hygiene",
        "artifact": "08h5_g6_lane_coverage_repair_report.json",
        "artifact_path": "08h5_g6_lane_coverage_repair_report.json",
        "class": SignalClass.ADVISORY.value,
        # The stage defaults this repair to ON when the variable is unset
        # (``os.getenv("UP_ENABLE_G6_LANE_COVERAGE_REPAIR", "1")``).  A plain
        # ``"UP_ENABLE_G6_LANE_COVERAGE_REPAIR"`` predicate would evaluate False
        # on an unset variable, so the report the stage writes would never be
        # read -- a dead signal in the default configuration (NEW-344).
        "enabled_by": ["not UP_ENABLE_G6_LANE_COVERAGE_REPAIR=0"],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH, PROFILE_DEBUG),
        "consumer": "final_run_verdict",
        "consumer_action": "RECORD_ADVISE",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "RECORD_IF_DISABLED",
        "missing_policy": "RECORD",
        "fields": ["ok", "status", "applied", "blocks_release", "reason"],
    },
    "CUMULATIVE_STAGE_GATES": {
        "signal_id": "CUMULATIVE_STAGE_GATES",
        "producer": "ultimate_pipeline.main_pipeline._finalize_gates",
        "artifact": "cumulative_gate_report.json",
        "artifact_path": "cumulative_gate_report.json",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": [],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH, PROFILE_DEBUG),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_NONZERO_FAILED",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": ["total", "passed", "failed", "results"],
    },
    "WRAPPED_GATE_FAILURES": {
        "signal_id": "WRAPPED_GATE_FAILURES",
        "producer": "ultimate_pipeline.main_pipeline._run_quality_gates_wrapper",
        "artifact": "gate_failures.json (wrapper + manager failures)",
        "artifact_path": "gate_failures.json",
        "class": SignalClass.HARD_GATE.value,
        "enabled_by": ["ENABLE_QUALITY_GATES_WRAPPER"],
        "required_release_profiles": _release_profiles(PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH, PROFILE_DEBUG),
        "consumer": "final_run_verdict",
        "consumer_action": "FAIL_ON_NONEMPTY",
        "pass_states": ["PASS"],
        "failure_states": ["FAIL", "INCOMPLETE"],
        "missing_states": ["MISSING"],
        "skip_policy": "NEVER",
        "missing_policy": "FAIL",
        "fields": ["gate_name", "status", "reason", "error"],
    },
}


# ---------------------------------------------------------------------------
# Artifact path resolution (release-root-relative, POSIX separators)
# ---------------------------------------------------------------------------

#: Signals whose ``artifact`` string is descriptive rather than a real
#: release-relative path.  The verdict computer needs an actual file to look
#: for, so every entry must resolve to one of these or to ``artifact_path``.
_ARTIFACT_PATHS: dict[str, str] = {
    "MAP_ACCEPTANCE": "map_acceptance.json",
    "FINAL_ARTIFACT_RECEIPT": "final_artifact_receipt.json",
    "CUMULATIVE_GATES": "gate_failures.json",
    "PIPELINE_HEALTH": "pipeline_health_summary.json",
    "RUN_SUMMARY": "run_summary.json",
    "ENVIRONMENT_SNAPSHOT": "environment_snapshot.json",
    "VALIDATION_REPORT": "logs/validation_report_full.json",
    "FINAL_RUN_VERDICT": "final_run_verdict.json",
    "SUCCESS_MARKER": "SUCCESS.txt",
    "CARLA_PREFLIGHT": "carla_loadability_status.json",
    "TILE_QA": "step10_tile_qa_status.json",
    "ROAD_DEFECTS": "step10c_road_defects_status.json",
    "LOCAL_PERCEPTION": "step10c_local_perception_status.json",
    "THESIS_PERCEPTION": "step10d2_thesis_perception_status.json",
    "SCENARIORUNNER": "step10d3_scenariorunner_status.json",
    "DOMAIN_GAP": "domain_gap_stage_status.json",
    "RQ1_DETERMINISM": "receipt_run_00.json",
    "DETERMINISM_FINGERPRINT": "determinism_fingerprint.json",
    "EXPERIMENT_READINESS": "map_acceptance.json",
    "G6_HYGIENE": "08h5_g6_lane_coverage_repair_report.json",
    "CUMULATIVE_STAGE_GATES": "cumulative_gate_report.json",
    "WRAPPED_GATE_FAILURES": "gate_failures.json",
}

#: Signals that are always evaluated for a given release profile regardless of
#: environment predicates (their producer runs unconditionally).
_ALWAYS_ON: frozenset[str] = frozenset(
    sid
    for sid, entry in SIGNAL_REGISTRY.items()
    if not entry.get("enabled_by")
)


def artifact_relpath(signal_id: str) -> str | None:
    """Return the release-root-relative path of a signal's artifact."""
    entry = SIGNAL_REGISTRY.get(signal_id)
    if entry is None:
        return None
    return entry.get("artifact_path") or _ARTIFACT_PATHS.get(signal_id) or entry.get(
        "artifact"
    )


def resolve_artifact_path(out_dir: str | os.PathLike[str], signal_id: str) -> str | None:
    """Absolute path of ``signal_id``'s artifact inside ``out_dir``."""
    rel = artifact_relpath(signal_id)
    if not rel:
        return None
    return os.path.join(str(out_dir), *rel.split("/"))


# ---------------------------------------------------------------------------
# Enablement predicates
# ---------------------------------------------------------------------------

_TRUE = {"1", "true", "yes", "on", "ok", "enabled"}
_FALSE = {"0", "false", "no", "off", "disabled"}


def _env_truthy(name: str, env: dict[str, str]) -> bool:
    return str(env.get(name, "")).strip().lower() in _TRUE


def _windows() -> bool:
    import platform as _p

    return _p.system().lower().startswith("win")


def is_signal_enabled(
    signal_id: str,
    *,
    settings: Any = None,
    env: dict[str, str] | None = None,
) -> bool:
    """Evaluate a signal's ``enabled_by`` predicate.

    Grammar (one entry per predicate, OR-ed together):

    * ``"NAME"``          -- truthy env var ``NAME`` or truthy settings attr
    * ``"not NAME"``      -- negation of the above
    * ``"NAME=VALUE"``    -- env var ``NAME`` equals ``VALUE`` (case-insensitive)

    An empty ``enabled_by`` means the producer runs unconditionally and the
    signal is always evaluated.
    """
    entry = SIGNAL_REGISTRY.get(signal_id)
    if entry is None:
        return False
    predicates = entry.get("enabled_by") or []
    if not predicates:
        return True

    env = dict(os.environ) if env is None else env

    def _value(name: str) -> bool:
        if name in env:
            return _env_truthy(name, env)
        if settings is not None:
            attr = getattr(settings, name, None)
            if attr is not None:
                return bool(attr)
        return False

    for raw in predicates:
        text = str(raw).strip()
        negate = False
        if text.lower().startswith("not "):
            negate = True
            text = text[4:].strip()
        expected: str | None = None
        if "=" in text:
            text, expected = text.split("=", 1)
            text = text.strip()
            expected = expected.strip().lower()

        if text == "windows":
            result = _windows()
        elif expected is not None:
            result = str(env.get(text, "")).strip().lower() == expected
        else:
            result = _value(text)

        if negate:
            result = not result
        if result:
            return True
    return False


def enabled_signals(
    *, settings: Any = None, env: dict[str, str] | None = None
) -> list[str]:
    return sorted(
        sid
        for sid in SIGNAL_REGISTRY
        if is_signal_enabled(sid, settings=settings, env=env)
    )


# ---------------------------------------------------------------------------
# Profile manifests
# ---------------------------------------------------------------------------

#: Release artifacts that ``finalize_run_pack`` must treat as MANDATORY for a
#: profile.  NEW-336: this is registry-derived, not a hand-maintained list, so
#: a new HARD_GATE registered for a profile automatically becomes mandatory.
PROFILE_MANDATORY_PACK_ARTIFACTS: dict[str, list[str]] = {}


def _build_profile_mandatory_pack_artifacts() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for profile in (PROFILE_STRUCTURAL, PROFILE_VISUAL, PROFILE_RESEARCH, PROFILE_DEBUG):
        paths = ["/final.xodr"]  # placeholder replaced by caller (XODR is not a signal)
        for sid, entry in SIGNAL_REGISTRY.items():
            if profile not in entry.get("required_release_profiles", []):
                continue
            if entry.get("consumer") != "final_run_verdict":
                # The run pack is the verdict's evidence set. Signals owned by
                # another consumer (the five-run matrix, external callers) are
                # not pack evidence and must not be able to fail it.
                continue
            if entry.get("class") not in (
                SignalClass.HARD_GATE.value,
                SignalClass.REQUIRED_WHEN_ENABLED.value,
            ):
                continue
            if sid == "SUCCESS_MARKER":
                continue  # produced by the pack itself
            rel = artifact_relpath(sid)
            if rel and rel not in paths:
                paths.append(rel)
        out[profile] = paths
    return out


PROFILE_MANDATORY_PACK_ARTIFACTS = _build_profile_mandatory_pack_artifacts()


def mandatory_pack_artifacts(
    profile: str,
    final_xodr: str,
    *,
    settings: Any = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Absolute/relative paths ``finalize_run_pack`` must hash for ``profile``.

    The final XODR is always mandatory (V5/NEW-202 invariant).  Signals whose
    ``enabled_by`` predicate evaluates False for this run are excluded -- a
    disabled producer must not turn into a mandatory missing artifact.
    """
    profile = canonical_release_profile(profile)
    rel_paths = PROFILE_MANDATORY_PACK_ARTIFACTS.get(
        profile, PROFILE_MANDATORY_PACK_ARTIFACTS[PROFILE_STRUCTURAL]
    )
    out = [final_xodr]
    for rel in rel_paths:
        if rel == "/final.xodr":
            continue
        out.append(rel)  # release-root-relative; pack resolves against root
    if settings is not None or env is not None:
        wanted = set(out)
        out = [final_xodr]
        for rel in rel_paths:
            if rel == "/final.xodr":
                continue
            sid = next(
                (s for s in SIGNAL_REGISTRY if artifact_relpath(s) == rel), None
            )
            if sid and not is_signal_enabled(sid, settings=settings, env=env):
                continue
            if rel in wanted:
                out.append(rel)
    return out


# ---------------------------------------------------------------------------
# Expected pipeline-health gate names (NEW-335)
# ---------------------------------------------------------------------------

#: Gates that a complete, non-abbreviated structural run is contractually
#: expected to have produced evidence for.  Anything observed beyond this is
#: recorded but not required; anything in here that is missing makes the health
#: summary (and therefore the final verdict) FAIL rather than "NOT_RUN-ish pass".
EXPECTED_HEALTH_GATES: tuple[str, ...] = (
    "geometric_continuity",
    "planview_internal_seams",
    "origin_sanity",
    "elevation_seams",
    "elevation_continuity",
    "full_map_metrics",
    "drivable_surface",
    "junction_integrity",
    "post_tiling_integrity",
    "lane_width_continuity",
    "lane_geometry_continuity",
)


def expected_health_gates() -> list[str]:
    return list(EXPECTED_HEALTH_GATES)


def registry_sha256() -> str:
    """Return a stable SHA256 of the registry itself, usable as an evidence pin."""
    import hashlib
    serialized = json.dumps({k: v for k, v in sorted(SIGNAL_REGISTRY.items())}, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def write_registry(out_dir: str | Path) -> str:
    """Write the registry as JSON to out_dir/FINAL_SIGNAL_REGISTRY.json."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "signal_registry/v1",
        "registry_sha256": registry_sha256(),
        "baseline_sha": os.getenv("UP_BASELINE_SHA", ""),
        "classes": [c.value for c in SignalClass],
        "signals": {k: v for k, v in SIGNAL_REGISTRY.items()},
    }
    p = out_dir / "FINAL_SIGNAL_REGISTRY.json"
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(p)


def classify(signal_id: str) -> SignalClass | None:
    """Return the class of a signal, or None if not registered."""
    entry = SIGNAL_REGISTRY.get(signal_id)
    if entry is None:
        return None
    return SignalClass(entry["class"])


#: ``settings.RELEASE_PROFILE`` values are UPPERCASE enum-ish names while the
#: registry speaks in lowercase profile vocabulary.  Without this map, a
#: settings profile like ``STRUCTURAL_RELEASE`` resolves to "no such profile"
#: and every ``required_release_profiles`` check silently evaluates False.
PROFILE_ALIASES: dict[str, str] = {
    "": PROFILE_STRUCTURAL,
    "debug": PROFILE_DEBUG,
    "development": PROFILE_DEBUG,
    "experimental_unsafe": PROFILE_DEBUG,
    "scenario_augmentation": PROFILE_DEBUG,
    "structural_release": PROFILE_STRUCTURAL,
    "carla_release": PROFILE_STRUCTURAL,
    "visual_build": PROFILE_VISUAL,
    "visual_release": PROFILE_VISUAL,
    "perception_research": PROFILE_RESEARCH,
    "perception_release": PROFILE_RESEARCH,
}


def canonical_release_profile(name: str | None) -> str:
    """Normalize a release-profile name (any case) to registry vocabulary."""
    key = str(name or "").strip().lower()
    return PROFILE_ALIASES.get(key, key or PROFILE_STRUCTURAL)


def required_for_profile(profile: str) -> list[str]:
    """Return the list of signal_ids that are required for a given release profile."""
    canonical = canonical_release_profile(profile)
    out: list[str] = []
    for sid, entry in SIGNAL_REGISTRY.items():
        if canonical in entry.get("required_release_profiles", []):
            out.append(sid)
    return out


if __name__ == "__main__":
    out = os.getenv("UP_SIGNAL_REGISTRY_OUT", "reports/dead_signal_hardening/20261001T000000Z")
    p = write_registry(out)
    print(f"Wrote signal registry: {p}")
    print(f"Registry sha256: {registry_sha256()}")
    print(f"Total signals: {len(SIGNAL_REGISTRY)}")
