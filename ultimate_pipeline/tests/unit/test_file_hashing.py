import pytest
import tempfile
import os
from pathlib import Path
from ultimate_pipeline.utils.file_hashing import (
    sha256_file,
    md5_file,
    hash_file,
    safe_sha256_file,
    safe_md5_file,
    DEFAULT_CHUNK_SIZE,
)


class TestSha256File:
    def test_basic_hash(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = f.name
        try:
            h = sha256_file(path)
            assert len(h) == 64
            # Known SHA-256 of "hello world"
            assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            h = sha256_file(path)
            assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        finally:
            os.unlink(path)

    def test_large_file_streaming(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            # Write 10MB of data
            f.write(b"x" * (10 * 1024 * 1024))
            path = f.name
        try:
            h = sha256_file(path)
            assert len(h) == 64
            # Verify deterministic
            assert sha256_file(path) == h
        finally:
            os.unlink(path)

    def test_custom_chunk_size(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test data")
            path = f.name
        try:
            h1 = sha256_file(path, chunk_size=1)
            h2 = sha256_file(path, chunk_size=1024)
            assert h1 == h2
        finally:
            os.unlink(path)

    def test_pathlib_path(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"pathlib test")
            path = Path(f.name)
        try:
            h = sha256_file(path)
            assert len(h) == 64
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            sha256_file("/nonexistent/path/file.txt")


class TestMd5File:
    def test_basic_hash(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = f.name
        try:
            h = md5_file(path)
            assert len(h) == 32
            assert h == "5eb63bbbe01eeed093cb22bb8f5acdc3"
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            h = md5_file(path)
            assert h == "d41d8cd98f00b204e9800998ecf8427e"
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            md5_file("/nonexistent/path/file.txt")


class TestHashFile:
    def test_sha256_algorithm(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"algorithm test")
            path = f.name
        try:
            h = hash_file(path, algorithm="sha256")
            assert len(h) == 64
            assert h == sha256_file(path)
        finally:
            os.unlink(path)

    def test_md5_algorithm(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"algorithm test")
            path = f.name
        try:
            h = hash_file(path, algorithm="md5")
            assert len(h) == 32
            assert h == md5_file(path)
        finally:
            os.unlink(path)

    def test_sha1_algorithm(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"algorithm test")
            path = f.name
        try:
            h = hash_file(path, algorithm="sha1")
            assert len(h) == 40
        finally:
            os.unlink(path)

    def test_invalid_algorithm(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test")
            path = f.name
        try:
            with pytest.raises(ValueError):
                hash_file(path, algorithm="invalid_algo")
        finally:
            os.unlink(path)


class TestSafeSha256File:
    def test_existing_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"safe test")
            path = f.name
        try:
            h = safe_sha256_file(path)
            assert h == sha256_file(path)
        finally:
            os.unlink(path)

    def test_none_path(self):
        assert safe_sha256_file(None) is None

    def test_missing_file(self):
        assert safe_sha256_file("/nonexistent/file.txt") is None

    def test_pathlib_path(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"pathlib")
            path = Path(f.name)
        try:
            h = safe_sha256_file(path)
            assert h is not None
        finally:
            os.unlink(path)


class TestSafeMd5File:
    def test_existing_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"safe md5")
            path = f.name
        try:
            h = safe_md5_file(path)
            assert h == md5_file(path)
        finally:
            os.unlink(path)

    def test_none_path(self):
        assert safe_md5_file(None) is None

    def test_missing_file(self):
        assert safe_md5_file("/nonexistent/file.txt") is None


class TestDefaultChunkSize:
    def test_constant_value(self):
        assert DEFAULT_CHUNK_SIZE == 1024 * 1024


class TestFileHashingIntegration:
    def test_consistency_across_functions(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"integration test data")
            path = f.name
        try:
            assert safe_sha256_file(path) == sha256_file(path)
            assert safe_md5_file(path) == md5_file(path)
            assert hash_file(path, "sha256") == sha256_file(path)
            assert hash_file(path, "md5") == md5_file(path)
        finally:
            os.unlink(path)

    def test_different_files_different_hashes(self):
        with tempfile.NamedTemporaryFile(delete=False) as f1:
            f1.write(b"file 1")
            path1 = f1.name
        with tempfile.NamedTemporaryFile(delete=False) as f2:
            f2.write(b"file 2")
            path2 = f2.name
        try:
            assert sha256_file(path1) != sha256_file(path2)
            assert md5_file(path1) != md5_file(path2)
        finally:
            os.unlink(path1)
            os.unlink(path2)