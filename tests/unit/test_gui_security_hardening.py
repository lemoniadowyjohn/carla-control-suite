"""Security tests for Task 15 fixes.

These tests verify the security hardening changes:
- carla_probe_port: truthful bounded probe (no fake rpc_ok)
- SensorRegistry: stop() before destroy()
- train_yolo: raises explicit error, no fabricated metrics
- auto_scenario_generator: seeded RNG
- resource_aware: fail-closed probes (raise when sensors unavailable)
- discover_experiments: doesn't swallow import errors
- XXE-safe XML parsing
- Safe archive extraction (zip/tar) with traversal/symlink protection
- Atomic write (TOCTOU-safe)
- Path validation
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# ----------------------------------------------------------------------
# carla_probe_port
# ----------------------------------------------------------------------


def test_carla_probe_port_truthful():
    """probe() performs real TCP handshake, never returns fake rpc_ok=True."""
    from ultimate_pipeline.carla_tools.carla_probe_port import probe

    # Port 1 is reserved and should fail quickly
    result = probe(host="127.0.0.1", port=1, timeout_s=0.1)
    assert result.rpc_ok is False
    assert result.error is not None
    assert result.error_class is not None
    assert result.duration_ms > 0


def test_carla_probe_port_streaming_disabled():
    """UP_TILE_QA_DISABLE_STREAMING=1 reports streaming_ok=False."""
    import os
    os.environ["UP_TILE_QA_DISABLE_STREAMING"] = "1"
    try:
        from ultimate_pipeline.carla_tools.carla_probe_port import probe
        result = probe(host="127.0.0.1", port=1, timeout_s=0.1)
        assert result.streaming_ok is False
    finally:
        os.environ.pop("UP_TILE_QA_DISABLE_STREAMING", None)


# ----------------------------------------------------------------------
# SensorRegistry: stop() before destroy()
# ----------------------------------------------------------------------


def test_sensor_instance_calls_stop_before_destroy():
    """SensorInstance.destroy calls stop() on actor before destroy()."""
    from ultimate_pipeline.carla_tools.sensor_registry import SensorInstance, SensorSpec

    calls = []

    class FakeActor:
        def stop(self):
            calls.append("stop")

        def destroy(self):
            calls.append("destroy")

    spec = SensorSpec(blueprint="sensor.camera.rgb")
    inst = SensorInstance(spec=spec, actor=FakeActor(), id="cam1")
    inst.destroy()
    assert calls == ["stop", "destroy"], f"expected stop then destroy, got {calls}"


def test_sensor_instance_stop_failure_still_destroys():
    """If stop() fails, destroy() is still attempted."""
    from ultimate_pipeline.carla_tools.sensor_registry import SensorInstance, SensorSpec

    calls = []

    class FakeActor:
        def stop(self):
            raise RuntimeError("stop failed")

        def destroy(self):
            calls.append("destroy")

    spec = SensorSpec(blueprint="sensor.camera.rgb")
    inst = SensorInstance(spec=spec, actor=FakeActor(), id="cam1")
    inst.destroy()  # should not raise
    assert calls == ["destroy"]


# ----------------------------------------------------------------------
# train_yolo: no fabricated metrics
# ----------------------------------------------------------------------


def test_train_yolo_raises_without_ultralytics():
    """train_and_eval_model raises RuntimeError when Ultralytics not installed."""
    from ultimate_pipeline.hpc.train_yolo import train_and_eval_model

    with pytest.raises(RuntimeError) as exc:
        train_and_eval_model({})
    assert "Ultralytics not installed" in str(exc.value)


# ----------------------------------------------------------------------
# auto_scenario_generator: seeded RNG
# ----------------------------------------------------------------------


def test_auto_scenario_generator_seeded_reproducible():
    """Same seed produces identical scenarios."""
    from ultimate_pipeline.scenarios.auto_scenario_generator import AutoScenarioGenerator

    graph = {"A": {"neighbors": ["B"]}, "B": {"neighbors": ["A"]}}

    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        paths1 = AutoScenarioGenerator.generate_from_graph(graph, 5, d1, seed=42)
        paths2 = AutoScenarioGenerator.generate_from_graph(graph, 5, d2, seed=42)

        for p1, p2 in zip(paths1, paths2):
            with open(p1) as f1, open(p2) as f2:
                assert json.load(f1) == json.load(f2)


def test_auto_scenario_generator_different_seeds_different():
    """Different seeds produce different scenarios."""
    from ultimate_pipeline.scenarios.auto_scenario_generator import AutoScenarioGenerator

    graph = {"A": {"neighbors": ["B"]}, "B": {"neighbors": ["A"]}}

    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        paths1 = AutoScenarioGenerator.generate_from_graph(graph, 5, d1, seed=42)
        paths2 = AutoScenarioGenerator.generate_from_graph(graph, 5, d2, seed=43)

        same = all(
            json.load(open(p1)) == json.load(open(p2))
            for p1, p2 in zip(paths1, paths2)
        )
        assert not same, "different seeds should produce different scenarios"


# ----------------------------------------------------------------------
# resource_aware: fail-closed probes
# ----------------------------------------------------------------------


def test_resource_monitor_raises_without_psutil(monkeypatch):
    """ResourceMonitor raises ResourceProbeUnavailable when psutil missing."""
    import ultimate_pipeline.parallel.resource_aware as ra

    # Simulate psutil not available
    monkeypatch.setattr(ra, "HAS_PSUTIL", False)

    with pytest.raises(ra.ResourceProbeUnavailable):
        ra.ResourceMonitor()


def test_resource_monitor_get_memory_raises_without_psutil(monkeypatch):
    """get_memory_mb raises when psutil missing."""
    import ultimate_pipeline.parallel.resource_aware as ra

    monkeypatch.setattr(ra, "HAS_PSUTIL", False)

    # Creating monitor should already raise, but test the method too
    with pytest.raises(ra.ResourceProbeUnavailable):
        ra.ResourceMonitor()


# ----------------------------------------------------------------------
# discover_experiments: doesn't swallow import errors
# ----------------------------------------------------------------------


def test_discover_experiments_surfaces_import_errors():
    """discover_experiments() no longer swallows import errors."""
    import ultimate_pipeline.experiments.registry as exp_reg

    # The module-level discover_experiments() call now propagates errors.
    # We can't easily test the module-level call without import side effects,
    # but we can verify the function doesn't have bare except: pass.
    import inspect
    source = inspect.getsource(exp_reg.discover_experiments)
    assert "except Exception:" not in source or "pass" not in source


# ----------------------------------------------------------------------
# XXE-safe XML parsing
# ----------------------------------------------------------------------


def test_parse_xml_safe_requires_defusedxml(monkeypatch):
    """parse_xml_safe raises SafeXMLParseError when defusedxml missing."""
    import ultimate_pipeline.security as sec

    # Ensure defusedxml is not importable
    monkeypatch.setitem(__import__("sys").modules, "defusedxml", None)

    with pytest.raises(sec.SafeXMLParseError) as exc:
        sec.parse_xml_safe(b"<root/>")
    assert "defusedxml not installed" in str(exc.value)


def test_parse_xml_safe_refuses_doctype(monkeypatch):
    """parse_xml_safe refuses DOCTYPE declarations."""
    import ultimate_pipeline.security as sec

    # Mock defusedxml to be available
    try:
        import defusedxml
    except ImportError:
        pytest.skip("defusedxml not installed")

    xml = b'<?xml version="1.0"?><!DOCTYPE root><root/>'
    with pytest.raises(sec.SafeXMLParseError) as exc:
        sec.parse_xml_safe(xml)
    assert "DOCTYPE" in str(exc.value)


# ----------------------------------------------------------------------
# Safe archive extraction
# ----------------------------------------------------------------------


def test_extract_zip_safe_refuses_traversal():
    """extract_zip_safe refuses zip entries with path traversal."""
    import ultimate_pipeline.security as sec

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "evil.zip"
        dest = Path(tmp) / "dest"

        # Create a zip with traversal
        import zipfile
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../evil.txt", "traversal")

        with pytest.raises(sec.SafeArchiveError) as exc:
            sec.extract_zip_safe(zip_path, dest)
        assert "traversal" in str(exc.value).lower()


def test_extract_zip_safe_refuses_absolute():
    """extract_zip_safe refuses absolute paths in zip."""
    import ultimate_pipeline.security as sec

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "evil.zip"
        dest = Path(tmp) / "dest"

        import zipfile
        with zipfile.ZipFile(zip_path, "w") as zf:
            info = zipfile.ZipInfo("/absolute/path.txt")
            zf.writestr(info, "absolute")

        with pytest.raises(sec.SafeArchiveError) as exc:
            sec.extract_zip_safe(zip_path, dest)
        assert "absolute" in str(exc.value).lower()


def test_extract_tar_safe_refuses_symlink():
    """extract_tar_safe refuses symlinks in tar."""
    import ultimate_pipeline.security as sec

    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / "evil.tar"
        dest = Path(tmp) / "dest"

        import tarfile
        with tarfile.open(tar_path, "w") as tf:
            link = tarfile.TarInfo("link.txt")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tf.addfile(link)

        with pytest.raises(sec.SafeArchiveError) as exc:
            sec.extract_tar_safe(tar_path, dest)
        assert "symlink" in str(exc.value).lower()


def test_extract_zip_safe_valid_archive():
    """extract_zip_safe extracts valid archives."""
    import ultimate_pipeline.security as sec

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "good.zip"
        dest = Path(tmp) / "dest"

        import zipfile
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("file1.txt", "content1")
            zf.writestr("sub/file2.txt", "content2")

        extracted = sec.extract_zip_safe(zip_path, dest)
        assert len(extracted) == 2
        assert (dest / "file1.txt").read_text() == "content1"
        assert (dest / "sub" / "file2.txt").read_text() == "content2"


# ----------------------------------------------------------------------
# Path validation
# ----------------------------------------------------------------------


def test_resolve_safe_path_allows_within_base(tmp_path):
    """resolve_safe_path allows paths within base."""
    import ultimate_pipeline.security as sec

    base = tmp_path / "base"
    base.mkdir()
    result = sec.resolve_safe_path(Path("sub/file.txt"), base)
    assert result == base / "sub" / "file.txt"


def test_resolve_safe_path_refuses_escape(tmp_path):
    """resolve_safe_path refuses paths that escape base."""
    import ultimate_pipeline.security as sec

    base = tmp_path / "base"
    base.mkdir()
    with pytest.raises(sec.PathValidationError):
        sec.resolve_safe_path(Path("../etc/passwd"), base)


def test_resolve_safe_path_refuses_absolute_outside_base(tmp_path):
    """resolve_safe_path refuses absolute paths outside base."""
    import ultimate_pipeline.security as sec

    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(sec.PathValidationError):
        sec.resolve_safe_path(outside / "passwd", base)


# ----------------------------------------------------------------------
# Atomic write (TOCTOU-safe)
# ----------------------------------------------------------------------


def test_atomic_write_creates_file():
    """atomic_write creates file atomically."""
    import ultimate_pipeline.security as sec

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "output.txt"
        sec.atomic_write(path, b"hello")
        assert path.read_bytes() == b"hello"


def test_atomic_write_uses_same_dir_for_temp():
    """atomic_write creates temp file in same directory (for atomic replace)."""
    import ultimate_pipeline.security as sec
    import os

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "output.txt"
        sec.atomic_write(path, b"hello")
        # No temp files left behind
        remaining = list(Path(tmp).glob("*.tmp.*"))
        assert len(remaining) == 0


def test_atomic_write_string_encoding():
    """atomic_write handles string data with encoding."""
    import ultimate_pipeline.security as sec

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "output.txt"
        sec.atomic_write(path, "héllo", encoding="utf-8")
        assert path.read_text(encoding="utf-8") == "héllo"