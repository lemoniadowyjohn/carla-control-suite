"""RoadRunner contract validation exceptions."""

from __future__ import annotations


class RoadRunnerContractError(ValueError):
    """Raised when a RoadRunner contract violates required invariants."""


class RoadRunnerGateError(RoadRunnerContractError):
    """Raised when a gate matrix cannot approve a release."""
