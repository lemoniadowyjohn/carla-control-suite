"""Stage B0 acceptance: mutation-authorization fail-closed evidence.

Every mutation gate must refuse unavailable (``None``), shared, malformed
or non-string authority, and accept only explicit ``EXCLUSIVE_*`` grants
(enum members or their string forms, so JSON/config round-trips keep
working). The gates pinned here are: :func:`exclusive_claimed`,
``Session.may_mutate`` / ``Session.acquire_tick``, the mock backend tick
grant, fuzz admission, ``connect()`` tick readiness, the map/weather panel
authority gates and :func:`mutating_controls_enabled`.

A Git writer lease is NOT a CARLA runtime lease: source-control authority
never grants simulator mutation, and no test in this file contacts a
simulator. Historical wording ("session is SHARED_READONLY") is kept as
the blocking reason for non-exclusive authority even when the value is
malformed rather than the enum member.
"""

from __future__ import annotations

import pytest

from ultimate_pipeline.gui.adapters.mock_backend import MockCarlaBackend
from ultimate_pipeline.gui.fuzz.service import (
    SCENARIO_SCHEMA,
    BudgetDecision,
    CaseJournal,
    FuzzerService,
    ResourceProbe,
)
from ultimate_pipeline.gui.health import (
    ConnectionState,
    SessionAuthority,
    mutating_controls_enabled,
)
from ultimate_pipeline.gui.results import Result, Tri
from ultimate_pipeline.gui.runtime.connection import ConnectStage, connect
from ultimate_pipeline.gui.session.session import (
    EXCLUSIVE_AUTHORITY_VALUES,
    Session,
    exclusive_claimed,
)

# ------------------------------------------------------------------ inputs
EXCLUSIVE_INPUTS = [
    SessionAuthority.EXCLUSIVE_TICK,
    SessionAuthority.EXCLUSIVE_WORLD,
    SessionAuthority.EXCLUSIVE_TM_PORT,
    "EXCLUSIVE_TICK",
    "EXCLUSIVE_WORLD",
    "EXCLUSIVE_TM_PORT",
]

NON_EXCLUSIVE_INPUTS = [
    SessionAuthority.SHARED_READONLY,
    "SHARED_READONLY",
    None,
    "",
    "garbage",
    "exclusive_world",
    "EXCLUSIVE_WORLD ",
    object(),
    42,
    True,
    b"EXCLUSIVE_WORLD",
]

FUZZ_GOOD = {"schema": SCENARIO_SCHEMA, "seed": 1, "steps": ["noop"],
             "max_actors": 2, "max_sensors": 1}


# ------------------------------------------------------------------ fakes
class FakeSettings:
    def __init__(self, synchronous_mode=False, fixed_delta_seconds=0.0):
        self.synchronous_mode = synchronous_mode
        self.fixed_delta_seconds = fixed_delta_seconds


class FakeWorld:
    def __init__(self):
        self._settings = FakeSettings()
        self.ticks = 0

    def get_settings(self):
        return self._settings

    def apply_settings(self, settings):
        self._settings = FakeSettings(settings.synchronous_mode,
                                      settings.fixed_delta_seconds)

    def tick(self):
        self.ticks += 1


class StubBackend:
    """Minimal offline backend for the connect() ladder."""

    def probe(self, host, port, timeout_s):
        return Result.success(f"{host}:{port}")

    def server_version(self):
        return "0.9.16"

    def available_maps(self):
        return Tri.available_value(["Town01"])


@pytest.fixture
def app():
    from ultimate_pipeline.gui.shell.main_window import create_application
    return create_application([])


# ======================================================== exclusive_claimed
def test_exclusive_claimed_allow_list_contents():
    assert EXCLUSIVE_AUTHORITY_VALUES == frozenset(
        {"EXCLUSIVE_TICK", "EXCLUSIVE_WORLD", "EXCLUSIVE_TM_PORT"})


@pytest.mark.parametrize("authority", EXCLUSIVE_INPUTS)
def test_exclusive_claimed_accepts_explicit_exclusive_values(authority):
    assert exclusive_claimed(authority) is True


@pytest.mark.parametrize("authority", NON_EXCLUSIVE_INPUTS)
def test_exclusive_claimed_fails_closed_for_everything_else(authority):
    assert exclusive_claimed(authority) is False


# ============================================================== Session gate
@pytest.mark.parametrize("authority", NON_EXCLUSIVE_INPUTS)
def test_session_may_mutate_fails_closed_matrix(authority):
    session = Session(FakeWorld(), authority=authority)
    assert session.may_mutate is False


def test_session_may_mutate_default_is_shared_readonly():
    assert Session(FakeWorld()).may_mutate is False


@pytest.mark.parametrize("authority", EXCLUSIVE_INPUTS)
def test_session_may_mutate_accepts_exclusive_values(authority):
    session = Session(FakeWorld(), authority=authority)
    assert session.may_mutate is True


# The historical P0 exploit: the old ``authority is not SHARED_READONLY``
# identity deny-list returned True for the plain string "SHARED_READONLY"
# (and for None), so ``exclusive=True`` granted a tick under nominally
# shared authority. Red before the fail-closed fix, green after.
@pytest.mark.parametrize(
    "authority",
    ["SHARED_READONLY", None, "garbage", SessionAuthority.SHARED_READONLY, ""],
)
def test_tick_refused_for_malformed_authority_even_with_exclusive_flag(authority):
    session = Session(FakeWorld(), exclusive=True, authority=authority)
    assert session.may_mutate is False
    result = session.acquire_tick()
    assert result.ok is False
    assert "SHARED_READONLY" in result.reason
    assert session.tick.granted is False


@pytest.mark.parametrize("authority", [SessionAuthority.EXCLUSIVE_TICK,
                                       "EXCLUSIVE_TICK"])
def test_tick_granted_only_for_exclusive_authority(authority):
    session = Session(FakeWorld(), authority=authority)
    result = session.acquire_tick()
    assert result.ok is True
    assert session.tick.granted is True
    assert session.tick.release(owner="session").ok is True


# ============================================================ mock backend
def test_mock_backend_refuses_tick_for_malformed_authority():
    for authority in (None, "garbage", "SHARED_READONLY",
                      SessionAuthority.SHARED_READONLY, object(), ""):
        backend = MockCarlaBackend()
        backend._authority = authority
        grant = backend.acquire_tick("t")
        assert grant.granted is False, authority
        assert "not an explicit exclusive grant" in grant.reason


@pytest.mark.parametrize("authority", [SessionAuthority.EXCLUSIVE_WORLD,
                                       "EXCLUSIVE_WORLD"])
def test_mock_backend_grants_tick_only_for_exclusive_authority(authority):
    backend = MockCarlaBackend()
    backend._authority = authority
    grant = backend.acquire_tick("t")
    assert grant.granted is True
    assert grant.holder == "t"


# =================================================================== health
@pytest.mark.parametrize("authority",
                         [None, "garbage", "SHARED_READONLY", object(), ""])
def test_mutating_controls_enabled_fails_closed_for_malformed_authority(authority):
    assert mutating_controls_enabled(ConnectionState.HEALTHY, authority) is False


def test_mutating_controls_enabled_requires_healthy_state():
    assert mutating_controls_enabled(ConnectionState.OFFLINE,
                                     SessionAuthority.EXCLUSIVE_WORLD) is False
    assert mutating_controls_enabled(ConnectionState.VERSION_MISMATCH,
                                     SessionAuthority.EXCLUSIVE_WORLD) is False


@pytest.mark.parametrize("authority", [SessionAuthority.EXCLUSIVE_WORLD,
                                       "EXCLUSIVE_WORLD"])
def test_mutating_controls_enabled_accepts_exclusive_authority(authority):
    assert mutating_controls_enabled(ConnectionState.HEALTHY, authority) is True


# ========================================================== connect() ladder
def test_connect_treats_authority_without_may_mutate_as_not_ready():
    """An authority object lacking may_mutate must read as NOT ready.

    The old direct attribute access raised AttributeError instead of
    reporting the stage; the gate now fails closed via getattr.
    """
    result = connect(StubBackend(), tick_authority=object())
    assert result.ok is True
    stage = [s for s in result.unwrap()["stages"]
             if s["stage"] == ConnectStage.TICK_AUTHORITY][0]
    assert stage["ok"] is False


def test_connect_without_session_reports_tick_authority_ready():
    result = connect(StubBackend(), tick_authority=None)
    assert result.ok is True
    stage = [s for s in result.unwrap()["stages"]
             if s["stage"] == ConnectStage.TICK_AUTHORITY][0]
    assert stage["ok"] is True


# ============================================================ fuzz admission
def _fuzz_service(tmp_path) -> FuzzerService:
    return FuzzerService(
        journal=CaseJournal(tmp_path / "journal.jsonl"),
        probe=ResourceProbe(vram_free_mib=6000, disk_free_gib=17.0),
    )


@pytest.mark.parametrize("authority",
                         ["garbage", None, "", "exclusive_world",
                          SessionAuthority.SHARED_READONLY])
def test_fuzz_admission_fails_closed_for_malformed_authority(tmp_path, authority):
    admission = _fuzz_service(tmp_path).admit(FUZZ_GOOD, authority=authority)
    assert admission.admitted is False
    refusing = next(c for c in admission.checks if c.resource == "authority")
    assert refusing.decision == BudgetDecision.EXCEEDED.value


def test_fuzz_admission_accepts_exclusive_authority(tmp_path):
    admission = _fuzz_service(tmp_path).admit(FUZZ_GOOD,
                                              authority="EXCLUSIVE_WORLD")
    authority_checks = [c for c in admission.checks if c.resource == "authority"]
    assert authority_checks
    assert authority_checks[0].decision == BudgetDecision.OK.value
    assert admission.admitted is True


# ============================================================ panel gates
@pytest.mark.parametrize("authority",
                         [None, "garbage", "SHARED_READONLY",
                          SessionAuthority.SHARED_READONLY, ""])
def test_panel_gates_refuse_malformed_authority(app, authority):
    from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel
    from ultimate_pipeline.gui.control_center.weather_panel import WeatherPanel

    assert MapsPanel(authority=authority)._has_exclusive_authority() is False
    assert WeatherPanel(authority=authority)._has_exclusive_authority() is False


def test_panel_gates_accept_exclusive_authority(app):
    from ultimate_pipeline.gui.control_center.maps_panel import MapsPanel
    from ultimate_pipeline.gui.control_center.weather_panel import WeatherPanel

    assert MapsPanel(authority="EXCLUSIVE_WORLD")._has_exclusive_authority() is True
    assert WeatherPanel(authority="EXCLUSIVE_WORLD")._has_exclusive_authority() is True
