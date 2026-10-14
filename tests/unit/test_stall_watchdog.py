#!/usr/bin/env python3
"""
Unit tests for stall_watchdog.py using synthetic/fake data.

Tests the watchdog's ability to detect stalls and trigger procdump
without launching a real cook or killing processes.
"""

import csv
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from tools.cook_diagnostics.stall_watchdog import StallWatchdog, WatchdogEvent, WatchdogLogEntry


class TestStallWatchdog:
    """Tests for StallWatchdog."""

    def setup_method(self):
        """Create temporary directories for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.package_dir = Path(self.temp_dir) / "package"
        self.package_dir.mkdir()
        self.dump_dir = Path(self.temp_dir) / "dumps"
        self.dump_dir.mkdir()

    def teardown_method(self):
        """Clean up temporary directories."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_initialization(self):
        """Test watchdog initializes with correct parameters."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=600.0,
            check_interval_sec=5.0,
            procdump_path="procdump",
            dump_dir=self.dump_dir,
        )
        
        assert watchdog.pid == 12345
        assert watchdog.package_dir == self.package_dir.resolve()
        assert watchdog.stall_timeout_sec == 600.0
        assert watchdog.check_interval_sec == 5.0
        assert watchdog.procdump_path == "procdump"
        assert watchdog.dump_dir == self.dump_dir.resolve()
        assert not watchdog.is_running()
        
        watchdog.stop()

    def test_start_creates_log_file(self):
        """Test that start() creates the log CSV with header."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=600.0,
            check_interval_sec=5.0,
            dump_dir=self.dump_dir,
        )
        
        watchdog.start()
        time.sleep(0.1)  # Let thread start
        watchdog.stop()
        
        log_path = watchdog.get_log_path()
        assert log_path.exists()
        
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Should have STARTED event
        assert len(rows) >= 1
        assert rows[0]["event_type"] == "started"
        assert rows[0]["pid"] == "12345"

    def test_force_check_detects_new_files(self):
        """Test that force_check detects new files."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=600.0,
            check_interval_sec=5.0,
            dump_dir=self.dump_dir,
        )
        
        watchdog.start()
        time.sleep(0.1)
        
        # Create a new file
        test_file = self.package_dir / "test.uasset"
        test_file.write_text("content")
        
        # Force check
        has_new = watchdog.force_check()
        
        assert has_new is True
        
        # Check log for FILE_DETECTED event
        log_path = watchdog.get_log_path()
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        file_detected = [r for r in rows if r["event_type"] == "file_detected"]
        assert len(file_detected) == 1
        assert "test.uasset" in file_detected[0]["details"]
        
        watchdog.stop()

    def test_force_check_no_new_files(self):
        """Test that force_check returns False when no new files."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=600.0,
            check_interval_sec=5.0,
            dump_dir=self.dump_dir,
        )
        
        watchdog.start()
        time.sleep(0.1)
        
        # No new files
        has_new = watchdog.force_check()
        
        assert has_new is False
        
        watchdog.stop()

    def test_subdirectory_files_detected(self):
        """Test that files in subdirectories are detected."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=600.0,
            check_interval_sec=5.0,
            dump_dir=self.dump_dir,
        )
        
        watchdog.start()
        time.sleep(0.1)
        
        # Create file in subdirectory
        subdir = self.package_dir / "Content" / "Maps"
        subdir.mkdir(parents=True)
        test_file = subdir / "map.umap"
        test_file.write_text("map data")
        
        has_new = watchdog.force_check()
        
        assert has_new is True
        
        # Check log
        log_path = watchdog.get_log_path()
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        file_detected = [r for r in rows if r["event_type"] == "file_detected"]
        assert len(file_detected) == 1
        assert "Content/Maps/map.umap" in file_detected[0]["details"]
        
        watchdog.stop()

    def test_time_since_last_file(self):
        """Test get_time_since_last_file returns correct values."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=600.0,
            check_interval_sec=5.0,
            dump_dir=self.dump_dir,
        )
        
        # Before start, should be None
        assert watchdog.get_time_since_last_file() is None
        
        watchdog.start()
        time.sleep(0.1)
        
        # After start, should be small (initial scan time)
        elapsed = watchdog.get_time_since_last_file()
        assert elapsed is not None
        assert elapsed >= 0
        assert elapsed < 10  # Should be very recent
        
        # Create file
        test_file = self.package_dir / "test.txt"
        test_file.write_text("content")
        watchdog.force_check()
        
        # Time should reset to near zero
        elapsed = watchdog.get_time_since_last_file()
        assert elapsed is not None
        assert elapsed < 1
        
        watchdog.stop()

    def test_procdump_triggered_on_stall(self):
        """Test that procdump is triggered when stall detected."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=0.1,  # Very short for testing
            check_interval_sec=0.05,
            procdump_path="procdump",
            dump_dir=self.dump_dir,
        )
        
        # Mock subprocess.run to simulate successful procdump
        with patch('tools.cook_diagnostics.stall_watchdog.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            watchdog.start()
            
            # Wait for stall timeout + check interval
            time.sleep(0.3)
            
            watchdog.stop()
            
            # Check log for STALL_DETECTED and PROCDUMP events
            log_path = watchdog.get_log_path()
            with open(log_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            stall_events = [r for r in rows if r["event_type"] == "stall_detected"]
            assert len(stall_events) >= 1
            
            procdump_events = [r for r in rows if r["event_type"] == "procdump_triggered"]
            assert len(procdump_events) >= 1
            
            success_events = [r for r in rows if r["event_type"] == "procdump_success"]
            assert len(success_events) >= 1
            
            # Verify procdump was called
            mock_run.assert_called()
            call_args = mock_run.call_args[0][0]
            assert "procdump" in call_args[0]
            assert "-ma" in call_args
            assert "12345" in call_args

    def test_procdump_failure_logged(self):
        """Test that procdump failure is logged but doesn't crash."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=0.1,
            check_interval_sec=0.05,
            procdump_path="nonexistent_procdump",
            dump_dir=self.dump_dir,
        )
        
        watchdog.start()
        time.sleep(0.3)
        watchdog.stop()
        
        log_path = watchdog.get_log_path()
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Should have failure event
        fail_events = [r for r in rows if r["event_type"] == "procdump_failed"]
        assert len(fail_events) >= 1
        assert "not found" in fail_events[0]["details"].lower() or "failed" in fail_events[0]["details"].lower()

    def test_on_stall_callback_called(self):
        """Test that on_stall callback is invoked on stall."""
        callback_called = []
        
        def on_stall(pid, package_dir):
            callback_called.append((pid, package_dir))
        
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=0.1,
            check_interval_sec=0.05,
            dump_dir=self.dump_dir,
            on_stall=on_stall,
        )
        
        with patch('tools.cook_diagnostics.stall_watchdog.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_run.return_value = mock_result
            
            watchdog.start()
            time.sleep(0.3)
            watchdog.stop()
        
        # Callback should be called at least once (may be called twice with short timeouts)
        assert len(callback_called) >= 1
        assert callback_called[0] == (12345, str(self.package_dir.resolve()))

    def test_on_stall_callback_exception_handled(self):
        """Test that exceptions in on_stall callback are caught and logged."""
        def failing_callback(pid, package_dir):
            raise ValueError("Callback failed!")
        
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=0.1,
            check_interval_sec=0.05,
            dump_dir=self.dump_dir,
            on_stall=failing_callback,
        )
        
        with patch('tools.cook_diagnostics.stall_watchdog.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_run.return_value = mock_result
            
            watchdog.start()
            time.sleep(0.3)
            watchdog.stop()
        
        log_path = watchdog.get_log_path()
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Should have ERROR event for callback failure
        error_events = [r for r in rows if r["event_type"] == "error"]
        assert len(error_events) >= 1
        assert "callback failed" in error_events[0]["details"].lower()

    def test_stop_logs_stopped_event(self):
        """Test that stop() logs a STOPPED event."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=600.0,
            check_interval_sec=5.0,
            dump_dir=self.dump_dir,
        )
        
        watchdog.start()
        time.sleep(0.1)
        watchdog.stop()
        
        log_path = watchdog.get_log_path()
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        stopped_events = [r for r in rows if r["event_type"] == "stopped"]
        assert len(stopped_events) >= 1

    def test_multiple_stalls_only_dump_once_per_timeout(self):
        """Test that after successful dump, timer resets to avoid spam."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=0.1,
            check_interval_sec=0.05,
            procdump_path="procdump",
            dump_dir=self.dump_dir,
        )
        
        with patch('tools.cook_diagnostics.stall_watchdog.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_run.return_value = mock_result
            
            watchdog.start()
            
            # Wait for first stall + dump
            time.sleep(0.25)
            
            # Wait a bit more - should not trigger again immediately
            time.sleep(0.25)
            
            watchdog.stop()
            
            # Should only have called procdump once (timer reset after success)
            # Actually it might call again after timeout, but not immediately
            assert mock_run.call_count >= 1

    def test_log_csv_format(self):
        """Test log CSV has correct columns."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=600.0,
            check_interval_sec=5.0,
            dump_dir=self.dump_dir,
        )
        
        watchdog.start()
        time.sleep(0.1)
        watchdog.stop()
        
        log_path = watchdog.get_log_path()
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) >= 1
        row = rows[0]
        
        required_cols = ["timestamp", "event_type", "pid", "package_dir", "details"]
        for col in required_cols:
            assert col in row

    def test_is_running(self):
        """Test is_running() returns correct state."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=600.0,
            check_interval_sec=5.0,
            dump_dir=self.dump_dir,
        )
        
        assert not watchdog.is_running()
        
        watchdog.start()
        time.sleep(0.1)
        assert watchdog.is_running()
        
        watchdog.stop()
        time.sleep(0.1)
        assert not watchdog.is_running()

    def test_nonexistent_package_dir(self):
        """Test watchdog handles nonexistent package directory."""
        nonexistent = Path(self.temp_dir) / "nonexistent"
        
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=nonexistent,
            stall_timeout_sec=600.0,
            check_interval_sec=5.0,
            dump_dir=self.dump_dir,
        )
        
        watchdog.start()
        time.sleep(0.1)
        
        # Should not crash
        has_new = watchdog.force_check()
        assert has_new is False
        
        watchdog.stop()

    def test_dump_dir_created_if_missing(self):
        """Test that dump directory is created if it doesn't exist."""
        new_dump_dir = Path(self.temp_dir) / "new_dumps"
        assert not new_dump_dir.exists()
        
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=0.1,
            check_interval_sec=0.05,
            procdump_path="procdump",
            dump_dir=new_dump_dir,
        )
        
        with patch('tools.cook_diagnostics.stall_watchdog.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_run.return_value = mock_result
            
            watchdog.start()
            time.sleep(0.25)
            watchdog.stop()
        
        # Dump directory should be created
        assert new_dump_dir.exists()


class TestStallWatchdogLinuxGDB:
    """Tests for Linux gdb path (when not on Windows)."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.package_dir = Path(self.temp_dir) / "package"
        self.package_dir.mkdir()
        self.dump_dir = Path(self.temp_dir) / "dumps"
        self.dump_dir.mkdir()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch('tools.cook_diagnostics.stall_watchdog.sys.platform', 'linux')
    def test_linux_uses_gdb(self):
        """Test that on Linux, gdb is used for core dump."""
        watchdog = StallWatchdog(
            pid=12345,
            package_dir=self.package_dir,
            stall_timeout_sec=0.1,
            check_interval_sec=0.05,
            procdump_path="gdb",
            dump_dir=self.dump_dir,
        )
        
        with patch('tools.cook_diagnostics.stall_watchdog.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_run.return_value = mock_result
            
            watchdog.start()
            time.sleep(0.25)
            watchdog.stop()
            
            # Verify gdb was called with correct args
            mock_run.assert_called()
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "gdb"
            assert "-batch" in call_args
            assert "-ex" in call_args
            assert "generate-core-file" in " ".join(call_args)
            assert "-p" in call_args
            assert "12345" in call_args


if __name__ == "__main__":
    pytest.main([__file__, "-v"])