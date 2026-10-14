#!/usr/bin/env python3
"""UE cook terminal-log classifier (GAP-049 L).

Maps a cook console log to exactly one terminal class. Previously the
2026-10-11 SavePackage write failure ("Could not write to ...T_Fabric_15_R.ubulk!",
SavePackageUtilities.cpp:527) had no classifier entry and fell through to the
"silent hang" bucket. A log carrying an explicit UE fatal must never classify
as silent.

Allowed classes: CLEAN_SUCCESS, SAVE_PACKAGE_WRITE_FAILURE,
SHADER_COMPILER_OOM, PACKAGE_STALL, STORAGE_FAILURE, UE_FATAL_OTHER,
TIMEOUT, UNKNOWN_EXPLICIT, SILENT_HANG.

SILENT_HANG is returned ONLY when all hold: the process is alive, the log is
quiescent for the governed interval, no terminal UE error is present, and no
OS crash/storage event is recorded. Anything else explicit wins first.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

CLASSES = (
    "CLEAN_SUCCESS",
    "SAVE_PACKAGE_WRITE_FAILURE",
    "SHADER_COMPILER_OOM",
    "PACKAGE_STALL",
    "STORAGE_FAILURE",
    "UE_FATAL_OTHER",
    "TIMEOUT",
    "UNKNOWN_EXPLICIT",
    "SILENT_HANG",
)

_PATTERNS = [
    # (class, compiled regex, evidence group index or None)
    ("SAVE_PACKAGE_WRITE_FAILURE",
     re.compile(r"Could not write to\s+(?P<path>\S+?\.ubulk)!?", re.IGNORECASE), "path"),
    ("SAVE_PACKAGE_WRITE_FAILURE",
     re.compile(r"Could not save to\s+(?P<path>\S+)!?", re.IGNORECASE), "path"),
    ("SAVE_PACKAGE_WRITE_FAILURE",
     re.compile(r"SavePackage\w*\.cpp.*Line:\s*(?P<line>\d+)", re.IGNORECASE), "line"),
    ("SHADER_COMPILER_OOM",
     re.compile(r"(?P<ctx>ShaderCompileWorker[^\n]{0,120}?(?:Ran out of memory|Out of memory))|"
                r"((?:Ran out of memory|Out of memory)[^\n]{0,120}?Shader)", re.IGNORECASE), None),
    ("STORAGE_FAILURE",
     re.compile(r"CreateFile failed[^\n]*?(?P<path>[A-Z]:[^\s]*)?", re.IGNORECASE), "path"),
    ("UE_FATAL_OTHER",
     re.compile(r"Assertion failed[^\n]*", re.IGNORECASE), None),
    ("UE_FATAL_OTHER",
     re.compile(r"LowLevelFatalError[^\n]*", re.IGNORECASE), None),
    ("UE_FATAL_OTHER",
     re.compile(r"Fatal error:\s*Runnable thread\s+(?P<thread>\S+)\s+crashed", re.IGNORECASE), "thread"),
    ("UE_FATAL_OTHER",
     re.compile(r"Fatal error:[^\n]*", re.IGNORECASE), None),
    ("UE_FATAL_OTHER",
     re.compile(r"===\s*Critical error:\s*===", re.IGNORECASE), None),
    ("UE_FATAL_OTHER",
     re.compile(r"(?P<msg>Critical error:[^\n]*)", re.IGNORECASE), "msg"),
    ("CLEAN_SUCCESS",
     re.compile(r"LogCook:.*?(?:completed successfully|succeeded)", re.IGNORECASE), None),
]


def classify_terminal(
    log_text: str,
    *,
    process_alive: bool = False,
    progress_ceased: bool = False,
    log_quiescent: bool = False,
    timed_out: bool = False,
    os_crash_event: bool = False,
) -> Dict[str, object]:
    """Classify a UE cook console log.

    Args:
        log_text: full console text (tail is fine if it holds the terminal).
        process_alive: cook PID still exists.
        progress_ceased: package counters frozen for the governed interval.
        log_quiescent: no new log output for the governed interval.
        timed_out: harness killed the run on timeout.
        os_crash_event: Windows crash/storage event recorded for the window.

    Returns {"class": <one of CLASSES>, "evidence": [quoted lines]}.
    """
    text = log_text or ""
    evidence: List[str] = []
    for cls, rx, group in _PATTERNS:
        m = rx.search(text)
        if m:
            snippet = m.group(0).strip()[:220]
            evidence.append(snippet)
            if cls == "SAVE_PACKAGE_WRITE_FAILURE" and group == "line" \
                    and "Could not write to" not in text and "Could not save to" not in text:
                # A bare SavePackage line reference without a write-failure
                # message is not, by itself, a proven write failure.
                evidence.pop()
                continue
            return {"class": cls, "evidence": evidence}

    if timed_out:
        return {"class": "TIMEOUT",
                "evidence": ["harness timeout with no terminal UE error in log"]}
    if process_alive and progress_ceased and not log_quiescent:
        return {"class": "PACKAGE_STALL",
                "evidence": ["counters frozen, process alive, log still advancing"]}
    if process_alive and progress_ceased and log_quiescent \
            and not os_crash_event:
        return {"class": "SILENT_HANG",
                "evidence": ["process alive, log quiescent, no terminal error, no OS event"]}
    if process_alive and progress_ceased and log_quiescent and os_crash_event:
        return {"class": "STORAGE_FAILURE",
                "evidence": ["log quiescent with a recorded OS crash/storage event"]}
    return {"class": "UNKNOWN_EXPLICIT", "evidence": []}


def classes() -> List[str]:
    return list(CLASSES)
