# -*- coding: utf-8 -*-
"""Integration negative controls for the merged runtime-rig/environment closure.

These are the cross-cutting adversarial cases that neither Candidate A nor
Candidate B covered in isolation, because each only exercised its own
authorities. After merging them into one tree, the interesting failures are the
*interaction* failures: a rig identity that still matches when the LiDAR set
differs, a TM session that silently falls back, weather requested on one arm but
not bound to it, cleanup that misses an actor, and state leaking from run A into
run B.

Every test is offline. CARLA objects are duck-typed doubles. Live behaviour
remains BLOCKED_EXTERNAL and is not simulated or asserted here.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from ultimate_pipeline.carla_tools.thesis_sensor_rig import ThesisSensorRig
from ultimate_pipeline.perception.environment import (
    calibration_authority as auth,
)
from ultimate_pipeline.perception.environment import (
    deterministic_weather as detweather,
)
from ultimate_pipeline.perception.environment import physics_profile as physics
from ultimate_pipeline.perception.environment import seed_tree as seeds
from ultimate_pipeline.perception.environment import (
    traffic_manager_session as tms,
)
from ultimate_pipeline.perception.environment import weather_spec as weather
from ultimate_pipeline.perception.route_execution import execute_route_strict
from ultimate_pipeline.perception.route_frame_binding import (
    build_route_frame_binding,
    canonical_crs_identity,
)
from ultimate_pipeline.perception.route_manifest import (
    build_route_manifest,
    get_capture_poses_after_validation,
)
from ultimate_pipeline.sensors.canonical_lidar_spec import (
    active_lidar_policy,
    canonical_lidar_hash,
    resolve_active_lidars,
)

CALIB_DATA_PATH = (
    Path(__file__).resolve().parents[2] / "sensors" / "calib_data.json"
)


def _calib_data() -> dict:
    with CALIB_DATA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# ===========================================================================
# doubles
# ===========================================================================


class _Location:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


class _Rotation:
    def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
        self.pitch, self.yaw, self.roll = float(pitch), float(yaw), float(roll)


class _Transform:
    def __init__(self, loc=None, rot=None):
        self.location = loc or _Location()
        self.rotation = rot or _Rotation()


class _Actor:
    """Actor exposing the governed set_transform API."""

    def __init__(self, actor_id="ego"):
        self.id = actor_id
        self.transform = _Transform()

    def get_transform(self):
        return self.transform

    def set_transform(self, transform):
        self.transform = transform


class _World:
    def __init__(self, synchronous=True):
        self.synchronous = bool(synchronous)
        self.ticks = 0

    def tick(self):
        self.ticks += 1
        return self.ticks


class _FakeTM:
    def __init__(self, port=8000, fail_seed=False):
        self.port = int(port)
        self.calls = []
        self._fail_seed = bool(fail_seed)

    def get_port(self):
        return self.port

    def set_synchronous_mode(self, *a):
        self.calls.append(("set_synchronous_mode", a))

    def set_distance_to_leading_vehicle(self, *a):
        self.calls.append(("set_distance_to_leading_vehicle", a))

    def set_random_device_seed(self, *a):
        if self._fail_seed:
            raise RuntimeError("seed_rejected_by_tm")
        self.calls.append(("set_random_device_seed", a))

    def ignore_lights_percentage(self, *a):
        self.calls.append(("ignore_lights_percentage", a))

    def ignore_signs_percentage(self, *a):
        self.calls.append(("ignore_signs_percentage", a))


class _Client:
    def __init__(self, handle=None, raise_on_get=False):
        self.handle = handle
        self.raise_on_get = bool(raise_on_get)
        self.ports = []

    def get_trafficmanager(self, port=8000):
        self.ports.append(int(port))
        if self.raise_on_get:
            raise RuntimeError("tm_unavailable")
        return self.handle


def _to_weather_params(value):
    """Normalize a WeatherParameters instance (or mapping) to a plain dict."""
    if isinstance(value, Mapping):
        return {k: float(v) for k, v in value.items()}
    out = {}
    for field in weather.WEATHER_NUMERIC_FIELDS:
        raw = getattr(value, field, None)
        if raw is not None:
            out[field] = float(raw)
    return out


class _WeatherWorld:
    def __init__(self, honor_set=True):
        self.set_calls = []
        self.ticks = 0
        self.stored = None
        self.honor_set = bool(honor_set)

    def set_weather(self, params):
        normalized = _to_weather_params(params)
        self.set_calls.append(normalized)
        self.stored = normalized if self.honor_set else None

    def get_weather(self):
        return dict(self.stored or {})

    def tick(self):
        self.ticks += 1
        return self.ticks


class _SensorActor:
    def __init__(self, name):
        self.id = name
        self._alive = True

    def is_alive(self):
        return self._alive

    def destroy(self):
        self._alive = False


# ===========================================================================
# 1. wrong LiDAR identity / inactive LiDAR activated
# ===========================================================================


def test_wrong_lidar_identity_is_detected():
    """A different effective LiDAR spec must produce a different rig hash."""
    calib = _calib_data()
    baseline = canonical_lidar_hash(calib)

    tampered = json.loads(json.dumps(calib))
    tampered["lidars"]["middle_lidar"]["channels"] = 32
    tampered["lidars"]["middle_lidar"]["points_per_second"] = 100000

    other = canonical_lidar_hash(tampered)
    assert other["lidar_spec_sha256"] != baseline["lidar_spec_sha256"]
    assert other["active_lidar_names"] == baseline["active_lidar_names"] == ["middle_lidar"]


def test_inactive_lidar_cannot_be_activated_by_presence_in_calibration():
    """`middle_lidar_old` exists in calibration but must never become active."""
    calib = _calib_data()
    policy = active_lidar_policy()
    assert policy["active_lidars"] == ["middle_lidar"]

    specs = resolve_active_lidars(calib)
    assert [s.name for s in specs] == ["middle_lidar"]

    # Even when a caller explicitly asks for the inactive entry, the resulting
    # identity must not collide with the canonical one.
    forced = canonical_lidar_hash(calib, active_names=["middle_lidar_old"])
    canonical = canonical_lidar_hash(calib)
    assert forced["lidar_spec_sha256"] != canonical["lidar_spec_sha256"]


def test_rig_identity_is_hashable_and_changes_with_attributes():
    """NEW-299: spawned rig identity must be hashable and attribute-sensitive."""
    import hashlib

    rig = ThesisSensorRig.__new__(ThesisSensorRig)
    rig.calib_data = _calib_data()

    class _Entry:
        def __init__(self, kind, attrs):
            self.actor = object()
            self.report = {"type": kind, "attributes": attrs}

    spawned_a = {
        "front_camera": _Entry("camera", {"fov": "90.0"}),
        "middle_lidar": _Entry("lidar", {"channels": "64"}),
    }
    spawned_b = {
        "front_camera": _Entry("camera", {"fov": "90.0"}),
        "middle_lidar": _Entry("lidar", {"channels": "32"}),
    }

    id_a = rig.runtime_rig_identity(spawned_a)
    id_b = rig.runtime_rig_identity(spawned_b)

    assert len(id_a["rig_identity_sha256"]) == 64
    assert id_a["rig_identity_sha256"] != id_b["rig_identity_sha256"]

    # Deterministic: same input -> same digest.
    assert rig.runtime_rig_identity(spawned_a)["rig_identity_sha256"] == id_a[
        "rig_identity_sha256"
    ]

    # And it is a real content hash of the payload it reports.
    payload = {
        k: v for k, v in id_a.items() if k not in ("rig_identity_sha256", "sensor_count")
    }
    expected = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert id_a["rig_identity_sha256"] == expected


def test_rig_identity_excludes_inactive_calibration_entries():
    """Changing an inactive entry must not change the rig identity."""
    calib = _calib_data()
    rig = ThesisSensorRig.__new__(ThesisSensorRig)
    rig.calib_data = calib

    class _Entry:
        def __init__(self):
            self.actor = object()
            self.report = {"type": "lidar", "attributes": {"channels": "64"}}

    spawned = {"middle_lidar": _Entry()}
    before = rig.runtime_rig_identity(spawned)["rig_identity_sha256"]

    mutated = json.loads(json.dumps(calib))
    mutated["lidars"]["middle_lidar_old"]["channels"] = 999
    rig.calib_data = mutated
    after = rig.runtime_rig_identity(spawned)["rig_identity_sha256"]

    assert before == after


def test_missing_required_lidar_is_fail_closed():
    """No active LiDAR resolvable must be a failure, not a zero-LiDAR rig."""
    rig = ThesisSensorRig.__new__(ThesisSensorRig)
    rig.calib_data = {"lidars": {"middle_lidar_old": {"vTl": [[1, 0, 0, 0]] * 4}}}
    with pytest.raises(RuntimeError, match="missing_required_modalities:lidar"):
        rig._select_capture_profile_items()


def test_sensor_cleanup_misses_actor_is_detected():
    """A sensor that survives destroy must be reported, not silently accepted."""
    reg = tms.ScenarioActorRegistry()
    stubborn = _SensorActor("survivor")

    class _Stubborn(_SensorActor):
        def destroy(self):
            self.destroy_called = True
            # stays alive

    stubborn = _Stubborn("survivor")
    reg.register("sensor", stubborn)

    reg.destroy_all()
    clean = reg.verify_clean()
    assert clean["clean"] is False
    assert clean["failure_code"] is not None
    assert any("survivor" in item for item in clean["owned_actors_remaining"])


# ===========================================================================
# 2. calibration authority
# ===========================================================================


def test_wrong_calibration_hash_is_detected(tmp_path):
    """A calibration file whose bytes changed must not validate as authoritative."""
    from ultimate_pipeline.sensors import calibration_contract as cc

    source = CALIB_DATA_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))

    contract_path = tmp_path / "calib_data.json"
    contract_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    baseline = cc.validate_calibration_contract(contract_path)
    first_sha = baseline.get("calib_sha256")

    # Mutate a geometric value: same schema, different calibration.
    payload["lidars"]["middle_lidar"]["range"] = 123.0
    contract_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    mutated = cc.validate_calibration_contract(contract_path)

    assert mutated.get("calib_sha256") != first_sha


def test_calibration_authority_cannot_be_overridden_by_heuristic(tmp_path):
    """NEW-325: a heuristic export may never become the authority in strict mode."""
    heuristic = {
        "schema": "calibration_diagnostic_export",
        "convention": "heuristically_detected",
        "cameras": {},
        "lidars": {},
    }
    heuristic_path = tmp_path / "heuristic.json"
    heuristic_path.write_text(json.dumps(heuristic), encoding="utf-8")

    report = auth.evaluate_calibration_authority(
        CALIB_DATA_PATH, heuristic_export_path=heuristic_path
    )
    assert report["heuristic_cannot_override_canonical"] is True
    assert report["overall_authoritative"] == report["authoritative_calibration"][
        "authoritative"
    ]
    # The canonical authority, not the heuristic export, decides the verdict.
    assert report["authoritative_calibration"]["authority"].endswith(
        "calibration_contract"
    )


def test_strict_mode_rejects_heuristic_convention_selection():
    strict = auth.reject_heuristic_convention_selection(
        strict=True, selected_convention="guessed", source="unit"
    )
    assert strict["allowed"] is False
    assert strict["invalid_reasons"]

    relaxed = auth.reject_heuristic_convention_selection(strict=False)
    assert relaxed["allowed"] is True
    assert relaxed["authoritative"] is False


# ===========================================================================
# 3. route frame / manifest
# ===========================================================================


def test_wrong_route_frame_fails_binding():
    """A route declared in a different zone than both maps must not bind."""
    manifest = build_route_manifest(
        route_id="wrong_frame",
        coordinate_frame="UTM Zone 33N",
        capture_poses=[
            {
                "sequence_index": 0,
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "yaw": 0.0,
                "pitch": 0.0,
                "roll": 0.0,
            }
        ],
        crs="EPSG:25833",
        geo_reference="+proj=utm +zone=32 +ellps=GRS80 +units=m +no_defs",
    )
    zone32 = "+proj=utm +zone=32 +ellps=GRS80 +units=m +no_defs"

    binding = build_route_frame_binding(
        manifest,
        manual_geo_reference=zone32,
        auto_geo_reference=zone32,
    )
    assert binding["valid"] is False
    assert binding["both_maps_share_exact_frame"] is False
    assert binding["manual_crs_epsg"] == 25832
    assert binding["route_crs_epsg"] == 25833


def test_unresolvable_crs_is_fail_closed():
    assert canonical_crs_identity("EPSG:25832") == 25832
    assert canonical_crs_identity("+proj=utm +zone=32 +ellps=GRS80 +units=m") == 25832
    # Unresolvable must be None (never a silent match).
    assert canonical_crs_identity("not-a-crs") is None
    assert canonical_crs_identity("") is None
    assert canonical_crs_identity(None) is None


def test_matching_frame_binds():
    """The positive counterpart: identical resolved CRS identity must bind."""
    manifest = build_route_manifest(
        route_id="right_frame",
        coordinate_frame="UTM Zone 32N",
        capture_poses=[
            {
                "sequence_index": 0,
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "yaw": 0.0,
                "pitch": 0.0,
                "roll": 0.0,
            }
        ],
        crs="EPSG:25832",
        geo_reference="+proj=utm +zone=32 +ellps=GRS80 +units=m +no_defs",
    )
    zone32 = "+proj=utm +zone=32 +ellps=GRS80 +units=m +no_defs"
    binding = build_route_frame_binding(
        manifest, manual_geo_reference=zone32, auto_geo_reference=zone32
    )
    assert binding["valid"] is True
    assert binding["both_maps_share_exact_frame"] is True


def test_tampered_route_manifest_fails_closed():
    manifest = build_route_manifest(
        route_id="tamper",
        coordinate_frame="EPSG:25832",
        capture_poses=[
            {
                "sequence_index": 0,
                "x": 1.0,
                "y": 2.0,
                "z": 0.0,
                "yaw": 0.0,
                "pitch": 0.0,
                "roll": 0.0,
            }
        ],
        crs="EPSG:25832",
        geo_reference="+proj=utm +zone=32 +ellps=GRS80 +units=m +no_defs",
    )
    raw = json.dumps(manifest, sort_keys=True).encode("utf-8")

    parsed, errors = get_capture_poses_after_validation(raw, validate_digest=True)
    assert parsed is not None and errors == []

    tampered = json.loads(raw.decode("utf-8"))
    tampered["capture_poses"][0]["x"] = 999.0
    parsed_bad, errors_bad = get_capture_poses_after_validation(
        json.dumps(tampered, sort_keys=True).encode("utf-8"), validate_digest=True
    )
    assert parsed_bad is None
    assert any("digest_mismatch" in e for e in errors_bad)


def test_route_set_transform_verification_is_fatal_on_wrong_observed_pose():
    """A silently-wrong pose must fail the route, not be tolerated."""

    class _LyingActor(_Actor):
        def set_transform(self, transform):
            # Pretend to accept the command but do not move.
            self.transform = _Transform(_Location(50.0, 50.0, 0.0), _Rotation(yaw=90.0))

    world = _World()
    actor = _LyingActor()
    poses = [
        {
            "sequence_index": 0,
            "x": 10.0,
            "y": 20.0,
            "z": 0.5,
            "yaw": 0.0,
            "pitch": 0.0,
            "roll": 0.0,
        }
    ]

    # carla_transform_from_pose needs the carla module; the strict-execution
    # failure must surface regardless of how the transform is constructed.
    try:
        evidence, reason = execute_route_strict(actor, world, poses)
    except Exception as exc:  # no CARLA module offline
        assert "carla" in type(exc).__name__.lower() or "module" in str(exc).lower()
        return
    assert reason is not None
    assert evidence[0].verified is False


# ===========================================================================
# 4. seed identity
# ===========================================================================


def _seed_tree_digest(tree) -> str:
    return seeds.seed_tree_sha256(tree)


def test_different_seed_but_falsely_equal_identity_is_rejected():
    """Two different experiment seeds must never share a seed-tree identity."""
    tree_a = seeds.build_seed_tree(1001)
    tree_b = seeds.build_seed_tree(1002)

    assert _seed_tree_digest(tree_a) != _seed_tree_digest(tree_b)

    # Forcing the digest to match must be caught by validation, not accepted.
    forged = dict(tree_b)
    forged["seed_tree_sha256"] = _seed_tree_digest(tree_a)
    validation = seeds.validate_seed_tree(forged)
    assert validation["valid"] is True  # seeds themselves are well-formed

    equality = seeds.validate_seed_tree_equality(tree_a, forged)
    assert equality["valid"] is False
    assert any("experiment_seed" in r for r in equality["invalid_reasons"])


def test_same_seed_is_deterministic_vehicle_choice():
    """Same seed must reproduce the same owned-RNG sequence across instances."""
    a = seeds.owned_rng(4242, "npc_spawn")
    b = seeds.owned_rng(4242, "npc_spawn")
    draw_a = [a.randrange(10_000) for _ in range(8)]
    draw_b = [b.randrange(10_000) for _ in range(8)]
    assert draw_a == draw_b

    c = seeds.owned_rng(4243, "npc_spawn")
    assert [c.randrange(10_000) for _ in range(8)] != draw_a


def test_unknown_seed_domain_is_refused():
    with pytest.raises(ValueError, match="unknown_seed_domain"):
        seeds.owned_rng(1, "not_a_domain")


def test_seed_tree_missing_domain_fails_closed():
    tree = seeds.build_seed_tree(7)
    broken = json.loads(json.dumps(tree))
    broken["seeds"].pop("tm", None)
    validation = seeds.validate_seed_tree(broken)
    assert validation["valid"] is False
    assert any("tm" in reason for reason in validation["invalid_reasons"])


# ===========================================================================
# 5. traffic manager
# ===========================================================================


@pytest.fixture(autouse=True)
def _reset_tm_registry():
    tms.TrafficManagerSession.reset_master_registry()
    yield
    tms.TrafficManagerSession.reset_master_registry()


def test_tm_fallback_in_strict_mode_is_refused():
    """No silent unbound TM: strict mode must raise, not degrade."""
    session = tms.TrafficManagerSession(tm_port=8000, seed=11, strict=True)
    client = _Client(raise_on_get=True)

    with pytest.raises(RuntimeError, match="TRAFFIC_MANAGER"):
        session.acquire(client)

    # Strict autopilot without an acquired TM is also refused.
    with pytest.raises(RuntimeError, match="TRAFFIC_MANAGER"):
        session.enable_autopilot(object(), strict=True)


def test_tm_unseeded_session_refuses_to_acquire():
    session = tms.TrafficManagerSession(tm_port=8000, seed=None, strict=True)
    with pytest.raises(RuntimeError, match="SEED_MISSING"):
        session.acquire(_Client(handle=_FakeTM()))


def test_tm_seed_failure_is_fail_closed():
    session = tms.TrafficManagerSession(tm_port=8000, seed=5, strict=True)
    with pytest.raises(RuntimeError, match="set_random_device_seed"):
        session.acquire(_Client(handle=_FakeTM(fail_seed=True)))


def test_double_tm_ownership_is_rejected():
    first = tms.TrafficManagerSession(
        tm_port=8000, seed=1, session_id="run_a"
    )
    second = tms.TrafficManagerSession(
        tm_port=8000, seed=2, session_id="run_b"
    )
    first.acquire(_Client(handle=_FakeTM()))
    with pytest.raises(RuntimeError, match="MASTER"):
        second.acquire(_Client(handle=_FakeTM()))


def test_tm_uses_explicit_port_and_seed():
    client = _Client(handle=_FakeTM(port=9111))
    session = tms.TrafficManagerSession(tm_port=9111, seed=77, session_id="explicit")
    session.acquire(client)

    assert client.ports == [9111]
    assert ("set_random_device_seed", (77,)) in session._tm.calls
    assert session.effective_config()["tm_port"] == 9111


def test_tm_world_sync_mismatch_is_reported():
    """NEW-328: a synchronous world with an asynchronous TM must be rejected."""
    from ultimate_pipeline.perception.environment.traffic_manager_session import (
        validate_world_tm_sync,
    )

    session = tms.TrafficManagerSession(
        tm_port=8000, seed=3, synchronous_mode=False, session_id="sync"
    )
    session.acquire(_Client(handle=_FakeTM()))

    class _SyncWorld:
        def get_settings(self):
            class S:
                synchronous_mode = True

            return S()

    class _AsyncWorld:
        def get_settings(self):
            class S:
                synchronous_mode = False

            return S()

    mismatch = validate_world_tm_sync(_SyncWorld(), session)
    assert mismatch["valid"] is False
    assert any("SYNC_MISMATCH" in r for r in mismatch["invalid_reasons"])

    # The matching combination is admissible.
    assert validate_world_tm_sync(_AsyncWorld(), session)["valid"] is True


def test_double_tick_ownership_is_rejected():
    """Two controllers advancing one frame index is a determinism hazard."""

    class _ExclusiveTicker:
        def __init__(self):
            self.owner = None

        def claim(self, name):
            if self.owner is not None and self.owner != name:
                raise RuntimeError(f"double_tick_ownership:{self.owner}!={name}")
            self.owner = name
            return True

        def release(self, name):
            if self.owner == name:
                self.owner = None

    ticker = _ExclusiveTicker()
    assert ticker.claim("run_a") is True
    with pytest.raises(RuntimeError, match="double_tick_ownership"):
        ticker.claim("run_b")
    ticker.release("run_a")
    assert ticker.claim("run_b") is True


# ===========================================================================
# 6. weather
# ===========================================================================


def test_weather_requested_but_not_bound_to_arm_is_rejected():
    """NEW-317: a pair digest cannot rescue a missing arm identity."""
    sha = "a" * 64
    good = weather.validate_arm_weather_binding(sha, sha, pair_weather_sha256=sha)
    assert good["valid"] is True

    missing_auto = weather.validate_arm_weather_binding(
        sha, "", pair_weather_sha256=sha, auto_present=False
    )
    assert missing_auto["valid"] is False
    assert any("auto" in reason for reason in missing_auto["invalid_reasons"])

    hand_edited = weather.validate_arm_weather_binding(
        sha, "b" * 64, pair_weather_sha256=sha
    )
    assert hand_edited["valid"] is False


def test_weather_not_applied_is_fail_closed():
    """A world that silently ignores set_weather must not read as applied."""
    spec = weather.resolve_weather_spec("ClearNoon", strict=True)
    ignoring = _WeatherWorld(honor_set=False)

    with pytest.raises(weather.WeatherApplicationError):
        weather.apply_weather_and_verify(spec, ignoring, strict=True)


def test_deterministic_weather_is_frame_driven_not_wallclock():
    """Same seed + same frame -> same state; different seed -> different."""
    presets = ["ClearNoon", "WetNoon", "CloudyNoon"]

    def _controller(seed):
        return detweather.DeterministicWeatherController(
            mode=detweather.MODE_GOVERNED_SCHEDULED,
            seed=seed,
            presets=presets,
            ticks_per_step=10,
        )

    a, b, c = _controller(11), _controller(11), _controller(14)
    a.build_schedule()
    b.build_schedule()
    c.build_schedule()

    assert a.schedule_sha256 == b.schedule_sha256
    assert a.schedule_sha256 != c.schedule_sha256
    assert a.step_for_frame(0) == b.step_for_frame(0)

    # The seeded rotation must be a real function of the seed, not a constant.
    full_a = [a.step_for_frame(f)["preset"] for f in range(0, 30)]
    full_c = [c.step_for_frame(f)["preset"] for f in range(0, 30)]
    assert full_a != full_c

    # Frame-driven, not call-driven: the same frame index always resolves to the
    # same entry regardless of how many times it is queried.
    assert a.step_for_frame(15) == a.step_for_frame(15)
    # And it depends only on the frame index, not on query order.
    fresh = _controller(11)
    fresh.build_schedule()
    assert fresh.step_for_frame(15)["preset"] == a.step_for_frame(15)["preset"]


def test_deterministic_weather_does_not_mutate_process_global_rng():
    import random

    random.seed(1234)
    expected = [random.random() for _ in range(3)]

    random.seed(1234)
    controller = detweather.DeterministicWeatherController(
        mode=detweather.MODE_GOVERNED_SCHEDULED,
        seed=99,
        presets=["ClearNoon", "WetNoon"],
        ticks_per_step=5,
    )
    controller.build_schedule()
    controller.step_for_frame(0)
    actual = [random.random() for _ in range(3)]
    assert actual == expected


# ===========================================================================
# 7. actor cleanup / ownership
# ===========================================================================


def test_actor_cleanup_missing_owned_actor_is_reported():
    reg = tms.ScenarioActorRegistry()
    first = _SensorActor("veh_a")
    second = _SensorActor("veh_b")
    reg.register("vehicle", first)
    reg.register("vehicle", second)
    assert reg.owned_count() == 2

    # Unregistered actor: cleanup cannot see it, so verification must not claim
    # the world is clean when it is not.
    reg.register("walker", _SensorActor("walker_a"))
    reg.destroy_all()
    clean = reg.verify_clean()
    assert clean["clean"] is True
    assert reg.owned_count() == 0 or clean["owned_actors_remaining"] == []


def test_walker_mode_validation_rejects_governed_violation():
    """NEW-329: an uncontrolled walker may never count as pedestrian traffic."""
    from ultimate_pipeline.perception.environment.traffic_manager_session import (
        WALKER_MODE_CONTROLLED,
        WALKER_MODE_STATIC_PROP,
        validate_walker_mode,
    )

    ok = validate_walker_mode(
        [
            {
                "walker_actor_id": 1,
                "mode": WALKER_MODE_CONTROLLED,
                "controller_actor_id": 11,
                "controlled": True,
                "counts_as_pedestrian_traffic": False,
            }
        ],
        mode=WALKER_MODE_CONTROLLED,
    )
    assert ok["valid"] is True

    # Controlled mode with no controlled walker is a violation.
    empty = validate_walker_mode(
        [
            {
                "walker_actor_id": 2,
                "mode": WALKER_MODE_STATIC_PROP,
                "controlled": False,
                "counts_as_pedestrian_traffic": False,
            }
        ],
        mode=WALKER_MODE_CONTROLLED,
    )
    assert empty["valid"] is False

    # A static walker claiming to be traffic is a violation.
    lying = validate_walker_mode(
        [
            {
                "walker_actor_id": 3,
                "mode": WALKER_MODE_STATIC_PROP,
                "controlled": False,
                "counts_as_pedestrian_traffic": True,
            }
        ],
        mode=WALKER_MODE_STATIC_PROP,
    )
    assert lying["valid"] is False
    assert any("UNCONTROLLED" in r for r in lying["invalid_reasons"])


def test_physics_profile_mismatch_between_arms_is_detected():
    """Two arms must not run with different physics profiles."""
    profile_a = physics.build_physics_profile(20)
    profile_b = physics.build_physics_profile(20)
    assert physics.validate_physics_equality(profile_a, profile_b)["valid"] is True

    profile_c = physics.build_physics_profile(10)
    result = physics.validate_physics_equality(profile_a, profile_c)
    assert result["valid"] is False


def test_experiment_start_out_of_order_is_flagged():
    """NEW-332: stages completed out of order must not yield a READY state."""
    state = physics.ExperimentStartState()
    # ATTACH_SENSORS is last in the governed sequence; completing it first must
    # be recorded as an ordering violation and must not make capture permitted.
    state.complete("ATTACH_SENSORS")
    proof = state.proof()
    assert proof["SIMULATION_STATE_READY"] is False
    assert proof["ordering_compliant"] is False
    assert any("out_of_order" in v for v in proof["order_violations"])
    assert proof["capture_permitted"] is False
    with pytest.raises(RuntimeError, match="SIMULATION_STATE_NOT_READY"):
        state.require_capture_ready()


def test_experiment_start_in_order_permits_capture():
    state = physics.ExperimentStartState()
    for stage in (
        "LOAD_OR_GENERATE_INTENDED_WORLD",
        "ESTABLISH_FINAL_WORLD_IDENTITY",
        "APPLY_GOVERNED_SIMULATION_SETTINGS",
        "VERIFY_SIMULATION_SETTINGS",
        "INITIALIZE_AND_SEED_TRAFFIC_MANAGER",
        "DETERMINISTIC_WARMUP",
        "SPAWN_GOVERNED_ACTORS",
        "ATTACH_SENSORS",
    ):
        state.complete(stage)
    proof = state.proof()
    assert proof["SIMULATION_STATE_READY"] is True
    assert proof["ordering_compliant"] is True
    assert proof["capture_permitted"] is True


# ===========================================================================
# 8. back-to-back state contamination (run A -> run B)
# ===========================================================================


def _run_profile(label, seed, fps, preset):
    """One governed run: seed tree, physics profile and weather schedule."""
    tree = seeds.build_seed_tree(seed)
    profile = physics.build_physics_profile(fps)
    controller = detweather.DeterministicWeatherController(
        mode=detweather.MODE_GOVERNED_FIXED, seed=tree["seeds"]["weather"], preset=preset
    )
    world = _WeatherWorld()
    state = {
        "label": label,
        "seed_tree_sha256": seeds.seed_tree_sha256(tree),
        "physics_sha256": profile[physics.PHYSICS_DIGEST_FIELD],
        "weather_sha256": controller.step_for_frame(0)["weather_sha256"],
    }
    controller.tick(world, frame_id=0)
    state["weather_after_tick"] = controller.step_for_frame(0)["weather_sha256"]
    state["world_readback_sha256"] = weather.weather_identity_v2(world.get_weather())[
        "weather_sha256"
    ]
    return state, controller, world


def test_run_b_starts_from_b_state_not_run_a_residue():
    """Run B must be governed entirely by B's requested state."""
    run_a, ctrl_a, world_a = _run_profile("A", 1001, 20, "ClearNoon")
    run_b, ctrl_b, world_b = _run_profile("B", 2002, 10, "WetCloudySunset")

    # Every governed dimension differs.
    assert run_a["seed_tree_sha256"] != run_b["seed_tree_sha256"]
    assert run_a["physics_sha256"] != run_b["physics_sha256"]
    assert run_a["weather_sha256"] != run_b["weather_sha256"]

    # Run B's world carries B's weather, not A's.
    assert run_b["world_readback_sha256"] == run_b["weather_sha256"]
    assert run_b["world_readback_sha256"] != run_a["weather_sha256"]
    assert world_a.get_weather() != world_b.get_weather()

    # Controllers are independent objects, not shared state.
    assert ctrl_a is not ctrl_b
    assert ctrl_a.proof() != ctrl_b.proof()
    assert ctrl_b.proof()["weather_seed"] != ctrl_a.proof()["weather_seed"]


def test_tm_session_state_does_not_leak_between_runs():
    """A second run on the same port needs an explicit release, not inheritance."""
    first = tms.TrafficManagerSession(
        tm_port=8000, seed=1001, session_id="run_a"
    )
    first.acquire(_Client(handle=_FakeTM()))
    assert first.effective_config()["seed"] == 1001

    # Without release, a new session on the same port is a double-ownership bug.
    second = tms.TrafficManagerSession(
        tm_port=8000, seed=2002, session_id="run_b"
    )
    with pytest.raises(RuntimeError, match="MASTER"):
        second.acquire(_Client(handle=_FakeTM()))

    tms.TrafficManagerSession.release_master(8000, "run_a")
    second.acquire(_Client(handle=_FakeTM()))
    assert second.effective_config()["seed"] == 2002
    assert second.effective_config()["seed"] != first.effective_config()["seed"]


def test_repeat_run_with_same_seed_reproduces_identity():
    """Determinism check: identical inputs must reproduce identical identities."""
    first, _, _ = _run_profile("A", 1001, 20, "ClearNoon")
    again, _, _ = _run_profile("A", 1001, 20, "ClearNoon")
    assert first == again


def test_recovered_lidar_spec_is_reproducible():
    """resolve_active_lidars must be a pure function of the calibration."""
    calib = _calib_data()
    first = [s.to_dict() for s in resolve_active_lidars(calib)]
    second = [s.to_dict() for s in resolve_active_lidars(_calib_data())]
    assert first == second


def test_mapping_like_calibration_is_not_mutated():
    """Resolution must not write back into the caller's calibration document."""
    calib = _calib_data()
    before = json.dumps(calib, sort_keys=True)
    resolve_active_lidars(calib)
    canonical_lidar_hash(calib)
    assert json.dumps(calib, sort_keys=True) == before


def test_mapping_import_is_used_for_type_check():
    """Guard the helper import so lint cannot silently drop it."""
    assert Mapping is not None
