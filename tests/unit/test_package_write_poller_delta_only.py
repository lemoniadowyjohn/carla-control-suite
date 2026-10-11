"""Regression tests for the package_write_poller runaway-CSV defect.

Observed 2026-10-11 on a city-scale cook: the poller emitted ~1,430,000 rows of
which only 7,874 carried signal (99.4% noise), producing a 273 MB CSV on C: --
the same volume UE uses for scratch/DDC. The poller died with OSError ENOSPC
while the cook crashed with "Could not write to ...T_Fabric_15_R.ubulk!".

A diagnostic must not be able to exhaust the disk it is measuring. These tests
pin delta-only emission and per-cycle flushing.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from tools.cook_diagnostics.package_write_poller import PackageWritePoller


def _poller(tmp_path: Path, interval: float = 0.01) -> PackageWritePoller:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    csv_path = tmp_path / "writes.csv"
    return PackageWritePoller(str(pkg), str(csv_path), interval_sec=interval)


def _rows(csv_path: Path):
    with open(csv_path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_unchanged_files_are_not_re_emitted(tmp_path: Path) -> None:
    """The core defect: a stable directory must produce no new rows per cycle."""
    p = _poller(tmp_path)
    (tmp_path / "pkg" / "a.uasset").write_bytes(b"aaaa")
    (tmp_path / "pkg" / "b.uasset").write_bytes(b"bbbb")

    p.poll_once()
    first = len(_rows(tmp_path / "writes.csv"))
    assert first == 2, "first cycle should emit one row per file"

    for _ in range(20):
        p.poll_once()

    after = len(_rows(tmp_path / "writes.csv"))
    assert after == first, (
        f"20 further polls over an unchanged directory added {after - first} rows; "
        "unchanged files must not be re-emitted"
    )
    p.stop()


def test_growth_is_bounded_by_signal_not_file_count(tmp_path: Path) -> None:
    """Row count must scale with changes, not with cycles x files."""
    p = _poller(tmp_path)
    for i in range(10):
        (tmp_path / "pkg" / f"f{i}.uasset").write_bytes(b"seed")

    p.poll_once()
    baseline = len(_rows(tmp_path / "writes.csv"))

    # 50 cycles, one genuine change in the middle
    for i in range(50):
        if i == 25:
            (tmp_path / "pkg" / "f3.uasset").write_bytes(b"CHANGED")
        p.poll_once()

    total = len(_rows(tmp_path / "writes.csv"))
    # 10 initial + exactly 1 for the one changed file
    assert total == baseline + 1, (
        f"expected exactly 1 signal row for 1 change across 50 cycles, got "
        f"{total - baseline}"
    )
    p.stop()


def test_new_and_changed_are_still_emitted(tmp_path: Path) -> None:
    """Delta filtering must not suppress the rows that carry the signal."""
    p = _poller(tmp_path)
    target = tmp_path / "pkg" / "x.uasset"

    target.write_bytes(b"one")
    p.poll_once()

    target.write_bytes(b"two-longer")
    p.poll_once()

    target.unlink()
    p.poll_once()

    rows = _rows(tmp_path / "writes.csv")
    statuses = [r["status"] for r in rows]
    assert "new" in statuses, "a first-seen file must be reported as new"
    assert "changed" in statuses, "a modified file must be reported as changed"
    p.stop()


def test_csv_size_stays_small_over_many_idle_cycles(tmp_path: Path) -> None:
    """A regression guard on the actual symptom: file size, not row semantics."""
    p = _poller(tmp_path)
    for i in range(20):
        (tmp_path / "pkg" / f"g{i}.uasset").write_bytes(os.urandom(64))

    p.poll_once()
    for _ in range(100):
        p.poll_once()
    p.stop()

    size = (tmp_path / "writes.csv").stat().st_size
    # 100 idle cycles over 20 files previously produced 2000 extra rows
    assert size < 4096, f"CSV grew to {size} bytes over 100 idle cycles"