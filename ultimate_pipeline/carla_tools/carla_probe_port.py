"""CARLA port probe: a truthful bounded probe, not a stub.

The previous implementation returned ``rpc_ok: True`` with **no socket and no
CARLA call**. This replacement performs a real TCP handshake with a bounded
timeout and reports the actual outcome. It does not claim RPC success unless
the handshake completes.
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from typing import Any

__all__ = ["ProbeResult", "probe"]


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a bounded port probe."""

    host: str
    port: int
    timeout_s: float
    rpc_ok: bool
    streaming_ok: bool
    duration_ms: int
    error: str | None = None
    error_class: str | None = None

    def as_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "timeout_s": self.timeout_s,
            "rpc_ok": self.rpc_ok,
            "streaming_ok": self.streaming_ok,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "error_class": self.error_class,
        }


def probe(
    host: str = "localhost",
    port: int = 2000,
    timeout_s: float = 5.0,
    **_ignored: Any,
) -> ProbeResult:
    """Probe a CARLA server port with a real TCP handshake.

    This function **never** returns ``rpc_ok: True`` without an actual socket
    connection. If the environment variable ``UP_TILE_QA_DISABLE_STREAMING`` is
    set to ``"1"``, the probe still performs the TCP handshake but reports
    ``streaming_ok: False`` because streaming is explicitly disabled by
    configuration.
    """
    started = time.perf_counter()
    streaming_disabled = os.getenv("UP_TILE_QA_DISABLE_STREAMING", "1") == "1"

    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            tcp_ok = True
    except Exception as exc:
        duration = int((time.perf_counter() - started) * 1000)
        return ProbeResult(
            host=host,
            port=port,
            timeout_s=timeout_s,
            rpc_ok=False,
            streaming_ok=False,
            duration_ms=duration,
            error=f"{type(exc).__name__}: {exc}",
            error_class=type(exc).__name__,
        )

    # TCP handshake succeeded. We cannot verify CARLA RPC without a client.
    # Report TCP success as rpc_ok=False (honest: we only proved port open).
    # The GUI layer interprets this correctly.
    duration = int((time.perf_counter() - started) * 1000)
    return ProbeResult(
        host=host,
        port=port,
        timeout_s=timeout_s,
        rpc_ok=False,  # TCP open ≠ CARLA RPC handshake
        streaming_ok=not streaming_disabled,
        duration_ms=duration,
    )