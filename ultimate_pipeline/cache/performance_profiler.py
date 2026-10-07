#!/usr/bin/env python3
"""Performance profiling harness for PERFORMANCE_BASELINE.json."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


@dataclass
class StageMetrics:
    """Metrics for a single pipeline stage."""
    stage: str
    wall_seconds: float
    cpu_seconds: float
    peak_ram_mb: float
    read_mb: float
    write_mb: float
    cache_hit: bool
    cache_miss: bool
    input_sha256: str = ""
    output_sha256: str = ""
    cache_key: str = ""
    dependencies: dict[str, str] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class PerformanceBaseline:
    """Complete performance baseline for a pipeline run."""
    schema: str = "performance_baseline/v1"
    run_id: str = ""
    generated_at_utc: str = ""
    git_commit: str = ""
    stages: list[StageMetrics] = field(default_factory=list)
    total_wall_seconds: float = 0.0
    total_cpu_seconds: float = 0.0
    peak_ram_mb: float = 0.0
    total_read_mb: float = 0.0
    total_write_mb: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    stage_times_pct: dict[str, float] = field(default_factory=dict)
    bottlenecks: list[dict] = field(default_factory=list)

    def add_stage(self, metrics: StageMetrics):
        self.stages.append(metrics)
        self.total_wall_seconds += metrics.wall_seconds
        self.total_cpu_seconds += metrics.cpu_seconds
        self.peak_ram_mb = max(self.peak_ram_mb, metrics.peak_ram_mb)
        self.total_read_mb += metrics.read_mb
        self.total_write_mb += metrics.write_mb
        if metrics.cache_hit:
            self.cache_hits += 1
        if metrics.cache_miss:
            self.cache_misses += 1

    def finalize(self):
        """Compute derived metrics after all stages recorded."""
        if self.total_wall_seconds > 0:
            for stage in self.stages:
                pct = (stage.wall_seconds / self.total_wall_seconds) * 100
                self.stage_times_pct[stage.stage] = round(pct, 2)

            # Identify bottlenecks (>10% of wall time)
            for stage in self.stages:
                pct = self.stage_times_pct.get(stage.stage, 0)
                if pct >= 10.0:
                    self.bottlenecks.append({
                        "stage": stage.stage,
                        "wall_pct": pct,
                        "wall_seconds": stage.wall_seconds,
                        "cpu_seconds": stage.cpu_seconds,
                        "peak_ram_mb": stage.peak_ram_mb,
                        "candidate_for_optimization": pct >= 25.0,
                    })

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "generated_at_utc": self.generated_at_utc,
            "git_commit": self.git_commit,
            "total_wall_seconds": round(self.total_wall_seconds, 3),
            "total_cpu_seconds": round(self.total_cpu_seconds, 3),
            "peak_ram_mb": round(self.peak_ram_mb, 2),
            "total_read_mb": round(self.total_read_mb, 2),
            "total_write_mb": round(self.total_write_mb, 2),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": round(self.cache_hits / (self.cache_hits + self.cache_misses), 4)
            if (self.cache_hits + self.cache_misses) > 0 else 0.0,
            "stage_times_pct": self.stage_times_pct,
            "bottlenecks": self.bottlenecks,
            "stages": [asdict(s) for s in self.stages],
        }


class PerformanceProfiler:
    """Context-manager based profiler for pipeline stages."""

    def __init__(self, run_id: str, git_commit: str = "", output_path: Optional[Path] = None):
        self.run_id = run_id
        self.git_commit = git_commit or self._get_git_commit()
        self.output_path = output_path
        self.baseline = PerformanceBaseline(
            run_id=run_id,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            git_commit=self.git_commit,
        )
        self._current_stage: Optional[StageMetrics] = None
        self._stage_start_wall: float = 0
        self._stage_start_cpu: float = 0
        self._stage_peak_ram: float = 0
        self._read_bytes: int = 0
        self._write_bytes: int = 0

    @staticmethod
    def _get_git_commit() -> str:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2]
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    @staticmethod
    def _get_memory_mb() -> float:
        if HAS_PSUTIL:
            try:
                return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
            except Exception:
                return 0.0
        return 0.0

    @contextmanager
    def stage(
        self,
        stage_name: str,
        input_sha256: str = "",
        output_sha256: str = "",
        cache_key: str = "",
        cache_hit: bool = False,
        dependencies: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ):
        """Profile a single pipeline stage."""
        self._current_stage = StageMetrics(
            stage=stage_name,
            wall_seconds=0,
            cpu_seconds=0,
            peak_ram_mb=0,
            read_mb=0,
            write_mb=0,
            cache_hit=cache_hit,
            cache_miss=not cache_hit,
            input_sha256=input_sha256,
            output_sha256=output_sha256,
            cache_key=cache_key,
            dependencies=dependencies or {},
            started_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )
        self._stage_start_wall = time.perf_counter()
        self._stage_start_cpu = time.process_time()
        self._stage_peak_ram = self._get_memory_mb()
        self._read_bytes = 0
        self._write_bytes = 0

        try:
            yield
        finally:
            end_wall = time.perf_counter()
            end_cpu = time.process_time()
            end_mem = self._get_memory_mb()

            self._current_stage.wall_seconds = round(end_wall - self._stage_start_wall, 3)
            self._current_stage.cpu_seconds = round(end_cpu - self._stage_start_cpu, 3)
            self._current_stage.peak_ram_mb = round(max(self._stage_peak_ram, end_mem), 2)
            self._current_stage.read_mb = round(self._read_bytes / (1024 * 1024), 2)
            self._current_stage.write_mb = round(self._write_bytes / (1024 * 1024), 2)
            self._current_stage.finished_at = datetime.now(timezone.utc).isoformat()

            self.baseline.add_stage(self._current_stage)
            self._current_stage = None

    def record_read(self, bytes_count: int):
        """Record bytes read."""
        self._read_bytes += bytes_count

    def record_write(self, bytes_count: int):
        """Record bytes written."""
        self._write_bytes += bytes_count

    def save(self, path: Optional[Path] = None) -> Path:
        """Save baseline to JSON."""
        self.baseline.finalize()
        out_path = path or self.output_path or Path(f"reports/opencode_hardening/PERFORMANCE_BASELINE_{self.run_id}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(self.baseline.to_dict(), indent=2) + "\n", encoding="utf-8")
        return out_path


# Convenience function for quick profiling
@contextmanager
def profile_stage(
    profiler: PerformanceProfiler,
    stage_name: str,
    **kwargs
):
    """Profile a stage with automatic recording."""
    with profiler.stage(stage_name, **kwargs):
        yield profiler


# Global profiler
_default_profiler: Optional[PerformanceProfiler] = None


def get_profiler(run_id: str, **kwargs) -> PerformanceProfiler:
    """Get or create global profiler."""
    global _default_profiler
    if _default_profiler is None:
        _default_profiler = PerformanceProfiler(run_id, **kwargs)
    return _default_profiler


def set_profiler(profiler: PerformanceProfiler) -> None:
    global _default_profiler
    _default_profiler = profiler