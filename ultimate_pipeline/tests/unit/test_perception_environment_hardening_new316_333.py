# -*- coding: utf-8 -*-
"""Adversarial unit tests for the NEW-316..NEW-333 perception-environment hardening.

Every test is one adversarial scenario, written so that it fails for the *right*
reason if the governed invariant is removed:

* NEW-316/317/318 weather authority  -- an unapplied weather is a hard failure,
  arm weather identity is mandatory (a hand-edited top-level manifest cannot
  rescue a missing arm identity) and the v2 digest sees the three fields the
  legacy 11-field identity dropped;
* NEW-319 deterministic weather -- governed schedules are a pure function of
  (seed, frame), never of wall clock or the process-global RNG;
* NEW-320 camera intrinsics -- the CARLA-native pinhole is not ``K_undistortion``,
  the residual is quantified, remap keeps RGB/semantic correspondence exact and
  a label map is never bilinearly blended;
* NEW-321/322/323/324/325 -- live calibration assay, transactional cleanup,
  quantitative LiDAR/camera gate, vehicle-calibration binding, calibration
  authority;
* NEW-326..NEW-333 -- traffic-manager session, seed tree, physics profile,
  experiment-start lifecycle, camera response profile.

No CARLA server is required or contacted: every CARLA object used here is a
duck-typed test double.
"""
from __future__ import annotations

import json
import math
import random
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pytest

from ultimate_pipeline.perception import rq3_capture_contract as rq3
from ultimate_pipeline.perception.environment import calibration_authority as auth
from ultimate_pipeline.perception.environment import calibration_lifecycle as lifecycle
from ultimate_pipeline.perception.environment import camera_intrinsics as intr
from ultimate_pipeline.perception.environment import camera_response as response
from ultimate_pipeline.perception.environment import deterministic_weather as detweather
from ultimate_pipeline.perception.environment import lidar_camera_gate as gate
from ultimate_pipeline.perception.environment import live_calibration_assay as assay
from ultimate_pipeline.perception.environment import physics_profile as physics
from ultimate_pipeline.perception.environment import seed_tree as seeds
from ultimate_pipeline.perception.environment import traffic_manager_session as tms
from ultimate_pipeline.perception.environment import vehicle_binding as binding
from ultimate_pipeline.perception.environment import weather_spec as weather

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CALIB_DATA_PATH = PACKAGE_ROOT / "sensors" / "calib_data.json"


def _calib_data():
    with CALIB_DATA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# ===========================================================================
# doubles
# ===========================================================================


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
    """Duck-typed world whose ``set_weather`` may silently do nothing."""

    def __init__(self, *, honor_set=True, readback_mutator=None):
        self.set_calls = []
        self.ticks = 0
        self._stored = None
        self._honor_set = bool(honor_set)
        self._readback_mutator = readback_mutator

    def set_weather(self, params):
        self.set_calls.append(_to_weather_params(params))
        self._stored = _to_weather_params(params) if self._honor_set else None

    def get_weather(self):
        params = dict(self._stored or {})
        if self._readback_mutator is not None:
            self._readback_mutator(params)
        return params

    def tick(self):
        self.ticks += 1
        return self.ticks


class _FakeTrafficManager:
    def __init__(self, port=8000):
        self._port = int(port)
        self.calls = []

    def get_port(self):
        return self._port

    def set_synchronous_mode(self, *args):
        self.calls.append(("set_synchronous_mode", args))

    def set_distance_to_leading_vehicle(self, *args):
        self.calls.append(("set_distance_to_leading_vehicle", args))

    def set_random_device_seed(self, *args):
        self.calls.append(("set_random_device_seed", args))

    def ignore_lights_percentage(self, *args):
        self.calls.append(("ignore_lights_percentage", args))

    def ignore_signs_percentage(self, *args):
        self.calls.append(("ignore_signs_percentage", args))


class _FakeClient:
    def __init__(self, tm_handle=None, raise_on_get=False):
        self._handle = tm_handle
        self._raise = bool(raise_on_get)
        self.requested_ports = []

    def get_trafficmanager(self, port=8000):
        self.requested_ports.append(int(port))
        if self._raise:
            raise RuntimeError("no_trafficmanager_server")
        return self._handle


class _FakeWorldSettings:
    def __init__(self, synchronous_mode=True):
        self.synchronous_mode = bool(synchronous_mode)


class _FakeSyncWorld:
    def __init__(self, synchronous_mode=True):
        self._settings = _FakeWorldSettings(synchronous_mode)

    def get_settings(self):
        return self._settings


class _FakeActor:
    def __init__(self, name, *, destroy_raises=False, alive_after_destroy=False):
        self.id = name
        self.destroy_calls = 0
        self._alive = True
        self._destroy_raises = bool(destroy_raises)
        self._alive_after_destroy = bool(alive_after_destroy)

    def is_alive(self):
        return bool(self._alive)

    def destroy(self):
        self.destroy_calls += 1
        if self._destroy_raises:
            raise RuntimeError(f"rpc_channel_closed:{self.id}")
        self._alive = self._alive_after_destroy


class _FakeListener:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


class _CleanupWorld:
    def __init__(self, fail_after=None):
        self.settings = _FakeWorldSettings(True)
        self.applied_settings = []
        self._fail_after = fail_after
        self.spawn_count = 0

    def get_settings(self):
        return self.settings

    def apply_settings(self, settings):
        self.applied_settings.append(settings)

    def spawn_actor(self, name):
        self.spawn_count += 1
        if self._fail_after is not None and self.spawn_count > self._fail_after:
            raise RuntimeError("sensor_spawn_failed")
        return _FakeActor(name)


class _LeakyActor:
    """destroy() succeeds but the actor is still alive afterwards."""

    id = 4711

    def __init__(self):
        self.destroy_calls = 0

    def is_alive(self):
        return True

    def destroy(self):
        self.destroy_calls += 1


_IDENTITY4 = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]

#: A benign 1920x1080 pinhole used by the LiDAR/camera and assay tests.
_K = [[1000.0, 0.0, 1000.0], [0.0, 1000.0, 1000.0], [0.0, 0.0, 1.0]]
_WIDTH, _HEIGHT = 1920, 1080


def _pair_manifest(*, manual_arm=None, auto_arm=None, top_overrides=None,
                   weather_sha="w1", claim_level=rq3.CLAIM_PAIRED_PROTOCOL_VALID):
    arm_base = {
        "calibration_sha256": "calib1",
        "sensor_rig_sha256": "rig1",
        "weather_sha256": weather_sha,
        "capture_config_sha256": "cfg1",
        "route_manifest_sha256": "route1",
        "camera_response_sha256": "cam1",
        "traffic_manager_sha256": "tm1",
        "simulation_physics_sha256": "ph1",
        "runtime_sensor_rig_sha256": "rr1",
        "vehicle_calibration_binding_sha256": "vb1",
        # sim_timing_sha256 is a mandatory arm identity: an arm that never
        # recorded how it was timed cannot be shown to be comparable.
        "sim_timing_sha256": "st1",
    }
    manual = dict(arm_base, completion_status=rq3.COMPLETION_PASS,
                  pair_frame_index=[0, 1, 2])
    auto = dict(arm_base, completion_status=rq3.COMPLETION_PASS,
                pair_frame_index=[0, 1, 2])
    manual.update(manual_arm or {})
    auto.update(auto_arm or {})
    top = {
        "calibration_sha256": "calib1",
        "sensor_rig_sha256": "rig1",
        "weather_sha256": weather_sha,
        "capture_config_sha256": "cfg1",
        "route_manifest_sha256": "route1",
        "camera_response_sha256": "cam1",
        "traffic_manager_sha256": "tm1",
        "simulation_physics_sha256": "ph1",
        "runtime_sensor_rig_sha256": "rr1",
        "vehicle_calibration_binding_sha256": "vb1",
        "sim_timing_sha256": "st1",
    }
    top.update(top_overrides or {})
    return rq3.build_pair_manifest(
        pair_id="p-new316-333",
        software_git_sha="deadbeef",
        carla_client_version="0.9.16",
        carla_server_version="0.9.16",
        manual_map_identity=rq3.cooked_arm_map_identity(
            requested_map_name="Grid0821", resolved_carla_map_name="Grid0821"),
        auto_map_identity=rq3.xodr_arm_map_identity(
            xodr_path="campaigns/ingolstadt_auto.xodr", xodr_sha256="x"),
        route_manifest_path="route.json",
        route_manifest_sha256=top["route_manifest_sha256"],
        calibration_sha256=top["calibration_sha256"],
        sensor_rig_sha256=top["sensor_rig_sha256"],
        weather_sha256=top["weather_sha256"],
        capture_config_sha256=top["capture_config_sha256"],
        camera_response_sha256=top["camera_response_sha256"],
        traffic_manager_sha256=top["traffic_manager_sha256"],
        simulation_physics_sha256=top["simulation_physics_sha256"],
        runtime_sensor_rig_sha256=top["runtime_sensor_rig_sha256"],
        vehicle_calibration_binding_sha256=top["vehicle_calibration_binding_sha256"],
        sim_timing_sha256=top["sim_timing_sha256"],
        manual_arm=manual,
        auto_arm=auto,
        pair_valid=True,
        invalid_reasons=[],
        claim_level=claim_level,
    )


# ===========================================================================
# WEATHER -- NEW-316 / NEW-317 / NEW-318
# ===========================================================================


def test_requested_weather_not_applied_raises_weather_application_failed():
    """NEW-316: a requested weather that did not become effective is a failure."""

    def perturb(params):
        params["cloudiness"] = 99.0
        params["fog_density"] = 42.0

    world = _WeatherWorld(readback_mutator=perturb)
    with pytest.raises(weather.WeatherApplicationError) as excinfo:
        weather.apply_weather_and_verify(world, "ClearNoon", settle_ticks=3)

    exc = excinfo.value
    assert exc.failure_code == weather.WEATHER_APPLICATION_FAILED, (
        "a weather that was set but not read back as requested must fail with "
        f"WEATHER_APPLICATION_FAILED, got {exc.failure_code}"
    )
    assert exc.payload["failure_code"] == weather.WEATHER_APPLICATION_FAILED
    assert exc.payload["effective_matches_requested"] is False
    assert set(exc.payload["comparison"]["mismatched_fields"]) == {"cloudiness", "fog_density"}


def test_weather_not_applied_is_never_warning_only():
    """NEW-316: `set_weather` that silently does nothing must still fail closed."""
    world = _WeatherWorld(honor_set=False)
    with pytest.raises(weather.WeatherApplicationError) as excinfo:
        weather.apply_weather_and_verify(world, "ClearNoon", settle_ticks=2)

    exc = excinfo.value
    assert exc.failure_code == weather.WEATHER_APPLICATION_FAILED
    payload = exc.payload
    assert payload["failure_code"] == weather.WEATHER_APPLICATION_FAILED, (
        "the evidence payload must carry the failure code so the caller can "
        "persist it; a warning-only outcome would leave it None"
    )
    assert payload["effective_matches_requested"] is False
    assert payload["comparison"]["match"] is False
    # the requested identity was never obtained
    assert exc.payload["requested_preset"] == "ClearNoon"


def test_pair_manual_vs_auto_weather_mismatch_rejected():
    result = weather.validate_arm_weather_binding("sha-manual", "sha-auto")
    assert result["valid"] is False
    assert any(r.startswith(weather.PAIR_WEATHER_MISMATCH) for r in result["invalid_reasons"]), (
        "differing arm weather identities must report PAIR_WEATHER_MISMATCH, got "
        f"{result['invalid_reasons']}"
    )


def test_pair_manual_weather_missing_rejected():
    result = weather.validate_arm_weather_binding(
        "", "sha-auto", pair_weather_sha256="sha-auto", manual_present=False)
    assert result["valid"] is False
    assert any(weather.PAIR_WEATHER_MISSING_ARM in r for r in result["invalid_reasons"]), (
        f"a missing manual arm weather identity must be PAIR_WEATHER_MISSING_ARM: "
        f"{result['invalid_reasons']}"
    )


def test_pair_auto_weather_missing_rejected():
    result = weather.validate_arm_weather_binding(
        "sha-manual", "", pair_weather_sha256="sha-manual", auto_present=False)
    assert result["valid"] is False
    assert any(weather.PAIR_WEATHER_MISSING_ARM in r for r in result["invalid_reasons"]), (
        f"a missing auto arm weather identity must be PAIR_WEATHER_MISSING_ARM: "
        f"{result['invalid_reasons']}"
    )


def test_fog_falloff_difference_changes_weather_digest_v2_sees_it():
    """NEW-318: `fog_falloff` was invisible to the legacy 11-field identity."""
    base = dict(weather.FROZEN_PRESETS_0_9_16["ClearNoon"])
    other = dict(base, fog_falloff=0.9)

    assert "fog_falloff" not in rq3.WEATHER_IDENTITY_V1_FIELDS, (
        "premise: the legacy identity must not contain fog_falloff"
    )
    assert "fog_falloff" in rq3.WEATHER_IDENTITY_COMPLETE_FIELDS
    assert "fog_falloff" in weather.WEATHER_NUMERIC_FIELDS

    a = weather.weather_identity_v2(base)
    b = weather.weather_identity_v2(other)
    assert a["weather_sha256"] != b["weather_sha256"], (
        "two arms differing only in fog_falloff must not share a weather_sha256"
    )
    assert a["parameter_count"] == len(weather.WEATHER_NUMERIC_FIELDS)
    assert b["parameters"]["fog_falloff"] == pytest.approx(0.9)


def test_rayleigh_scattering_difference_changes_weather_digest():
    base = dict(weather.FROZEN_PRESETS_0_9_16["ClearNoon"])
    other = dict(base, rayleigh_scattering_scale=0.5)
    assert "rayleigh_scattering_scale" not in rq3.WEATHER_IDENTITY_V1_FIELDS
    a = weather.weather_identity_v2(base)
    b = weather.weather_identity_v2(other)
    assert a["weather_sha256"] != b["weather_sha256"]
    assert b["parameters"]["rayleigh_scattering_scale"] == pytest.approx(0.5)


def test_dust_storm_difference_changes_weather_digest():
    base = dict(weather.FROZEN_PRESETS_0_9_16["ClearNoon"])
    other = dict(base, dust_storm=100.0)
    assert "dust_storm" not in rq3.WEATHER_IDENTITY_V1_FIELDS
    a = weather.weather_identity_v2(base)
    b = weather.weather_identity_v2(other)
    assert a["weather_sha256"] != b["weather_sha256"]
    assert b["parameters"]["dust_storm"] == pytest.approx(100.0)


def test_weather_identity_v2_records_schema_version_and_unsupported_fields():
    ident = weather.weather_identity_v2(weather.FROZEN_PRESETS_0_9_16["ClearNoon"])
    assert ident["weather_schema_version"] == weather.WEATHER_SCHEMA_VERSION
    assert "unsupported_fields" in ident
    assert isinstance(ident["unsupported_fields"], list)
    assert ident["identity_complete"] is True
    assert ident["read_errors"] == []

    caps = weather.weather_schema_capabilities()
    # every field the installed API supports is present in the identity
    for field in caps["supported_fields"]:
        assert field in ident["parameters"], (
            f"{field} is a supported field but was omitted from the identity"
        )
    # ...and anything the API does not support is reported, never defaulted away
    unsupported = set(caps["unsupported_fields"])
    assert set(ident["unsupported_fields"]) == {
        f for f in unsupported if f not in ident["parameters"]}
    assert not (set(ident["unsupported_fields"]) & set(ident["parameters"]))

    # a supported field that cannot be read is reported, and marks the identity
    # incomplete rather than being silently dropped
    partial = dict(weather.FROZEN_PRESETS_0_9_16["ClearNoon"])
    partial.pop("fog_falloff")
    incomplete = weather.weather_identity_v2(partial)
    assert incomplete["identity_complete"] is False
    assert "fog_falloff" in incomplete["supported_but_unreadable_fields"]
    assert incomplete["weather_sha256"] != ident["weather_sha256"]


def test_unknown_weather_preset_unsupported():
    spec = weather.resolve_weather_spec("TotallyBogusWeather")
    assert spec["ok"] is False
    assert spec["failure_code"] == weather.WEATHER_PRESET_UNSUPPORTED
    assert spec["parameters"] == {}

    world = _WeatherWorld()
    with pytest.raises(weather.WeatherApplicationError) as excinfo:
        weather.apply_weather_and_verify(world, "TotallyBogusWeather")
    assert excinfo.value.failure_code == weather.WEATHER_PRESET_UNSUPPORTED
    assert world.set_calls == [], (
        "an unsupported preset must fail before anything is applied to the world"
    )


def test_hand_edited_top_level_weather_sha_does_not_rescue_missing_arm_identity():
    """NEW-317 key case: the top-level SHA matches, the manual arm's is absent."""
    manifest = _pair_manifest(weather_sha="sha-auto-only")
    assert manifest["manual_arm"]["weather_sha256"] == "sha-auto-only"
    assert manifest["auto_arm"]["weather_sha256"] == "sha-auto-only"
    assert manifest["weather_sha256"] == "sha-auto-only"

    del manifest["manual_arm"]["weather_sha256"]

    result = rq3.validate_pair_manifest(manifest)
    assert result["valid"] is False
    assert f"{rq3.PAIR_ARM_IDENTITY_MISSING}:manual:weather_sha256" in result["invalid_reasons"], (
        "a hand-edited top-level weather_sha256 must not rescue a missing manual "
        f"arm identity; got {result['invalid_reasons']}"
    )


# ===========================================================================
# WEATHER DETERMINISM -- NEW-319
# ===========================================================================


def _scheduled_controller(seed):
    controller = detweather.DeterministicWeatherController(
        mode=detweather.MODE_GOVERNED_SCHEDULED,
        seed=seed,
        presets=["ClearNoon", "MidRainyNoon", "CloudyNoon", "HardRainNoon"],
        ticks_per_step=50,
    )
    controller.build_schedule()
    return controller


def _drive(controller, frames, world):
    for frame in frames:
        controller.tick(world, frame)


def test_same_seed_yields_identical_schedule_and_transition_frames():
    frames = list(range(0, 200, 25))
    a = _scheduled_controller(1234)
    b = _scheduled_controller(1234)
    _drive(a, frames, _WeatherWorld())
    _drive(b, frames, _WeatherWorld())

    pa, pb = a.proof(), b.proof()
    assert a.schedule_sha256 == b.schedule_sha256
    assert pa["transition_frame_ids"] == pb["transition_frame_ids"]
    assert pa["transition_frame_ids"] == [0, 50, 100, 150], (
        "ticks_per_step=50 over 4 scheduled steps must transition at the frame "
        f"boundaries, got {pa['transition_frame_ids']}"
    )
    verdict = detweather.DeterministicWeatherController.determinism_proof(pa, pb)
    assert verdict["identical"] is True, verdict["invalid_reasons"]


def test_different_seed_yields_different_schedule_digest():
    a = _scheduled_controller(1234)
    b = _scheduled_controller(4321)
    assert a.schedule_sha256
    assert b.schedule_sha256
    assert a.schedule_sha256 != b.schedule_sha256, (
        "the weather seed must actually enter the governed schedule digest"
    )


def test_wall_clock_speed_does_not_change_the_governed_schedule(monkeypatch):
    frames = list(range(0, 200, 25))
    fast = _scheduled_controller(99)
    _drive(fast, frames, _WeatherWorld())

    monkeypatch.setattr(detweather.time, "time", lambda: 4.102e9)
    slow = _scheduled_controller(99)
    _drive(slow, frames, _WeatherWorld())

    pf, ps = fast.proof(), slow.proof()
    assert slow.schedule_sha256 == fast.schedule_sha256, (
        "the schedule digest must not depend on the host wall clock"
    )
    assert ps["transition_frame_ids"] == pf["transition_frame_ids"], (
        "frame-driven transitions must not depend on the host wall clock"
    )
    assert detweather.DeterministicWeatherController.determinism_proof(pf, ps)["identical"] is True


def test_dynamic_weather_mode_rejected_for_paired_claim():
    diag_a = detweather.DeterministicWeatherController(
        mode=detweather.MODE_DIAGNOSTIC_DYNAMIC, seed=7, preset="ClearNoon",
        ticks_per_step=50).proof()
    diag_b = detweather.DeterministicWeatherController(
        mode=detweather.MODE_DIAGNOSTIC_DYNAMIC, seed=7, preset="ClearNoon",
        ticks_per_step=50).proof()
    assert diag_a["governed"] is False and diag_b["governed"] is False

    verdict = detweather.DeterministicWeatherController.determinism_proof(diag_a, diag_b)
    assert verdict["identical"] is False
    assert any(detweather.WEATHER_MODE_DYNAMIC_FORBIDDEN in r
               for r in verdict["invalid_reasons"]), (
        "a DIAGNOSTIC_DYNAMIC_WEATHER proof must be refused for a paired claim: "
        f"{verdict['invalid_reasons']}"
    )


def test_governed_weather_control_does_not_mutate_process_global_rng():
    random.seed(20260918)
    before_value = random.random()
    # `armed_state` is taken *after* the seeding draw, so any further change can
    # only have come from the governed controllers under test.
    armed_state = random.getstate()

    frames = list(range(0, 200, 25))
    for seed in (1, 2, 3):
        controller = _scheduled_controller(seed)
        _drive(controller, frames, _WeatherWorld())
    fixed = detweather.DeterministicWeatherController(
        mode=detweather.MODE_GOVERNED_FIXED, seed=11, preset="ClearNoon")
    _drive(fixed, frames, _WeatherWorld())

    assert random.getstate() == armed_state, (
        "governed weather control advanced the process-global RNG; NEW-319 "
        "requires an owned random.Random instance only"
    )
    assert random.random() != before_value  # sanity: the global stream is live
    random.seed(20260918)
    assert random.random() == before_value


# ===========================================================================
# CAMERA INTRINSICS -- NEW-320
# ===========================================================================


def test_fx_equal_but_fy_differs_is_reported_with_a_remap_strategy():
    calib = _calib_data()
    cam = calib["cameras"]["back_left_camera"]
    width, height = cam["image_size"]
    entry = intr.camera_intrinsic_realization(
        "back_left_camera", cam["K_undistortion"], width, height)

    assert entry["delta_fx"] == pytest.approx(0.0, abs=1e-6), (
        "premise: the configured FOV is derived from the target fx"
    )
    assert entry["delta_fy"] != 0.0, (
        "CARLA forces fx == fy, so a non-square target K must surface a "
        f"non-zero delta_fy; got {entry['delta_fy']}"
    )
    assert entry["strategy"] in (
        intr.STRATEGY_DETERMINISTIC_REMAP, intr.STRATEGY_BOUNDED_APPROXIMATION,
    ), f"unexpected strategy {entry['strategy']}"
    assert entry["residual"]["rmse_fy_px"] == pytest.approx(abs(entry["delta_fy"]))
    assert entry["fy_relative_error_pct"] < -1.0


def test_principal_point_offset_is_reported_non_zero():
    calib = _calib_data()
    cam = calib["cameras"]["right_camera"]
    width, height = cam["image_size"]
    entry = intr.camera_intrinsic_realization(
        "right_camera", cam["K_undistortion"], width, height)

    assert entry["delta_cx"] != 0.0 and entry["delta_cy"] != 0.0, (
        "CARLA pins the principal point to the image centre, so a target K with "
        f"an offset must surface it: delta_cx={entry['delta_cx']} "
        f"delta_cy={entry['delta_cy']}"
    )
    assert entry["cx_relative_error_pct"] < -1.0
    assert entry["cy_relative_error_pct"] > 1.0
    assert entry["residual"]["max_abs_delta_px"] == pytest.approx(
        max(abs(entry["delta_cx"]), abs(entry["delta_cy"])))


def test_unrealisable_target_k_returns_bounded_approximation_with_residual():
    calib = _calib_data()
    cam = calib["cameras"]["right_camera"]
    width, height = cam["image_size"]
    entry = intr.camera_intrinsic_realization(
        "right_camera", cam["K_undistortion"], width, height)

    assert entry["strategy"] == intr.STRATEGY_BOUNDED_APPROXIMATION, (
        "the worst-case calibration camera must be declared a bounded "
        f"approximation, got {entry['strategy']}"
    )
    coverage = entry["mapping"]["coverage_fraction"]
    assert coverage < 1.0, "a bounded approximation must quantify its coverage"
    assert coverage == pytest.approx(0.892148, abs=1e-6)
    assert entry["residual"]["observable_crop"], "the observable crop must be reported"
    assert entry["bounded_reason"], "the reason for bounding must be recorded"
    assert entry["exact_calibration_claim"] is False
    assert entry["residual"]["unobservable_target_pixels"] > 0


def test_remapped_rgb_and_semantic_agree_with_independently_predicted_native_pixel():
    calib = _calib_data()
    cam = calib["cameras"]["right_camera"]
    width, height = cam["image_size"]
    k_target = np.asarray(cam["K_undistortion"], dtype=float)
    entry = intr.camera_intrinsic_realization(
        "right_camera", cam["K_undistortion"], width, height)
    k_native = np.asarray(entry["K_native_carla"], dtype=float)
    grid = intr.compute_remap_grid(k_target, k_native, width, height)
    valid = grid["valid"]
    nw, nh = grid["native_width_px"], grid["native_height_px"]

    # A synthetic native frame whose value IS its own pixel coordinate.
    native_u = np.broadcast_to(np.arange(nw, dtype=np.float64), (nh, nw))
    native_v = np.broadcast_to(np.arange(nh, dtype=np.float64)[:, None], (nh, nw))
    native_rgb = np.stack([native_u, native_v], axis=-1)
    native_sem = (native_v * nw + native_u).astype(np.int64)

    rgb_out = intr.remap_rgb(native_rgb, grid)
    sem_out = intr.remap_labels(native_sem, grid, "semantic_seg")

    # Independent prediction of the native pixel, computed here from scratch.
    homography = k_native @ np.linalg.inv(k_target)
    tu, tv = np.meshgrid(np.arange(width, dtype=float),
                         np.arange(height, dtype=float), indexing="xy")
    homogeneous = homography @ np.stack(
        [tu.ravel(), tv.ravel(), np.ones(tu.size)], axis=0)
    pred_u = (homogeneous[0] / homogeneous[2]).reshape(height, width)
    pred_v = (homogeneous[1] / homogeneous[2]).reshape(height, width)

    assert valid.any(), "premise: the crop has observable target pixels"

    rgb_err_u = np.abs(rgb_out[..., 0] - pred_u)[valid].max()
    rgb_err_v = np.abs(rgb_out[..., 1] - pred_v)[valid].max()
    assert rgb_err_u < 0.5, f"bilinear RGB lost the native pixel (u err {rgb_err_u})"
    assert rgb_err_v < 0.5, f"bilinear RGB lost the native pixel (v err {rgb_err_v})"

    sem_u = np.mod(sem_out, nw).astype(float)
    sem_v = np.floor(sem_out.astype(float) / nw)
    sem_err_u = np.abs(sem_u - pred_u)[valid].max()
    sem_err_v = np.abs(sem_v - pred_v)[valid].max()
    assert sem_err_u < 0.5, f"nearest semantic remap lost the native pixel (u err {sem_err_u})"
    assert sem_err_v < 0.5, f"nearest semantic remap lost the native pixel (v err {sem_err_v})"

    gap_u = np.abs(sem_u - pred_u - (rgb_out[..., 0] - pred_u))[valid].max()
    gap_v = np.abs(sem_v - pred_v - (rgb_out[..., 1] - pred_v))[valid].max()
    assert gap_u < 0.5 and gap_v < 0.5, (
        f"RGB and semantic must stay in exact correspondence, gaps {gap_u}/{gap_v}"
    )


def test_semantic_remap_never_uses_bilinear():
    calib = _calib_data()
    cam = calib["cameras"]["front_left_camera"]
    width, height = cam["image_size"]
    k_target = np.asarray(cam["K_undistortion"], dtype=float)
    entry = intr.camera_intrinsic_realization(
        "front_left_camera", cam["K_undistortion"], width, height)
    k_native = np.asarray(entry["K_native_carla"], dtype=float)
    grid = intr.compute_remap_grid(k_target, k_native, width, height)
    labels = np.zeros((grid["native_height_px"], grid["native_width_px"]), dtype=np.int64)
    class_ids = np.arange(1, 8, dtype=np.int64)
    labels[:] = np.resize(class_ids, labels.shape)

    with pytest.raises(ValueError) as excinfo:
        intr.remap_labels(labels, grid, "semantic_seg", interpolation="BILINEAR")
    assert "label_modality_forbids_interpolation" in str(excinfo.value)

    with pytest.raises(ValueError) as excinfo:
        intr.apply_remap(labels, grid, "semantic_seg", interpolation="BILINEAR")
    assert "label_modality_forbids_interpolation" in str(excinfo.value)

    # the governed nearest-neighbour path still works and never invents a class id
    out = intr.remap_labels(labels, grid, "semantic_seg")
    assert out.dtype == np.int64
    assert out.shape == (height, width)
    produced = set(np.unique(out).tolist())
    assert produced.issubset(set(class_ids.tolist())), (
        f"a label remap must not synthesise class ids, got {sorted(produced)}"
    )


def test_invalid_remap_coverage_is_reported_for_every_real_calib_camera():
    calib = _calib_data()
    assert calib["cameras"], "the real calibration fixture must contain cameras"
    for name in sorted(calib["cameras"]):
        cam = calib["cameras"][name]
        width, height = cam["image_size"]
        k_target = np.asarray(cam["K_undistortion"], dtype=float)
        entry = intr.camera_intrinsic_realization(name, cam["K_undistortion"], width, height)
        k_native = np.asarray(entry["K_native_carla"], dtype=float)
        grid = intr.compute_remap_grid(k_target, k_native, width, height)
        valid = np.asarray(grid["valid"], dtype=bool)

        assert grid["coverage_fraction"] < 1.0, (
            f"{name}: coverage must be below 1 for a non-native K_target"
        )
        assert grid["invalid_pixel_count"] > 0, (
            f"{name}: unobservable target pixels must be counted, not hidden"
        )
        assert int(np.count_nonzero(~valid)) == grid["invalid_pixel_count"]
        assert bool(valid.all()) is False, (
            f"{name}: not every target pixel is observable from the native K"
        )
        assert grid["observable_crop"], f"{name}: the observable crop must be reported"
        assert grid["policies"]["semantic_seg"] == intr.REMAP_POLICIES["semantic_seg"]
        # invalid pixels are masked, never extrapolated
        depth_source = np.full((grid["native_height_px"], grid["native_width_px"]),
                               7.0, dtype=np.float64)
        remapped_depth = intr.remap_depth(depth_source, grid, invalid_value=0.0)
        assert np.all(remapped_depth[~valid] == 0.0), (
            f"{name}: unobservable pixels must not be filled with extrapolated data"
        )


# ===========================================================================
# LIVE CALIBRATION ASSAY -- NEW-321
# ===========================================================================


def _assay_targets(count=10, x_from=-4.0, x_to=4.0):
    targets = []
    step = (x_to - x_from) / max(1, count - 1)
    for index in range(count):
        targets.append({
            "name": f"marker_{index:02d}",
            "point_vehicle": [x_from + step * index, 0.0, 10.0],
        })
    return targets


def _observed_from_prediction(targets, offset=0.0):
    observations = {}
    for target in targets:
        predicted = assay.predict_target_pixel(_K, target["point_vehicle"], _IDENTITY4)
        assert predicted is not None
        observations[target["name"]] = [predicted[0] + offset, predicted[1]]
    return observations


def test_live_reprojection_target_not_detected_is_a_fail():
    targets = _assay_targets()
    result = assay.evaluate_camera_reprojection(
        camera_name="front_left_camera", k_matrix=_K, cTv=_IDENTITY4,
        width_px=_WIDTH, height_px=_HEIGHT, targets=targets, observations={})

    assert result["verdict"] == assay.VERDICT_LIVE_FAIL
    assert result["valid"] is False
    assert result["targets_expected_visible"] == len(targets)
    assert result["targets_detected"] == 0
    assert any(assay.REPROJECTION_TARGET_NOT_DETECTED in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]


def test_live_reprojection_p95_above_threshold_is_a_fail():
    targets = _assay_targets()
    offset = assay.ACCEPTANCE_THRESHOLDS["max_p95_reprojection_error_px"] + 1.5
    observations = _observed_from_prediction(targets, offset=offset)

    result = assay.evaluate_camera_reprojection(
        camera_name="front_left_camera", k_matrix=_K, cTv=_IDENTITY4,
        width_px=_WIDTH, height_px=_HEIGHT, targets=targets,
        observations=observations)

    stats = result["reprojection_error_px"]
    assert stats["p95"] > assay.ACCEPTANCE_THRESHOLDS["max_p95_reprojection_error_px"]
    assert stats["max"] <= assay.ACCEPTANCE_THRESHOLDS["max_reprojection_error_px"], (
        "premise: only the p95 gate should be the discriminating statistic"
    )
    assert result["verdict"] == assay.VERDICT_LIVE_FAIL
    assert any(assay.REPROJECTION_P95_EXCEEDED in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]


def test_lidar_projection_outside_image_fails_the_gate():
    # 5 m in front, 2 m to the left of the image centre -> projected off-image
    c_tv = [
        [1.0, 0.0, 0.0, -12.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    result = gate.lidar_camera_gate(
        k_matrix=_K, width_px=_WIDTH, height_px=_HEIGHT,
        vTl=_IDENTITY4, cTv=c_tv,
        vehicle_targets={"forward_5m": (5.0, 2.0, 5.0)})

    assert result["ok"] is False
    assert any(gate.LIDAR_PROJECTION_OUTSIDE_IMAGE in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]
    check = result["checks"][0]
    assert check["camera_depth_m"] > 0.0, (
        "premise: the projection has positive depth, so only the bounds check "
        "can reject it"
    )
    u, v = check["pixel"]
    assert not (0.0 <= u < _WIDTH and 0.0 <= v < _HEIGHT)


def test_lidar_pixel_far_outside_image_with_positive_depth_does_not_pass():
    """NEW-323 regression: `[-5000, 20000]` with positive depth used to PASS."""
    c_tv = [
        [1.0, 0.0, 0.0, -6.0],
        [0.0, 1.0, 0.0, 19.0],
        [0.0, 0.0, 1.0, 1.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    result = gate.lidar_camera_gate(
        k_matrix=_K, width_px=_WIDTH, height_px=_HEIGHT,
        vTl=_IDENTITY4, cTv=c_tv,
        vehicle_targets={"forward_5m": (0.0, 0.0, 0.0)})

    check = result["checks"][0]
    assert check["pixel"] == [-5000.0, 20000.0], (
        "premise: the legacy defect produced exactly this far-outside pixel, "
        f"got {check['pixel']}"
    )
    assert check["camera_depth_m"] == pytest.approx(1.0)
    assert check["ok"] is False, (
        "a positive-depth projection far outside the image must not count as a "
        "successful LiDAR-camera check"
    )
    assert result["ok"] is False
    assert result["targets_passed"] == 0
    assert any(gate.LIDAR_PROJECTION_OUTSIDE_IMAGE in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]


def test_lidar_residual_above_threshold_fails_the_gate():
    targets = {
        "forward_5m": (1.0, 0.0, 5.0),
        "forward_10m": (2.0, 0.0, 10.0),
    }
    predicted = {}
    for name, point in targets.items():
        pixel = gate.check_projection(
            _K, point, _IDENTITY4, _IDENTITY4,
            width_px=_WIDTH, height_px=_HEIGHT, target_name=name)
        assert pixel["pixel"] is not None, f"premise: {name} must project inside"
        predicted[name] = pixel["pixel"]

    threshold = gate.DEFAULT_GATE_THRESHOLDS["max_reprojection_residual_px"]
    observed = {name: [p[0] + (threshold * 3.0), p[1]] for name, p in predicted.items()}

    result = gate.lidar_camera_gate(
        k_matrix=_K, width_px=_WIDTH, height_px=_HEIGHT,
        vTl=_IDENTITY4, cTv=_IDENTITY4,
        vehicle_targets=targets, observed_pixels=observed)

    assert result["ok"] is False
    assert result["residual_px"]["count"] == len(targets)
    assert result["residual_px"]["max"] > threshold
    assert any(gate.LIDAR_PROJECTION_RESIDUAL_EXCEEDED in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]


def test_predicted_vs_predicted_reprojection_is_refused():
    targets = _assay_targets()
    observations = _observed_from_prediction(targets)

    result = assay.evaluate_camera_reprojection(
        camera_name="front_left_camera", k_matrix=_K, cTv=_IDENTITY4,
        width_px=_WIDTH, height_px=_HEIGHT, targets=targets,
        observations=observations, observed_source="predicted")

    assert result["verdict"] == assay.VERDICT_LIVE_FAIL
    assert any(assay.REPROJECTION_PREDICTED_VS_PREDICTED in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]
    assert result["targets_detected"] == 0, (
        "predicted-vs-predicted must be refused before any scoring happens"
    )


def test_no_live_evidence_blocks_acceptance_despite_mathematical_pass():
    result = assay.calibration_acceptance(
        mathematical_contract_verdict=assay.VERDICT_MATHEMATICAL_PASS,
        live_evidence_available=False)

    assert result["mathematical_contract_verdict"] == assay.VERDICT_MATHEMATICAL_PASS
    assert result["live_reprojection_verdict"] == assay.VERDICT_BLOCKED
    assert result["accepted"] is False, (
        "MATHEMATICAL_CONTRACT_PASS must never upgrade a blocked live assay"
    )
    assert result["claim"] == assay.VERDICT_BLOCKED
    assert result["verdicts_are_distinct"] is True
    assert result["mathematical_pass_does_not_imply_live_pass"] is True
    assert result["live_evidence_available"] is False
    assert result["thresholds_declared"]["declared_before_run"] is True


# ===========================================================================
# CLEANUP -- NEW-322
# ===========================================================================


def test_exception_during_sensor_spawn_still_destroys_every_registered_actor(tmp_path):
    world = _CleanupWorld(fail_after=2)
    guard = lifecycle.CalibrationCleanupGuard(world, out_dir=tmp_path)
    ego = sensor_a = sensor_b = temp = None
    with pytest.raises(RuntimeError) as excinfo:
        with guard:
            ego = guard.track_ego(_FakeActor("ego"))
            sensor_a = guard.track_sensor(world.spawn_actor("sensor_a"))
            sensor_b = guard.track_sensor(world.spawn_actor("sensor_b"))
            temp = guard.track_temp_actor(_FakeActor("calibration_target"))
            world.spawn_actor("sensor_c")  # raises: the spawn path blew up
    assert "sensor_spawn_failed" in str(excinfo.value)

    receipt = guard.receipt()
    assert guard.cleanup_complete() is True, guard.cleanup_complete_reasons()
    assert receipt["cleanup_complete"] is True
    assert receipt["guarded_failure_reason"] == "exception_during_assay"
    assert receipt["guarded_exception"].startswith("RuntimeError:sensor_spawn_failed")
    for actor in (ego, sensor_a, sensor_b, temp):
        assert actor.destroy_calls == 1
        assert actor.is_alive() is False, f"{actor.id} leaked into the next run"
    groups = receipt["cleanup_results"]["groups"]
    assert sorted(groups["sensors"]["destroyed"]) == ["sensor_a", "sensor_b"]
    assert groups["ego"]["clean"] is True
    assert receipt["residual_actor_leak_possible"] is False

    written = guard.write_receipt()
    assert written is not None
    with open(written, "r", encoding="utf-8") as handle:
        on_disk = json.load(handle)
    assert on_disk["cleanup_complete"] is True


def test_exception_during_image_callback_still_destroys_every_actor(tmp_path):
    world = _CleanupWorld()
    guard = lifecycle.CalibrationCleanupGuard(world, out_dir=tmp_path)
    listener = _FakeListener()

    def image_callback(_image):
        raise RuntimeError("image_callback_failed")

    ego = sensor = None
    with pytest.raises(RuntimeError) as excinfo:
        with guard:
            ego = guard.track_ego(world.spawn_actor("ego"))
            sensor = guard.track_sensor(world.spawn_actor("sensor"))
            guard.track_listener(listener)
            image_callback(object())

    assert "image_callback_failed" in str(excinfo.value)
    receipt = guard.receipt()
    assert guard.cleanup_complete() is True, guard.cleanup_complete_reasons()
    assert receipt["cleanup_complete"] is True
    assert listener.stop_calls == 1, "the sensor listener must be stopped"
    assert ego.destroy_calls == 1 and ego.is_alive() is False
    assert sensor.destroy_calls == 1 and sensor.is_alive() is False
    assert receipt["guarded_exception"].startswith("RuntimeError:image_callback_failed")


def test_actor_whose_destroy_raises_is_reported_as_a_survivor(tmp_path):
    world = _CleanupWorld()
    guard = lifecycle.CalibrationCleanupGuard(world, out_dir=tmp_path)
    with guard:
        guard.track_ego(_FakeActor("ego"))
        stubborn = guard.track_sensor(
            _FakeActor("stubborn_sensor", destroy_raises=True))
        guard.track_sensor(_FakeActor("good_sensor"))
    # a second guard run shows a destroy() that raises even when the actor
    # reports itself dead afterwards
    guard2 = lifecycle.CalibrationCleanupGuard(world, out_dir=tmp_path)
    with guard2:
        guard2.track_sensor(
            _FakeActor("zombie", destroy_raises=True, alive_after_destroy=True))

    receipt = guard.receipt()
    assert receipt["cleanup_complete"] is False
    assert any(lifecycle.CLEANUP_ACTOR_SURVIVED in r
               for r in receipt["invalid_reasons"]), receipt["invalid_reasons"]
    assert "stubborn_sensor" in str(receipt["invalid_reasons"])
    assert receipt["residual_actor_leak_possible"] is True
    assert receipt["next_perception_run_contaminated"] is True
    assert stubborn.is_alive() is True
    assert stubborn.destroy_calls == 1

    receipt2 = guard2.receipt()
    assert receipt2["cleanup_complete"] is False
    assert any(lifecycle.CLEANUP_ACTOR_SURVIVED in r
               for r in receipt2["invalid_reasons"]), receipt2["invalid_reasons"]
    assert "zombie" in str(receipt2["invalid_reasons"])


# ===========================================================================
# VEHICLE BINDING -- NEW-324
# ===========================================================================


def _incompatible_dimension():
    # a blueprint bounding box that is nowhere near the calibration vehicle
    return {"available": True, "length_m": 4.5, "width_m": 2.9, "height_m": 1.4}


def test_incompatible_vehicle_geometry_refuses_the_rig_replica_claim():
    calib = _calib_data()
    built = binding.build_binding(
        calib, blueprint_id="vehicle.tesla.model3",
        actual_dimension=_incompatible_dimension(),
        manual_blueprint_id="vehicle.tesla.model3",
        auto_blueprint_id="vehicle.tesla.model3",
        requested_claim=binding.CLAIM_RIG_REPLICA)

    assert built["valid"] is False
    assert built["dimensional_comparison"]["dimensions_compatible"] is False
    assert built["claim_granted"] is False
    assert built["resolved_claim"] == "UNCLAIMED"
    assert any(binding.VEHICLE_RIG_REPLICA_FORBIDDEN in r
               for r in built["claim_reasons"]), built["claim_reasons"]

    verdict = binding.validate_claim_level(
        built, requested_claim=binding.CLAIM_RIG_REPLICA)
    assert verdict["valid"] is False
    assert any(binding.VEHICLE_RIG_REPLICA_FORBIDDEN in r
               for r in verdict["invalid_reasons"]), verdict["invalid_reasons"]


def test_same_invalid_calibration_on_both_arms_never_becomes_a_rig_pass():
    calib = _calib_data()
    built = binding.build_binding(
        calib, blueprint_id="vehicle.tesla.model3",
        actual_dimension=_incompatible_dimension(),
        manual_blueprint_id="vehicle.tesla.model3",
        auto_blueprint_id="vehicle.tesla.model3",
        requested_claim=binding.CLAIM_PAIRWISE_SIM)

    pairwise = binding.validate_claim_level(
        built, requested_claim=binding.CLAIM_PAIRWISE_SIM)
    assert pairwise["valid"] is True, (
        "the same simulated vehicle on both arms may still be compared"
    )
    assert built["same_simulated_vehicle_both_arms"] is True
    assert built["dimensional_comparison"]["dimensions_compatible"] is False

    replica = binding.validate_claim_level(
        built, requested_claim=binding.CLAIM_RIG_REPLICA)
    assert replica["valid"] is False, (
        "using the same wrong calibration on both arms must not grant physical "
        "rig geometry fidelity"
    )
    assert any(binding.VEHICLE_RIG_REPLICA_FORBIDDEN in r
               for r in replica["invalid_reasons"]), replica["invalid_reasons"]
    assert replica["granted_claim"] != binding.CLAIM_RIG_REPLICA


# ===========================================================================
# CALIBRATION AUTHORITY -- NEW-325
# ===========================================================================


def test_heuristic_export_is_rejected_by_a_strict_perception_loader(tmp_path):
    export = {
        "format": auth.LEGACY_EXPORT_FORMAT,
        "cameras": {},
        "lidars": {},
        "global_selected_convention": "no_invert",
    }
    stamped = auth.attach_diagnostic_status(export, selected_convention="no_invert")
    assert stamped["calibration_authority"]["authoritative"] is False
    assert auth.is_diagnostic_export(stamped) is True

    verdict = auth.assert_loadable_by_perception(
        stamped, source="calibrate_sensors_in_carla_export.json", strict=True)
    assert verdict["loadable"] is False
    assert any(auth.HEURISTIC_EXPORT_REJECTED in r
               for r in verdict["invalid_reasons"]), verdict["invalid_reasons"]
    assert verdict["authoritative"] is False

    # even on disk, and even when renamed away from the diagnostic schema
    path = tmp_path / "carla_export_v1.json"
    path.write_text(json.dumps(stamped), encoding="utf-8")
    with path.open("r", encoding="utf-8") as handle:
        reloaded = json.load(handle)
    assert auth.assert_loadable_by_perception(reloaded, strict=True)["loadable"] is False

    # the authoritative path accepts the real calibration
    assert auth.authoritative_calibration(CALIB_DATA_PATH)["verdict"] == "PASS"


def test_strict_mode_refuses_heuristic_convention_selection():
    result = auth.reject_heuristic_convention_selection(
        strict=True, selected_convention="no_invert",
        source="ultimate_pipeline.tools.calibrate_sensors_in_carla")
    assert result["allowed"] is False
    assert result["authoritative"] is False
    assert any(auth.HEURISTIC_CONVENTION_FORBIDDEN in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]


def test_canonical_calibration_contract_validates_real_calib_data():
    result = auth.authoritative_calibration(CALIB_DATA_PATH)
    assert result["verdict"] == "PASS", result["invalid_reasons"]
    assert result["authoritative"] is True
    assert result["status"] == auth.STATUS_AUTHORITATIVE
    assert result["calib_sha256"]
    assert result["authority"] == "ultimate_pipeline.sensors.calibration_contract"


# ===========================================================================
# TRAFFIC MANAGER -- NEW-326 / NEW-328 / NEW-329 / NEW-330
# ===========================================================================


def test_traffic_manager_unavailable_never_falls_back_to_the_default_manager():
    tms.TrafficManagerSession.reset_master_registry()
    session = tms.TrafficManagerSession(
        seed=1234, strict=True, tm_port=8100, session_id="tm-unavailable")
    client = _FakeClient(raise_on_get=True)

    with pytest.raises(RuntimeError) as excinfo:
        session.acquire(client)
    assert tms.TRAFFIC_MANAGER_SETUP_FAILED in str(excinfo.value), (
        "strict TM acquisition must fail closed instead of silently using the "
        f"unseeded default manager; got {excinfo.value}"
    )

    class _Ego:
        def __init__(self):
            self.autopilot_calls = []

        def set_autopilot(self, *args):
            self.autopilot_calls.append(args)

    ego = _Ego()
    with pytest.raises(RuntimeError) as excinfo:
        session.enable_autopilot(ego)
    assert tms.TRAFFIC_MANAGER_SETUP_FAILED in str(excinfo.value)
    assert ego.autopilot_calls == [], (
        "an unbound set_autopilot(True) with no port must never be issued"
    )


def test_two_traffic_manager_masters_on_one_port_are_refused():
    tms.TrafficManagerSession.reset_master_registry()
    first = tms.TrafficManagerSession(
        seed=1234, strict=True, tm_port=8000, session_id="session-a")
    first.acquire(_FakeClient(_FakeTrafficManager(8000)))

    second = tms.TrafficManagerSession(
        seed=9999, strict=True, tm_port=8000, session_id="session-b")
    with pytest.raises(RuntimeError) as excinfo:
        second.acquire(_FakeClient(_FakeTrafficManager(8000)))
    assert tms.TRAFFIC_MANAGER_MULTIPLE_MASTERS in str(excinfo.value), str(excinfo.value)

    with pytest.raises(RuntimeError) as excinfo:
        tms.TrafficManagerSession.claim_master(8000, "session-c")
    assert tms.TRAFFIC_MANAGER_MULTIPLE_MASTERS in str(excinfo.value)

    # a different port is fine
    other = tms.TrafficManagerSession(
        seed=1, strict=True, tm_port=8001, session_id="session-d")
    other.acquire(_FakeClient(_FakeTrafficManager(8001)))
    assert other.effective_config()["tm_port"] == 8001


def test_world_sync_true_with_tm_sync_false_is_rejected():
    world = _FakeSyncWorld(synchronous_mode=True)
    session = tms.TrafficManagerSession(
        seed=5, synchronous_mode=False, tm_port=8300, session_id="sync-mismatch")
    result = tms.validate_world_tm_sync(world, session)
    assert result["valid"] is False
    assert any(tms.TRAFFIC_MANAGER_SYNC_MISMATCH in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]

    synced = tms.TrafficManagerSession(
        seed=5, synchronous_mode=True, tm_port=8301, session_id="sync-ok")
    assert tms.validate_world_tm_sync(world, synced)["valid"] is True


def test_traffic_manager_seed_missing_is_refused():
    tms.TrafficManagerSession.reset_master_registry()
    session = tms.TrafficManagerSession(
        seed=None, strict=True, tm_port=8200, session_id="no-seed")
    client = _FakeClient(_FakeTrafficManager(8200))
    with pytest.raises(RuntimeError) as excinfo:
        session.acquire(client)
    assert tms.TRAFFIC_MANAGER_SEED_MISSING in str(excinfo.value)
    assert client.requested_ports == [], (
        "no TM handle may be obtained before the governed seed is resolved"
    )


def test_world_reload_without_reseed_fails_until_the_seed_is_reapplied():
    tms.TrafficManagerSession.reset_master_registry()
    session = tms.TrafficManagerSession(
        seed=31337, strict=True, tm_port=8400, session_id="reseed")
    client = _FakeClient(_FakeTrafficManager(8400))
    session.acquire(client)
    session.verify_after_reload()  # no reload yet

    session.reseed_after_world_reload()
    with pytest.raises(RuntimeError) as excinfo:
        session.verify_after_reload()
    assert tms.TRAFFIC_MANAGER_RESEED_REQUIRED in str(excinfo.value), str(excinfo.value)

    session.acquire(client)
    session.verify_after_reload()
    config = session.effective_config()
    assert config["seed"] == 31337
    assert config["seeded"] is True


def test_tm_config_without_seed_is_invalid_under_strict():
    config = {
        "schema": tms.TM_SCHEMA,
        "session_id": "hand-written",
        "host": "127.0.0.1",
        "tm_port": 8000,
        "is_master": True,
        "synchronous_mode": True,
        "reseed_required": False,
        tms.TM_DIGEST_FIELD: "deadbeef",
    }
    result = tms.validate_tm_config(config, strict=True)
    assert result["valid"] is False
    assert tms.TRAFFIC_MANAGER_SEED_MISSING in result["invalid_reasons"], (
        "a config with neither `seed` nor `seeded` must be refused under strict: "
        f"{result['invalid_reasons']}"
    )
    # a missing digest is refused too, in strict and non-strict mode
    assert tms.validate_tm_config(dict(config, **{tms.TM_DIGEST_FIELD: ""}),
                                   strict=False)["valid"] is False


def test_uncontrolled_walker_counted_as_traffic_fails():
    entries = [{
        "mode": tms.WALKER_MODE_STATIC_PROP,
        "controlled": False,
        "counts_as_pedestrian_traffic": True,
        "walker_actor_id": 4242,
        "controller_actor_id": None,
    }]
    result = tms.validate_walker_mode(entries, mode=tms.WALKER_MODE_STATIC_PROP)
    assert result["valid"] is False
    assert any(tms.WALKER_UNCONTROLLED in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]
    assert "4242" in str(result["invalid_reasons"])


def test_controlled_walker_without_a_controller_id_fails():
    entries = [{
        "mode": tms.WALKER_MODE_CONTROLLED,
        "controlled": True,
        "counts_as_pedestrian_traffic": False,
        "walker_actor_id": 777,
        "controller_actor_id": None,
    }]
    result = tms.validate_walker_mode(entries, mode=tms.WALKER_MODE_CONTROLLED)
    assert result["valid"] is False
    assert any(tms.WALKER_CONTROLLER_MISMATCH in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]

    # with a controller id the same entry validates
    ok = tms.validate_walker_mode(
        [dict(entries[0], controller_actor_id=778)], mode=tms.WALKER_MODE_CONTROLLED)
    assert ok["valid"] is True, ok["invalid_reasons"]


def test_scenario_actor_that_survives_cleanup_is_a_leak():
    registry = tms.ScenarioActorRegistry()
    leaky = _LeakyActor()
    registry.register("anomaly_vehicle", leaky)
    assert registry.owned_count() == 1

    destroyed = registry.destroy_all()
    assert leaky.destroy_calls == 1
    assert destroyed["owned_count_before"] == 1

    verdict = registry.verify_clean()
    assert verdict["clean"] is False, (
        "a scenario-owned actor still alive after cleanup must fail closed"
    )
    assert verdict["failure_code"] == tms.SCENARIO_ACTOR_LEAK
    assert "anomaly_vehicle" in str(verdict["owned_actors_remaining"])


def test_seed_tree_malformed_root_seed_is_invalid():
    with pytest.raises(ValueError) as excinfo:
        seeds.seed_tree_from_environment({"UP_EXPERIMENT_SEED": "forty-two"})
    assert seeds.SEED_INVALID in str(excinfo.value), str(excinfo.value)


def test_seed_tree_missing_root_seed_is_an_error():
    with pytest.raises(ValueError) as excinfo:
        seeds.seed_tree_from_environment({})
    assert seeds.SEED_MISSING in str(excinfo.value), str(excinfo.value)

    with pytest.raises(ValueError) as excinfo:
        seeds.seed_tree_from_environment({"UP_EXPERIMENT_SEED": "   "})
    assert seeds.SEED_MISSING in str(excinfo.value)


def test_seed_tree_resolves_all_six_governed_domains():
    tree = seeds.seed_tree_from_environment({"UP_EXPERIMENT_SEED": "20260918"})
    assert set(seeds.SEED_DOMAINS) == {
        "tm", "npc_blueprint", "npc_spawn", "pedestrian", "weather", "scenario"}
    for domain in seeds.SEED_DOMAINS:
        assert domain in tree["seeds"], f"{domain} was not resolved"
        assert isinstance(tree["seeds"][domain], int)
        assert tree["domains"][domain]["source"] == "derived"
    assert tree["all_domains_resolved"] is True
    assert tree["process_global_rng_mutated"] is False
    assert seeds.validate_seed_tree(tree)["valid"] is True


def test_derived_seeds_are_stable_and_distinct_across_domains():
    a = seeds.build_seed_tree(4242)
    b = seeds.build_seed_tree(4242)
    assert a["seeds"] == b["seeds"], "seed derivation must be reproducible"
    assert seeds.seed_tree_sha256(a) == seeds.seed_tree_sha256(b)

    values = list(a["seeds"].values())
    assert len(set(values)) == len(values), (
        f"each governed domain must get its own seed, got {a['seeds']}"
    )
    assert seeds.derive_seed(4242, "tm") == seeds.derive_seed(4242, "tm")
    assert seeds.derive_seed(4242, "tm") != seeds.derive_seed(4243, "tm")
    assert seeds.build_seed_tree(4243)["seeds"] != a["seeds"]

    # an override is recorded as an override, never mistaken for a derived seed
    pinned = seeds.build_seed_tree(4242, overrides={"tm": 7})
    assert pinned["seeds"]["tm"] == 7
    assert pinned["domains"]["tm"]["source"] == "explicit_override"

    # owned RNG instances never touch the process-global RNG
    random.seed(99)
    before = random.getstate()
    rng = seeds.owned_rng(4242, "npc_spawn")
    rng.random()
    assert random.getstate() == before
    random.setstate(before)


# ===========================================================================
# PHYSICS -- NEW-331 / NEW-332
# ===========================================================================


def test_substepping_disabled_under_strict_profile_fails():
    profile = physics.build_physics_profile(20, overrides={"substepping": False})
    result = physics.validate_physics_profile(profile, strict=True)
    assert result["valid"] is False
    assert any(physics.PHYSICS_SUBSTEPPING_DISABLED in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]

    enabled = physics.build_physics_profile(20)
    assert physics.validate_physics_profile(enabled, strict=True)["valid"] is True


def test_fixed_delta_beyond_the_substep_budget_fails():
    profile = physics.build_physics_profile(20)
    assert profile["max_substep_delta_time"] * profile["max_substeps"] >= \
        profile["fixed_delta_seconds"]

    starved = dict(profile)
    starved["max_substeps"] = 4
    result = physics.validate_physics_profile(starved, strict=True)
    assert result["valid"] is False
    assert any(physics.PHYSICS_SUBSTEP_BUDGET_EXCEEDED in r
               for r in result["invalid_reasons"]), (
        "a fixed delta larger than max_substep_delta_time*max_substeps cannot "
        f"be represented; got {result['invalid_reasons']}"
    )


def test_capture_is_refused_before_simulation_state_ready():
    state = physics.ExperimentStartState()
    assert state.simulation_state_ready is False
    assert state.capture_permitted() is False
    with pytest.raises(RuntimeError) as excinfo:
        state.require_capture_ready()
    assert physics.SIMULATION_STATE_NOT_READY in str(excinfo.value), str(excinfo.value)

    for stage in (
        "LOAD_OR_GENERATE_INTENDED_WORLD",
        "ESTABLISH_FINAL_WORLD_IDENTITY",
        "APPLY_GOVERNED_SIMULATION_SETTINGS",
        "VERIFY_SIMULATION_SETTINGS",
        "INITIALIZE_AND_SEED_TRAFFIC_MANAGER",
    ):
        state.complete(stage)
    assert state.simulation_state_ready is True
    state.require_capture_ready()
    assert state.capture_permitted() is False, (
        "settings+TM readiness alone does not permit capture; actors and sensors "
        "must be attached first"
    )
    for stage in ("DETERMINISTIC_WARMUP", "SPAWN_GOVERNED_ACTORS", "ATTACH_SENSORS"):
        state.complete(stage)
    assert state.capture_permitted() is True
    assert state.proof()["ordering_compliant"] is True


def test_completing_lifecycle_stages_out_of_order_is_recorded():
    state = physics.ExperimentStartState()
    state.complete("ATTACH_SENSORS")
    state.complete("VERIFY_SIMULATION_SETTINGS")

    proof = state.proof()
    assert proof["ordering_compliant"] is False
    assert proof["order_violations"], "an out-of-order stage must be recorded"
    assert any("ATTACH_SENSORS:out_of_order" in v
               for v in proof["order_violations"]), proof["order_violations"]
    assert any("VERIFY_SIMULATION_SETTINGS:out_of_order" in v
               for v in proof["order_violations"]), proof["order_violations"]

    verdict = physics.evaluate_start_state_transcript(proof)
    assert verdict["valid"] is False
    assert any(physics.SIMULATION_STATE_NOT_READY in r
               for r in verdict["invalid_reasons"]), verdict["invalid_reasons"]


def test_physics_profile_digest_must_match_across_arms():
    manual = physics.build_physics_profile(20)
    auto = physics.build_physics_profile(25)
    assert manual[physics.PHYSICS_DIGEST_FIELD] != auto[physics.PHYSICS_DIGEST_FIELD]

    result = physics.validate_physics_equality(manual, auto)
    assert result["valid"] is False
    assert any("profile_digest" in r
               for r in result["invalid_reasons"]), result["invalid_reasons"]

    same = physics.build_physics_profile(20)
    assert physics.validate_physics_equality(manual, same)["valid"] is True

    missing = physics.validate_physics_equality({}, same)
    assert missing["valid"] is False
    assert missing["invalid_reasons"], "a missing arm digest must be reported"


# ===========================================================================
# PAIR RESPONSE -- NEW-333
# ===========================================================================


def test_camera_response_difference_invalidates_the_pair():
    manual = response.profile_report(
        response.PROFILE_PINHOLE_POSTPROCESS_DISABLED)["camera_response_sha256"]
    auto = response.profile_report(
        response.PROFILE_POSTPROCESS_ENABLED,
        overrides={"gamma": "1.8"})["camera_response_sha256"]
    assert manual != auto

    verdict = response.validate_response_equality(
        manual, auto,
        manual_profile=response.PROFILE_PINHOLE_POSTPROCESS_DISABLED,
        auto_profile=response.PROFILE_POSTPROCESS_ENABLED)
    assert verdict["valid"] is False
    assert any(response.CAMERA_RESPONSE_MISMATCH in r
               for r in verdict["invalid_reasons"]), verdict["invalid_reasons"]

    manifest = _pair_manifest(
        manual_arm={"camera_response_sha256": manual},
        auto_arm={"camera_response_sha256": auto},
        top_overrides={"camera_response_sha256": manual},
    )
    result = rq3.validate_pair_manifest(manifest)
    assert result["valid"] is False, (
        "a pair whose arms ran different camera-response profiles must not "
        "validate as a paired RQ3 experiment"
    )
    assert any("camera_response_sha256" in r and "manual_vs_auto" in r
               for r in result["invalid_reasons"]), (
        "the arm-level camera-response identity mismatch must be reported; got "
        f"{result['invalid_reasons']}"
    )


def test_matching_camera_response_identity_validates_the_pair():
    manual = response.profile_report(
        response.PROFILE_PINHOLE_POSTPROCESS_DISABLED)["camera_response_sha256"]
    auto = response.profile_report(
        response.PROFILE_PINHOLE_POSTPROCESS_DISABLED)["camera_response_sha256"]
    assert manual == auto
    verdict = response.validate_response_equality(
        manual, auto,
        manual_profile=response.PROFILE_PINHOLE_POSTPROCESS_DISABLED,
        auto_profile=response.PROFILE_PINHOLE_POSTPROCESS_DISABLED)
    assert verdict["valid"] is True, verdict["invalid_reasons"]

    manifest = _pair_manifest(
        manual_arm={"camera_response_sha256": manual},
        auto_arm={"camera_response_sha256": auto},
        top_overrides={"camera_response_sha256": manual},
    )
    assert rq3.validate_pair_manifest(manifest)["valid"] is True
