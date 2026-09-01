# ultimate_pipeline/run_full_domain_gap.py::resolve_manual_xodr() -- live via
# a real CLI argument (--manual-map, a human-typeable string), zero prior
# test coverage.
#
# Real bug: the generic fallback for an unrecognized/typo'd manual_map_name
# (anything that isn't exactly "GRID0828" or "GRID0821") included
# manual_maps/manual_ingolstadt_grid0828.xodr, Grid0821.xodr, and
# Grid0828.xodr as candidates -- i.e. it would silently substitute a
# DIFFERENT, specific known manual town's reference map if none of the
# requested-name-derived candidates existed. This is exactly the "wrong
# map, silent misalignment" risk the function's own GRID0821 branch
# explicitly documents and guards against 15 lines above ("NOTE: do NOT
# fall back to Grid0828 here"), just not applied consistently to the
# generic path. Directly reproduced with an isolated temp _REPO_ROOT: a
# call for the unrecognized name "Typo_Town" (simulating a CLI typo)
# silently returned a file containing Grid0828's content. Domain-gap
# comparisons (RQ1-relevant) run against whatever this function returns as
# the "manual"/ground-truth reference.
#
# Fixed: the generic fallback now only tries spelling/layout variants of
# the REQUESTED name; it no longer falls back to a different known town.
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

import ultimate_pipeline.run_full_domain_gap as rfdg


@pytest.fixture
def fake_repo_root(tmp_path: Path, monkeypatch):
    manual_maps = tmp_path / "manual_maps"
    manual_maps.mkdir()
    monkeypatch.setattr(rfdg, "_REPO_ROOT", tmp_path)
    monkeypatch.delenv("UP_MANUAL_XODR", raising=False)
    return tmp_path


def _clear_env_for(monkeypatch, manual_map_name: str) -> None:
    monkeypatch.delenv(f"UP_MANUAL_XODR_{manual_map_name.upper()}", raising=False)


def test_unrecognized_name_does_not_silently_substitute_grid0828(fake_repo_root, monkeypatch):
    _clear_env_for(monkeypatch, "Typo_Town")
    (fake_repo_root / "manual_maps" / "Grid0828.xodr").write_text(
        "GRID0828 CONTENT", encoding="utf-8"
    )

    with pytest.raises(FileNotFoundError):
        rfdg.resolve_manual_xodr("Typo_Town")


def test_unrecognized_name_does_not_silently_substitute_grid0821(fake_repo_root, monkeypatch):
    _clear_env_for(monkeypatch, "Typo_Town")
    (fake_repo_root / "manual_maps" / "Grid0821.xodr").write_text(
        "GRID0821 CONTENT", encoding="utf-8"
    )

    with pytest.raises(FileNotFoundError):
        rfdg.resolve_manual_xodr("Typo_Town")


def test_unrecognized_name_still_resolves_its_own_exact_file(fake_repo_root, monkeypatch):
    _clear_env_for(monkeypatch, "NewTown")
    (fake_repo_root / "manual_maps" / "NewTown.xodr").write_text(
        "NEWTOWN CONTENT", encoding="utf-8"
    )

    result = rfdg.resolve_manual_xodr("NewTown")

    assert result.read_text(encoding="utf-8") == "NEWTOWN CONTENT"


def test_unrecognized_name_resolves_uppercase_variant(fake_repo_root, monkeypatch):
    _clear_env_for(monkeypatch, "NewTown")
    (fake_repo_root / "manual_maps" / "NEWTOWN.xodr").write_text(
        "UPPERCASE VARIANT", encoding="utf-8"
    )

    result = rfdg.resolve_manual_xodr("NewTown")

    assert result.read_text(encoding="utf-8") == "UPPERCASE VARIANT"


def test_grid0821_still_never_falls_back_to_grid0828(fake_repo_root, monkeypatch):
    """Pre-existing, already-correct behavior for the explicitly-named
    GRID0821 case -- confirms the fix didn't disturb it."""
    _clear_env_for(monkeypatch, "GRID0821")
    (fake_repo_root / "manual_maps" / "Grid0828.xodr").write_text(
        "GRID0828 CONTENT", encoding="utf-8"
    )

    with pytest.raises(FileNotFoundError):
        rfdg.resolve_manual_xodr("GRID0821")


def test_grid0828_resolves_correctly_when_present(fake_repo_root, monkeypatch):
    _clear_env_for(monkeypatch, "GRID0828")
    (fake_repo_root / "manual_maps" / "manual_ingolstadt_grid0828.xodr").write_text(
        "GRID0828 CONTENT", encoding="utf-8"
    )

    result = rfdg.resolve_manual_xodr("GRID0828")

    assert result.read_text(encoding="utf-8") == "GRID0828 CONTENT"
