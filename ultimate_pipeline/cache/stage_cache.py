#!/usr/bin/env python3
"""Content-addressed stage cache with SHA256 keys.

Provides fine-grained caching for pipeline stages with dependency-aware invalidation.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class CacheEntry:
    """A single cache entry."""
    key: str
    stage: str
    input_sha256: str
    output_sha256: str
    output_path: str
    created_at: str
    wall_seconds: float
    cpu_seconds: float
    peak_ram_mb: float
    read_mb: float
    write_mb: float
    dependencies: dict[str, str] = field(default_factory=dict)  # dep_name -> dep_sha


@dataclass
class StageResult:
    """Result of a cached or executed stage."""
    hit: bool
    output_path: str
    output_sha256: str
    wall_seconds: float
    cpu_seconds: float
    peak_ram_mb: float
    metadata: dict = field(default_factory=dict)


class ContentAddressedCache:
    """Content-addressed cache with SQLite index and filesystem storage."""

    def __init__(self, cache_root: Path, run_id: str):
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.db_path = self.cache_root / f"cache_index_{run_id}.sqlite"
        self.blob_root = self.cache_root / "blobs"
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self._init_db()

        # Run-scoped hash registry
        self.hash_registry: dict[str, str] = {}

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    output_sha256 TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    wall_seconds REAL NOT NULL,
                    cpu_seconds REAL NOT NULL,
                    peak_ram_mb REAL NOT NULL,
                    read_mb REAL NOT NULL,
                    write_mb REAL NOT NULL,
                    dependencies TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stage ON cache_entries(stage)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_input_sha ON cache_entries(input_sha256)")

    def _sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _compute_key(self, stage: str, input_sha256: str, config_sha: str = "") -> str:
        """Compute content-addressed cache key."""
        parts = [stage, input_sha256]
        if config_sha:
            parts.append(config_sha)
        combined = "|".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:32]

    def register_hash(self, name: str, sha256: str) -> None:
        """Register a hash in the run-scoped registry."""
        self.hash_registry[name] = sha256

    def get_hash(self, name: str) -> Optional[str]:
        """Get a hash from the run-scoped registry."""
        return self.hash_registry.get(name)

    @contextmanager
    def _measure(self) -> tuple[Callable[[], float], Callable[[], float]]:
        """Context manager to measure wall and CPU time."""
        start_wall = time.perf_counter()
        start_cpu = time.process_time()
        yield lambda: time.perf_counter() - start_wall, lambda: time.process_time() - start_cpu

    def _get_memory_mb(self) -> float:
        """Get current process memory in MB (cross-platform best effort)."""
        try:
            import psutil
            return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        except ImportError:
            return 0.0

    def lookup(self, stage: str, input_sha256: str, config_sha: str = "") -> Optional[CacheEntry]:
        """Look up a cache entry by content address."""
        key = self._compute_key(stage, input_sha256, config_sha)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM cache_entries WHERE key = ?", (key,)
            ).fetchone()
            if row:
                return CacheEntry(
                    key=row["key"],
                    stage=row["stage"],
                    input_sha256=row["input_sha256"],
                    output_sha256=row["output_sha256"],
                    output_path=row["output_path"],
                    created_at=row["created_at"],
                    wall_seconds=row["wall_seconds"],
                    cpu_seconds=row["cpu_seconds"],
                    peak_ram_mb=row["peak_ram_mb"],
                    read_mb=row["read_mb"],
                    write_mb=row["write_mb"],
                    dependencies=json.loads(row["dependencies"]),
                )
        return None

    def store(
        self,
        stage: str,
        input_sha256: str,
        output_path: Path,
        wall_seconds: float,
        cpu_seconds: float,
        peak_ram_mb: float,
        read_mb: float,
        write_mb: float,
        dependencies: dict[str, str],
        config_sha: str = "",
    ) -> CacheEntry:
        """Store a new cache entry."""
        output_path = Path(output_path)
        output_sha = self._sha256(output_path)

        key = self._compute_key(stage, input_sha256, config_sha)

        # Copy output to blob storage (content-addressed)
        blob_dir = self.blob_root / key[:2] / key[2:4]
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / key
        shutil.copy2(output_path, blob_path)

        entry = CacheEntry(
            key=key,
            stage=stage,
            input_sha256=input_sha256,
            output_sha256=output_sha,
            output_path=str(blob_path),
            created_at=datetime.now(timezone.utc).isoformat(),
            wall_seconds=wall_seconds,
            cpu_seconds=cpu_seconds,
            peak_ram_mb=peak_ram_mb,
            read_mb=read_mb,
            write_mb=write_mb,
            dependencies=dependencies,
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO cache_entries
                (key, stage, input_sha256, output_sha256, output_path, created_at,
                 wall_seconds, cpu_seconds, peak_ram_mb, read_mb, write_mb, dependencies)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.key,
                    entry.stage,
                    entry.input_sha256,
                    entry.output_sha256,
                    entry.output_path,
                    entry.created_at,
                    entry.wall_seconds,
                    entry.cpu_seconds,
                    entry.peak_ram_mb,
                    entry.read_mb,
                    entry.write_mb,
                    json.dumps(entry.dependencies),
                ),
            )

        return entry

    def invalidate(self, input_sha256: str) -> int:
        """Invalidate all entries depending on a given input SHA."""
        with sqlite3.connect(self.db_path) as conn:
            # Find entries with this input_sha256
            rows = conn.execute(
                "SELECT key FROM cache_entries WHERE input_sha256 = ?", (input_sha256,)
            ).fetchall()
            count = 0
            for (key,) in rows:
                # Remove blob
                blob_dir = self.blob_root / key[:2] / key[2:4]
                blob_path = blob_dir / key
                if blob_path.exists():
                    blob_path.unlink()
                    try:
                        blob_dir.rmdir()
                        blob_dir.parent.rmdir()
                    except OSError:
                        pass
                count += 1
            # Delete from index
            conn.execute("DELETE FROM cache_entries WHERE input_sha256 = ?", (input_sha256,))
            return count

    def invalidate_by_stage(self, stage: str) -> int:
        """Invalidate all entries for a given stage."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT key FROM cache_entries WHERE stage = ?", (stage,)).fetchall()
            count = 0
            for (key,) in rows:
                blob_dir = self.blob_root / key[:2] / key[2:4]
                blob_path = blob_dir / key
                if blob_path.exists():
                    blob_path.unlink()
                    try:
                        blob_dir.rmdir()
                        blob_dir.parent.rmdir()
                    except OSError:
                        pass
                count += 1
            conn.execute("DELETE FROM cache_entries WHERE stage = ?", (stage,))
            return count

    def stats(self) -> dict:
        """Get cache statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0]
            by_stage = dict(conn.execute(
                "SELECT stage, COUNT(*) FROM cache_entries GROUP BY stage"
            ).fetchall())
            total_wall = conn.execute(
                "SELECT SUM(wall_seconds) FROM cache_entries"
            ).fetchone()[0] or 0
            return {
                "total_entries": total,
                "by_stage": by_stage,
                "total_wall_seconds_saved": total_wall,
            }


def cached_stage(
    cache: ContentAddressedCache,
    stage: str,
    config_sha: str = "",
) -> Callable:
    """Decorator to cache a stage function with content addressing."""
    def decorator(func: Callable) -> Callable:
        def wrapper(input_path: Path, output_path: Path, *args, **kwargs) -> StageResult:
            input_sha = cache._sha256(input_path)

            # Build dependency map from registered hashes
            deps = {k: v for k, v in cache.hash_registry.items()}

            entry = cache.lookup(stage, input_sha, config_sha)
            if entry and Path(entry.output_path).exists():
                # Verify output integrity
                if cache._sha256(Path(entry.output_path)) == entry.output_sha256:
                    shutil.copy2(entry.output_path, output_path)
                    return StageResult(
                        hit=True,
                        output_path=str(output_path),
                        output_sha256=entry.output_sha256,
                        wall_seconds=0.0,
                        cpu_seconds=0.0,
                        peak_ram_mb=0.0,
                        metadata={"cache_hit": True, "entry": entry.__dict__},
                    )

            # Cache miss - execute stage
            start_wall = time.perf_counter()
            start_cpu = time.process_time()
            start_mem = cache._get_memory_mb()
            peak_mem = start_mem

            # Track I/O
            read_bytes = 0
            write_bytes = 0

            def track_read(n):
                nonlocal read_bytes
                read_bytes += n

            def track_write(n):
                nonlocal write_bytes
                write_bytes += n

            try:
                result = func(input_path, output_path, *args, **kwargs)
            except Exception:
                raise

            end_wall = time.perf_counter()
            end_cpu = time.process_time()
            end_mem = cache._get_memory_mb()
            peak_mem = max(peak_mem, end_mem)

            entry = cache.store(
                stage=stage,
                input_sha256=input_sha,
                output_path=output_path,
                wall_seconds=end_wall - start_wall,
                cpu_seconds=end_cpu - start_cpu,
                peak_ram_mb=peak_mem,
                read_mb=read_bytes / (1024 * 1024),
                write_mb=write_bytes / (1024 * 1024),
                dependencies=deps,
                config_sha=config_sha,
            )

            return StageResult(
                hit=False,
                output_path=str(output_path),
                output_sha256=entry.output_sha256,
                wall_seconds=entry.wall_seconds,
                cpu_seconds=entry.cpu_seconds,
                peak_ram_mb=entry.peak_ram_mb,
                metadata={"cache_hit": False, "entry": entry.__dict__},
            )
        return wrapper
    return decorator


# Global cache instance for easy access
_default_cache: Optional[ContentAddressedCache] = None


def get_default_cache(cache_root: Optional[Path] = None, run_id: Optional[str] = None) -> ContentAddressedCache:
    """Get or create the global default cache."""
    global _default_cache
    if _default_cache is None:
        if cache_root is None:
            cache_root = Path(os.environ.get("UP_CACHE_ROOT", Path.cwd() / ".cache"))
        if run_id is None:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _default_cache = ContentAddressedCache(cache_root, run_id)
    return _default_cache


def set_default_cache(cache: ContentAddressedCache) -> None:
    """Set the global default cache."""
    global _default_cache
    _default_cache = cache