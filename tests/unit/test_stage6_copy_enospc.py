"""Tests for Stage-6 atomic artifact copy with ENOSPC handling.

GAP-070: _copy_artifact must materialize each artifact atomically so a
mid-write ENOSPC leaves the destination either absent or a previous
complete copy -- never a partial file.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from ultimate_pipeline.pipeline_stages import stage_06_links


def _make_src(tmp_path: Path, name: str, content: str) -> str:
    src = tmp_path / name
    src.write_text(content, encoding="utf-8")
    return str(src)


def test_copy_artifact_is_atomic_when_source_differs(tmp_path: Path) -> None:
    """The destination must not exist before the copy and must equal the source after."""
    src = _make_src(tmp_path, "src.txt", "hello")
    dst = str(tmp_path / "dst.txt")
    stage_06_links._copy_artifact(src, dst)
    assert os.path.exists(dst)
    assert Path(dst).read_text(encoding="utf-8") == "hello"


def test_copy_artifact_is_idempotent_when_source_equals_dst(tmp_path: Path) -> None:
    """Same-path copy is a no-op and does not raise."""
    src = _make_src(tmp_path, "same.txt", "hello")
    stage_06_links._copy_artifact(src, src)
    assert Path(src).read_text(encoding="utf-8") == "hello"


def test_copy_artifact_creates_missing_parent(tmp_path: Path) -> None:
    src = _make_src(tmp_path, "src.txt", "hello")
    dst = str(tmp_path / "nested" / "deep" / "dst.txt")
    stage_06_links._copy_artifact(src, dst)
    assert Path(dst).read_text(encoding="utf-8") == "hello"


def test_copy_artifact_raises_on_enospc(tmp_path: Path, monkeypatch) -> None:
    """A simulated ENOSPC during the copy must raise, never leave a partial file."""
    src = _make_src(tmp_path, "src.txt", "hello")
    dst = str(tmp_path / "dst.txt")

    real_copy2 = shutil.copy2

    def _fake_copy2(src_path: str, dst_path: str, *args, **kwargs) -> None:
        real_copy2(src_path, dst_path)
        Path(dst_path).write_bytes(b"partially copied")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shutil, "copy2", _fake_copy2)

    with pytest.raises(OSError):
        stage_06_links._copy_artifact(src, dst)

    # Destination must be absent or a previous complete copy -- never partial.
    if os.path.exists(dst):
        assert Path(dst).read_text(encoding="utf-8") == "hello"


def test_copy_artifact_atomic_temp_file_not_visible(tmp_path: Path, monkeypatch) -> None:
    """The temp file used during the copy must not be visible at the final path."""
    src = _make_src(tmp_path, "src.txt", "hello")
    dst = str(tmp_path / "dst.txt")

    seen_paths: list[str] = []
    real_copy2 = shutil.copy2

    def _spy_copy2(src_path: str, dst_path: str, *args, **kwargs) -> None:
        seen_paths.append(dst_path)
        real_copy2(src_path, dst_path)

    monkeypatch.setattr(shutil, "copy2", _spy_copy2)
    stage_06_links._copy_artifact(src, dst)

    # The final dst must be present and complete.
    assert os.path.exists(dst)
    assert seen_paths == [dst + ".tmp"]
    assert not Path(dst + ".tmp").exists()
    assert Path(dst).read_text(encoding="utf-8") == "hello"
