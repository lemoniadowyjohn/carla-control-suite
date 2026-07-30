from __future__ import annotations

from ultimate_pipeline.artifacts.errors import RecoveryError
from ultimate_pipeline.artifacts.model import ArtifactRef


class RecoveryEngine:
    """Recovery helpers for immutable artifact stores."""

    def verify_integrity(self, store) -> tuple[str, ...]:
        return tuple(store.verify_integrity())

    def require_integrity(self, store) -> None:
        issues = self.verify_integrity(store)
        if issues:
            raise RecoveryError("; ".join(issues))

    def rollback(self, store) -> ArtifactRef | None:
        previous = store.rollback()
        if previous is None:
            raise RecoveryError("no accepted artifact is available to roll back")
        return previous


__all__ = ["RecoveryEngine"]
