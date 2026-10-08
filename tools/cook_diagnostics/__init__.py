"""
Cook Diagnostics Harness for GAP-049.

Tools for monitoring Unreal Engine package cooking:
- package_write_poller: Logs new/changed files in package output directory
- cook_resource_census: Samples process memory with separate committed/limit counters
- stall_watchdog: Triggers procdump on stall without killing cook process
"""

from .package_write_poller import PackageWritePoller, FileRecord
from .cook_resource_census import CookResourceCensus, MemorySample
from .stall_watchdog import StallWatchdog, WatchdogEvent, WatchdogLogEntry

__all__ = [
    "PackageWritePoller",
    "FileRecord",
    "CookResourceCensus",
    "MemorySample",
    "StallWatchdog",
    "WatchdogEvent",
    "WatchdogLogEntry",
]

__version__ = "1.0.0"