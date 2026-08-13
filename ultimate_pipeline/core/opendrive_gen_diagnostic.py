"""LOAD_DIAGNOSTIC - CARLA OpenDRIVE generation load diagnostics.

Resolves generation nondeterminism by classifying each
``client.generate_opendrive_world`` attempt into one of:
  - LENGTH_ASSERT: deterministic content defect (s <= road->GetLength() crash)
  - OOM: GPU/host memory exhaustion
  - RPC_TIMEOUT: transport-level timeout (server blocked elsewhere)
  - GENERIC_FATAL: LowLevelFatalError without known markers
  - SUCCESS: world generated and world-with-map accessible

Determinism contract: a runtime sha may only be certified after >=2
SUCCESS loads (``MIN_SUCCESSFUL_LOADS``) with identical world identity,
and any LENGTH_ASSERT attempt is a hard failure of the candidate (not a
retryable transient).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

MIN_SUCCESSFUL_LOADS = 2
STALL_NO_PROGRESS_S = float(os.environ.get("UP_LOAD_STALL_S", "300.0"))

LENGTH_ASSERT_PATTERNS = (
    r"s <= road->GetLength\(\)",
    r"GetLength\(\).*Exception thrown",
    r"road.*GetLength",
)

OOM_PATTERNS = (
    r"out of memory",
    r"not enough memory",
    r"LowLevelFatalError.*[Mm]emory",
    r"insufficient (gpu|host) memory",
)

RPC_TIMEOUT_PATTERNS = (
    r"RPC timed out",
    r"rpc_timeout",
    r"timeout after",
    r"network issue",
)

GENERIC_FATAL_PATTERNS = (
    r"LowLevelFatalError",
    r"Fatal error",
    r"Exception thrown",
)


@dataclass
class LoadAttempt:
    """A single generate_opendrive_world attempt observation."""

    attempt: int
    started_at: float
    outcome: str = "UNKNOWN"
    duration_s: Optional[float] = None
    marker: str = ""
    map_name: str = ""
    vram_used_mb: int = -1
    cpu_pct: float = -1.0
    rss_mb: float = -1.0
    window_s: float = 0.0
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt": self.attempt,
            "started_at": self.started_at,
            "outcome": self.outcome,
            "duration_s": self.duration_s,
            "marker": self.marker,
            "map_name": self.map_name,
            "vram_used_mb": self.vram_used_mb,
            "cpu_pct": self.cpu_pct,
            "rss_mb": self.rss_mb,
            "window_s": self.window_s,
            "diagnostics": self.diagnostics,
        }


def sample_vram_mb() -> int:
    """Sample VRAM usage (many GPUs) or -1 when unavailable.

    Prefers pynvml; falls back to ``nvidia-smi``; returns -1 if neither works.
    """
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return int(mem.used / (1024 * 1024))
    except Exception:
        pass
    try:
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return int(out.splitlines()[0].strip())
    except Exception:
        return -1


def classify_failure(text: str, duration_s: Optional[float] = None) -> str:
    """Classify a failed attempt's combined log text (server stderr + RPC exc).

    Priority: LENGTH_ASSERT > OOM > RPC_TIMEOUT > GENERIC_FATAL > STALL > UNKNOWN.
    """
    if not text:
        return "UNKNOWN"
    for pat in LENGTH_ASSERT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return "LENGTH_ASSERT"
    for pat in OOM_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return "OOM"
    for pat in RPC_TIMEOUT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return "RPC_TIMEOUT"
    for pat in GENERIC_FATAL_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return "GENERIC_FATAL"
    return "UNKNOWN"


def detect_stall(
    resource_samples: List[Dict[str, Any]],
    *,
    stall_s: float = STALL_NO_PROGRESS_S,
) -> bool:
    """True when the server made no observable progress for ``stall_s``."""
    if len(resource_samples) < 2:
        return False
    samples = sorted(resource_samples, key=lambda r: float(r.get("t_s", 0.0)))
    t0 = float(samples[0].get("t_s", 0.0))
    rss0 = float(samples[0].get("rss_mb", 0.0) or 0.0)
    for s in samples:
        dt = float(s.get("t_s", 0.0)) - t0
        if dt >= stall_s:
            return True
        if float(s.get("rss_mb", 0.0) or 0.0) - rss0 > 1.0:
            t0 = float(s.get("t_s", 0.0))
            rss0 = float(s.get("rss_mb", 0.0) or 0.0)
    return False


def determinism_verdict(
    attempts: List[Dict[str, Any]],
    *,
    min_successes: int = MIN_SUCCESSFUL_LOADS,
) -> Dict[str, Any]:
    """Enforce the >=2 successful non-crashing loads rule for a runtime sha.

    ``attempts``: list of LoadAttempt.to_dict() dicts (chronological).
    Verdicts:
      LOADS_DETERMINISTIC        - >= min_successes SUCCESS, no LENGTH_ASSERT,
                                   identical map names, outcome sequence recorded
      LOADS_INSUFFICIENT         - fewer successes than required
      LOADS_LENGTH_ASSERT_FAILED - any attempt classified LENGTH_ASSERT
      LOADS_CRASHED              - failures present but not length-assert
    """
    successes = [a for a in attempts if a.get("outcome") == "SUCCESS"]
    length_asserts = [a for a in attempts if a.get("outcome") == "LENGTH_ASSERT"]
    failures = [a for a in attempts if a.get("outcome") != "SUCCESS"]

    outcome_sequence = [a.get("outcome") for a in attempts]

    if length_asserts:
        verdict = "LOADS_LENGTH_ASSERT_FAILED"
        reason = "candidate is defective: s <= road->GetLength() crash observed; candidate must be repaired, attempts are NOT retryable"
    elif len(successes) < min_successes:
        verdict = "LOADS_INSUFFICIENT"
        reason = f"{len(successes)}/{min_successes} successful loads; runtime sha must not be certified"
    elif failures:
        verdict = "LOADS_CRASHED"
        reason = "some attempts failed (classify as OOM/RPC_TIMEOUT/GENERIC_FATAL before re-running)"
    else:
        verdict = "LOADS_DETERMINISTIC"
        reason = ">=2 consecutive successful non-crashing loads with identical world identity"

    map_names = sorted({a.get("map_name") for a in successes if a.get("map_name")})
    return {
        "verdict": verdict,
        "reason": reason,
        "successes": len(successes),
        "failures": len(failures),
        "length_asserts": len(length_asserts),
        "memory_pattern": "OOM_PRESENT" if any(a.get("outcome") == "OOM" for a in attempts) else "NO_OOM",
        "map_names_uniform": len(map_names) <= 1,
        "map_names": map_names,
        "outcome_sequence": outcome_sequence,
        "min_successful_loads": min_successes,
    }


def load_diagnostic_release(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Standalone evidence gate: verdict for a runtime certification run.

    ``evidence`` keys: {"loads": [attempt dicts], "candidate_sha256": str,
    "runtime_sha256": str, "attempted_at_utc": str}
    """
    dv = determinism_verdict(evidence.get("loads", []))
    return {
        "gate": "LOAD_DIAGNOSTIC",
        "pass": dv["verdict"] == "LOADS_DETERMINISTIC",
        "determinism": dv,
        "candidate_sha256": evidence.get("candidate_sha256", ""),
        "runtime_sha256": evidence.get("runtime_sha256", ""),
        "recorded_at_utc": evidence.get("attempted_at_utc", ""),
    }


def summarize_loads_jsonl(path: str) -> Dict[str, Any]:
    """Load attempts from a JSONL file (one LoadAttempt.to_dict() per line)."""
    attempts: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                attempts.append(json.loads(line))
    return {
        "attempts": attempts,
        "verdict": determinism_verdict(attempts),
    }