"""Guard tests for the delta-only package_write_poller redesign (GAP-049 K).

Proves, on a bounded synthetic tree (no cook required):
  * metadata-first: an unchanged cycle hashes 0 files;
  * one changed file among 7000 hashes exactly that file;
  * unchanged rows are never emitted; flush happens at most once per cycle;
  * deleted/error rows are emitted exactly once;
  * low-space and size-cap guards stop gracefully (reason row, exit 3,
    no traceback) instead of filling the diagnostic disk.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tools.cook_diagnostics.package_write_poller import (
    EXIT_GUARD_STOP,
    PackageWritePoller,
)


def _poller(tmp_path: Path, **kw) -> PackageWritePoller:
    pkg = tmp_path / "pkg"
    pkg.mkdir(exist_ok=True)
    return PackageWritePoller(str(pkg), str(tmp_path / "writes.csv"),
                              interval_sec=0.01, **kw)


def _rows(tmp_path: Path):
    with open(tmp_path / "writes.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_unchanged_cycle_hashes_zero_files(tmp_path: Path) -> None:
    p = _poller(tmp_path)
    for i in range(5):
        (tmp_path / "pkg" / f"f{i}.bin").write_bytes(b"x" * 64)
    p.poll_once()
    first_hashes = p.stats["hash_calls"]
    assert first_hashes == 5
    p.poll_once()
    assert p.stats["hash_calls"] == first_hashes, (
        "metadata-identical files must not be re-hashed"
    )
    rows = _rows(tmp_path)
    assert [r for r in rows if r["status"] == "unchanged"] == []
    # Cycle 2 contributed exactly its heartbeat row.
    assert [r["cycle"] for r in rows].count("2") == 1
    p.stop()


def test_one_changed_file_in_7000_hashes_only_it(tmp_path: Path) -> None:
    p = _poller(tmp_path)
    for i in range(7000):
        (tmp_path / "pkg" / f"f{i:05d}.bin").write_bytes(b"seed")
    p.poll_once()
    assert p.stats["hash_calls"] == 7000
    (tmp_path / "pkg" / "f03456.bin").write_bytes(b"CHANGED!")
    p.poll_once()
    assert p.stats["hash_calls"] == 7001, (
        f"expected exactly 1 re-hash, got {p.stats['hash_calls'] - 7000}"
    )
    rows = _rows(tmp_path)
    changed = [r for r in rows if r["status"] == "changed"]
    assert len(changed) == 1 and changed[0]["file_path"] == "f03456.bin"
    p.stop()


def test_flush_at_most_once_per_cycle(tmp_path: Path) -> None:
    p = _poller(tmp_path)
    for i in range(10):
        (tmp_path / "pkg" / f"f{i}.bin").write_bytes(b"v1")
    for _ in range(5):
        p.poll_once()
    assert p.stats["cycles"] == 5
    assert p.stats["flush_calls"] <= 5, (
        f"{p.stats['flush_calls']} flushes in 5 cycles"
    )
    p.stop()


def test_deleted_row_emitted_exactly_once(tmp_path: Path) -> None:
    p = _poller(tmp_path)
    target = tmp_path / "pkg" / "gone.uasset"
    target.write_bytes(b"data")
    p.poll_once()
    target.unlink()
    p.poll_once()
    p.poll_once()
    rows = _rows(tmp_path)
    deleted = [r for r in rows if r["status"] == "deleted"]
    assert len(deleted) == 1 and deleted[0]["file_path"] == "gone.uasset"
    p.stop()


def test_error_row_emitted_once_not_every_cycle(tmp_path: Path, monkeypatch) -> None:
    p = _poller(tmp_path)
    target = tmp_path / "pkg" / "locked.ubulk"
    target.write_bytes(b"v1")
    p.poll_once()
    target.write_bytes(b"v2-longer")
    monkeypatch.setattr(p, "_compute_sha256", lambda path: "ERROR:PermissionError")
    # count only the forced-error hashes, not the earlier real ones
    p.stats["hash_calls"] = 0
    p.poll_once()
    p.poll_once()
    rows = _rows(tmp_path)
    errors = [r for r in rows if r["status"] == "error"]
    assert len(errors) == 1 and errors[0]["file_path"] == "locked.ubulk"
    p.stop()


def test_low_space_guard_stops_gracefully(tmp_path: Path) -> None:
    p = _poller(tmp_path, min_free_gb=1e12)
    (tmp_path / "pkg" / "a.bin").write_bytes(b"data")
    p.poll_once()  # must not raise
    assert p.stop_reason == "low_space"
    rows = _rows(tmp_path)
    stops = [r for r in rows if r["status"] == "stop:low_space"]
    assert len(stops) == 1
    assert p.run(max_cycles=3) == EXIT_GUARD_STOP
    p.stop()


def test_size_cap_guard_stops_gracefully(tmp_path: Path) -> None:
    p = _poller(tmp_path, max_output_mb=0.0001)  # ~100 bytes
    for i in range(5):
        (tmp_path / "pkg" / f"f{i}.bin").write_bytes(b"0123456789abcdef" * 4)
    code = p.run(max_cycles=10)
    assert code == EXIT_GUARD_STOP
    assert p.stop_reason == "size_cap"
    rows = _rows(tmp_path)
    assert [r for r in rows if r["status"] == "stop:size_cap"]
    p.stop()


def test_heartbeat_present_every_cycle(tmp_path: Path) -> None:
    p = _poller(tmp_path)
    (tmp_path / "pkg" / "a.bin").write_bytes(b"data")
    for _ in range(4):
        p.poll_once()
    rows = _rows(tmp_path)
    beats = [r for r in rows if r["status"] == "heartbeat"]
    assert len(beats) == 4
    assert sorted({r["cycle"] for r in beats}) == ["1", "2", "3", "4"]
    p.stop()


def test_no_heartbeat_mode_stays_delta_only(tmp_path: Path) -> None:
    p = _poller(tmp_path, heartbeat=False)
    (tmp_path / "pkg" / "a.bin").write_bytes(b"data")
    p.poll_once()
    p.poll_once()
    rows = _rows(tmp_path)
    assert len(rows) == 1 and rows[0]["status"] == "new"
    p.stop()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
