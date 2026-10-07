"""A1/A2 regression tests: portable external-path resolution + registry frame.

A1: production tooling must not embed developer-machine absolute paths.
  External locations resolve via CLI arg > env var > portable repo-relative
  default, and missing dependencies fail with a precise error naming what
  was checked and how to provide the path.

A2: tile cooking must derive HEADER_OFFSET_XY from the authoritative map
  registry (structured rebase_dx/rebase_dy), never a re-typed literal.
  The registry values must match the XODR <offset> header.

These tests are offline and fast (no Blender/OSM2World/CARLA execution).
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

KNOWN_DX = 832671.676
KNOWN_DY = 5458671.104


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cook_mod():
    return _load_module(
        "cook_full_grid_tiles_a1a2", REPO_ROOT / "scripts" / "cook_full_grid_tiles.py"
    )


@pytest.fixture(scope="module")
def probe_mod():
    return _load_module(
        "probe_tile_fbx_densest_a1a2", REPO_ROOT / "tools" / "probe_tile_fbx_densest.py"
    )


# ---------------------------------------------------------------------------
# A2: authoritative frame
# ---------------------------------------------------------------------------
class TestRegistryFrameAuthority:
    def test_receipt_exposes_structured_frame(self):
        receipt = verify_pinned_map("auto_map_of_record")
        assert receipt["rebase_dx"] == pytest.approx(KNOWN_DX, abs=1e-9)
        assert receipt["rebase_dy"] == pytest.approx(KNOWN_DY, abs=1e-9)
        assert receipt["frame_kind"] == "rebased_local"
        assert receipt["frame_status"] == "STRUCTURED"

    def test_xodr_header_offset_matches_registry(self):
        receipt = verify_pinned_map("auto_map_of_record")
        xodr = Path(receipt["resolved_path"])
        head = xodr.read_bytes()[:6000].decode("utf-8", errors="replace")
        m = re.search(
            r'<offset\b[^>]*\bx="([0-9eE+.\-]+)"[^>]*\by="([0-9eE+.\-]+)"', head
        ) or re.search(
            r'<offset\b[^>]*\by="([0-9eE+.\-]+)"[^>]*\bx="([0-9eE+.\-]+)"', head
        )
        # attribute order in this file is hdg,z,x,y -- accept any order
        if m is None:
            mx = re.search(r'<offset\b[^>]*\bx="([0-9eE+.\-]+)"', head)
            my = re.search(r'<offset\b[^>]*\by="([0-9eE+.\-]+)"', head)
            assert mx and my, "XODR header <offset> not found in first 6KB"
            hx, hy = float(mx.group(1)), float(my.group(1))
        else:
            # first alternative captured (x, y); second captured (y, x)
            raw = head[m.start():m.end()]
            mx = re.search(r'\bx="([0-9eE+.\-]+)"', raw)
            my = re.search(r'\by="([0-9eE+.\-]+)"', raw)
            hx, hy = float(mx.group(1)), float(my.group(1))
        assert hx == pytest.approx(receipt["rebase_dx"], abs=1e-6)
        assert hy == pytest.approx(receipt["rebase_dy"], abs=1e-6)

    def test_cook_and_probe_offsets_match_registry(self, cook_mod, probe_mod):
        receipt = verify_pinned_map("auto_map_of_record")
        assert tuple(cook_mod.HEADER_OFFSET_XY) == pytest.approx(
            (receipt["rebase_dx"], receipt["rebase_dy"]), abs=1e-9
        )
        assert tuple(probe_mod.HEADER_OFFSET_XY) == pytest.approx(
            (receipt["rebase_dx"], receipt["rebase_dy"]), abs=1e-9
        )
        # before/after: values unchanged from the long-standing known offset
        assert tuple(cook_mod.HEADER_OFFSET_XY) == pytest.approx(
            (KNOWN_DX, KNOWN_DY), abs=1e-9
        )

    def test_missing_metadata_fails_clearly(self, cook_mod):
        with pytest.raises(ValueError, match="rebase_dx.*rebase_dy"):
            cook_mod._header_offset_from_registry({})
        with pytest.raises(ValueError, match="PINNED_MAP_REGISTRY"):
            cook_mod._header_offset_from_registry({"registry_key": "x"})

    def test_malformed_metadata_fails_clearly(self, cook_mod):
        with pytest.raises((ValueError, TypeError)):
            cook_mod._header_offset_from_registry(
                {"rebase_dx": "not-a-number", "rebase_dy": KNOWN_DY}
            )

    def test_dev_machine_path_does_not_affect_frame(
        self, cook_mod, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("OSM2WORLD_HOME", str(tmp_path / "bogus-osm2world"))
        receipt = verify_pinned_map("auto_map_of_record")
        assert cook_mod._header_offset_from_registry(receipt) == pytest.approx(
            (KNOWN_DX, KNOWN_DY), abs=1e-9
        )


# ---------------------------------------------------------------------------
# A1: portable path resolution
# ---------------------------------------------------------------------------
class TestPortablePathResolution:
    def test_no_hardcoded_username_in_production_defaults(
        self, cook_mod, probe_mod
    ):
        """A1: production defaults must not embed a developer-machine path.

        The defect being guarded against is a *hardcoded* absolute path baked
        into source or configuration. It is not the resolved runtime value:
        the portable default is repo-relative, so on a checkout that happens
        to live under ``C:\\Users\\<name>`` the resolved value legitimately
        contains that prefix. Asserting on the resolved value therefore
        rejected a portable checkout instead of detecting a real hardcoding.

        So this checks two distinct things:

        1. the *source text* of each default definition contains no absolute
           developer path literal, and
        2. the resolved default is repo-relative (not an absolute machine path).
        """
        from ultimate_pipeline.enrichment import osm2world_runner as runner

        # (1) No hardcoded absolute dev path in the source that defines them.
        sources = {
            "cook_full_grid_tiles.py": REPO_ROOT / "scripts" / "cook_full_grid_tiles.py",
            "probe_tile_fbx_densest.py": REPO_ROOT / "tools" / "probe_tile_fbx_densest.py",
            "osm2world_runner.py": REPO_ROOT
            / "ultimate_pipeline"
            / "enrichment"
            / "osm2world_runner.py",
        }
        dev_path_pattern = re.compile(
            r"[A-Za-z]:[\\/]Users[\\/][^\\'\"\s]+", re.IGNORECASE
        )
        for label, path in sources.items():
            text = path.read_text(encoding="utf-8", errors="replace")
            hits = dev_path_pattern.findall(text)
            assert not hits, f"{label} hardcodes a developer path literal(s): {hits}"

        # The repo/project directory name must never appear as a path literal
        # either (that is how a machine-specific checkout leaks into defaults).
        for label, path in sources.items():
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            assert "pycharmprojects" not in text, (
                f"{label} hardcodes a project-directory path literal"
            )

        # (2) The defaults must be *derived from* the repo root, not from a
        # machine location. The resolved value is absolute because REPO_ROOT is
        # absolute; portability is proven by the value being anchored at the
        # repo root, so that a checkout in any directory resolves correctly.
        for label, value in [
            ("cook DEFAULT_OSM2WORLD_HOME", cook_mod.DEFAULT_OSM2WORLD_HOME),
            ("probe DEFAULT_OSM2WORLD_HOME", probe_mod.DEFAULT_OSM2WORLD_HOME),
            ("runner DEFAULT_OSM2WORLD_HOME", str(runner.DEFAULT_OSM2WORLD_HOME)),
        ]:
            assert Path(str(value)).is_relative_to(REPO_ROOT), (
                f"{label} must be anchored at the repo root, got: {value}"
            )

        # A hardcoded machine path would NOT be anchored at the repo root when
        # the checkout lives elsewhere, which is exactly what (1) catches in
        # source and this catches in the resolved value.

    def test_osm2world_default_is_env_or_repo_relative(self, cook_mod, monkeypatch):
        monkeypatch.delenv("OSM2WORLD_HOME", raising=False)
        default = cook_mod._resolve_default_osm2world_home()
        assert default.startswith(str(REPO_ROOT)), (
            f"default must be repo-relative when env is unset, got {default!r}"
        )

    def test_osm2world_env_precedence(self, cook_mod, monkeypatch, tmp_path):
        custom = tmp_path / "custom-osm2world"
        custom.mkdir()
        monkeypatch.setenv("OSM2WORLD_HOME", str(custom))
        assert cook_mod._resolve_default_osm2world_home() == str(custom)
        assert cook_mod._require_osm2world_home(None, context="t") == str(custom)
        assert cook_mod._require_osm2world_home("", context="t") == str(custom)

    def test_osm2world_cli_precedence_over_env(
        self, cook_mod, monkeypatch, tmp_path
    ):
        cli_dir = tmp_path / "cli-osm2world"
        cli_dir.mkdir()
        env_dir = tmp_path / "env-osm2world"
        env_dir.mkdir()
        monkeypatch.setenv("OSM2WORLD_HOME", str(env_dir))
        assert cook_mod._require_osm2world_home(str(cli_dir), context="t") == str(
            cli_dir
        )

    def test_missing_osm2world_fails_precisely(
        self, cook_mod, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("OSM2WORLD_HOME", str(tmp_path / "does-not-exist"))
        with pytest.raises(SystemExit) as exc:
            cook_mod._require_osm2world_home(None, context="cook_full_grid_tiles")
        msg = str(exc.value)
        assert "OSM2World home not found" in msg
        assert "--osm2world-home" in msg
        assert "OSM2WORLD_HOME" in msg

    def test_find_carla_server_env_precedence(self, monkeypatch, tmp_path):
        import scripts.find_carla_server as finder

        fake_exe = tmp_path / "CarlaUE4.exe"
        fake_exe.write_bytes(b"MZ")
        monkeypatch.setenv("CARLA_EXE", str(fake_exe))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(os.path, "exists", lambda p: str(p) == str(fake_exe))
            import subprocess

            mp.setattr(
                subprocess,
                "run",
                lambda *a, **k: type("R", (), {"returncode": 0})(),
            )
            exe, _ = finder.find_carla_server()
            assert exe == str(fake_exe)
        monkeypatch.delenv("CARLA_EXE", raising=False)

    def test_find_carla_root_env_without_exe(self, monkeypatch, tmp_path):
        import scripts.find_carla_server as finder

        monkeypatch.delenv("CARLA_EXE", raising=False)
        monkeypatch.delenv("UP_CARLA_EXE", raising=False)
        monkeypatch.setenv("CARLA_ROOT", str(tmp_path))
        # "no exe on disk" must be genuinely simulated, not left to a real
        # filesystem scan: on a workstation that actually has CARLA
        # installed at one of COMMON_CARLA_PATHS (e.g. E:\CARLA\...), an
        # unmocked os.path.exists()/subprocess.run() here would find it and
        # launch the real CarlaUE4.exe simulator as a side effect of an
        # "offline"/unit test -- a confirmed livelock hazard. Mock both,
        # matching test_find_carla_server_env_precedence's pattern, so this
        # test is hermetic on every machine regardless of what's installed.
        monkeypatch.setattr(os.path, "exists", lambda p: False)

        def _no_subprocess(*args, **kwargs):
            raise AssertionError(
                "find_carla_server() must not invoke subprocess.run() when "
                "no candidate path exists on disk"
            )

        monkeypatch.setattr("subprocess.run", _no_subprocess)
        root = finder.get_carla_root()
        # no exe on disk -> falls back to CARLA_ROOT env value itself
        assert root == str(tmp_path)
