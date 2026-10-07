#!/usr/bin/env python3
"""Resource-aware parallelism for tile processing."""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, Future, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


@dataclass
class ResourceLimits:
    """Resource limits for a worker."""
    max_memory_mb: int = 4096
    max_vram_mb: int = 6144
    max_cpu_percent: float = 80.0
    max_workers: int = 1


@dataclass
class WorkerStats:
    """Runtime statistics for a worker."""
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_wall_time: float = 0.0
    peak_memory_mb: float = 0.0
    current_memory_mb: float = 0.0
    last_heartbeat: float = 0.0


class ResourceMonitor:
    """Monitor system resources and enforce limits."""

    def __init__(self, limits: Optional[ResourceLimits] = None):
        self.limits = limits or ResourceLimits()
        self._process = psutil.Process(os.getpid()) if HAS_PSUTIL else None
        self._gpu_available = self._check_gpu()

    def _check_gpu(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5
                )
                return result.returncode == 0
            except Exception:
                return False

    def get_memory_mb(self) -> float:
        """Get current process memory in MB."""
        if self._process:
            return self._process.memory_info().rss / (1024 * 1024)
        return 0.0

    def get_vram_mb(self) -> float:
        """Get current GPU VRAM usage in MB."""
        if not self._gpu_available:
            return 0.0
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return float(result.stdout.strip().split("\n")[0])
        except Exception:
            pass
        return 0.0

    def get_cpu_percent(self) -> float:
        """Get current CPU usage percent."""
        if self._process:
            return self._process.cpu_percent(interval=0.1)
        return 0.0

    def check_limits(self) -> tuple[bool, list[str]]:
        """Check if current usage exceeds limits. Returns (ok, warnings)."""
        warnings = []
        ok = True

        mem = self.get_memory_mb()
        if mem > self.limits.max_memory_mb:
            warnings.append(f"Memory {mem:.0f}MB exceeds limit {self.limits.max_memory_mb}MB")
            ok = False

        vram = self.get_vram_mb()
        if vram > self.limits.max_vram_mb:
            warnings.append(f"VRAM {vram:.0f}MB exceeds limit {self.limits.max_vram_mb}MB")
            ok = False

        cpu = self.get_cpu_percent()
        if cpu > self.limits.max_cpu_percent:
            warnings.append(f"CPU {cpu:.1f}% exceeds limit {self.limits.max_cpu_percent}%")
            ok = False

        return ok, warnings

    def wait_for_resources(self, timeout: float = 300.0, poll_interval: float = 5.0) -> bool:
        """Wait until resources are within limits."""
        start = time.time()
        while time.time() - start < timeout:
            ok, _ = self.check_limits()
            if ok:
                return True
            time.sleep(poll_interval)
        return False


class ResourceAwareExecutor:
    """Executor that respects resource limits."""

    def __init__(
        self,
        max_workers: int = 1,
        memory_limit_mb: int = 4096,
        vram_limit_mb: int = 6144,
        gpu_jobs: int = 1,
    ):
        self.max_workers = max_workers
        self.memory_limit_mb = memory_limit_mb
        self.vram_limit_mb = vram_limit_mb
        self.gpu_jobs = gpu_jobs

        self.monitor = ResourceMonitor(ResourceLimits(
            max_memory_mb=memory_limit_mb,
            max_vram_mb=vram_limit_mb,
            max_workers=max_workers,
        ))

        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: dict[Future, dict] = {}
        self._completed: list[Future] = []
        self._lock = threading.Lock()
        self._shutdown = False

    def __enter__(self):
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)

    def submit(
        self,
        fn: Callable,
        *args,
        requires_gpu: bool = False,
        memory_mb: int = 0,
        **kwargs,
    ) -> Future:
        """Submit a task with resource requirements."""
        if self._shutdown:
            raise RuntimeError("Executor is shutdown")

        # Check if we can schedule this task
        if requires_gpu:
            # Limit concurrent GPU jobs
            current_gpu = sum(
                1 for f, meta in self._futures.items()
                if not f.done() and meta.get("requires_gpu", False)
            )
            if current_gpu >= self.gpu_jobs:
                # Wait for a GPU slot
                while current_gpu >= self.gpu_jobs:
                    time.sleep(0.5)
                    current_gpu = sum(
                        1 for f, meta in self._futures.items()
                        if not f.done() and meta.get("requires_gpu", False)
                    )

        # Check memory
        if memory_mb > 0:
            current_mem = self.monitor.get_memory_mb()
            if current_mem + memory_mb > self.memory_limit_mb:
                # Wait for memory to free
                while self.monitor.get_memory_mb() + memory_mb > self.memory_limit_mb:
                    time.sleep(1.0)

        future = self._executor.submit(fn, *args, **kwargs)
        with self._lock:
            self._futures[future] = {
                "requires_gpu": requires_gpu,
                "memory_mb": memory_mb,
                "submitted_at": time.time(),
            }
        return future

    def as_completed(self, futures: list[Future], timeout: Optional[float] = None):
        """Yield futures as they complete."""
        return as_completed(futures, timeout=timeout)

    def wait_for_all(self, futures: list[Future], timeout: Optional[float] = None) -> list[Future]:
        """Wait for all futures to complete."""
        done, not_done = as_completed(futures, timeout=timeout)
        return list(done) + list(not_done)

    def shutdown(self, wait: bool = True):
        self._shutdown = True
        if self._executor:
            self._executor.shutdown(wait=wait)

    def get_stats(self) -> dict:
        with self._lock:
            running = sum(1 for f in self._futures if not f.done())
            completed = sum(1 for f in self._futures if f.done())
            return {
                "max_workers": self.max_workers,
                "running": running,
                "completed": completed,
                "memory_mb": self.monitor.get_memory_mb(),
                "vram_mb": self.monitor.get_vram_mb(),
                "cpu_percent": self.monitor.get_cpu_percent(),
            }


# Process-based executor for CPU-intensive tasks
class ProcessResourceExecutor:
    """Process-based executor with resource limits."""

    def __init__(
        self,
        max_workers: int = 2,
        memory_limit_mb: int = 8192,
        worker_timeout: float = 3600.0,
    ):
        self.max_workers = max_workers
        self.memory_limit_mb = memory_limit_mb
        self.worker_timeout = worker_timeout
        self._executor: Optional[ProcessPoolExecutor] = None
        self._futures: dict[Future, dict] = {}
        self._lock = threading.Lock()

    def __enter__(self):
        self._executor = ProcessPoolExecutor(max_workers=self.max_workers)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        future = self._executor.submit(fn, *args, **kwargs)
        with self._lock:
            self._futures[future] = {"submitted_at": time.time()}
        return future

    def shutdown(self, wait: bool = True):
        if self._executor:
            self._executor.shutdown(wait=wait)


# Task queue with priority and resource awareness
@dataclass
class Task:
    """A task with resource requirements."""
    fn: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    priority: int = 0  # Higher = more urgent
    requires_gpu: bool = False
    memory_mb: int = 0
    estimated_time: float = 60.0  # seconds
    task_id: str = ""
    metadata: dict = field(default_factory=dict)


class TaskScheduler:
    """Priority queue scheduler with resource awareness."""

    def __init__(self, executor: ResourceAwareExecutor):
        self.executor = executor
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._futures: dict[str, Future] = {}
        self._running = True
        self._scheduler_thread: Optional[threading.Thread] = None

    def add_task(self, task: Task) -> str:
        """Add task to queue. Returns task ID."""
        if not task.task_id:
            task.task_id = f"task_{time.time()}_{id(task)}"
        # Negative priority for max-heap behavior
        self._queue.put((-task.priority, time.time(), task))
        return task.task_id

    def add_tasks(self, tasks: list[Task]) -> list[str]:
        return [self.add_task(t) for t in tasks]

    def start(self):
        """Start scheduler thread."""
        self._running = True
        self._scheduler_thread = threading.Thread(target=self._run, daemon=True)
        self._scheduler_thread.start()

    def stop(self):
        self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=10.0)

    def _run(self):
        while self._running:
            try:
                _, _, task = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            future = self.executor.submit(
                task.fn,
                *task.args,
                requires_gpu=task.requires_gpu,
                memory_mb=task.memory_mb,
                **task.kwargs,
            )
            self._futures[task.task_id] = future

    def get_result(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """Get result for a task ID."""
        future = self._futures.get(task_id)
        if future:
            return future.result(timeout=timeout)
        raise KeyError(f"Task {task_id} not found")

    def wait_all(self, timeout: Optional[float] = None) -> dict[str, Any]:
        """Wait for all submitted tasks."""
        results = {}
        for task_id, future in self._futures.items():
            try:
                results[task_id] = future.result(timeout=timeout)
            except Exception as e:
                results[task_id] = e
        return results


# Tile-specific scheduling
@dataclass
class TileTask:
    """Task for processing a single tile."""
    tile_index: tuple[int, int]
    stage: str  # "osm2world", "blender", "roundtrip"
    input_sha: str
    output_path: Path
    dependencies: dict[str, str]
    requires_gpu: bool = False
    memory_mb: int = 1024
    estimated_time: float = 300.0


class TileScheduler:
    """Scheduler optimized for 20-tile pipeline."""

    def __init__(self, executor: ResourceAwareExecutor, tile_cache: Optional[Any] = None):
        self.executor = executor
        self.tile_cache = tile_cache
        self._futures: dict[tuple[int, int], dict[str, Future]] = {}
        self._results: dict[tuple[int, int], dict] = {}

    def schedule_tile(
        self,
        tile_index: tuple[int, int],
        stage: str,
        fn: Callable,
        input_sha: str,
        output_path: Path,
        dependencies: dict[str, str],
        requires_gpu: bool = False,
        memory_mb: int = 1024,
    ) -> Future:
        """Schedule a tile stage with caching."""
        # Check cache first
        if self.tile_cache:
            entry = self.tile_cache.lookup(tile_index, stage, input_sha)
            if entry and Path(entry.output_path).exists():
                # Cache hit - restore and return completed future
                shutil.copy2(entry.output_path, output_path)
                future = Future()
                future.set_result({"hit": True, "entry": entry})
                return future

        # Cache miss - schedule execution
        future = self.executor.submit(
            fn,
            tile_index,
            stage,
            input_sha,
            output_path,
            dependencies,
            requires_gpu=requires_gpu,
            memory_mb=memory_mb,
        )

        if tile_index not in self._futures:
            self._futures[tile_index] = {}
        self._futures[tile_index][stage] = future
        return future

    def wait_for_tile(self, tile_index: tuple[int, int], stages: list[str]) -> dict[str, Any]:
        """Wait for all stages of a tile to complete."""
        results = {}
        for stage in stages:
            future = self._futures.get(tile_index, {}).get(stage)
            if future:
                results[stage] = future.result()
        return results

    def wait_for_stage(self, stage: str, tile_indices: list[tuple[int, int]]) -> dict[tuple[int, int], Any]:
        """Wait for a stage across all tiles."""
        results = {}
        for tile_index in tile_indices:
            future = self._futures.get(tile_index, {}).get(stage)
            if future:
                results[tile_index] = future.result()
        return results

    def wait_all(self) -> dict[tuple[int, int], dict]:
        """Wait for all tiles and stages."""
        for tile_index, stages in self._futures.items():
            self._results[tile_index] = {}
            for stage, future in stages.items():
                self._results[tile_index][stage] = future.result()
        return self._results


# Convenience function for simple parallel map with resource awareness
def parallel_map(
    fn: Callable,
    items: list[Any],
    max_workers: int = 2,
    memory_per_task_mb: int = 1024,
    requires_gpu: bool = False,
    **kwargs,
) -> list[Any]:
    """Parallel map with resource awareness."""
    with ResourceAwareExecutor(
        max_workers=max_workers,
        memory_limit_mb=max_workers * memory_per_task_mb,
        vram_limit_mb=6144,
        gpu_jobs=1 if requires_gpu else 0,
    ) as executor:
        futures = [executor.submit(fn, item, **kwargs) for item in items]
        return [f.result() for f in as_completed(futures)]


import shutil
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, Future, as_completed