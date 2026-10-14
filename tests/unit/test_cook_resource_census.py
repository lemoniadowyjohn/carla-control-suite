#!/usr/bin/env python3
"""
Unit tests for cook_resource_census.py using synthetic/fake data.

Tests the census's ability to sample memory with separate committed/commit_limit counters.
Uses mocking to avoid requiring a real process.
"""

import csv
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from tools.cook_diagnostics.cook_resource_census import CookResourceCensus, MemorySample


class TestCookResourceCensus:
    """Tests for CookResourceCensus."""

    def setup_method(self):
        """Create temporary directory for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.output_csv = Path(self.temp_dir) / "census_output.csv"

    def teardown_method(self):
        """Clean up temporary directories."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sample_returns_memory_sample(self):
        """Test that sample() returns a MemorySample with correct fields."""
        with patch('tools.cook_diagnostics.cook_resource_census.psutil.Process') as mock_proc_class:
            # Setup mock process
            mock_proc = MagicMock()
            mock_proc_class.return_value = mock_proc
            
            # Mock memory_info
            mock_mem_info = MagicMock()
            mock_mem_info.private = 1024 * 1024 * 100  # 100 MB private bytes
            mock_mem_info.rss = 1024 * 1024 * 150      # 150 MB RSS
            mock_proc.memory_info.return_value = mock_mem_info
            
            # Mock virtual_memory for system commit limit
            with patch('tools.cook_diagnostics.cook_resource_census.psutil.virtual_memory') as mock_vm:
                mock_vm_obj = MagicMock()
                mock_vm_obj.total = 1024 * 1024 * 1024 * 16  # 16 GB
                mock_vm_obj.available = 1024 * 1024 * 1024 * 8  # 8 GB
                mock_vm.return_value = mock_vm_obj
                
                census = CookResourceCensus(
                    pid=12345,
                    output_csv=self.output_csv,
                    interval_sec=0.01,
                )
                
                sample = census.sample()
                
                assert sample is not None
                assert isinstance(sample, MemorySample)
                assert sample.pid == 12345
                assert sample.committed_bytes == 1024 * 1024 * 100
                assert sample.commit_limit == 1024 * 1024 * 1024 * 16
                assert sample.available_bytes == 1024 * 1024 * 1024 * 8
                assert sample.percent_used == pytest.approx((100 * 1024 * 1024) / (16 * 1024 * 1024 * 1024) * 100, rel=0.01)
                assert sample.cycle == 1
                
                census.stop()

    def test_separate_counters_not_double_read(self):
        """Test that committed_bytes and commit_limit are separate counters."""
        with patch('tools.cook_diagnostics.cook_resource_census.psutil.Process') as mock_proc_class:
            mock_proc = MagicMock()
            mock_proc_class.return_value = mock_proc
            
            mock_mem_info = MagicMock()
            mock_mem_info.private = 500 * 1024 * 1024  # 500 MB
            mock_proc.memory_info.return_value = mock_mem_info
            
            with patch('tools.cook_diagnostics.cook_resource_census.psutil.virtual_memory') as mock_vm:
                mock_vm_obj = MagicMock()
                mock_vm_obj.total = 32 * 1024 * 1024 * 1024  # 32 GB
                mock_vm_obj.available = 16 * 1024 * 1024 * 1024
                mock_vm.return_value = mock_vm_obj
                
                census = CookResourceCensus(
                    pid=12345,
                    output_csv=self.output_csv,
                    interval_sec=0.01,
                )
                
                sample1 = census.sample()
                sample2 = census.sample()
                
                # Both should have independent values
                assert sample1.committed_bytes == sample2.committed_bytes == 500 * 1024 * 1024
                assert sample1.commit_limit == sample2.commit_limit == 32 * 1024 * 1024 * 1024
                assert sample1.commit_limit != sample1.committed_bytes  # Different counters!
                assert sample2.commit_limit != sample2.committed_bytes
                
                # Cycles should increment
                assert sample1.cycle == 1
                assert sample2.cycle == 2
                
                census.stop()

    def test_process_gone_returns_none(self):
        """Test that sample() returns None when process no longer exists."""
        import psutil
        
        with patch('tools.cook_diagnostics.cook_resource_census.psutil.Process') as mock_proc_class:
            mock_proc_class.side_effect = psutil.NoSuchProcess(12345)
            
            census = CookResourceCensus(
                pid=12345,
                output_csv=self.output_csv,
                interval_sec=0.01,
            )
            
            sample = census.sample()
            
            assert sample is None
            assert census.get_cycle_count() == 1  # Cycle still increments
            
            census.stop()

    def test_access_denied_returns_none(self):
        """Test that sample() returns None on AccessDenied."""
        import psutil
        
        with patch('tools.cook_diagnostics.cook_resource_census.psutil.Process') as mock_proc_class:
            mock_proc_class.side_effect = psutil.AccessDenied(12345)
            
            census = CookResourceCensus(
                pid=12345,
                output_csv=self.output_csv,
                interval_sec=0.01,
            )
            
            sample = census.sample()
            
            assert sample is None
            census.stop()

    def test_csv_output_format(self):
        """Test CSV has correct columns and format."""
        with patch('tools.cook_diagnostics.cook_resource_census.psutil.Process') as mock_proc_class:
            mock_proc = MagicMock()
            mock_proc_class.return_value = mock_proc
            
            mock_mem_info = MagicMock()
            mock_mem_info.private = 256 * 1024 * 1024
            mock_proc.memory_info.return_value = mock_mem_info
            
            with patch('tools.cook_diagnostics.cook_resource_census.psutil.virtual_memory') as mock_vm:
                mock_vm_obj = MagicMock()
                mock_vm_obj.total = 8 * 1024 * 1024 * 1024
                mock_vm_obj.available = 4 * 1024 * 1024 * 1024
                mock_vm.return_value = mock_vm_obj
                
                census = CookResourceCensus(
                    pid=99999,
                    output_csv=self.output_csv,
                    interval_sec=0.01,
                )
                
                census.sample()
                census.stop()
                
                # Read CSV
                with open(self.output_csv, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                
                assert len(rows) == 1
                row = rows[0]
                
                # Check columns
                required_cols = ["timestamp", "cycle", "pid", "committed_bytes", 
                                "commit_limit", "available_bytes", "percent_used"]
                for col in required_cols:
                    assert col in row
                
                # Check values
                assert row["pid"] == "99999"
                assert row["cycle"] == "1"
                assert row["committed_bytes"] == str(256 * 1024 * 1024)
                assert row["commit_limit"] == str(8 * 1024 * 1024 * 1024)
                assert row["available_bytes"] == str(4 * 1024 * 1024 * 1024)
                assert float(row["percent_used"]) > 0

    def test_get_samples_returns_all(self):
        """Test that get_samples returns all collected samples."""
        with patch('tools.cook_diagnostics.cook_resource_census.psutil.Process') as mock_proc_class:
            mock_proc = MagicMock()
            mock_proc_class.return_value = mock_proc
            
            mock_mem_info = MagicMock()
            mock_mem_info.private = 100 * 1024 * 1024
            mock_proc.memory_info.return_value = mock_mem_info
            
            with patch('tools.cook_diagnostics.cook_resource_census.psutil.virtual_memory') as mock_vm:
                mock_vm_obj = MagicMock()
                mock_vm_obj.total = 16 * 1024 * 1024 * 1024
                mock_vm_obj.available = 8 * 1024 * 1024 * 1024
                mock_vm.return_value = mock_vm_obj
                
                census = CookResourceCensus(
                    pid=12345,
                    output_csv=self.output_csv,
                    interval_sec=0.01,
                )
                
                census.sample()
                census.sample()
                census.sample()
                
                samples = census.get_samples()
                
                assert len(samples) == 3
                assert all(isinstance(s, MemorySample) for s in samples)
                assert samples[0].cycle == 1
                assert samples[1].cycle == 2
                assert samples[2].cycle == 3
                
                census.stop()

    def test_get_latest_returns_most_recent(self):
        """Test that get_latest returns the most recent sample."""
        with patch('tools.cook_diagnostics.cook_resource_census.psutil.Process') as mock_proc_class:
            mock_proc = MagicMock()
            mock_proc_class.return_value = mock_proc
            
            mock_mem_info = MagicMock()
            mock_mem_info.private = 100 * 1024 * 1024
            mock_proc.memory_info.return_value = mock_mem_info
            
            with patch('tools.cook_diagnostics.cook_resource_census.psutil.virtual_memory') as mock_vm:
                mock_vm_obj = MagicMock()
                mock_vm_obj.total = 16 * 1024 * 1024 * 1024
                mock_vm_obj.available = 8 * 1024 * 1024 * 1024
                mock_vm.return_value = mock_vm_obj
                
                census = CookResourceCensus(
                    pid=12345,
                    output_csv=self.output_csv,
                    interval_sec=0.01,
                )
                
                assert census.get_latest() is None
                
                census.sample()
                latest1 = census.get_latest()
                assert latest1 is not None
                assert latest1.cycle == 1
                
                census.sample()
                latest2 = census.get_latest()
                assert latest2 is not None
                assert latest2.cycle == 2
                assert latest2 is not latest1  # Different object
                
                census.stop()

    def test_percent_used_calculation(self):
        """Test percent_used is calculated correctly."""
        with patch('tools.cook_diagnostics.cook_resource_census.psutil.Process') as mock_proc_class:
            mock_proc = MagicMock()
            mock_proc_class.return_value = mock_proc
            
            # 1 GB committed, 16 GB limit = 6.25%
            mock_mem_info = MagicMock()
            mock_mem_info.private = 1024 * 1024 * 1024
            mock_proc.memory_info.return_value = mock_mem_info
            
            with patch('tools.cook_diagnostics.cook_resource_census.psutil.virtual_memory') as mock_vm:
                mock_vm_obj = MagicMock()
                mock_vm_obj.total = 16 * 1024 * 1024 * 1024
                mock_vm_obj.available = 8 * 1024 * 1024 * 1024
                mock_vm.return_value = mock_vm_obj
                
                census = CookResourceCensus(
                    pid=12345,
                    output_csv=self.output_csv,
                    interval_sec=0.01,
                )
                
                sample = census.sample()
                
                expected_percent = (1024 * 1024 * 1024) / (16 * 1024 * 1024 * 1024) * 100
                assert sample.percent_used == pytest.approx(expected_percent, rel=0.001)
                
                census.stop()

    def test_zero_commit_limit_handled(self):
        """Test that zero commit_limit doesn't cause division by zero."""
        with patch('tools.cook_diagnostics.cook_resource_census.psutil.Process') as mock_proc_class:
            mock_proc = MagicMock()
            mock_proc_class.return_value = mock_proc
            
            mock_mem_info = MagicMock()
            mock_mem_info.private = 100 * 1024 * 1024
            mock_proc.memory_info.return_value = mock_mem_info
            
            with patch('tools.cook_diagnostics.cook_resource_census.psutil.virtual_memory') as mock_vm:
                mock_vm_obj = MagicMock()
                mock_vm_obj.total = 0  # Edge case: zero total
                mock_vm_obj.available = 0
                mock_vm.return_value = mock_vm_obj
                
                census = CookResourceCensus(
                    pid=12345,
                    output_csv=self.output_csv,
                    interval_sec=0.01,
                )
                
                sample = census.sample()
                
                assert sample.percent_used == 0.0
                
                census.stop()

    def test_rss_used_on_linux_no_private(self):
        """Test that RSS is used when private attribute not available (Linux)."""
        with patch('tools.cook_diagnostics.cook_resource_census.psutil.Process') as mock_proc_class:
            mock_proc = MagicMock()
            mock_proc_class.return_value = mock_proc
            
            # Simulate Linux: no 'private' attribute, only 'rss'
            mock_mem_info = MagicMock()
            del mock_mem_info.private  # Remove private attribute
            mock_mem_info.rss = 200 * 1024 * 1024
            mock_proc.memory_info.return_value = mock_mem_info
            
            with patch('tools.cook_diagnostics.cook_resource_census.psutil.virtual_memory') as mock_vm:
                mock_vm_obj = MagicMock()
                mock_vm_obj.total = 16 * 1024 * 1024 * 1024
                mock_vm_obj.available = 8 * 1024 * 1024 * 1024
                mock_vm.return_value = mock_vm_obj
                
                census = CookResourceCensus(
                    pid=12345,
                    output_csv=self.output_csv,
                    interval_sec=0.01,
                )
                
                sample = census.sample()
                
                # Should use RSS when private not available
                assert sample.committed_bytes == 200 * 1024 * 1024
                
                census.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])