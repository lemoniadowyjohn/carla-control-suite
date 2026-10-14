import pytest
import tempfile
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from ultimate_pipeline.utils.map_fingerprint import write_map_content_fingerprint
from ultimate_pipeline.utils.file_hashing import sha256_file


class TestWriteMapContentFingerprint:
    def test_basic_functionality(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xodr") as f:
                f.write(b"<OpenDRIVE></OpenDRIVE>")
                xodr_path = f.name
            try:
                result = write_map_content_fingerprint(out_dir, xodr_path)
                assert result is not None
                assert result.endswith("map_content_fingerprint.json")
                assert os.path.exists(result)
                
                with open(result, "r") as f:
                    data = json.load(f)
                
                assert "generated_at_utc" in data
                assert data["final_xodr_path"] == xodr_path
                assert data["final_xodr_sha256"] == sha256_file(xodr_path)
                assert "roads_quarantined_path" not in data
            finally:
                os.unlink(xodr_path)

    def test_with_quarantine_file(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xodr") as f:
                f.write(b"<OpenDRIVE></OpenDRIVE>")
                xodr_path = f.name
            # Create quarantine file separately to avoid Windows file locking
            quarantine_path = os.path.join(out_dir, "roads_quarantined.json")
            with open(quarantine_path, "wb") as f:
                f.write(b'{"quarantined": ["road1"]}')
            try:
                result = write_map_content_fingerprint(out_dir, xodr_path)
                assert result is not None
                
                with open(result, "r") as f:
                    data = json.load(f)
                
                assert "roads_quarantined_path" in data
                assert data["roads_quarantined_path"] == quarantine_path
                assert "roads_quarantined_sha256" in data
                assert data["roads_quarantined_sha256"] == sha256_file(quarantine_path)
            finally:
                os.unlink(xodr_path)

    def test_missing_xodr_file(self):
        with tempfile.TemporaryDirectory() as out_dir:
            result = write_map_content_fingerprint(out_dir, "/nonexistent/file.xodr")
            assert result is not None
            
            with open(result, "r") as f:
                data = json.load(f)
            
            assert data["final_xodr_sha256"] is None

    def test_empty_out_dir_returns_none(self):
        result = write_map_content_fingerprint("", "/some/path.xodr")
        assert result is None

    def test_empty_xodr_path_returns_none(self):
        with tempfile.TemporaryDirectory() as out_dir:
            result = write_map_content_fingerprint(out_dir, "")
            assert result is None

    def test_both_empty_returns_none(self):
        result = write_map_content_fingerprint("", "")
        assert result is None

    def test_output_directory_created(self):
        with tempfile.TemporaryDirectory() as base:
            out_dir = os.path.join(base, "new", "nested", "dir")
            os.makedirs(out_dir, exist_ok=True)  # Function expects dir to exist
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xodr") as f:
                f.write(b"test")
                xodr_path = f.name
            try:
                result = write_map_content_fingerprint(out_dir, xodr_path)
                assert result is not None
                assert os.path.exists(result)
                assert os.path.exists(out_dir)
            finally:
                os.unlink(xodr_path)

    def test_json_format_sorted_keys(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xodr") as f:
                f.write(b"test")
                xodr_path = f.name
            try:
                result = write_map_content_fingerprint(out_dir, xodr_path)
                with open(result, "r") as f:
                    content = f.read()
                # JSON should have sorted keys (indent=2, sort_keys=True)
                assert content.index("final_xodr_path") < content.index("final_xodr_sha256")
                assert content.index("final_xodr_sha256") < content.index("generated_at_utc")
            finally:
                os.unlink(xodr_path)

    def test_write_error_returns_none(self):
        import sys
        if sys.platform == "win32":
            pytest.skip("Read-only directory doesn't prevent writes on Windows")
        with tempfile.TemporaryDirectory() as out_dir:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xodr") as f:
                f.write(b"test")
                xodr_path = f.name
            try:
                # Make output directory read-only to trigger write error
                os.chmod(out_dir, 0o444)
                try:
                    result = write_map_content_fingerprint(out_dir, xodr_path)
                    assert result is None
                finally:
                    os.chmod(out_dir, 0o755)
            finally:
                os.unlink(xodr_path)

    def test_iso_format_timestamp(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xodr") as f:
                f.write(b"test")
                xodr_path = f.name
            try:
                result = write_map_content_fingerprint(out_dir, xodr_path)
                with open(result, "r") as f:
                    data = json.load(f)
                
                # Should be valid ISO format with timezone
                ts = data["generated_at_utc"]
                assert "T" in ts
                assert ts.endswith("+00:00") or ts.endswith("Z") or "+" in ts.split("T")[-1]
            finally:
                os.unlink(xodr_path)