#!/usr/bin/env python3
"""Fine-grained 20-tile cache with dependency-aware invalidation."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass
class TileCacheEntry:
    """Cache entry for a single tile."""
    tile_index: tuple[int, int]
    stage: str  # "osm2world", "blender", "roundtrip"
    input_sha256: str
    output_sha256: str
    output_path: str
    created_at: str
    wall_seconds: float
    cpu_seconds: float
    peak_ram_mb: float
    dependencies: dict[str, str]  # dep_name -> dep_sha


class TileCache:
    """Per-tile cache with dependency-aware invalidation."""

    def __init__(self, cache_root: Path, run_id: str):
        self.cache_root = Path(cache_root) / "tiles"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.db_path = self.cache_root / f"tile_cache_{run_id}.sqlite"
        self.blob_root = self.cache_root / "blobs"
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tile_cache (
                    tile_tx INTEGER NOT NULL,
                    tile_ty INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    output_sha256 TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    wall_seconds REAL NOT NULL,
                    cpu_seconds REAL NOT NULL,
                    peak_ram_mb REAL NOT NULL,
                    dependencies TEXT NOT NULL,
                    PRIMARY KEY (tile_tx, tile_ty, stage)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stage ON tile_cache(stage)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_input_sha ON tile_cache(input_sha256)")

    def _sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _make_key(self, tile_index: tuple[int, int], stage: str, input_sha: str) -> str:
        parts = [str(tile_index[0]), str(tile_index[1]), stage, input_sha]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]

    def lookup(self, tile_index: tuple[int, int], stage: str, input_sha: str) -> Optional[TileCacheEntry]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM tile_cache WHERE tile_tx=? AND tile_ty=? AND stage=? AND input_sha256=?",
                (tile_index[0], tile_index[1], stage, input_sha)
            ).fetchone()
            if row and Path(row["output_path"]).exists():
                if self._sha256(Path(row["output_path"])) == row["output_sha256"]:
                    return TileCacheEntry(
                        tile_index=(row["tile_tx"], row["tile_ty"]),
                        stage=row["stage"],
                        input_sha256=row["input_sha256"],
                        output_sha256=row["output_sha256"],
                        output_path=row["output_path"],
                        created_at=row["created_at"],
                        wall_seconds=row["wall_seconds"],
                        cpu_seconds=row["cpu_seconds"],
                        peak_ram_mb=row["peak_ram_mb"],
                        dependencies=json.loads(row["dependencies"]),
                    )
        return None

    def store(
        self,
        tile_index: tuple[int, int],
        stage: str,
        input_sha: str,
        output_path: Path,
        wall_seconds: float,
        cpu_seconds: float,
        peak_ram_mb: float,
        dependencies: dict[str, str],
    ) -> TileCacheEntry:
        output_sha = self._sha256(output_path)
        key = self._make_key(tile_index, stage, input_sha)

        # Store in blob storage
        blob_dir = self.blob_root / key[:2] / key[2:4]
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / key
        shutil.copy2(output_path, blob_path)

        entry = TileCacheEntry(
            tile_index=tile_index,
            stage=stage,
            input_sha256=input_sha,
            output_sha256=output_sha,
            output_path=str(blob_path),
            created_at=datetime.now(timezone.utc).isoformat(),
            wall_seconds=wall_seconds,
            cpu_seconds=cpu_seconds,
            peak_ram_mb=peak_ram_mb,
            dependencies=dependencies,
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tile_cache
                (tile_tx, tile_ty, stage, input_sha256, output_sha256, output_path,
                 created_at, wall_seconds, cpu_seconds, peak_ram_mb, dependencies)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.tile_index[0],
                    entry.tile_index[1],
                    entry.stage,
                    entry.input_sha256,
                    entry.output_sha256,
                    entry.output_path,
                    entry.created_at,
                    entry.wall_seconds,
                    entry.cpu_seconds,
                    entry.peak_ram_mb,
                    json.dumps(entry.dependencies),
                ),
            )

        return entry

    def invalidate_tile(self, tile_index: tuple[int, int]) -> int:
        """Invalidate all stages for a tile."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT output_path FROM tile_cache WHERE tile_tx=? AND tile_ty=?",
                (tile_index[0], tile_index[1])
            ).fetchall()
            count = 0
            for (path,) in rows:
                if Path(path).exists():
                    Path(path).unlink()
                count += 1
            conn.execute(
                "DELETE FROM tile_cache WHERE tile_tx=? AND tile_ty=?",
                (tile_index[0], tile_index[1])
            )
            return count

    def invalidate_by_input(self, input_sha: str) -> int:
        """Invalidate all tiles that depend on a given input SHA."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT tile_tx, tile_ty, output_path FROM tile_cache WHERE input_sha256=?",
                (input_sha,)
            ).fetchall()
            count = 0
            for tx, ty, path in rows:
                if Path(path).exists():
                    Path(path).unlink()
                count += 1
            conn.execute("DELETE FROM tile_cache WHERE input_sha256=?", (input_sha,))
            return count

    def invalidate_stage(self, stage: str) -> int:
        """Invalidate a stage across all tiles."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT output_path FROM tile_cache WHERE stage=?", (stage,)
            ).fetchall()
            count = 0
            for (path,) in rows:
                if Path(path).exists():
                    Path(path).unlink()
                count += 1
            conn.execute("DELETE FROM tile_cache WHERE stage=?", (stage,))
            return count

    def get_tile_status(self, tile_index: tuple[int, int]) -> dict[str, Any]:
        """Get cache status for all stages of a tile."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tile_cache WHERE tile_tx=? AND tile_ty=?",
                (tile_index[0], tile_index[1])
            ).fetchall()
            return {row["stage"]: dict(row) for row in rows}

    def stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM tile_cache").fetchone()[0]
            by_stage = dict(conn.execute(
                "SELECT stage, COUNT(*) FROM tile_cache GROUP BY stage"
            ).fetchall())
            return {"total_entries": total, "by_stage": by_stage}


def compute_tile_cache_key(
    tile_index: tuple[int, int],
    stage: str,
    source_sha: str,
    frame_sha: str,
    osm2world_version: str,
    blender_version: str,
    config_sha: str,
) -> str:
    """Compute content-addressed key for a tile stage."""
    parts = [
        f"tx={tile_index[0]}",
        f"ty={tile_index[1]}",
        f"stage={stage}",
        f"source={source_sha[:16]}",
        f"frame={frame_sha[:16]}",
        f"osm2world={osm2world_version}",
        f"blender={blender_version}",
        f"config={config_sha[:16]}",
    ]
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()[:32]


@contextmanager
def tile_stage(
    tile_cache: TileCache,
    tile_index: tuple[int, int],
    stage: str,
    input_sha: str,
    output_path: Path,
    dependencies: dict[str, str],
):
    """Context manager for a tile stage with caching."""
    entry = tile_cache.lookup(tile_index, stage, input_sha)
    if entry and Path(entry.output_path).exists():
        # Verify and restore
        if tile_cache._sha256(Path(entry.output_path)) == entry.output_sha256:
            shutil.copy2(entry.output_path, output_path)
            yield {"hit": True, "entry": entry}
            return

    # Cache miss - execute stage
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    peak_ram = 0
    try:
        yield {"hit": False}
    finally:
        wall = time.perf_counter() - start_wall
        cpu = time.process_time() - start_cpu
        entry = tile_cache.store(
            tile_index=tile_index,
            stage=stage,
            input_sha=input_sha,
            output_path=output_path,
            wall_seconds=wall,
            cpu_seconds=cpu,
            peak_ram_mb=peak_ram,
            dependencies=dependencies,
        )


import time
from typing import Optional, Any