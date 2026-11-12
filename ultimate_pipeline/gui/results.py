"""Typed result objects.

The Phase 1 contract forbids returning a "successful-looking ``None``".  Every
operation that can be unsupported, blocked or empty returns one of these
objects instead, so a caller cannot mistake silence for success.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

__all__ = ["TriState", "Tri", "Result", "UnsupportedCapability", "Diagnostic"]

T = TypeVar("T")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_jsonable(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


class TriState:
    """The three-way probe outcome used by ``available_maps`` and friends."""

    AVAILABLE = "AVAILABLE"
    EMPTY = "EMPTY"
    PROBE_UNSUPPORTED = "PROBE_UNSUPPORTED"


@dataclass(frozen=True)
class Tri(Generic[T]):
    """A value that may legitimately be unavailable or unsupported."""

    state: str
    value: T | None = None
    reason: str = ""
    evidence_at: str = ""

    @property
    def available(self) -> bool:
        return self.state == TriState.AVAILABLE

    @property
    def supported(self) -> bool:
        return self.state != TriState.PROBE_UNSUPPORTED

    @classmethod
    def available_value(cls, value: T, evidence_at: str = "") -> "Tri[T]":
        return cls(TriState.AVAILABLE, value, "", evidence_at or _now())

    @classmethod
    def empty(cls, reason: str = "query returned no rows") -> "Tri[T]":
        return cls(TriState.EMPTY, None, reason, _now())

    @classmethod
    def unsupported(cls, reason: str) -> "Tri[T]":
        """The capability genuinely does not exist.  Never an error, never a pass."""
        return cls(TriState.PROBE_UNSUPPORTED, None, reason, _now())


@dataclass(frozen=True)
class UnsupportedCapability:
    """A capability that this backend does not implement.

    Surfacing these explicitly is what stops a widget from silently doing
    nothing when a service lacks a method.
    """

    capability: str
    reason: str
    remediation: str = ""
    source: str = ""


@dataclass(frozen=True)
class Result(Generic[T]):
    """A typed operation outcome carrying provenance and failure detail.

    ``error_class`` keeps the *original* exception type name so a UI can show
    ``operation -> backend function and file:line -> exception class`` as the
    error presentation contract requires.
    """

    ok: bool
    value: T | None = None
    reason: str = ""
    error_class: str = ""
    error_source: str = ""
    remediation: str = ""
    state_restored: bool | None = None
    evidence_at: str = field(default_factory=_now)

    @classmethod
    def success(cls, value: T, evidence_at: str = "") -> "Result[T]":
        return cls(True, value, "", "", "", "", True, evidence_at or _now())

    @classmethod
    def failure(
        cls,
        reason: str,
        error_class: str = "",
        error_source: str = "",
        remediation: str = "",
        state_restored: bool | None = None,
        value: Any = None,
    ) -> "Result[T]":
        # ``value`` is permitted on a failure so structured *evidence* (for
        # example the exact leaked actor ids) can travel with the error instead
        # of forcing callers to parse it back out of the reason string.
        return cls(False, value, reason, error_class, error_source, remediation,
                   state_restored, _now())

    @classmethod
    def blocked(cls, reason: str, remediation: str = "",
                error_class: str = "BlockedExternal",
                error_source: str = "",
                state_restored: bool | None = None) -> "Result[T]":
        """A block is a refusal with a known cause.

        ``error_class`` defaults to ``BlockedExternal`` but callers may name a
        more specific cause (a schema mismatch, a drift, an unsupported
        capability) so a UI can distinguish them.
        """
        return cls(False, None, reason, error_class, error_source, remediation,
                   True if state_restored is None else state_restored, _now())

    def unwrap(self) -> T:
        """Return the value or raise.  Never returns ``None`` on success."""
        if not self.ok or self.value is None:
            raise ValueError(f"Result.unwrap() on failure: {self.reason}")
        return self.value

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "value": self.value if _is_jsonable(self.value) else repr(self.value),
                "reason": self.reason,
                "error_class": self.error_class,
                "error_source": self.error_source,
                "remediation": self.remediation,
                "state_restored": self.state_restored,
                "evidence_at": self.evidence_at,
            },
            sort_keys=True,
        )


@dataclass(frozen=True)
class Diagnostic:
    """A surfaced swallowed exception or unsupported capability."""

    kind: str  # "SWALLOWED_EXCEPTION" | "UNSUPPORTED_CAPABILITY" | "DEGRADED_PATH"
    subject: str
    detail: str
    source: str = ""
    severity: str = "WARNING"


def digest(value: Any) -> str:
    """Stable sha256 over any JSON-serialisable payload (never over secrets)."""
    blob = json.dumps(value, sort_keys=True, default=repr).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()