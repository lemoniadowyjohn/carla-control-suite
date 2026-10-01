#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Governed perception runtime environment (NEW-316 .. NEW-333).

This package is the single authority for every environment variable that can
change the appearance or determinism of an RQ3 perception capture:

* ``weather_spec``            -- NEW-316/317/318: resolve, apply, read back and
  digest weather; fail closed when the requested weather is not effective.
* ``deterministic_weather``   -- NEW-319: seeded, frame-driven weather schedules.
* ``camera_intrinsics``       -- NEW-320: native-vs-target intrinsic realization
  contract and deterministic geometric remap geometry.
* ``camera_response``         -- NEW-333: frozen camera photometric response
  profile with capability detection.
* ``calibration_authority``   -- NEW-325: authoritative vs legacy-diagnostic
  calibration semantics.
* ``vehicle_binding``         -- NEW-324: rig-to-vehicle geometry binding.
* ``lidar_camera_gate``       -- NEW-323: quantitative LiDAR/camera gate.
* ``calibration_lifecycle``   -- NEW-322: transactional CARLA cleanup guard.
* ``seed_tree``               -- NEW-327: owned RNG / seed-tree authority.
* ``traffic_manager_session`` -- NEW-326/328/329/330: one TM authority,
  fail-closed autopilot, walker control modes, scenario actor ownership.
* ``physics_profile``         -- NEW-331/332: substepping profile and the
  experiment-start lifecycle (``SIMULATION_STATE_READY``).

Nothing in this package imports CARLA at module level, so every contract is
offline-testable and safe to import in analysis-only contexts.
"""

__all__ = [
    "calibration_authority",
    "calibration_lifecycle",
    "camera_intrinsics",
    "camera_response",
    "deterministic_weather",
    "lidar_camera_gate",
    "physics_profile",
    "seed_tree",
    "traffic_manager_session",
    "vehicle_binding",
    "weather_spec",
]