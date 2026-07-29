from __future__ import annotations

from typing import Literal, TypeAlias

ReleaseProfile: TypeAlias = Literal[
    "structural_release",
    "visual_build",
    "scenario_augmentation",
    "debug",
    "experimental_unsafe",
]
