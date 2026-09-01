# ultimate_pipeline/tools/hash_tree.py -- live via thesis_orchestrator.py, a
# thesis-reproducibility hashing tool. Zero prior test coverage. No bugs found
# after a careful read of the ignore-pattern matching (_matches_pattern,
# _should_ignore both correct for extension-glob and exact-name patterns,
# checked against every path component so nested ignored directories are
# excluded regardless of depth).
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline.tools.hash_tree import (
    DEFAULT_IGNORE_PATTERNS,
    _matches_pattern,
    _should_ignore,
    hash_tree,
    main,
)


# ---------------------------------------------------------------------------
# _matches_pattern
# ---------------------------------------------------------------------------


def test_matches_extension_pattern():
    assert _matches_pattern("foo.log", "*.log") is True
    assert _matches_pattern("foo.txt", "*.log") is False


def test_matches_exact_pattern():
    assert _matches_pattern("__pycache__", "__pycache__") is True
    assert _matches_pattern("__pycache2__", "__pycache__") is False


# ---------------------------------------------------------------------------
# _should_ignore
# ---------------------------------------------------------------------------


def test_should_ignore_by_own_filename():
    assert _should_ignore(Path("foo.pyc"), ["*.pyc"]) is True
    assert _should_ignore(Path("foo.py"), ["*.pyc"]) is False


def test_should_ignore_by_parent_directory_at_any_depth():
    assert _should_ignore(Path("a/b/__pycache__/foo.txt"), ["__pycache__"]) is True
    assert _should_ignore(Path("a/b/c/foo.txt"), ["__pycache__"]) is False


def test_should_ignore_exact_match_settings_snapshot_at_any_depth():
    assert _should_ignore(
        Path("run_x/settings_snapshot.json"), ["settings_snapshot.json"]
    ) is True


# ---------------------------------------------------------------------------
# hash_tree
# ---------------------------------------------------------------------------


def test_hash_tree_hashes_files_and_excludes_ignored(tmp_path: Path):
    (tmp_path / "keep.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "skip.log").write_text("ignored", encoding="utf-8")
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "mod.pyc").write_bytes(b"\x00\x01")

    result = hash_tree(str(tmp_path))

    assert "keep.txt" in result["files"]
    assert "skip.log" not in result["files"]
    assert not any("pyc" in k for k in result["files"])
    assert result["_meta"]["file_count"] == 1
    assert result["_meta"]["ignored_count"] >= 2


def test_hash_tree_deterministic_hash_for_same_content(tmp_path: Path):
    (tmp_path / "a.txt").write_text("same content", encoding="utf-8")

    r1 = hash_tree(str(tmp_path))
    r2 = hash_tree(str(tmp_path))

    assert r1["files"] == r2["files"]


def test_hash_tree_different_content_different_hash(tmp_path: Path):
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "a.txt").write_text("content A", encoding="utf-8")
    (d2 / "a.txt").write_text("content B", encoding="utf-8")

    r1 = hash_tree(str(d1))
    r2 = hash_tree(str(d2))

    assert r1["files"]["a.txt"] != r2["files"]["a.txt"]


def test_hash_tree_nonexistent_root_raises_value_error(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        hash_tree(str(tmp_path / "does_not_exist"))


def test_hash_tree_root_is_a_file_raises_value_error(tmp_path: Path):
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        hash_tree(str(f))


def test_hash_tree_unsupported_algo_raises_value_error(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported hash algorithm"):
        hash_tree(str(tmp_path), algo="not_a_real_algo")


def test_hash_tree_custom_ignore_overrides_default(tmp_path: Path):
    (tmp_path / "keep.log").write_text("x", encoding="utf-8")  # normally ignored by default

    result = hash_tree(str(tmp_path), ignore=["*.txt"])  # custom, non-default ignore list

    assert "keep.log" in result["files"]


def test_hash_tree_normalizes_windows_separators_in_relpath(tmp_path: Path):
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "f.txt").write_text("x", encoding="utf-8")

    result = hash_tree(str(tmp_path))

    assert "sub/f.txt" in result["files"]
    assert not any("\\" in k for k in result["files"])


# ---------------------------------------------------------------------------
# main() CLI entry point
# ---------------------------------------------------------------------------


def test_main_writes_output_json(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    out = tmp_path / "out" / "hashes.json"

    rc = main(["--in", str(tmp_path), "--out", str(out)])

    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "a.txt" in payload["files"]


def test_main_nonexistent_input_dir_returns_nonzero(tmp_path: Path, capsys):
    rc = main(["--in", str(tmp_path / "missing"), "--out", str(tmp_path / "out.json")])

    assert rc == 1
    assert "Error" in capsys.readouterr().err
