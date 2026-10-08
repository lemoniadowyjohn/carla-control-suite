#!/usr/bin/env python3
"""
Unit tests for package_write_poller.py using synthetic/fake data.

Tests the poller's ability to detect new/changed files without launching a real cook.
"""

import csv
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tools.cook_diagnostics.package_write_poller import PackageWritePoller, FileRecord


class TestPackageWritePoller:
    """Tests for PackageWritePoller."""

    def setup_method(self):
        """Create temporary directories for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.package_dir = Path(self.temp_dir) / "package"
        self.package_dir.mkdir()
        self.output_csv = Path(self.temp_dir) / "poller_output.csv"

    def teardown_method(self):
        """Clean up temporary directories."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_poll_once_detects_new_files(self):
        """Test that poll_once detects new files and logs them as 'new'."""
        # Create a file
        test_file = self.package_dir / "test.uasset"
        test_file.write_text("hello world")
        
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,  # Fast for testing
        )
        
        # Run one poll cycle
        results = poller.poll_once()
        
        # Should detect 1 new file
        assert len(results) == 1
        record = results["test.uasset"]
        assert record.status == "new"
        assert record.size == len("hello world")
        assert record.sha256 != "ERROR"
        
        # Check CSV output
        assert self.output_csv.exists()
        with open(self.output_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["file_path"] == "test.uasset"
        assert rows[0]["status"] == "new"
        assert rows[0]["cycle"] == "1"
        
        poller.stop()

    def test_poll_once_detects_changed_files(self):
        """Test that poll_once detects changed files and logs them as 'changed'."""
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,
        )
        
        # Create initial file
        test_file = self.package_dir / "test.uasset"
        test_file.write_text("version 1")
        
        # First poll - should be 'new'
        results1 = poller.poll_once()
        assert results1["test.uasset"].status == "new"
        
        # Modify file
        time.sleep(0.01)  # Ensure mtime changes
        test_file.write_text("version 2 - modified content")
        
        # Second poll - should be 'changed'
        results2 = poller.poll_once()
        assert results2["test.uasset"].status == "changed"
        assert results2["test.uasset"].sha256 != results1["test.uasset"].sha256
        
        # Check CSV has both entries
        with open(self.output_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["status"] == "new"
        assert rows[1]["status"] == "changed"
        assert rows[1]["cycle"] == "2"
        
        poller.stop()

    def test_poll_once_unchanged_files(self):
        """Test that unchanged files are logged as 'unchanged'."""
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,
        )
        
        test_file = self.package_dir / "test.uasset"
        test_file.write_text("stable content")
        
        # First poll
        poller.poll_once()
        
        # Second poll without changes
        poller.poll_once()
        
        # Check CSV
        with open(self.output_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["status"] == "new"
        assert rows[1]["status"] == "unchanged"
        
        poller.stop()

    def test_subdirectory_files(self):
        """Test that files in subdirectories are tracked with relative paths."""
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,
        )
        
        subdir = self.package_dir / "Content" / "Maps"
        subdir.mkdir(parents=True)
        test_file = subdir / "map.umap"
        test_file.write_text("map data")
        
        results = poller.poll_once()
        
        assert "Content/Maps/map.umap" in results
        record = results["Content/Maps/map.umap"]
        assert record.status == "new"
        assert record.path == "Content/Maps/map.umap"
        
        poller.stop()

    def test_empty_directory(self):
        """Test polling an empty directory."""
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,
        )
        
        results = poller.poll_once()
        
        assert len(results) == 0
        assert poller.get_cycle_count() == 1
        
        # CSV should only have header
        with open(self.output_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 0
        
        poller.stop()

    def test_nonexistent_directory(self):
        """Test polling a non-existent directory."""
        nonexistent = Path(self.temp_dir) / "nonexistent"
        poller = PackageWritePoller(
            package_dir=nonexistent,
            output_csv=self.output_csv,
            interval_sec=0.01,
        )
        
        results = poller.poll_once()
        
        assert len(results) == 0
        poller.stop()

    def test_cycle_count_increments(self):
        """Test that cycle count increments correctly."""
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,
        )
        
        assert poller.get_cycle_count() == 0
        
        poller.poll_once()
        assert poller.get_cycle_count() == 1
        
        poller.poll_once()
        assert poller.get_cycle_count() == 2
        
        poller.stop()

    def test_stop_closes_csv(self):
        """Test that stop() properly closes the CSV file."""
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,
        )
        
        poller.poll_once()
        poller.stop()
        
        # Should be able to read the file after stop
        with open(self.output_csv, "r", encoding="utf-8") as f:
            content = f.read()
        assert "timestamp" in content  # Header present

    def test_follow_symlinks_false_by_default(self):
        """Test that symlinks are not followed by default."""
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,
            follow_symlinks=False,
        )
        
        # Create a real file and a symlink to it
        real_file = self.package_dir / "real.txt"
        real_file.write_text("real content")
        
        link_file = self.package_dir / "link.txt"
        try:
            link_file.symlink_to(real_file)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform")
        
        results = poller.poll_once()
        
        # Only real file should be detected
        assert "real.txt" in results
        assert "link.txt" not in results
        
        poller.stop()

    def test_follow_symlinks_true(self):
        """Test that symlinks are followed when enabled."""
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,
            follow_symlinks=True,
        )
        
        real_file = self.package_dir / "real.txt"
        real_file.write_text("real content")
        
        link_file = self.package_dir / "link.txt"
        try:
            link_file.symlink_to(real_file)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform")
        
        results = poller.poll_once()
        
        # Both should be detected (same content, different paths)
        assert "real.txt" in results
        assert "link.txt" in results
        
        poller.stop()

    def test_csv_format_correct(self):
        """Test CSV has correct columns and data types."""
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,
        )
        
        test_file = self.package_dir / "test.uasset"
        test_file.write_bytes(b"binary data")
        
        poller.poll_once()
        poller.stop()
        
        with open(self.output_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 1
        row = rows[0]
        
        # Check all required columns
        required_cols = ["timestamp", "cycle", "file_path", "size_bytes", "mtime", "sha256", "status"]
        for col in required_cols:
            assert col in row
        
        # Check data types
        assert row["cycle"].isdigit()
        assert row["size_bytes"].isdigit()
        assert float(row["mtime"]) > 0
        assert len(row["sha256"]) == 64  # SHA256 hex
        assert row["status"] in ("new", "changed", "unchanged")


class TestPackageWritePollerIntegration:
    """Integration-style tests with multiple cycles."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.package_dir = Path(self.temp_dir) / "package"
        self.package_dir.mkdir()
        self.output_csv = Path(self.temp_dir) / "poller_output.csv"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multiple_cycles_accumulate(self):
        """Test multiple poll cycles accumulate correctly in CSV."""
        poller = PackageWritePoller(
            package_dir=self.package_dir,
            output_csv=self.output_csv,
            interval_sec=0.01,
        )
        
        # Cycle 1: add file A
        (self.package_dir / "a.txt").write_text("a")
        poller.poll_once()
        
        # Cycle 2: add file B
        (self.package_dir / "b.txt").write_text("b")
        poller.poll_once()
        
        # Cycle 3: modify file A
        time.sleep(0.01)
        (self.package_dir / "a.txt").write_text("a modified")
        poller.poll_once()
        
        poller.stop()
        
        # Check all cycles recorded - each cycle writes ALL current files
        # Cycle 1: a(new) = 1 row
        # Cycle 2: a(unchanged), b(new) = 2 rows
        # Cycle 3: a(changed), b(unchanged) = 2 rows
        # Total: 5 rows
        with open(self.output_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 5  # a(new), a(unchanged), b(new), a(changed), b(unchanged)
        
        # Verify cycle numbers
        cycles = [int(r["cycle"]) for r in rows]
        assert cycles == [1, 2, 2, 3, 3]
        
        # Verify statuses
        statuses = [r["status"] for r in rows]
        assert statuses == ["new", "unchanged", "new", "changed", "unchanged"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])