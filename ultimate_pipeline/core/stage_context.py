"""Explicit state shared by pipeline stages.

This is introduced beside the legacy ``MainPipeline.semantic_state`` mapping.
Stages are migrated incrementally so each change can be compared independently.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass
class StageContext:
    has_geometry: bool = False
    has_elevation: bool = False
    has_planview: bool = False
    has_lanes: bool = False

    def replace(self, **values: bool) -> None:
        """Set only declared contract fields, rejecting accidental state drift."""
        for name, value in values.items():
            if name not in self.__dataclass_fields__:
                raise KeyError(f"unknown stage-context field: {name}")
            setattr(self, name, bool(value))

    def as_legacy_mapping(self) -> dict[str, bool]:
        """Return the exact legacy mapping shape during the migration period."""
        return {name: bool(value) for name, value in asdict(self).items()}


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
            for name in StageContext.__dataclass_fields__
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
