# Regen SUMO guard (2026-08-17): SUMO 1.24.0 is installed at
# C:\Sumo\sumo-win64extra-1.24.0\sumo-1.24.0 and the pipeline's Settings
# autodetect resolves netconvert.exe there, but scripts/regen_map_of_record.py
# only accepted SUMO_HOME/PATH and wrongly refused to regenerate. The guard
# must accept the pipeline's own resolved binary as evidence of availability.
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import scripts.regen_map_of_record as regen


@pytest.fixture
def fake_netconvert(tmp_path: Path) -> Path:
    exe = tmp_path / "netconvert.exe"
    exe.write_text("", encoding="utf-8")
    return exe


def test_settings_netconvert_is_accepted(monkeypatch, fake_netconvert: Path) -> None:
    monkeypatch.delenv("SUMO_HOME", raising=False)
    monkeypatch.setattr(regen.shutil, "which", lambda _: None)

    class _FakeSettings:
        SUMO_NETCONVERT = str(fake_netconvert)

    monkeypatch.setattr("ultimate_pipeline.config.settings.SETTINGS", _FakeSettings())
    ok, message = regen._sumo_status()
    assert ok
    assert "Settings.SUMO_NETCONVERT" in message
    regen._check_sumo()  # must not raise


def test_sumo_home_is_accepted(monkeypatch) -> None:
    monkeypatch.setenv("SUMO_HOME", r"C:\Sumo\sumo-win64extra-1.24.0\sumo-1.24.0")
    ok, message = regen._sumo_status()
    assert ok
    assert "SUMO_HOME" in message


def test_netconvert_on_path_is_accepted(monkeypatch, fake_netconvert: Path) -> None:
    monkeypatch.delenv("SUMO_HOME", raising=False)
    monkeypatch.setattr(regen.shutil, "which", lambda name: str(fake_netconvert) if name == "netconvert" else None)
    ok, message = regen._sumo_status()
    assert ok
    assert "PATH" in message


def test_no_sumo_raises(monkeypatch) -> None:
    monkeypatch.delenv("SUMO_HOME", raising=False)
    monkeypatch.setattr(regen.shutil, "which", lambda _: None)

    class _FakeSettings:
        SUMO_NETCONVERT = r"C:\does\not\exist\netconvert.exe"

    monkeypatch.setattr("ultimate_pipeline.config.settings.SETTINGS", _FakeSettings())
    ok, message = regen._sumo_status()
    assert not ok
    with pytest.raises(RuntimeError, match="SUMO is not available"):
        regen._check_sumo()


def test_run_pipeline_wires_pinned_osm_env(monkeypatch, tmp_path: Path) -> None:
    # F1 contract fix (2026-08-17): _run_pipeline must pass UP_OSM_FILE so the
    # DEM sampler can establish the geographic frame (previously unset ->
    # fail-closed osm_source_unavailable).
    manifest = tmp_path / "INPUTS_MANIFEST.json"
    osm = tmp_path / "ingolstadt_authoritative.osm"
    osm.write_text("<osm/>", encoding="utf-8")
    manifest.write_text(
        json.dumps({"inputs": {"roads_osm": {"path": str(osm)}}}), encoding="utf-8"
    )
    seed = tmp_path / "seed.xodr"
    out_dir = tmp_path / "out"

    captured: dict = {}

    def _fake_run(cmd, cwd, env, stdout, stderr, text, encoding, errors):
        captured["env"] = env
        import subprocess

        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(regen, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(regen.subprocess, "run", _fake_run)
    monkeypatch.setattr(regen.sys, "executable", "python")
    regen._run_pipeline(seed, out_dir, "PERCEPTION_RELEASE", disable_carla=True)
    assert captured["env"]["UP_OSM_FILE"] == str(osm)
    assert captured["env"]["UP_DISABLE_CARLA"] == "1"
    assert captured["env"]["UP_AUTOFIX_LANE_SUCCESSORS"] == "1"
    assert captured["env"]["UP_STRICT_LANE_SUCCESSORS"] == "0"


def _write_global_xodr(path: Path) -> None:
    import xml.etree.ElementTree as _ET

    root = _ET.Element("OpenDRIVE")
    header = _ET.SubElement(root, "header")
    _ET.SubElement(header, "geoReference").text = "+proj=tmerc"
    for i, (x, y) in enumerate([(832671.68, 5458671.10), (845938.74, 5472741.98)]):
        road = _ET.SubElement(root, "road", {"id": str(i), "length": "100.0", "junction": "-1"})
        pv = _ET.SubElement(road, "planView")
        _ET.SubElement(
            pv, "geometry", {"s": "0.0", "x": f"{x:.3f}", "y": f"{y:.3f}", "hdg": "0.0", "length": "100.0"}
        )
    _ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_rebase_global_to_local(tmp_path: Path) -> None:
    src = tmp_path / "global.xodr"
    out = tmp_path / "local.xodr"
    _write_global_xodr(src)
    report = regen._rebase_to_local(src, out)
    assert report["shifted"] is True
    assert report["dx"] == 832671.68
    assert report["dy"] == 5458671.10

    import xml.etree.ElementTree as _ET

    root = _ET.parse(out).getroot()
    xs = [float(g.get("x")) for g in root.findall(".//planView/geometry")]
    ys = [float(g.get("y")) for g in root.findall(".//planView/geometry")]
    assert min(xs) == 0.0 and max(xs) == 13267.06
    assert min(ys) == 0.0 and max(ys) == 14070.88
    off = root.find("header/offset")
    assert off is not None
    assert float(off.get("x")) == 832671.68
    assert float(off.get("y")) == 5458671.10
    assert report["input_sha256"] != report["output_sha256"]


def test_rebase_noop_when_already_local(tmp_path: Path) -> None:
    import xml.etree.ElementTree as _ET

    root = _ET.Element("OpenDRIVE")
    road = _ET.SubElement(root, "road", {"id": "0", "length": "10.0", "junction": "-1"})
    pv = _ET.SubElement(road, "planView")
    _ET.SubElement(pv, "geometry", {"s": "0.0", "x": "0.07", "y": "0.17", "hdg": "0.0", "length": "10.0"})
    src = tmp_path / "local_in.xodr"
    out = tmp_path / "local_out.xodr"
    _ET.ElementTree(root).write(src, encoding="utf-8", xml_declaration=True)
    report = regen._rebase_to_local(src, out)
    assert report["shifted"] is False
    assert report["reason"] == "already_local"
    assert not out.exists()
