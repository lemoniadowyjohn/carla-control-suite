"""Session ownership, bounded cancellation and post-cleanup verification.

A :class:`Session` is the only object allowed to hold a tick grant and an actor
registry together. It exists so that:

* exactly one tick authority exists per session;
* teardown is ordered and *verified*, not assumed;
* an actor leak, an unrecovered Traffic Manager state or an incomplete
  synchronous-settings restore is recorded as explicit failure evidence;
* Ctrl+C, GUI close, worker crash and RPC timeout all converge on the same
  shutdown path instead of "defaulting to success".
"""

from __future__ import annotations

import signal
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled
from ultimate_pipeline.gui.health import SessionAuthority
from ultimate_pipeline.gui.results import Result
from ultimate_pipeline.gui.session.actor_registry import OwnedActorRegistry
from ultimate_pipeline.gui.session.tick_authority import TickAuthority

__all__ = [
    "ShutdownReason", "CleanupEvidence", "Session", "Watchdog",
    "exclusive_claimed", "EXCLUSIVE_AUTHORITY_VALUES",
]


class ShutdownReason(str, Enum):
    OPERATOR = "OPERATOR_STOP"
    CTRL_C = "CTRL_C"
    GUI_CLOSE = "GUI_CLOSE"
    WORKER_CRASH = "WORKER_CRASH"
    RPC_TIMEOUT = "RPC_TIMEOUT"
    LEASE_EXPIRED = "LEASE_EXPIRED"


@dataclass
class CleanupEvidence:
    """Explicit record of what cleanup did and did not achieve."""

    actor_leak: tuple[int, ...] = ()
    sync_restored: bool = False
    tm_state_recovered: bool = True
    tick_released: bool = False
    errors: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return (not self.actor_leak and self.sync_restored
                and self.tm_state_recovered and self.tick_released and not self.errors)

    def as_dict(self) -> dict:
        return {"clean": self.clean, "actor_leak": list(self.actor_leak),
                "sync_restored": self.sync_restored,
                "tm_state_recovered": self.tm_state_recovered,
                "tick_released": self.tick_released, "errors": list(self.errors)}


class Watchdog:
    """Bounded deadline for a long operation. Never an unbounded spin."""

    def __init__(self, timeout_s: float, clock: Callable[[], float] | None = None) -> None:
        self.timeout_s = float(timeout_s)
        self._clock = clock or __import__("time").monotonic

    def remaining(self) -> float:
        return self.timeout_s

    def expired(self, started_at: float) -> bool:
        return (self._clock() - started_at) >= self.timeout_s


class Session:
    """Owns tick authority, actors and cancellation for one GUI session."""

    def __init__(
        self,
        world: Any = None,
        *,
        name: str = "session",
        exclusive: bool = False,
        authority: SessionAuthority = SessionAuthority.SHARED_READONLY,
    ) -> None:
        self.name = name
        self.world = world
        self.authority = authority
        self.actors = OwnedActorRegistry()
        self.tick = TickAuthority(world=world, exclusive=exclusive or exclusive_claimed(authority))
        self.token = CancellationToken()
        self.evidence = CleanupEvidence()
        self._lock = threading.RLock()
        self._handlers_installed = False
        self._previous_sigint = None

    # -- exclusive authority ----------------------------------------------
    @property
    def may_mutate(self) -> bool:
        """Fail-closed mutation gate: only an explicitly exclusive authority.

        The previous implementation compared
        ``authority is not SessionAuthority.SHARED_READONLY`` -- an identity
        deny-list that failed OPEN for ``None``, plain strings
        (``"SHARED_READONLY" is not the enum singleton``) and every
        malformed value. :func:`exclusive_claimed` is the one allow-list.

        A Git writer lease is not a CARLA runtime lease: source-control
        authority never grants simulator mutation.
        """
        return exclusive_claimed(self.authority)

    def acquire_tick(self) -> Result:
        if not self.may_mutate:
            return Result.blocked(
                "session is SHARED_READONLY; every mutating simulator control stays disabled",
                remediation="obtain EXCLUSIVE_TICK authority to grant a tick",
            )
        grant = self.tick.acquire(owner=self.name)
        if not grant.granted:
            return Result.blocked(grant.reason, remediation="resolve the tick conflict first")
        return Result.success(grant)

    def tick_once(self) -> Result:
        self.token.raise_if_cancelled()
        return self.tick.tick(owner=self.name)

    # -- cooperative shutdown ---------------------------------------------
    def request_stop(self, reason: ShutdownReason = ShutdownReason.OPERATOR) -> None:
        self.token.cancel(reason.value)

    def install_signal_handlers(self) -> None:
        """Route SIGINT/Ctrl+C into cooperative cancellation, not a hard kill."""
        if self._handlers_installed:
            return
        try:
            self._previous_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._on_sigint)
            self._handlers_installed = True
        except (ValueError, OSError, AttributeError):
            # Not the main thread; the caller must poll the token instead.
            self._handlers_installed = False

    def _on_sigint(self, *_args: Any) -> None:
        self.request_stop(ShutdownReason.CTRL_C)

    def restore_signal_handlers(self) -> None:
        if self._handlers_installed and self._previous_sigint is not None:
            try:
                signal.signal(signal.SIGINT, self._previous_sigint)
            except (ValueError, OSError):
                pass
        self._handlers_installed = False

    # -- cleanup -----------------------------------------------------------
    def shutdown(self, reason: ShutdownReason = ShutdownReason.OPERATOR) -> CleanupEvidence:
        """Ordered teardown with post-cleanup verification.

        Never reports success while anything is unclean; the evidence object is
        returned either way so the caller can show exactly what went wrong.
        """
        with self._lock:
            errors: list[str] = []
            self.request_stop(reason)

            tm_ok = True
            if self.evidence.tm_state_recovered is False:
                tm_ok = False
                errors.append("Traffic Manager state was not recovered")

            tick_ok = True
            if self.tick.granted:
                released = self.tick.release(owner=self.name)
                tick_ok = released.ok
                if not released.ok:
                    errors.append(f"tick release failed: {released.reason}")
            self.evidence.tick_released = tick_ok

            actors_ok = self.actors.destroy_all()
            if not actors_ok.ok:
                errors.append(actors_ok.reason)

            verify = self.actors.cleanup_report()
            if not verify.ok:
                errors.append(verify.reason)

            self.evidence = CleanupEvidence(
                actor_leak=tuple((verify.value or {}).get("leaked_ids", ())) if isinstance(verify.value, dict) else (),
                sync_restored=tick_ok,
                tm_state_recovered=tm_ok,
                tick_released=tick_ok,
                errors=tuple(errors),
            )
            self.restore_signal_handlers()
            return self.evidence

    # -- long operations ---------------------------------------------------
    def run_bounded(
        self,
        work: Callable[[CancellationToken], Any],
        *,
        timeout_s: float,
        on_timeout: Callable[[], Any] | None = None,
    ) -> Result:
        """Run ``work`` cooperatively with a bounded deadline.

        A timeout cancels the token and invokes ``on_timeout``; it never
        silently reports success.
        """
        watchdog = Watchdog(timeout_s)
        started = watchdog._clock()
        try:
            return Result.success(work(self.token))
        except OperationCancelled:
            return Result.blocked("operation cancelled", remediation="re-run if still required")
        except TimeoutError as exc:
            self.request_stop(ShutdownReason.RPC_TIMEOUT)
            if on_timeout is not None:
                on_timeout()
            return Result.failure(f"timeout after {timeout_s}s: {exc}",
                                  error_class="TimeoutError", state_restored=False)
        except Exception as exc:
            self.request_stop(ShutdownReason.WORKER_CRASH)
            return Result.failure(f"operation crashed: {exc}",
                                  error_class=type(exc).__name__,
                                  error_source="ultimate_pipeline/gui/session/session.py",
                                  state_restored=False)


#: The only authority values that permit any mutation (fail-closed list).
EXCLUSIVE_AUTHORITY_VALUES: frozenset[str] = frozenset({
    SessionAuthority.EXCLUSIVE_TICK.value,
    SessionAuthority.EXCLUSIVE_WORLD.value,
    SessionAuthority.EXCLUSIVE_TM_PORT.value,
})


def exclusive_claimed(authority: Any) -> bool:
    """True only for an explicitly claimed exclusive authority.

    Fail-closed by construction: anything unavailable (``None``), shared
    (``SHARED_READONLY``), malformed or not a string is refused. String
    forms of the exclusive values are accepted so JSON/config round-trips
    keep working; identity checks (``is not SHARED_READONLY``) and
    deny-lists fail OPEN for those inputs and must never gate mutation.
    """
    if not isinstance(authority, str):
        return False
    return authority in EXCLUSIVE_AUTHORITY_VALUES