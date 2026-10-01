# -*- coding: utf-8 -*-
"""Offline tests for UE4/UE5 executable discovery and build-state separation.

The regression these guard: CARLA 0.9.x targets UE4.26, whose Windows editor is
``Engine/Binaries/Win64/UE4Editor.exe``. Tooling that searched only for
``UnrealEditor.exe`` (the UE5 name) reported a complete UE4.26 install as
missing. The old discovery also used ``next(iter((a, b)), None)``, which yields
only the first candidate, so one absent name masked every later one.

These tests are filesystem-only: they build throwaway trees under tmp_path and
never invoke an engine or a server.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import carla_source_build_receipt as receipt_mod
from tools import unreal_cook_resource_preflight as preflight_mod
from tools.ue_executable_discovery import (
    CARLA_SERVER_CANDIDATES,
    UE4_EDITOR_CANDIDATES,
    UE5_EDITOR_CANDIDATES,
    carla_project_compiled,
    editor_candidates,
    engine_family_from_editor,
    find_carla_server_executable,
    find_editor_executable,
    map_package_cooked,
)


def _make_ue_tree(root: Path, name: str) -> Path:
    binary = root / "Engine" / "Binaries" / "Win64"
    binary.mkdir(parents=True, exist_ok=True)
    (binary / name).write_bytes(b"MZ fake editor")
    return binary / name


def test_ue426_editor_is_discovered(tmp_path):
    """The real UE4.26 Windows editor name must be found."""
    root = tmp_path / "UE_4.26"
    expected = _make_ue_tree(root, "UE4Editor.exe")

    found = find_editor_executable(root, family="ue4", platform_name="windows")
    assert found == expected
    assert engine_family_from_editor(root, platform_name="windows") == "ue4"


def test_ue5_editor_is_still_discovered(tmp_path):
    """UE5 detection is kept deliberately, since the names differ."""
    root = tmp_path / "UE_5.4"
    expected = _make_ue_tree(root, "UnrealEditor.exe")

    found = find_editor_executable(root, family="ue5", platform_name="windows")
    assert found == expected
    assert engine_family_from_editor(root, platform_name="windows") == "ue5"


def test_ue426_install_is_not_reported_as_ue5_only(tmp_path):
    """A UE4.26 tree must not be missed because it lacks UnrealEditor.exe."""
    root = tmp_path / "UE_4.26_only"
    _make_ue_tree(root, "UE4Editor.exe")
    assert not (root / "Engine/Binaries/Win64/UnrealEditor.exe").exists()

    family = engine_family_from_editor(root, platform_name="windows")
    assert family == "ue4"
    assert find_editor_executable(root, family="ue5", platform_name="windows") is None


def test_absent_candidate_does_not_mask_later_candidates(tmp_path):
    """Regression: `next(iter((a, b)), None)` only ever probed the first name."""
    root = tmp_path / "UE_4.26_cmd"
    # UE4Editor.exe deliberately absent; the -Cmd variant is present.
    expected = _make_ue_tree(root, "UE4Editor-Cmd.exe")

    names = editor_candidates("ue4", "windows")
    assert names[0] == "UE4Editor.exe"
    found = find_editor_executable(root, family="ue4", platform_name="windows")
    assert found == expected
    assert found.name == names[1]


def test_missing_editor_returns_none_not_a_guess(tmp_path):
    root = tmp_path / "empty_ue"
    (root / "Engine" / "Binaries" / "Win64").mkdir(parents=True)
    assert find_editor_executable(root, family="ue4", platform_name="windows") is None
    assert engine_family_from_editor(root, platform_name="windows") == "unknown"


def test_editor_candidates_include_both_engine_families():
    assert "UE4Editor.exe" in UE4_EDITOR_CANDIDATES["windows"]
    assert "UnrealEditor.exe" in UE5_EDITOR_CANDIDATES["windows"]


def test_carla_server_binary_discovery(tmp_path):
    root = tmp_path / "Carla"
    (root / "Binaries" / "Win64").mkdir(parents=True)
    expected = root / "Binaries" / "Win64" / "CarlaUE4.exe"
    expected.write_bytes(b"MZ fake server")

    assert find_carla_server_executable(root, platform_name="windows") == expected
    assert "CarlaUE4.exe" in CARLA_SERVER_CANDIDATES["windows"]


def test_carla_server_absent_is_unknown_not_failure(tmp_path):
    root = tmp_path / "Carla_empty"
    root.mkdir(parents=True, exist_ok=True)
    assert find_carla_server_executable(root, platform_name="windows") is None


def test_project_compiled_state_is_independent_of_server_binary(tmp_path):
    """Compiled project artifacts present, server binary absent: keep both."""
    root = tmp_path / "Carla"
    (root / "Binaries" / "Win64").mkdir(parents=True)
    (root / "Binaries" / "Win64" / "UnrealEditor-Carla.dll").write_bytes(b"dll")

    state = carla_project_compiled(root)
    assert state["state"] == "present"
    # A compiled project does not imply a server binary exists.
    assert find_carla_server_executable(root, platform_name="windows") is None


def test_project_compiled_absent_is_reported_absent(tmp_path):
    root = tmp_path / "Carla_nothing"
    root.mkdir()
    assert carla_project_compiled(root)["state"] == "absent"


def test_map_cooked_state_is_not_runtime_loadable(tmp_path):
    root = tmp_path / "Carla"
    cooked = root / "Content" / "Cooked" / "Carla"
    cooked.mkdir(parents=True)

    state = map_package_cooked(root)
    assert state["state"] == "present"
    # Cooked content existing does not prove a map loads at runtime.
    assert "unverified" in state["note"]


def test_map_cooked_absent(tmp_path):
    root = tmp_path / "Carla_uncooked"
    root.mkdir()
    assert map_package_cooked(root)["state"] == "absent"


def test_receipt_keeps_unknown_unknown(tmp_path):
    """No CARLA/UE roots: every unevidenced state must stay unknown."""
    receipt = receipt_mod.build_receipt(None, None)
    states = receipt["build_states"]

    assert states["UE_ENGINE_EDITOR_PRESENT"]["status"] == "unknown"
    assert states["CARLA_PROJECT_COMPILED"]["status"] == "unknown"
    assert states["CARLA_SERVER_BINARY_PRESENT"]["status"] == "unknown"
    assert states["CARLA_RPC_RESPONSIVE"]["status"] == "unknown"
    assert states["MAP_PACKAGE_COOKED"]["status"] == "unknown"
    assert states["MAP_RUNTIME_LOADABLE"]["status"] == "unknown"
    # RPC state must never be inferred from a port or a file.
    assert "port listening is not a CARLA RPC response" in states[
        "CARLA_RPC_RESPONSIVE"
    ]["evidence"]


def test_receipt_finds_ue426_editor(tmp_path):
    ue = tmp_path / "UE_4.26"
    _make_ue_tree(ue, "UE4Editor.exe")

    receipt = receipt_mod.build_receipt(ue, None)
    assert receipt["build_states"]["UE_ENGINE_EDITOR_PRESENT"]["status"] == "verified"
    assert receipt["ue4"]["engine_family"]["value"] == "ue4"
    # Editor present does not imply a compiled CARLA project.
    assert receipt["build_states"]["CARLA_PROJECT_COMPILED"]["status"] == "unknown"
    assert receipt["build_states"]["MAP_RUNTIME_LOADABLE"]["status"] == "unknown"


def test_receipt_records_carla_project_and_server_separately(tmp_path):
    carla = tmp_path / "Carla"
    (carla / "Binaries" / "Win64").mkdir(parents=True)
    (carla / "Binaries" / "Win64" / "UnrealEditor-Carla.dll").write_bytes(b"dll")
    (carla / "Binaries" / "Win64" / "CarlaUE4.exe").write_bytes(b"exe")

    receipt = receipt_mod.build_receipt(None, carla)
    states = receipt["build_states"]
    assert states["CARLA_PROJECT_COMPILED"]["status"] == "present"
    assert states["CARLA_SERVER_BINARY_PRESENT"]["status"] == "verified"
    # Still no RPC and no runtime load, because nothing was started.
    assert states["CARLA_RPC_RESPONSIVE"]["status"] == "unknown"
    assert states["MAP_RUNTIME_LOADABLE"]["status"] == "unknown"


def test_preflight_separates_readiness_from_build_state(tmp_path):
    result = preflight_mod.preflight(
        tmp_path, None, None, 0.0, 0.0, 0.0, 0.0, None
    )
    separation = result["build_state_separation"]

    for state in (
        "UE_ENGINE_EDITOR_PRESENT",
        "CARLA_PROJECT_COMPILED",
        "CARLA_SERVER_BINARY_PRESENT",
        "CARLA_RPC_RESPONSIVE",
        "MAP_PACKAGE_COOKED",
        "MAP_RUNTIME_LOADABLE",
    ):
        assert state in separation
    # Preflight readiness is a resource claim only.
    assert separation["CARLA_RPC_RESPONSIVE"] == "UNKNOWN"
    assert "not a build or runtime claim" in separation["note"]


def test_preflight_editor_check_uses_ue426_name(tmp_path):
    ue = tmp_path / "UE_4.26"
    _make_ue_tree(ue, "UE4Editor.exe")

    check = preflight_mod.ue_editor_check(ue)
    assert check["state"] == "UE_ENGINE_EDITOR_PRESENT"
    assert check["engine_family"] == "ue4"
    assert "UE4Editor.exe" in check["path"]
    # Explicitly not a build claim.
    assert "unverified" in check["note"]


def test_preflight_editor_check_absent_is_not_a_build_verdict(tmp_path):
    ue = tmp_path / "UE_missing"
    (ue / "Engine" / "Binaries" / "Win64").mkdir(parents=True)

    check = preflight_mod.ue_editor_check(ue)
    assert check["state"] == "ABSENT"
    assert "not a build or cook verdict" in check["note"]
    # Both real names must appear in the searched set.
    assert "UE4Editor.exe" in check["searched_names"]
    assert "UnrealEditor.exe" in check["searched_names"]


def test_preflight_editor_check_unknown_without_root():
    check = preflight_mod.ue_editor_check(None)
    assert check["state"] == "UNKNOWN"
    assert check["evidence"] is None


def test_receipt_is_json_serialisable(tmp_path):
    receipt = receipt_mod.build_receipt(None, None)
    # Must not raise: the receipt is written to disk by the CLI.
    json.dumps(receipt, sort_keys=True)
