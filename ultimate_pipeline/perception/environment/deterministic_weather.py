#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-319 -- deterministic weather control for governed perception.

The pre-existing ``ultimate_pipeline/carla_tools/weather_controller.py`` is
unsuitable for a governed perception capture because it

* draws presets from the **process-global** ``random`` module (never seeded),
* schedules transitions on **wall-clock** ``time.sleep`` in a **background
  daemon thread**.

Under a synchronous simulation neither is reproducible: two arms with the same
protocol can observe different weather, and a slow host advances the schedule
faster than a fast host.

This module provides three explicit modes:

``DIAGNOSTIC_DYNAMIC_WEATHER``
    Non-authoritative.  Uses wall-clock sampling.  May never be used for a
    paired RQ3 claim.

``GOVERNED_FIXED_WEATHER``
    One weather for the whole episode.

``GOVERNED_SCHEDULED_WEATHER``
    A fixed, seeded list of weather states advanced on **simulation frame
    boundaries**.  Reproducible given the same seed, regardless of host speed.

Randomness ownership
--------------------
Every governed path uses a *local* ``random.Random(seed)`` instance.  This
module never calls ``random.seed()`` and never mutates the process-global RNG,
so importing or using it cannot change the behaviour of unrelated modules.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from . import weather_spec as _ws

MODE_DIAGNOSTIC_DYNAMIC = "DIAGNOSTIC_DYNAMIC_WEATHER"
MODE_GOVERNED_FIXED = "GOVERNED_FIXED_WEATHER"
MODE_GOVERNED_SCHEDULED = "GOVERNED_SCHEDULED_WEATHER"

VALID_MODES: tuple = (MODE_DIAGNOSTIC_DYNAMIC, MODE_GOVERNED_FIXED, MODE_GOVERNED_SCHEDULED)

#: Modes admissible for a paired RQ3 experiment.
GOVERNED_MODES: tuple = (MODE_GOVERNED_FIXED, MODE_GOVERNED_SCHEDULED)

WEATHER_SEED_DOMAIN = "weather"

WEATHER_MODE_DYNAMIC_FORBIDDEN = "WEATHER_MODE_DYNAMIC_FORBIDDEN_FOR_PAIR"
WEATHER_MODE_DETERMINISM_MISMATCH = "WEATHER_DETERMINISM_MISMATCH"
WEATHER_SCHEDULE_EMPTY = "WEATHER_SCHEDULE_EMPTY"


def _round6(value: float) -> float:
    return round(float(value), 6)


class DeterministicWeatherController:
    """Frame-driven, seeded weather control.

    Parameters
    ----------
    mode:
        One of :data:`VALID_MODES`.
    seed:
        Owned seed for the weather domain (NEW-327).  Never touches the
        process-global RNG.
    presets:
        Candidate weather preset names.  Required for scheduled mode; optional
        for fixed mode (which takes a single ``preset``).
    ticks_per_step:
        Number of simulation frames each scheduled step occupies.
    """

    def __init__(
        self,
        *,
        mode: str = MODE_GOVERNED_FIXED,
        seed: int = 0,
        preset: Optional[str] = None,
        presets: Optional[Sequence[str]] = None,
        ticks_per_step: int = 50,
        carla_module: Any = None,
        tick_source: Optional[Callable[[], int]] = None,
    ) -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"invalid_weather_mode:{mode}")
        if int(ticks_per_step) <= 0:
            raise ValueError(f"invalid_ticks_per_step:{ticks_per_step}")

        self.mode = str(mode)
        self.seed = int(seed)
        self.preset = str(preset) if preset else None
        self.presets: List[str] = [str(p) for p in (presets or [])]
        self.ticks_per_step = int(ticks_per_step)
        self.carla_module = carla_module
        self.tick_source = tick_source

        # NEW-327: owned RNG instance.  `random.Random(seed)` does not touch
        # the process-global generator.
        self._rng = random.Random(self.seed)

        self._schedule: List[Dict[str, Any]] = []
        self._step_index: int = -1
        self._current_frame: int = 0
        self._transitions: List[Dict[str, Any]] = []
        self._started: bool = False

    # -- schedule construction ------------------------------------------------

    def build_schedule(self) -> List[Dict[str, Any]]:
        """Build the fixed, frame-indexed schedule (scheduled mode only)."""
        if self.mode != MODE_GOVERNED_SCHEDULED:
            return []
        if not self.presets:
            raise ValueError(f"{WEATHER_SCHEDULE_EMPTY}:presets_required")

        # Deterministic rotation derived from the owned RNG.  The number of
        # steps is a function of (seed, preset list) only -- never of time.
        count = max(len(self.presets), 2)
        chosen: List[str] = []
        pool = list(self.presets)
        for _ in range(count):
            if not pool:
                pool = list(self.presets)
            chosen.append(str(self._rng.choice(pool)))

        schedule: List[Dict[str, Any]] = []
        for index, name in enumerate(chosen):
            spec = _ws.resolve_weather_spec(
                name, carla_module=self.carla_module, strict=True
            )
            schedule.append(
                {
                    "step_index": index,
                    "preset": name,
                    "start_frame": index * self.ticks_per_step,
                    "end_frame": (index + 1) * self.ticks_per_step,
                    "parameters": dict(spec.get("parameters") or {}),
                    "weather_sha256": _ws.weather_identity_v2(
                        spec.get("parameters") or {}
                    )["weather_sha256"],
                }
            )
        self._schedule = schedule
        self._step_index = -1
        self._transitions = []
        self._started = False
        return schedule

    @property
    def schedule(self) -> List[Dict[str, Any]]:
        return list(self._schedule)

    @property
    def schedule_sha256(self) -> str:
        """Digest of the exact schedule (transition frames + parameters)."""
        if not self._schedule:
            return ""
        payload = {
            "weather_schema_version": _ws.WEATHER_SCHEMA_VERSION,
            "mode": self.mode,
            "weather_seed": self.seed,
            "ticks_per_step": self.ticks_per_step,
            "schedule": [
                {
                    "step_index": s["step_index"],
                    "preset": s["preset"],
                    "start_frame": s["start_frame"],
                    "end_frame": s["end_frame"],
                    "weather_sha256": s["weather_sha256"],
                }
                for s in self._schedule
            ],
        }
        return _ws.sha256_text(_ws.canonical_dumps(payload))

    # -- frame-driven stepping ------------------------------------------------

    def step_for_frame(self, frame_id: int) -> Dict[str, Any]:
        """Return the schedule entry governing ``frame_id``."""
        if self.mode == MODE_GOVERNED_FIXED:
            spec = _ws.resolve_weather_spec(
                self.preset or "", carla_module=self.carla_module, strict=True
            )
            return {
                "step_index": 0,
                "preset": spec.get("requested"),
                "start_frame": 0,
                "end_frame": None,
                "parameters": dict(spec.get("parameters") or {}),
                "weather_sha256": _ws.weather_identity_v2(
                    spec.get("parameters") or {}
                )["weather_sha256"],
            }
        if self.mode == MODE_GOVERNED_SCHEDULED:
            if not self._schedule:
                self.build_schedule()
            index = int(frame_id) // self.ticks_per_step
            if index >= len(self._schedule):
                index = len(self._schedule) - 1
            return dict(self._schedule[max(0, index)])
        # Diagnostic dynamic mode: wall-clock driven, explicitly non-governed.
        index = int(time.time()) // max(1, self.ticks_per_step)
        pool = self.presets or [self.preset or "ClearNoon"]
        return {
            "step_index": index,
            "preset": pool[index % len(pool)],
            "start_frame": None,
            "end_frame": None,
            "wall_clock_index": index,
            "governed": False,
        }

    def tick(self, world: Any, frame_id: Optional[int] = None) -> Dict[str, Any]:
        """Advance to ``frame_id`` and apply the governing weather.

        In governed modes the schedule transitions happen strictly on simulation
        frame boundaries, so the applied weather is a pure function of the
        frame counter.
        """
        frame = int(frame_id) if frame_id is not None else self._current_frame
        self._current_frame = frame
        entry = self.step_for_frame(frame)
        self._started = True

        step_index = int(entry.get("step_index", 0))
        transitioned = False
        if self.mode == MODE_GOVERNED_SCHEDULED and step_index != self._step_index:
            transitioned = True

        if self.mode == MODE_GOVERNED_FIXED and self._transitions:
            # Fixed weather is applied exactly once per episode.
            transitioned = False
            return {
                "frame_id": frame,
                "transitioned": False,
                "applied": False,
                "preset": self._transitions[0]["preset"],
                "weather_sha256": self._transitions[0]["weather_sha256"],
            }

        applied = False
        failure_code: Optional[str] = None
        effective: Dict[str, Any] = {}
        try:
            evidence = _ws.apply_weather_and_verify(
                world,
                str(entry.get("preset")),
                settle_ticks=0,
                tick_fn=None,
                carla_module=self.carla_module,
                strict=self.mode in GOVERNED_MODES,
            )
            effective = dict(evidence.get("effective") or {})
            applied = True
        except _ws.WeatherApplicationError as exc:
            failure_code = exc.failure_code
            effective = dict((exc.payload.get("effective") or {}))

        record = {
            "step_index": step_index,
            "frame_id": frame,
            "preset": entry.get("preset"),
            "transition_frame_id": frame if transitioned else None,
            "weather_sha256": effective.get("weather_sha256", ""),
            "effective_matches_requested": evidence.get("effective_matches_requested")
            if applied
            else False,
            "applied": applied,
            "failure_code": failure_code,
        }
        if transitioned or not self._transitions:
            self._transitions.append(record)
        self._step_index = step_index
        return record

    # -- evidence -------------------------------------------------------------

    def proof(self) -> Dict[str, Any]:
        """Recorded determinism evidence (NEW-319)."""
        return {
            "schema": "WEATHER_DETERMINISM/v1",
            "mode": self.mode,
            "governed": self.mode in GOVERNED_MODES,
            "weather_seed": self.seed,
            "rng_ownership": "owned_random.Random_instance",
            "process_global_rng_mutated": False,
            "schedule": [
                {
                    "step_index": s["step_index"],
                    "preset": s["preset"],
                    "start_frame": s["start_frame"],
                    "end_frame": s["end_frame"],
                    "weather_sha256": s["weather_sha256"],
                }
                for s in self._schedule
            ],
            "schedule_sha256": self.schedule_sha256,
            "transition_frame_ids": [
                t["transition_frame_id"] for t in self._transitions
                if t["transition_frame_id"] is not None
            ],
            "transitions": list(self._transitions),
            "ticks_per_step": self.ticks_per_step,
            "started": self._started,
        }

    @staticmethod
    def determinism_proof(proof_a: Mapping[str, Any], proof_b: Mapping[str, Any]) -> Dict[str, Any]:
        """Prove two arms share an identical deterministic weather schedule.

        Dynamic weather is forbidden for a paired RQ3 claim unless this returns
        ``identical=True``.
        """
        reasons: List[str] = []
        mode_a = str(proof_a.get("mode", ""))
        mode_b = str(proof_b.get("mode", ""))

        if mode_a not in GOVERNED_MODES or mode_b not in GOVERNED_MODES:
            reasons.append(f"{WEATHER_MODE_DYNAMIC_FORBIDDEN}:{mode_a}|{mode_b}")

        if int(proof_a.get("weather_seed", -1)) != int(proof_b.get("weather_seed", -2)):
            reasons.append(
                f"{WEATHER_MODE_DETERMINISM_MISMATCH}:weather_seed:"
                f"{proof_a.get('weather_seed')}!={proof_b.get('weather_seed')}"
            )
        if int(proof_a.get("ticks_per_step", -1)) != int(proof_b.get("ticks_per_step", -2)):
            reasons.append(
                f"{WEATHER_MODE_DETERMINISM_MISMATCH}:ticks_per_step:"
                f"{proof_a.get('ticks_per_step')}!={proof_b.get('ticks_per_step')}"
            )

        sha_a = str(proof_a.get("schedule_sha256") or "")
        sha_b = str(proof_b.get("schedule_sha256") or "")
        if bool(sha_a) != bool(sha_b):
            reasons.append(f"{WEATHER_MODE_DETERMINISM_MISMATCH}:schedule_presence")
        elif sha_a and sha_a != sha_b:
            reasons.append(f"{WEATHER_MODE_DETERMINISM_MISMATCH}:schedule_sha256:{sha_a}!={sha_b}")

        trans_a = [t for t in (proof_a.get("transition_frame_ids") or []) if t is not None]
        trans_b = [t for t in (proof_b.get("transition_frame_ids") or []) if t is not None]
        if trans_a != trans_b:
            reasons.append(
                f"{WEATHER_MODE_DETERMINISM_MISMATCH}:transition_frame_ids:"
                f"{trans_a}!={trans_b}"
            )

        return {
            "identical": not reasons,
            "invalid_reasons": reasons,
            "schedule_sha256": sha_a,
            "weather_seed": int(proof_a.get("weather_seed", -1)),
            "mode": mode_a,
        }


def controller_from_environment(carla_module: Any = None) -> DeterministicWeatherController:
    """Build a controller from the governed NEW-316/319 environment variables."""
    import os

    mode = str(os.environ.get("UP_WEATHER_MODE", MODE_GOVERNED_FIXED)).strip() or MODE_GOVERNED_FIXED
    preset = str(os.environ.get("UP_WEATHER_PRESET", "")).strip() or None
    raw_seed = str(os.environ.get("UP_WEATHER_SEED", "")).strip()
    try:
        seed = int(raw_seed) if raw_seed else 0
    except (TypeError, ValueError):
        seed = 0
    raw_ticks = str(os.environ.get("UP_WEATHER_TICKS_PER_STEP", "50")).strip()
    try:
        ticks_per_step = int(raw_ticks) if raw_ticks else 50
    except (TypeError, ValueError):
        ticks_per_step = 50
    presets_raw = str(os.environ.get("UP_WEATHER_SCHEDULE", "")).strip()
    presets = [p.strip() for p in presets_raw.split(",") if p.strip()]

    return DeterministicWeatherController(
        mode=mode,
        seed=seed,
        preset=preset,
        presets=presets,
        ticks_per_step=ticks_per_step,
        carla_module=carla_module,
    )