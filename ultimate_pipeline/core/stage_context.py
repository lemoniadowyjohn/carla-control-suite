"""Explicit state shared by pipeline stages.

This is introduced beside the legacy ``MainPipeline.semantic_state`` mapping.
Stages are migrated incrementally so each change can be compared independently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping


@dataclass
class StageContext:
    # Legacy semantic flags (exact lockstep with the temporary legacy mapping).
    _LEGACY_BOOL_FIELDS: ClassVar[tuple[str, ...]] = (
        "has_geometry",
        "has_elevation",
        "has_planview",
        "has_lanes",
    )
    has_geometry: bool = False
    has_elevation: bool = False
    has_planview: bool = False
    has_lanes: bool = False
    # Typed-only field: NOT part of the legacy bool mapping and never
    # bool-coerced (it is None or a hex string fingerprint).
    horizontal_geometry_fingerprint: str | None = None

    def replace(self, **values) -> None:
        """Set only declared contract fields, rejecting accidental state drift."""
        for name, value in values.items():
            if name not in self.__dataclass_fields__:
                raise KeyError(f"unknown stage-context field: {name}")
            if name in self._LEGACY_BOOL_FIELDS:
                value = bool(value)
            setattr(self, name, value)

    def as_legacy_mapping(self) -> dict[str, bool]:
        """Return the exact legacy mapping shape during the migration period."""
        return {name: bool(getattr(self, name)) for name in self._LEGACY_BOOL_FIELDS}



    def fingerprint(self) -> str | None:
        """Return current horizontal geometry fingerprint if set."""
        return self.horizontal_geometry_fingerprint

    def set_geometry_fingerprint(self, fp: str) -> None:
        """Set fingerprint at freeze point."""
        self.horizontal_geometry_fingerprint = fp

    def verify_geometry_fingerprint(self, current_fp: str) -> None:
        """Fail closed if fingerprint mismatches (post-freeze mutation detected)."""
        if self.horizontal_geometry_fingerprint is None:
            return
        if current_fp != self.horizontal_geometry_fingerprint:
            raise RuntimeError(
                f"GEOM-FREEZE-001: horizontal geometry mutated after freeze: "
                f"expected {self.horizontal_geometry_fingerprint}, got {current_fp}"
            )

def ensure_stage_context(owner: Any) -> StageContext:
    """Return an owner's context, bootstrapping legacy test doubles safely.

    MainPipeline creates ``stage_context`` during initialization. The fallback
    only supports existing isolated-stage callers whose minimal fake pipeline
    objects still provide the legacy mapping.
    """
    context = getattr(owner, "stage_context", None)
    if isinstance(context, StageContext):
        return context
    legacy = getattr(owner, "semantic_state", {})
    if not isinstance(legacy, Mapping):
        legacy = {}
    context = StageContext(
        **{
            name: bool(legacy.get(name, False))
            for name in StageContext._LEGACY_BOOL_FIELDS
        }
    )
    owner.stage_context = context
    return context


def sync_legacy_semantic_state(owner: Any, context: StageContext) -> None:
    """Mirror typed state into the temporary legacy dictionary exactly."""
    mapping = context.as_legacy_mapping()
    legacy = getattr(owner, "semantic_state", None)
    if isinstance(legacy, dict):
        legacy.update(mapping)
    else:
        owner.semantic_state = mapping
