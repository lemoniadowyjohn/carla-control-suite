# C12 (explicit DR, methodology): the canonical RealismAugmentor must be
# importable from the capture writer. Before this fix, dataset_generator.py
# imported `ultimate_pipeline.augmentation.realism` (a module that does not
# exist) and silently fell back to RealismAugmentor=None, so explicit DR was
# absent from the capture path while other modules used the canonical
# `augmentation.realism_augmentor`.
from __future__ import annotations

import pytest


def test_canonical_augmentor_module_imports() -> None:
    from ultimate_pipeline.augmentation.realism_augmentor import RealismAugmentor

    assert RealismAugmentor is not None


def test_dataset_generator_resolves_canonical_augmentor() -> None:
    import ultimate_pipeline.perception.dataset_generator as dg

    assert dg.RealismAugmentor is not None
    assert dg.RealismAugmentor.__name__ == "RealismAugmentor"


def test_perception_runner_resolves_canonical_augmentor() -> None:
    import ultimate_pipeline.perception.perception_runner_local_aug as pr

    # First-choice import path is the canonical module; the old-name fallback
    # must never shadow it.
    assert pr.RealismAugmentor is not None
