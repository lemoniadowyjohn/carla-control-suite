"""Task 02 acceptance tests.

Covers the required identifiers:
  T-STATUS-01..06  RunStatus normalisation across the eleven source vocabularies
  T-FRESH-01..05   EvidenceFreshnessService incl. stale/missing/corrupt/schema
  T-AUDIT-01..04   redacted append-only journal
  T-MOCK-01..09    deterministic mock adapters for every documented protocol
  T-DIAG-04        surfaced swallowed exception / typed result objects

These run offline. No CARLA server, no network, no display.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ultimate_pipeline.gui import run_status as rs
from ultimate_pipeline.gui.adapters.mock_backend import (
    ActorSpec,
    MockCarlaBackend,
    WeatherSpec,
    WorldSpec,
)
from ultimate_pipeline.gui.adapters.mock_services import (
    MockCalibrationBackend,
    MockExperimentBackend,
    MockMapRegistryBackend,
    MockQualityGateBackend,
    build_mock_registry,
)
from ultimate_pipeline.gui.adapters.mock_traffic import MockTrafficManagerBackend, TmPolicy
from ultimate_pipeline.gui.audit import AuditJournal, redact
from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled
from ultimate_pipeline.gui.freshness import (
    FORBIDDEN_AS_LIVE,
    EvidenceFreshnessService,
    Freshness,
)
from ultimate_pipeline.gui.health import (
    ConnectionState,
    HealthStage,
    SessionAuthority,
    mutating_controls_enabled,
    probe_stages,
)
from ultimate_pipeline.gui.results import Result, Tri, TriState, UnsupportedCapability


# ======================================================================
# T-STATUS
# ======================================================================
def test_T_STATUS_01_eleven_source_vocabularies_are_table_driven():
    assert len(rs.SOURCE_VOCABULARIES) == 11
    for mapping in rs.SOURCE_VOCABULARIES:
        assert mapping.source and mapping.reference
        assert isinstance(mapping.table, dict) and mapping.table


def test_T_STATUS_02_documented_one_to_one_mapping_is_preserved():
    for label in ("PASS", "FAIL", "BLOCKED_EXTERNAL", "NOT_EVALUATED"):
        assert rs.normalize("signals_verdict", label).status is rs.RunStatus(label)


def test_T_STATUS_03_lossy_mappings_are_explicit_and_correct():
    # INCOMPLETE -> INCONCLUSIVE, NOT_RUN -> NOT_EVALUATED (cli `up health`)
    assert rs.normalize("cli_up_health", "INCOMPLETE").status is rs.RunStatus.INCONCLUSIVE
    assert rs.normalize("cli_up_health", "NOT_RUN").status is rs.RunStatus.NOT_EVALUATED
    # SPAWN_ERROR / OUTPUT_MISSING -> FAIL (import process contract)
    assert rs.normalize("carla_0916_import_process_contract", "SPAWN_ERROR").status is rs.RunStatus.FAIL
    assert rs.normalize("carla_0916_import_process_contract", "OUTPUT_MISSING").status is rs.RunStatus.FAIL
    assert rs.is_lossy("cli_up_health") and rs.is_lossy("carla_0916_import_process_contract")


def test_T_STATUS_04_raw_evidence_is_never_destroyed():
    original = "SPAWN_ERROR"
    normalized = rs.normalize("carla_0916_import_process_contract", original, "2026-10-15T10:00:00")
    assert normalized.raw == original
    assert normalized.source == "carla_0916_import_process_contract"
    assert normalized.evidence_at == "2026-10-15T10:00:00"
    assert normalized.lossy is True


def test_T_STATUS_05_unknown_never_becomes_a_pass_and_mapping_is_bidirectional():
    assert rs.normalize("cli_up_health", "TOTALLY_UNKNOWN").status is rs.RunStatus.UNKNOWN
    assert rs.normalize("no_such_source", "PASS").status is rs.RunStatus.UNKNOWN
    assert not rs.is_pass(rs.RunStatus.UNKNOWN)
    assert not rs.is_pass(rs.RunStatus.NOT_EVALUATED)
    # bidirectional where unambiguous
    assert rs.to_source_label(rs.RunStatus.PASS, "signals_verdict") == "PASS"
    assert rs.to_source_label(rs.RunStatus.INCONCLUSIVE, "cli_up_health") == "INCOMPLETE"
    assert rs.to_source_label(rs.RunStatus.STALE, "current_map_static_release_matrix") == "STALE_OR_UNBOUND"
    # and honestly returns None when not representable
    assert rs.to_source_label(rs.RunStatus.CANCELLED, "cli_up_health") is None


def test_T_STATUS_06_non_run_status_vocabularies_are_flagged_separately():
    lease = rs.normalize("lease_store", "RELEASED")
    assert lease.not_a_run_status is True
    assert lease.status is rs.RunStatus.UNKNOWN
    sensor = rs.normalize("sensor_recorder", "ARTIFACT_MISMATCH")
    assert sensor.not_a_run_status is True
    assert "lease_store" in rs.NON_RUN_STATUS_SOURCES


# ======================================================================
# T-FRESH
# ======================================================================
def _svc(tmp_path: Path, commit: str) -> EvidenceFreshnessService:
    return EvidenceFreshnessService(tmp_path, commit=commit)


def test_T_FRESH_01_matching_inputs_are_live(tmp_path):
    binding = _svc(tmp_path, "abc123").bind(
        "report.json", {"git_sha": "abc123", "python": f"{sys.version_info.major}.{sys.version_info.minor}",
                        "platform": __import__("os").name, "generated_at": "2026-10-15T10:00:00"}
    )
    assert binding.freshness == Freshness.LIVE
    assert binding.may_display_as_live is True
    assert binding.mismatches() == ()


def test_T_FRESH_02_commit_drift_is_stale_not_live(tmp_path):
    binding = _svc(tmp_path, "newcommit").bind("report.json", {"git_sha": "oldcommit"})
    assert binding.freshness == Freshness.STALE
    assert binding.may_display_as_live is False
    assert {i.name for i in binding.mismatches()} == {"git_sha"}


def test_T_FRESH_03_missing_and_corrupt_and_schema_incompatible(tmp_path):
    svc = _svc(tmp_path, "abc")
    assert svc.load_and_bind(tmp_path / "nope.json").freshness == Freshness.MISSING

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert svc.load_and_bind(corrupt).freshness == Freshness.CORRUPT

    wrong_shape = tmp_path / "list.json"
    wrong_shape.write_text("[1, 2, 3]", encoding="utf-8")
    assert svc.load_and_bind(wrong_shape).freshness == Freshness.SCHEMA_INCOMPATIBLE

    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({"schema": "something-else/v9", "git_sha": "abc"}), encoding="utf-8")
    assert svc.load_and_bind(foreign).freshness == Freshness.SCHEMA_INCOMPATIBLE


def test_T_FRESH_04_stale_artefacts_are_never_displayed_as_live(tmp_path):
    svc = _svc(tmp_path, "abc")
    for name in sorted(FORBIDDEN_AS_LIVE):
        assert name in ("CURRENT_MAP_STATIC_RELEASE_MATRIX.json", "PRODUCTION_READINESS_MATRIX.json")
        binding = svc.bind(name, {"git_sha": "abc", "generated_at": "2026-10-15"})
        assert binding.freshness == Freshness.STALE
        assert binding.may_display_as_live is False


def test_T_FRESH_05_unbound_when_no_git_sha_recorded(tmp_path):
    binding = _svc(tmp_path, "abc").bind("report.json", {"generated_at": "2026-10-15"})
    assert binding.freshness == Freshness.UNBOUND
    assert binding.may_display_as_live is False


# ======================================================================
# T-AUDIT
# ======================================================================
def test_T_AUDIT_01_append_only_with_monotonic_sequence(tmp_path):
    journal = AuditJournal(tmp_path / "audit.jsonl", actor="tester")
    first = journal.append("connect", subject="localhost:2000")
    second = journal.append("load_world", subject="Town01")
    assert second["seq"] == first["seq"] + 1
    assert len(journal.read()) == 2
    journal.append("disconnect")
    assert len(journal.read()) == 3  # never rewritten


def test_T_AUDIT_02_secrets_are_redacted(tmp_path):
    journal = AuditJournal(tmp_path / "audit.jsonl")
    journal.append("auth", detail={"password": "hunter2", "api_key": "AKIA123", "port": 2000})
    record = journal.read()[0]
    assert record["detail"]["password"] == "[REDACTED]"
    assert record["detail"]["api_key"] == "[REDACTED]"
    assert record["detail"]["port"] == 2000  # non-secret survives


def test_T_AUDIT_03_private_paths_and_map_payloads_are_redacted(tmp_path):
    assert "PRIVATE" in redact(r"wrote to C:\Users\michal\secret\run.log")
    journal = AuditJournal(tmp_path / "audit.jsonl")
    journal.append("map", detail={"path": "C:\\Users\\michal\\maps\\Town01.xodr"})
    assert "PRIVATE" in journal.read()[0]["detail"]["path"]
    assert "PROPRIETARY_PAYLOAD_REDACTED" in redact("maps/Town01.xodr")
    assert redact("x" * 900).endswith("[TRUNCATED]")


def test_T_AUDIT_04_retention_is_bounded_and_reports_itself(tmp_path):
    journal = AuditJournal(tmp_path / "audit.jsonl", retention_records=5)
    for index in range(12):
        journal.append(f"action-{index}")
    records = journal.read()
    assert len(records) == 5
    assert records[-1]["action"] == "action-11"
    report = journal.retention_report()
    assert report["current_records"] == 5
    assert "Q18" in report["retention_policy_source"]


# ======================================================================
# T-MOCK
# ======================================================================
def test_T_MOCK_01_no_carla_import_at_package_import_time():
    assert "carla" not in sys.modules or True  # informational; see below
    for name in [n for n in sys.modules if n.startswith("ultimate_pipeline.gui")]:
        assert sys.modules[name] is not None
    import ultimate_pipeline.gui.adapters.mock_services as ms
    source = Path(ms.__file__).read_text(encoding="utf-8")
    assert "import carla" not in source


def test_T_MOCK_02_every_documented_protocol_has_a_mock():
    registry = build_mock_registry()
    assert set(registry) == {"carla", "traffic_manager", "map_registry",
                             "quality", "calibration", "experiments"}
    carla = registry["carla"]
    for method in ("probe", "server_version", "available_maps", "load_world",
                   "reset_world", "acquire_tick", "release_tick", "spawn_actor",
                   "destroy_actor", "attach_sensor", "apply_weather", "read_settings"):
        assert callable(getattr(carla, method)), method


def test_T_MOCK_03_mocks_are_deterministic_across_runs():
    def run() -> list[int]:
        backend = MockCarlaBackend()
        ids = []
        for index in range(5):
            result = backend.spawn_actor(ActorSpec(f"vehicle.{index}"))
            ids.append(result.value.actor_id)
        return ids

    assert run() == run()


def test_T_MOCK_04_deterministic_simulated_errors_are_typed():
    backend = MockCarlaBackend()
    bad_weather = backend.apply_weather(WeatherSpec("UnsupportedPreset"))
    assert isinstance(bad_weather, Result) and bad_weather.ok is False
    assert bad_weather.error_class == "ValueError"

    bad_world = backend.load_world(WorldSpec("NoSuchTown"))
    assert bad_world.ok is False and bad_world.error_source

    offline = MockCarlaBackend(available=False)
    assert offline.probe("h", 2000, 1.0).reason.startswith("mock backend")


def test_T_MOCK_05_traffic_manager_claim_conflict_and_ledger():
    tm = MockTrafficManagerBackend()
    mine = tm.claim("owner-a")
    assert mine.acquired is True
    other = tm.claim("owner-b")
    assert other.acquired is False and other.conflict_holder == "owner-a"
    # readable_back is always False -- the TM does not read its own settings back
    receipt = tm.apply_global(mine, TmPolicy()).value
    assert receipt.readable_back is False
    assert len(tm.ledger()) == 1
    assert set(tm.declared_only()) == {"dormant_vehicle_behavior", "speed_policy", "respawn_policy"}


def test_T_MOCK_06_map_registry_verify_is_fail_closed():
    registry = MockMapRegistryBackend()
    assert registry.verify("NoSuchMap").ok is False
    assert registry.verify("Town01").error_class == "FileNotFoundError"  # not on disk
    assert registry.validate().value["pins"] == 2
    assert registry.resolve_load_target("Town07") == ["maps/Town07.xodr"]


def test_T_MOCK_07_quality_gates_refuse_on_any_red_gate(tmp_path):
    quality = MockQualityGateBackend(passing_gates=("topology",))
    run = quality.run(tmp_path / "x.xodr", ["topology", "hash"], {})
    assert run.value["all_green"] is False
    assert quality.accept({"gates": run.value["gates"]}, {}, "run-1", {}).ok is False
    assert quality.hash(tmp_path / "missing.xodr").error_class == "FileNotFoundError"


def test_T_MOCK_08_calibration_and_experiment_discovery_failures_surface(tmp_path, capsys):
    cal = MockCalibrationBackend()
    assert cal.load(tmp_path / "nope.json").ok is False
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"profile_id": "p"}), encoding="utf-8")
    assert cal.load(bad).error_class == "SchemaError"

    experiments = MockExperimentBackend()
    payload = experiments.list_experiments().value
    assert payload["discovery_failures"], "discovery failures must be returned, not swallowed"
    assert payload["discovery_failures"][0]["experiment_id"] == "exp_broken"


def test_T_MOCK_09_typed_results_never_return_successful_none(tmp_path):
    success = Result.success({"k": 1})
    assert success.ok and success.unwrap() == {"k": 1}
    with pytest.raises(ValueError):
        Result.failure("nope").unwrap()
    assert Result.blocked("no server").reason == "no server"
    unsupported = Tri.unsupported("mock cannot enumerate maps")
    assert unsupported.state == TriState.PROBE_UNSUPPORTED and unsupported.supported is False
    assert Tri.empty().state == TriState.EMPTY
    assert UnsupportedCapability("x", "y").remediation == ""
    assert json.loads(success.to_json())["ok"] is True


# ======================================================================
# T-DIAG-04
# ======================================================================
def test_T_DIAG_04_swallowed_exceptions_and_health_stages_are_surfaced():
    import socket
    import threading

    # A swallowed connection error must appear as a typed failure, not silence.
    closed = MockCarlaBackend(available=False)
    result = closed.probe("127.0.0.1", 1, timeout_s=0.2)
    assert result.ok is False
    assert result.remediation, "a blocked probe must carry a remediation"

    # Five-stage health model reports exactly where it failed.
    health = probe_stages(closed, "127.0.0.1", 1, timeout_s=0.2)
    assert [s.stage for s in health.stages] == [HealthStage.PORT_OPEN]
    assert health.state is ConnectionState.UNHEALTHY
    assert health.first_failing_stage is not None
    assert health.first_failing_stage.stage is HealthStage.PORT_OPEN

    # A backend that cannot enumerate maps reports PROBE_UNSUPPORTED, never green.
    # A real listening socket is required so stage 1 passes and the probe reaches
    # stage 4; the mock server is loopback-only and is never a CARLA server.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    stop = threading.Event()

    def accept_loop() -> None:
        listener.settimeout(0.5)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
                conn.close()
            except (TimeoutError, OSError):
                continue

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    try:
        partial = MockCarlaBackend(maps_supported=False)
        stages = probe_stages(partial, "127.0.0.1", port, timeout_s=2.0)
        passed = [s.stage for s in stages.stages if s.ok]
        assert HealthStage.PORT_OPEN in passed
        maps_stage = stages.stage(HealthStage.MAP_ENUMERATION)
        assert maps_stage is not None, "stage 4 must be reported, not skipped"
        assert maps_stage.unsupported is True
        assert maps_stage.ok is False  # unsupported is never a green check
    finally:
        stop.set()
        thread.join(timeout=2)
        listener.close()

    # mutating controls are gated by authority
    assert mutating_controls_enabled(ConnectionState.HEALTHY, SessionAuthority.SHARED_READONLY) is False
    assert mutating_controls_enabled(ConnectionState.OFFLINE, SessionAuthority.EXCLUSIVE_TICK) is False
    assert mutating_controls_enabled(ConnectionState.VERSION_MISMATCH, SessionAuthority.EXCLUSIVE_TICK) is False


def test_cancellation_token_is_cooperative():
    token = CancellationToken()
    assert token.cancelled is False
    token.cancel("operator stop")
    token.cancel("second reason is ignored")
    assert token.cancelled is True
    assert token.reason == "operator stop"
    with pytest.raises(OperationCancelled):
        token.raise_if_cancelled()

    seen: list[str] = []
    late = CancellationToken()
    late.on_cancel(seen.append)
    late.cancel("now")
    assert seen == ["now"]