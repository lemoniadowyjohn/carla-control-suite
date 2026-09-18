#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System metrics monitor (CPU/RAM) with optional psutil dependency.
"""
from __future__ import annotations

import csv
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SystemMetricsMonitor:
    def __init__(self, out_dir: Path, interval_s: float = 1.0, filename: str = "system_metrics.csv") -> None:
        self.out_dir = out_dir
        self.interval_s = max(0.2, interval_s)
        self.filename = filename
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._psutil = None

    def __enter__(self) -> "SystemMetricsMonitor":
        try:
            import psutil  # type: ignore

            self._psutil = psutil
        except Exception:
            self._psutil = None
            return self

        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_s * 2)

    def _run_loop(self) -> None:
        path = self.out_dir / self.filename
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["timestamp_utc", "cpu_percent", "ram_used_mb", "ram_total_mb"])
            while not self._stop.is_set():
                try:
                    cpu = float(self._psutil.cpu_percent(interval=None))
                    mem = self._psutil.virtual_memory()
                    ram_used = round(mem.used / (1024 * 1024), 2)
                    ram_total = round(mem.total / (1024 * 1024), 2)
                    writer.writerow([_utc_now(), cpu, ram_used, ram_total])
                    fh.flush()
                except Exception:
                    pass
                time.sleep(self.interval_s)


def start_system_metrics_monitor(out_dir: Path, interval_s: float = 1.0) -> SystemMetricsMonitor:
    return SystemMetricsMonitor(out_dir=out_dir, interval_s=interval_s)
