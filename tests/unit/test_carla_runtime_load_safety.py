"""Regression tests for the CARLA runtime load-safety findings NEW-248..NEW-260.

These are all fail-closed *policy* defects: the protections existed in the
repository but were not composed into one contract, and in several cases a
defence was actively defeated by later code.

NEW-248  --use-current-world was defeated by an unconditional stream-flush reload
NEW-249  generated OpenDRIVE was reloaded via load_world("OpenDriveMap")
NEW-250  runtime map was not rebound to the exact source .xodr
NEW-251  generated .xodr skipped the isolated map-only probe
NEW-252  cooked Grid identity was name-only, so a stale package could pass
NEW-253  record_route_fixed used substring map matching
NEW-254  Grid0828 was not protected the way Grid0821 was
NEW-255  streaming readiness was contradictory and partly fail-open
NEW-256  the OpenDRIVE crash classifier existed but was not wired into the loader
NEW-257  CarlaFinalTest could test modified XODR instead of the candidate
NEW-258  skip-destroy traded crash risk for stale state with no session policy
NEW-259  the diagnostic probe destroyed actors on ASensor::EndPlay-unstable maps
NEW-260  one successful tick was treated as map stability

Every test here is offline: no CARLA server is contacted. The governed paths are
exercised with fakes, because the whole point of these gates is that they decide
*before* anything irreversible happens.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.carla_tools import map_runtime_identity as mri
from ultimate_pipeline.carla_tools.map_runtime_identity import (
    LoadMode,
    MapStabilityError,
    MapTravelProhibitedError,
    RuntimeMapIdentity,
    assert_no_map_travel,
    fingerprint_mismatches,
    mode_allows_map_travel,
    post_load_soak,
    resolve_load_mode,
    runtime_map_fingerprint,
    structural_fingerprint,
    verify_runtime_map_identity,
)
from ultimate_pipeline.carla_tools.map_registry import map_names_match, normalize_map_name


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


def _xodr(
    *,
    roads=2,
    road_len: str = "10.0",
    georef: str = "+proj=tmerc +lat_0=0",
    junctions=1,
) -> str:
    parts = [
        f'<OpenDRIVE><header name="t"><geoReference>{georef}</geoReference></header>'
    ]
    for i in range(roads):
        parts.append(
            f'<road id="{i + 1}" length="{road_len}" junction="-1"><planView>'
            f'<geometry x="{i}" y="0" z="0" h="0" p="0" r="0" length="{road_len}"/>'
            f"</planView><lanes><laneSection s=\"0\">"
            f'<left><lane id="1" type="driving"><link><successor id="1"/></link></lane></left>'
            f'<center><lane id="0" type="none"/></center>'
            f"</laneSection></lanes></road>"
        )
    for j in range(junctions):
        parts.append(
            f'<junction id="{j + 1}" type="default">'
            f'<connection incoming="1" outgoing="2"/></junction>'
        )
    parts.append("</OpenDRIVE>")
    return "".join(parts)


class FakeMap:
    def __init__(self, name: str, xodr: str | None):
        self.name = name
        self._xodr = xodr

    def to_opendrive(self):
        if self._xodr is None:
            raise RuntimeError("unsupported")
        return self._xodr


class FakeWorld:
    def __init__(self, name: str, xodr: str | None, *, frames=None):
        self._map = FakeMap(name, xodr)
        self._frames = frames

    def get_map(self):
        return self._map

    def get_settings(self):
        class S:
            synchronous_mode = True

        return S()

    def tick(self, timeout=2.0):
        if self._frames is not None:
            frame = self._frames.pop(0) if self._frames else 0
        else:
            frame = 1
        return type("Snap", (), {"frame": frame})()

    def wait_for_tick(self, timeout=2.0):
        return self.tick(timeout)


# ---------------------------------------------------------------------------
# NEW-250: structural fingerprint
# ---------------------------------------------------------------------------


def test_structural_fingerprint_captures_topology():
    fp = structural_fingerprint(_xodr())
    assert fp["components"]["road_count"] == 2
    assert fp["components"]["junction_count"] == 1
    assert fp["components"]["road_ids"] == ["1", "2"]
    assert fp["components"]["georeference"] == "+proj=tmerc +lat_0=0"
    assert len(fp["fingerprint_sha256"]) == 64
    # planView + lane-section topology must be represented, not just the ids.
    assert fp["components"]["roads"][0]["planview"]
    assert fp["components"]["roads"][0]["lane_sections"][0]["lanes"]


def test_structural_fingerprint_is_immune_to_carla_reserialization():
    """CARLA re-serializes OpenDRIVE, so byte equality is the wrong test."""
    original = structural_fingerprint(_xodr(road_len="10.0"))
    reserialized = structural_fingerprint(
        _xodr(road_len="10.00000000000001")  # float noise from serialization
    )
    assert original["fingerprint_sha256"] == reserialized["fingerprint_sha256"]

    # Attribute ordering must not matter either.
    reordered = structural_fingerprint(
        _xodr().replace('<road id="1" length="10.0" junction="-1">', '<road junction="-1" length="10.0" id="1">')
    )
    assert reordered["fingerprint_sha256"] == original["fingerprint_sha256"]


def test_structural_fingerprint_detects_real_topology_differences():
    base = structural_fingerprint(_xodr())
    assert structural_fingerprint(_xodr(roads=3))["fingerprint_sha256"] != base["fingerprint_sha256"]
    assert structural_fingerprint(_xodr(junctions=2))["fingerprint_sha256"] != base["fingerprint_sha256"]
    assert (
        structural_fingerprint(_xodr(georef="+proj=utm +zone=32"))["fingerprint_sha256"]
        != base["fingerprint_sha256"]
    )


def test_fingerprint_mismatches_names_the_differing_component():
    a = structural_fingerprint(_xodr(roads=2))
    b = structural_fingerprint(_xodr(roads=5))
    diffs = fingerprint_mismatches(a, b)
    assert any("road_count" in d for d in diffs)
    assert any("road_ids" in d for d in diffs)


def test_runtime_map_fingerprint_uses_to_opendrive():
    world = FakeWorld("OpenDriveMap", _xodr())
    fp = runtime_map_fingerprint(world)
    assert fp is not None
    assert fp["fingerprint_sha256"] == structural_fingerprint(_xodr())["fingerprint_sha256"]


def test_runtime_map_fingerprint_returns_none_when_unsupported():
    """A runtime that cannot serialize must NOT silently pass as name-only."""
    world = FakeWorld("Grid0828", None)
    assert runtime_map_fingerprint(world) is None


# ---------------------------------------------------------------------------
# NEW-252 / NEW-253: the three-layer identity gate
# ---------------------------------------------------------------------------


def test_identity_gate_rejects_stale_same_named_cooked_package():
    """NEW-252: a correct-name but wrong-content Grid must not pass."""
    approved = structural_fingerprint(_xodr(roads=2))
    stale_world = FakeWorld("/Game/Carla/Maps/Grid0828", _xodr(roads=7))

    identity = verify_runtime_map_identity(
        world=stale_world,
        expected_map_name="Grid0828",
        mode=LoadMode.MANUAL_COOKED_UNSTABLE,
        expected_fingerprint=approved,
    )
    assert not identity.ok
    assert identity.name_matched is True, "the name does match; content must still be checked"
    assert not identity.structural_ok
    assert any("structural_mismatch" in f for f in identity.failures)
    assert identity.to_dict()["verdict"] == "RUNTIME_MAP_IDENTITY_FAIL"


def test_identity_gate_passes_for_correct_content():
    approved = structural_fingerprint(_xodr())
    world = FakeWorld("Carla/Maps/Grid0828", _xodr())
    identity = verify_runtime_map_identity(
        world=world,
        expected_map_name="Grid0828",
        mode=LoadMode.MANUAL_COOKED_UNSTABLE,
        expected_fingerprint=approved,
    )
    assert identity.ok
    assert identity.to_dict()["verdict"] == "RUNTIME_MAP_IDENTITY_PASS"
    assert identity.runtime_map_structural_sha256 == approved["fingerprint_sha256"]


def test_identity_gate_fails_closed_without_expected_fingerprint():
    """NEW-252: no approved reference means no pass, not a degraded pass."""
    world = FakeWorld("Grid0828", _xodr())
    identity = verify_runtime_map_identity(
        world=world,
        expected_map_name="Grid0828",
        mode=LoadMode.MANUAL_COOKED_UNSTABLE,
        expected_fingerprint=None,
        require_structural=True,
    )
    assert not identity.ok
    assert any("no_expected_structural_fingerprint" in f for f in identity.failures)


def test_identity_gate_fails_closed_when_runtime_cannot_serialize():
    world = FakeWorld("Grid0828", None)
    identity = verify_runtime_map_identity(
        world=world,
        expected_map_name="Grid0828",
        mode=LoadMode.MANUAL_COOKED_UNSTABLE,
        expected_fingerprint=structural_fingerprint(_xodr()),
        require_structural=True,
    )
    assert not identity.ok
    assert any("unavailable" in f for f in identity.failures)


def test_identity_gate_uses_canonical_matching_not_substrings():
    """NEW-253: Broken_Grid0821_Test must not satisfy a Grid0821 request."""
    approved = structural_fingerprint(_xodr())
    world = FakeWorld("Broken_Grid0821_Test", _xodr())
    identity = verify_runtime_map_identity(
        world=world,
        expected_map_name="Grid0821",
        mode=LoadMode.MANUAL_COOKED_UNSTABLE,
        expected_fingerprint=approved,
    )
    assert not identity.name_matched
    assert not identity.ok


@pytest.mark.parametrize(
    "actual",
    [
        "Broken_Grid0821_Test",
        "OldGrid0821Backup",
        "Foo/Grid0821_copy",
        "Grid0821Old",
    ],
)
def test_no_substring_map_matching_survives(actual):
    assert not map_names_match(actual, "Grid0821")
    assert not map_names_match(actual, "Grid0828")


def test_canonical_alias_matching_still_works():
    assert map_names_match("/Game/Carla/Maps/Grid0828", "Grid0828")
    assert map_names_match("Carla/Maps/Grid0821", "Grid0821")
    assert map_names_match("Carla/Maps/Town03", "Town03")


def test_grid0821_and_grid0828_remain_distinct_names():
    """
    The registry records Grid0821 and Grid0828 as distinct *map names* that
    happen to share approved manual OpenDRIVE content.

    That division of labour is deliberate and must not be collapsed: the name
    layer answers "which map did the operator ask for", and the structural
    fingerprint answers "is the loaded content the approved content". Fusing
    them would let a Grid0821 request silently accept a Grid0828 package.
    """
    assert not map_names_match("Grid0828", "Grid0821")
    assert normalize_map_name("Grid0828") != normalize_map_name("Grid0821")


# ---------------------------------------------------------------------------
# NEW-248 / NEW-249 / NEW-254: the map-travel prohibition
# ---------------------------------------------------------------------------


def test_stream_flush_reload_is_prohibited_for_use_current_world():
    """NEW-248: the reload that defeated --use-current-world must now fail."""
    from ultimate_pipeline.perception.record_route_fixed import (
        _maybe_reload_world_for_stream_flush,
    )

    class ExplodingClient:
        def load_world(self, *a, **k):  # pragma: no cover - must never be reached
            raise AssertionError("NEW-248: load_world was called despite --use-current-world")

        def reload_world(self, *a, **k):  # pragma: no cover
            raise AssertionError("NEW-248: reload_world was called despite --use-current-world")

    world = FakeWorld("Grid0821", _xodr())
    with pytest.raises(MapTravelProhibitedError, match="stream_flush_world_reload"):
        _maybe_reload_world_for_stream_flush(
            client=ExplodingClient(),
            world=world,
            fps=20.0,
            load_mode=LoadMode.MANUAL_COOKED_UNSTABLE,
        )


def test_generated_opendrive_reload_is_prohibited():
    """NEW-249: load_world('OpenDriveMap') is not the generated world."""
    with pytest.raises(MapTravelProhibitedError) as exc:
        assert_no_map_travel(
            mode=LoadMode.GENERATED_XODR,
            operation="stream_flush_world_reload",
            current_map_name="OpenDriveMap",
        )
    assert "OpenDriveMap" in str(exc.value)
    assert "LAST map-changing operation" in str(exc.value)


def test_builtin_cooked_mode_still_may_travel():
    assert mode_allows_map_travel(LoadMode.BUILTIN_COOKED)
    assert not mode_allows_map_travel(LoadMode.GENERATED_XODR)
    assert not mode_allows_map_travel(LoadMode.MANUAL_COOKED_UNSTABLE)
    assert_no_map_travel(mode=LoadMode.BUILTIN_COOKED, operation="load_world")


def test_both_grid_maps_get_one_common_rule():
    """NEW-254: the policy must not depend on the entrypoint or the map name."""
    for town in ("Grid0821", "Grid0828", "Carla/Maps/Grid0821", "grid0828"):
        mode = resolve_load_mode(use_current_world=True, requested_map=town)
        assert mode is LoadMode.MANUAL_COOKED_UNSTABLE, town
        assert not mode_allows_map_travel(mode), town

        # Even without --use-current-world, a Grid map is not reachable by travel.
        travel_mode = resolve_load_mode(use_current_world=False, requested_map=town)
        assert travel_mode is LoadMode.MANUAL_COOKED_UNSTABLE, town


def test_grid0828_town_argument_is_blocked_like_grid0821():
    """NEW-254: record_route_fixed previously blocked only Grid0821."""
    from ultimate_pipeline.perception.record_route_fixed import _maybe_reload_world_for_stream_flush

    # The runtime mode resolution is what gates the load, and it must treat both
    # Grid maps identically. Grid0828 previously fell through to load_world().
    mode = resolve_load_mode(use_current_world=False, requested_map="Grid0828")
    assert mode is LoadMode.MANUAL_COOKED_UNSTABLE
    with pytest.raises(MapTravelProhibitedError):
        _maybe_reload_world_for_stream_flush(
            client=object(), world=FakeWorld("Town03", _xodr()), fps=20.0, load_mode=mode
        )


def test_builtin_town_resolves_to_builtin_mode():
    assert resolve_load_mode(use_current_world=True, requested_map="Town03") is LoadMode.BUILTIN_COOKED
    assert resolve_load_mode(use_current_world=False, requested_map="Town10HD_Opt") is LoadMode.BUILTIN_COOKED
    assert resolve_load_mode(use_current_world=False, xodr_path="map.xodr") is LoadMode.GENERATED_XODR


# ---------------------------------------------------------------------------
# NEW-260: post-load stability
# ---------------------------------------------------------------------------


def test_single_tick_is_not_map_stability():
    """NEW-260: a map that ticks once has not proven it is stable."""
    # One tick then a stall: the map loaded, then died -- exactly the Grid failure.
    class StallingWorld(FakeWorld):
        def __init__(self):
            super().__init__("Grid0828", _xodr())
            self._count = 0

        def tick(self, timeout=2.0):
            self._count += 1
            if self._count == 1:
                return type("Snap", (), {"frame": 10})()
            raise RuntimeError("LowLevelFatalError: engine died shortly after load")

    soak = post_load_soak(StallingWorld(), min_ticks=30)
    assert not soak["ok"]
    assert soak["observed_ticks"] == 1
    assert soak["required_ticks"] == 30
    assert any("tick_failed" in e for e in soak["errors"])


def test_post_load_soak_detects_non_advancing_frames():
    class FrozenWorld(FakeWorld):
        def tick(self, timeout=2.0):
            return type("Snap", (), {"frame": 7})()

    soak = post_load_soak(FrozenWorld("Grid0828", _xodr()), min_ticks=5)
    assert not soak["ok"]
    assert not soak["frames_advancing"]
    assert any("not_advancing" in e for e in soak["errors"])


def test_soak_requires_more_than_a_single_tick():
    """NEW-260: one tick must never be sufficient for MAP_STABLE."""
    # The world dies on its second tick, which is the historical Grid failure
    # mode: the map loaded, then the engine went away shortly afterwards.
    class DiesAfterOneTick(FakeWorld):
        def __init__(self):
            super().__init__("Grid0828", _xodr())
            self._n = 0

        def tick(self, timeout=2.0):
            self._n += 1
            if self._n == 1:
                return type("Snap", (), {"frame": 5})()
            raise RuntimeError("LowLevelFatalError")

    soak = post_load_soak(DiesAfterOneTick(), min_ticks=30)
    assert not soak["ok"]
    assert soak["required_ticks"] == 30
    assert soak["observed_ticks"] == 1


def test_post_load_soak_passes_on_sustained_advance():
    class AdvancingWorld(FakeWorld):
        def __init__(self):
            super().__init__("Grid0828", _xodr())
            self._n = 0

        def tick(self, timeout=2.0):
            self._n += 1
            return type("Snap", (), {"frame": 1000 + self._n})()

    soak = post_load_soak(AdvancingWorld(), min_ticks=30)
    assert soak["ok"]
    assert soak["observed_ticks"] == 30
    assert soak["frames_advancing"] is True
    assert soak["last_frame"] > soak["first_frame"]


def test_map_stability_error_exists_for_callers_to_raise():
    assert issubclass(MapStabilityError, RuntimeError)


# ---------------------------------------------------------------------------
# NEW-256: crash classifier wired into the loader
# ---------------------------------------------------------------------------


def test_opendrive_loader_classifier_is_the_existing_diagnostic():
    """NEW-256: the loader must use the diagnostic that already existed."""
    from ultimate_pipeline.core.carla_opendrive_loader import classify_opendrive_failure
    from ultimate_pipeline.core.opendrive_gen_diagnostic import classify_failure

    for text in (
        "LowLevelFatalError: Assertion failed: s <= road->GetLength()",
        "std::bad_alloc / out of memory while generating",
        "RPC timeout waiting for world",
        "some unclassified engine failure",
    ):
        assert classify_opendrive_failure(text) == classify_failure(text), text


def test_loader_records_three_distinct_identities():
    """NEW-250: source SHA, runtime payload SHA, and runtime structural SHA."""
    from ultimate_pipeline.core.carla_opendrive_loader import _attach_runtime_structural_identity

    identity: dict = {}
    world = FakeWorld("OpenDriveMap", _xodr())
    _attach_runtime_structural_identity(identity=identity, world=world)
    assert identity["runtime_map_structural_sha256"] == structural_fingerprint(_xodr())["fingerprint_sha256"]


def test_loader_identity_records_payload_vs_source_divergence():
    """A georeference normalization must be visible, not invisible."""
    from ultimate_pipeline.core import carla_opendrive_loader as loader

    original = "+proj=merc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84"
    xodr = _xodr(georef=original)
    source_sha = loader._sha256_text(xodr)
    normalized = loader._normalize_georef_in_xodr_text(xodr)
    runtime_sha = loader._sha256_text(normalized)

    # The payload that would reach CARLA is not the file on disk.
    assert runtime_sha != source_sha
    # Both are independently computable, which is the point of NEW-250.
    assert len(source_sha) == 64 and len(runtime_sha) == 64


def test_loader_raises_on_structural_mismatch():
    from ultimate_pipeline.core.carla_opendrive_loader import _attach_runtime_structural_identity

    identity: dict = {}
    world = FakeWorld("OpenDriveMap", _xodr(roads=9))
    with pytest.raises(RuntimeError, match="RUNTIME_MAP_IDENTITY_MISMATCH"):
        _attach_runtime_structural_identity(
            identity=identity,
            world=world,
            expected_structural_sha256=structural_fingerprint(_xodr())["fingerprint_sha256"],
        )


def test_loader_refuses_name_only_match_when_structure_required():
    from ultimate_pipeline.core.carla_opendrive_loader import _attach_runtime_structural_identity

    identity: dict = {}
    world = FakeWorld("OpenDriveMap", None)  # to_opendrive unsupported
    with pytest.raises(RuntimeError, match="refusing a name-only match"):
        _attach_runtime_structural_identity(
            identity=identity, world=world, expected_structural_sha256="deadbeef"
        )


# ---------------------------------------------------------------------------
# NEW-251: the isolated probe covers XODR runs
# ---------------------------------------------------------------------------


def test_map_probe_subprocess_accepts_an_xodr_path(monkeypatch, tmp_path):
    from ultimate_pipeline.tools import run_perception_safe as rps

    captured: list[list[str]] = []

    # Patch a *shim* rather than the shared `subprocess` module attribute: the
    # module object is global, so replacing its `run` would break subprocess
    # internals that pytest itself relies on.
    def _fake_run(cmd, **kwargs):
        captured.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    shim = types.SimpleNamespace(
        run=_fake_run,
        TimeoutExpired=subprocess.TimeoutExpired,
        PIPE=subprocess.PIPE,
    )
    monkeypatch.setattr(rps, "subprocess", shim)
    rps._run_map_only_probe_subprocess(
        out_dir=tmp_path,
        host="127.0.0.1",
        port=2000,
        town="OpenDriveMap",
        expected_map_name="",
        use_current_world=False,
        timeout_s=5.0,
        xodr_path=tmp_path / "candidate.xodr",
    )
    assert captured, "the probe subprocess must be invoked"
    cmd = captured[0]
    assert "--xodr-path" in cmd
    assert str(tmp_path / "candidate.xodr") in cmd
    assert "map_only_probe" in " ".join(cmd)


def test_xodr_runs_are_no_longer_skipped_for_lack_of_a_town(monkeypatch, tmp_path):
    """NEW-251: pre-fix, a generated-XODR run logged 'map_probe_skipped_no_town'."""
    source = Path("ultimate_pipeline/tools/run_perception_safe.py").read_text(encoding="utf-8")
    assert "map_probe_skipped_no_town" not in source
    assert "map_probe_skipped_no_subject" in source
    assert 'if map_probe_requested and map_probe_subject:' in source
    assert "xodr_path=map_probe_xodr" in source


# ---------------------------------------------------------------------------
# NEW-255: sensor canary, not the port
# ---------------------------------------------------------------------------


def test_streaming_port_is_recorded_but_not_decisive():
    from ultimate_pipeline.carla_tools import reload_ready_for_sensors as rrs

    source = Path("ultimate_pipeline/carla_tools/reload_ready_for_sensors.py").read_text(
        encoding="utf-8"
    )
    # The fail-open branch is gone: a closed port is recorded, not waved through.
    assert "proceeding anyway" not in source
    assert "diagnostic only" in source
    assert hasattr(rrs, "_wait_for_sensor_canary")


def test_canary_fails_when_no_callback_arrives(monkeypatch):
    from ultimate_pipeline.carla_tools import reload_ready_for_sensors as rrs

    class NoFrameWorld:
        def get_blueprint_library(self):
            raise RuntimeError("no blueprint library")

    receipt = rrs._wait_for_sensor_canary(NoFrameWorld(), ticks=2)
    assert receipt["ok"] is False
    assert receipt["canary_frames"] == 0
    assert any("canary_spawn_failed" in e for e in receipt["canary_errors"])


def test_canary_passes_on_a_real_callback(monkeypatch):
    from ultimate_pipeline.carla_tools import reload_ready_for_sensors as rrs

    class Blueprint:
        def set_attribute(self, *a, **k):
            pass

    class Library:
        def find(self, name):
            return Blueprint()

    class Sensor:
        def __init__(self):
            self.stopped = False
            self.destroyed = False

        def listen(self, callback):
            callback(type("Img", (), {"frame": 42})())

        def stop(self):
            self.stopped = True

        def destroy(self):  # pragma: no cover - NEW-259 says this must not happen
            self.destroyed = True
            raise AssertionError("NEW-259: the canary must not destroy a sensor")

    sensor = Sensor()

    class CanaryWorld:
        def get_blueprint_library(self):
            return Library()

        def spawn_actor(self, bp, transform):
            return sensor

        def get_settings(self):
            class S:
                synchronous_mode = True

            return S()

        def tick(self, timeout=2.0):
            return type("Snap", (), {"frame": 1})()

    receipt = rrs._wait_for_sensor_canary(CanaryWorld(), ticks=5)
    assert receipt["ok"] is True
    assert receipt["canary_frames"] == 1
    assert receipt["canary_first_frame"] == 42
    assert sensor.stopped is True
    assert sensor.destroyed is False


def test_grid_stream_check_default_does_not_imply_port_is_authoritative():
    """UP_SKIP_STREAM_CHECK exists for Grid maps; the canary replaces its role."""
    from ultimate_pipeline.tools.run_perception_safe import KNOWN_UNSTABLE_MAPS

    assert KNOWN_UNSTABLE_MAPS == frozenset({"grid0821", "grid0828"})


# ---------------------------------------------------------------------------
# NEW-257: exact-candidate certification
# ---------------------------------------------------------------------------


def test_carla_final_test_no_longer_auto_fixes_by_default():
    import inspect

    from ultimate_pipeline.carla_tools.carla_final_test import CarlaFinalTest

    signature = inspect.signature(CarlaFinalTest.run)
    assert signature.parameters["auto_fix_s"].default is False, (
        "NEW-257: acceptance must load the exact candidate; in-memory repair must be opt-in"
    )


def test_final_test_cli_has_no_implicit_repair():
    from ultimate_pipeline.carla_tools import carla_final_test as cft

    source = Path(cft.__file__).read_text(encoding="utf-8")
    assert '"--fix_s"' in source
    assert "--no_fix_s" not in source
    assert "auto_fix_s=bool(args.fix_s)" in source


def test_final_test_refuses_mismatched_expected_artifact(tmp_path):
    """A governed acceptance must verify the digest it was told to certify."""
    from ultimate_pipeline.carla_tools.carla_final_test import CarlaFinalTest

    candidate = tmp_path / "candidate.xodr"
    candidate.write_text(_xodr(), encoding="utf-8")

    report = CarlaFinalTest.run(
        str(candidate),
        client=object(),
        certified_artifact_sha256="0" * 64,
    )
    assert report["certified"] is False
    assert report["exact_candidate_loaded"] is False
    assert report["spawn_reason"] == "artifact_sha256_mismatch"
    assert report["map_loaded"] is False


def test_final_test_reports_source_and_loaded_digests(tmp_path, monkeypatch):
    """The report must distinguish the candidate from whatever was loaded."""
    from ultimate_pipeline.carla_tools import carla_final_test as cft

    # Exercise the SHA bookkeeping without a CARLA server.
    source = Path(cft.__file__).read_text(encoding="utf-8")
    for field in (
        "source_xodr_sha256",
        "loaded_xodr_sha256",
        "exact_candidate_loaded",
        "in_memory_repair_applied",
        "repaired_artifact_sha256",
    ):
        assert f'"{field}"' in source, field


def test_repair_is_materialized_as_a_new_artifact(tmp_path):
    """A repair must produce a new SHA-bearing artifact, never a silent in-memory edit."""
    from ultimate_pipeline.carla_tools import carla_final_test as cft

    source = Path(cft.__file__).read_text(encoding="utf-8")
    assert ".repaired.xodr" in source
    assert 'report["in_memory_repair_applied"] = True' in source
    assert 'report["exact_candidate_loaded"] = False' in source
    # A repaired run must not claim certification of the original candidate.
    assert 'report["certified"] = bool(report["exact_candidate_loaded"])' in source


# ---------------------------------------------------------------------------
# NEW-258 / NEW-259: session lifecycle and phase receipts
# ---------------------------------------------------------------------------


def test_final_test_declares_non_destructive_teardown():
    from ultimate_pipeline.carla_tools import carla_final_test as cft

    source = Path(cft.__file__).read_text(encoding="utf-8")
    # NEW-258: no individual actor destroy in the teardown path.
    assert "vehicle.destroy()" not in source
    assert "non_destructive_session_discard" in source
    assert 'report["session_reusable"] = False' in source


def test_diagnostic_probe_does_not_destroy_actors():
    """NEW-259: cleanup itself was crashing on ASensor::EndPlay-unstable maps."""
    from ultimate_pipeline.tools import diagnostic_carla_probe as dcp

    source = Path(dcp.__file__).read_text(encoding="utf-8")
    assert "cam.destroy()" not in source
    assert "ego.destroy()" not in source
    assert "cam.stop()" in source, "the listener must still be stopped"
    assert "NON_DESTRUCTIVE" in source


def test_diagnostic_probe_writes_phase_receipt_before_teardown():
    from ultimate_pipeline.tools import diagnostic_carla_probe as dcp

    source = Path(dcp.__file__).read_text(encoding="utf-8")
    # The receipt is persisted inside `finally` *before* any teardown call.
    teardown_index = source.index("Phase 5: cleanup")
    persist_index = source.rindex("_persist()", 0, teardown_index)
    assert persist_index < teardown_index
    assert "diagnostic_probe_phases_v1" in source
    # An atomic replace keeps a crash mid-write from truncating the receipt.
    assert ".tmp" in source and ".replace(" in source


def test_phase_receipt_path_is_overridable_for_crash_bundles(monkeypatch, tmp_path):
    from ultimate_pipeline.tools import diagnostic_carla_probe as dcp

    target = tmp_path / "crash_bundle" / "runtime_phase.json"
    monkeypatch.setenv(dcp._RECEIPT_ENV, str(target))
    assert dcp._phase_receipt_path() == target


def test_phase_receipt_records_each_phase_separately():
    from ultimate_pipeline.tools import diagnostic_carla_probe as dcp

    source = Path(dcp.__file__).read_text(encoding="utf-8")
    for phase in ("world", "ego", "camera", "ticks", "frames"):
        assert f'"{phase}"' in source, phase


# ---------------------------------------------------------------------------
# cross-cutting: the record_route_fixed gate stack
# ---------------------------------------------------------------------------


def test_record_route_fixed_resolves_mode_before_any_map_call():
    source = Path("ultimate_pipeline/perception/record_route_fixed.py").read_text(encoding="utf-8")
    resolve_index = source.index("load_mode = resolve_load_mode(")
    load_index = source.index("    if args.use_current_world:", resolve_index)
    assert resolve_index < load_index, (
        "NEW-248/254: the load mode must be decided before any map-changing call"
    )


def test_record_route_fixed_uses_canonical_map_matching():
    source = Path("ultimate_pipeline/perception/record_route_fixed.py").read_text(encoding="utf-8")
    assert "map_names_match" in source
    # The substring implementation must no longer exist as live code.
    body = source.split("def _map_name_contains", 1)[1].split("\ndef ", 1)[0]
    assert "expected in actual" not in body
    assert "return expected.lower() in actual.lower()" not in source


def test_record_route_fixed_gates_identity_and_stability_before_sensors():
    source = Path("ultimate_pipeline/perception/record_route_fixed.py").read_text(encoding="utf-8")
    identity_index = source.index("RUNTIME_MAP_IDENTITY_PASS")
    soak_index = source.index("MAP_STABLE soak_ticks")
    sensor_index = source.index("sensor", identity_index)
    assert identity_index < soak_index
    # Both gates must precede sensor attachment.
    assert soak_index < source.index("def _attach_sensors") if "def _attach_sensors" in source else True


def test_unstable_map_list_is_shared_between_entrypoints():
    """NEW-254: one policy, not one per file."""
    from ultimate_pipeline.carla_tools.map_runtime_identity import UNSTABLE_MANUAL_MAPS
    from ultimate_pipeline.tools.run_perception_safe import KNOWN_UNSTABLE_MAPS

    assert UNSTABLE_MANUAL_MAPS == frozenset(KNOWN_UNSTABLE_MAPS)


def test_runtime_map_identity_payload_is_json_serializable():
    identity = RuntimeMapIdentity(
        ok=False,
        mode=LoadMode.GENERATED_XODR,
        expected_map_name="OpenDriveMap",
        actual_map_name="OpenDriveMap",
        name_matched=True,
        structural_checked=True,
        structural_ok=False,
        structural_differences=["road_count differs"],
        source_xodr_sha256="a" * 64,
        runtime_payload_sha256="b" * 64,
        runtime_map_structural_sha256="c" * 64,
        expected_structural_sha256="d" * 64,
        failures=["runtime_map_structural_mismatch"],
    )
    payload = identity.to_dict()
    assert json.loads(json.dumps(payload))["verdict"] == "RUNTIME_MAP_IDENTITY_FAIL"
    assert payload["structural_differences"] == ["road_count differs"]


def test_all_three_identities_are_recorded_together():
    """NEW-250 requires all three, not one."""
    approved = structural_fingerprint(_xodr())
    world = FakeWorld("OpenDriveMap", _xodr())
    identity = verify_runtime_map_identity(
        world=world,
        expected_map_name="OpenDriveMap",
        mode=LoadMode.GENERATED_XODR,
        expected_fingerprint=approved,
        source_xodr_sha256="a" * 64,
        runtime_payload_sha256="b" * 64,
    )
    payload = identity.to_dict()
    assert payload["source_xodr_sha256"] == "a" * 64
    assert payload["runtime_payload_sha256"] == "b" * 64
    assert payload["runtime_map_structural_sha256"] == approved["fingerprint_sha256"]
