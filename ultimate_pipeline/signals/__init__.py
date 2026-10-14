from __future__ import annotations

"""Canonical signal-policy package for the governed CARLA pipeline.

Public surface (NEW-334..NEW-349):

* :mod:`ultimate_pipeline.signals.registry` -- the single source of truth for
  what a governed signal is, who produces it, who consumes it and what happens
  when it is missing or failing.
* :mod:`ultimate_pipeline.signals.writer` -- the only sanctioned way to persist
  a governed signal artifact (atomic, verified, fail-closed).
* :mod:`ultimate_pipeline.signals.verdict` -- the only sanctioned computer of
  ``final_run_verdict.json``.
"""

from ultimate_pipeline.signals.registry import (  # noqa: F401
    SIGNAL_REGISTRY,
    SignalClass,
    classify,
    registry_sha256,
    required_for_profile,
)

__all__ = [
    "SIGNAL_REGISTRY",
    "SignalClass",
    "classify",
    "registry_sha256",
    "required_for_profile",
]
