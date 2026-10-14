# ultimate_pipeline/tests/unit/test_v4_large_map_contract.py
# -*- coding: utf-8 -*-
"""NEW-197 / NEW-198 / NEW-199: package binding, deterministic decals,
TilesInfo consistency tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline.tiling.carla_0916_large_map_contract import (
    AMBIGUOUS_CONFIG_STATUS,
    CONFIG_OUTSIDE_ROOT_STATUS,
    MISSING_CONFIG_STATUS,
    PACKAGE_MISMATCH_STATUS,
    PackageBindingError,
    format_tilesinfo,
    generate_deterministic_decals,
    parse_tilesinfo,
    parse_tilesinfo_line,
    parse_tilesinfo_token,
    resolve_material_config,
    resolve_package_identity,
    tilesinfo_roundtrip_check,
)


def _write_package(root: Path, package: str = "CityPkg", map_name: str = "CityMap",
                   with_manifest: bool = True) -> Path:
    pkg = root / package
    pkg.mkdir(parents=True, exist_ok=True)
    doc = {"maps": [{"name": map_name, "xodr": "./CityMap.xodr",
                     "use_carla_materials": True, "tile_size": 1000.0, "tiles": []}],
           "props": []}
    (pkg / "package.json").write_text(json.dumps(doc), encoding="utf-8")
    if with_manifest:
        manifest = {"xodr": {"filename": "CityMap.xodr", "sha256": ""}}
        (pkg / f"{package}.large_map_package.json").write_text(
            json.dumps(manifest), encoding="utf-8")
    return pkg


# --- NEW-197: package binding ---------------------------------------------

def test_correct_package_config_pass(tmp_path):
    pkg = _write_package(tmp_path)
    (pkg / "roadpainter_decals.json").write_text(
        json.dumps({"package": "CityPkg", "decals": []}), encoding="utf-8")
    identity = resolve_package_identity(requested_package="CityPkg",
                                        import_root=str(tmp_path))
    assert identity.resolved_package == "CityPkg"
    assert identity.map_name == "CityMap"
    receipt = resolve_material_config(identity)
    assert receipt["status"] == "PASS"
    assert Path(receipt["config_path"]).name == "roadpainter_decals.json"


def test_config_absent_fails(tmp_path):
    _write_package(tmp_path)
    identity = resolve_package_identity(requested_package="CityPkg",
                                        import_root=str(tmp_path))
    with pytest.raises(PackageBindingError) as excinfo:
        resolve_material_config(identity)
    assert excinfo.value.status == MISSING_CONFIG_STATUS


def test_wrong_package_fails(tmp_path):
    pkg = _write_package(tmp_path)
    (pkg / "roadpainter_decals.json").write_text(
        json.dumps({"package": "OtherPkg", "decals": []}), encoding="utf-8")
    identity = resolve_package_identity(requested_package="CityPkg",
                                        import_root=str(tmp_path))
    with pytest.raises(PackageBindingError) as excinfo:
        resolve_material_config(identity)
    assert excinfo.value.status == PACKAGE_MISMATCH_STATUS


def test_two_configs_ambiguous(tmp_path):
    pkg = _write_package(tmp_path)
    (pkg / "roadpainter_decals.json").write_text(json.dumps({}), encoding="utf-8")
    sub = pkg / "nested"
    sub.mkdir()
    (sub / "roadpainter_decals.json").write_text(json.dumps({}), encoding="utf-8")
    identity = resolve_package_identity(requested_package="CityPkg",
                                        import_root=str(tmp_path))
    with pytest.raises(PackageBindingError) as excinfo:
        resolve_material_config(identity)
    assert excinfo.value.status == AMBIGUOUS_CONFIG_STATUS


def test_manifest_hash_mismatch_fails(tmp_path):
    pkg = _write_package(tmp_path)
    doc = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
    doc["maps"][0]["xodr_sha256"] = "aa" * 32
    (pkg / "package.json").write_text(json.dumps(doc), encoding="utf-8")
    manifest = json.loads((pkg / "CityPkg.large_map_package.json").read_text(encoding="utf-8"))
    manifest["xodr"]["sha256"] = "bb" * 32
    (pkg / "CityPkg.large_map_package.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PackageBindingError) as excinfo:
        resolve_package_identity(requested_package="CityPkg",
                                 import_root=str(tmp_path))
    assert excinfo.value.status == PACKAGE_MISMATCH_STATUS


def test_cli_requested_vs_resolved_mismatch(tmp_path):
    _write_package(tmp_path, map_name="CityMap")
    with pytest.raises(PackageBindingError) as excinfo:
        resolve_package_identity(requested_package="CityPkg",
                                 import_root=str(tmp_path),
                                 map_name="WrongMap")
    assert excinfo.value.status == PACKAGE_MISMATCH_STATUS


def test_missing_package_dir_fails(tmp_path):
    with pytest.raises(PackageBindingError):
        resolve_package_identity(requested_package="Nope",
                                 import_root=str(tmp_path))


# --- NEW-198: deterministic decals -----------------------------------------

def test_same_input_twice_identical():
    kwargs = dict(xodr_sha256="ab" * 32, package_identity="P",
                  tile_identity="T", decal_count=5)
    first = generate_deterministic_decals(**kwargs)
    second = generate_deterministic_decals(**kwargs)
    assert first["artifact_hash"] == second["artifact_hash"]
    assert first["decals"] == second["decals"]
    assert first["seed"] == second["seed"]


def test_different_tile_different_seed():
    a = generate_deterministic_decals(xodr_sha256="ab" * 32, package_identity="P",
                                      tile_identity="T1", decal_count=2)
    b = generate_deterministic_decals(xodr_sha256="ab" * 32, package_identity="P",
                                      tile_identity="T2", decal_count=2)
    assert a["seed"] != b["seed"]
    assert a["artifact_hash"] != b["artifact_hash"]


def test_disabled_policy_emits_no_decals():
    receipt = generate_deterministic_decals(xodr_sha256="ab" * 32,
                                            package_identity="P",
                                            tile_identity="T", decal_count=5,
                                            policy="disabled")
    assert receipt["policy"] == "disabled"
    assert receipt["decals"] == []
    assert receipt["decal_count"] == 0


def test_unknown_policy_rejected():
    with pytest.raises(ValueError):
        generate_deterministic_decals(xodr_sha256="ab" * 32, package_identity="P",
                                      tile_identity="T", decal_count=1,
                                      policy="random")


def test_receipt_fields():
    receipt = generate_deterministic_decals(xodr_sha256="ab" * 32,
                                            package_identity="P",
                                            tile_identity="T", decal_count=2)
    for key in ("policy", "seed", "seed_derivation_inputs",
                "generator_version", "decal_count", "artifact_hash"):
        assert key in receipt


# --- NEW-199: TilesInfo consistency -----------------------------------------

TILESINFO_FIXTURES = [
    "0 0 1000",
    "1 1 1000",
    "-1 -1 1000",
    "100.0 200.0 1000.0",
    "100.25 -0.25 1000.0",
    "-0.25 -0.25 500.5",
    "1234567.89 -987654.321 1000.0",
    "1e3 2e-3 1E3",
]


@pytest.mark.parametrize("line", TILESINFO_FIXTURES)
def test_fixture_roundtrip(line):
    row = parse_tilesinfo_line(line)
    text = format_tilesinfo([row])
    check = tilesinfo_roundtrip_check(text)
    assert check["status"] == "PASS"
    assert check["row_count"] == 1


def test_fractional_coordinates_float_not_truncated():
    row = parse_tilesinfo_line("100.25 -0.25 1000.0")
    assert row.center_x == pytest.approx(100.25)
    assert row.center_y == pytest.approx(-0.25)
    # Integer truncation (the old Atoi bug) would yield 100.0 / -0.0.
    assert row.center_x != 100.0


def test_locale_comma_rejected():
    with pytest.raises(ValueError):
        parse_tilesinfo_token("100,25")


def test_scientific_notation_accepted():
    assert parse_tilesinfo_token("1e3") == pytest.approx(1000.0)


def test_invalid_size_rejected():
    with pytest.raises(ValueError):
        parse_tilesinfo_line("0 0 0")
    with pytest.raises(ValueError):
        parse_tilesinfo_line("0 0 -5")


def test_multirow_document_roundtrip():
    text = "".join(f"{line}\n" for line in TILESINFO_FIXTURES)
    rows = parse_tilesinfo(text)
    assert len(rows) == len(TILESINFO_FIXTURES)
    check = tilesinfo_roundtrip_check(text)
    assert check["status"] == "PASS"


def test_comments_and_blanks_ignored():
    text = "# TilesInfo\n\n0 0 1000\n\n# end\n"
    assert len(parse_tilesinfo(text)) == 1
