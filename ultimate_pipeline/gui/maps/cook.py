"""Pinned map registry, runtime identity and cooking capability.

Three separations the GUI spec demands, kept strictly apart:

1. **Map preflight / registry verification** -- fail-closed on unknown name,
   non-file, unreadable, unresolved LFS pointer, byte mismatch, SHA-256 drift
   and path escape. Mirrors ``map_registry.py``'s own refusal set.
2. **Runtime identity** -- bound to a *trusted fingerprint*, never to a map
   name. A map called ``Town01`` that is not the pinned ``Town01`` must not be
   presented as ``Town01``.
3. **Cooking** -- blocked. ``UE426_BLOCKED_OPERATOR_INSTALL`` is a real state,
   so the adapter diagnoses capability and refuses. It never calls
   ``make import`` or ``UnrealEditor-Cmd``.

An *unavailable* map probe is reported differently from *a server that has zero
maps*. Those are different failures with different remediations.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled
from ultimate_pipeline.gui.results import Result

__all__ = [
    "LFS_POINTER_PREFIX", "MapPin", "MapRegistry", "VerifyOutcome",
    "RuntimeMapIdentity", "bind_runtime_identity", "CookCapability",
    "CookBudget", "MapCookingAdapter", "ProbeOutcome", "probe_maps",
]


LFS_POINTER_PREFIX = b"version https://git-lfs"


@dataclass(frozen=True)
class MapPin:
    name: str
    relative_path: str
    sha256: str
    size_bytes: int | None = None
    supersedes_sha256: str | None = None


class VerifyOutcome(str, Enum):
    OK = "OK"
    UNKNOWN_NAME = "UNKNOWN_NAME"
    NOT_A_FILE = "NOT_A_FILE"
    UNREADABLE = "UNREADABLE"
    LFS_POINTER = "LFS_POINTER"
    SHA_DRIFT = "SHA_DRIFT"
    PATH_ESCAPE = "PATH_ESCAPE"
    EMPTY_FILE = "EMPTY_FILE"


@dataclass
class VerifyResult:
    outcome: str
    detail: str = ""
    remediation: str = ""
    path: Path | None = None
    observed_sha256: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == VerifyOutcome.OK

    def as_dict(self) -> dict:
        return {"outcome": self.outcome, "ok": self.ok, "detail": self.detail,
                "remediation": self.remediation,
                "observed_sha256": self.observed_sha256}


class MapRegistry:
    """SHA-256 pinned map registry with fail-closed verification."""

    def __init__(self, root: Path, pins: Iterable[MapPin] = ()) -> None:
        self.root = Path(root)
        self._pins: dict[str, MapPin] = {pin.name: pin for pin in pins}

    def add(self, pin: MapPin) -> None:
        self._pins[pin.name] = pin

    def names(self) -> list[str]:
        return sorted(self._pins)

    def pin(self, name: str) -> MapPin | None:
        return self._pins.get(name)

    def resolve(self, name: str) -> Path:
        pin = self._pins[name]
        root = self.root.resolve()
        resolved = (root / pin.relative_path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"registry path escapes repository: {pin.relative_path!r}") from exc
        return resolved

    def verify(self, name: str) -> VerifyResult:
        """Fail closed. Every refusal mode is distinct and actionable."""
        pin = self._pins.get(name)
        if pin is None:
            return VerifyResult(VerifyOutcome.UNKNOWN_NAME,
                                f"{name!r} is not a pinned map",
                                "list names() for the registered maps")
        try:
            path = self.resolve(name)
        except ValueError as exc:
            return VerifyResult(VerifyOutcome.PATH_ESCAPE, str(exc),
                                "fix the pinned relative path")

        if not path.exists() or not path.is_file():
            return VerifyResult(VerifyOutcome.NOT_A_FILE, f"{path} is not a file",
                                "produce or restore the map file", path)

        try:
            blob = path.read_bytes()
        except OSError as exc:
            return VerifyResult(VerifyOutcome.UNREADABLE, f"cannot read: {exc}",
                                "check file permissions", path)

        if blob.startswith(LFS_POINTER_PREFIX):
            return VerifyResult(
                VerifyOutcome.LFS_POINTER,
                f"{path.name} is an unresolved git-lfs pointer, not a map",
                "run git lfs pull", path)
        if not blob:
            return VerifyResult(VerifyOutcome.EMPTY_FILE, f"{path.name} is empty",
                                "regenerate the map", path)

        digest = hashlib.sha256(blob).hexdigest()
        if digest != pin.sha256:
            return VerifyResult(
                VerifyOutcome.SHA_DRIFT,
                f"sha256 drift: pinned {pin.sha256}, observed {digest}",
                "the map is not the pinned artefact; do not promote it",
                path, digest)
        if pin.size_bytes is not None and len(blob) != pin.size_bytes:
            return VerifyResult(
                VerifyOutcome.SHA_DRIFT,
                f"size drift: pinned {pin.size_bytes}, observed {len(blob)}",
                "re-pin deliberately", path, digest)
        return VerifyResult(VerifyOutcome.OK, "pinned map verified", path=path,
                            observed_sha256=digest)

    def audit(self) -> dict:
        results = {name: self.verify(name).as_dict() for name in self.names()}
        bad = sorted(n for n, r in results.items() if not r["ok"])
        return {"total": len(results), "failing": bad,
                "clean": not bad, "results": results}


@dataclass(frozen=True)
class RuntimeMapIdentity:
    """Identity bound to a trusted fingerprint, never to a name."""

    map_name: str
    fingerprint_sha256: str
    pinned_sha256: str
    trusted: bool
    reason: str = ""

    def as_dict(self) -> dict:
        return {"map_name": self.map_name, "fingerprint_sha256": self.fingerprint_sha256,
                "pinned_sha256": self.pinned_sha256, "trusted": self.trusted,
                "reason": self.reason}


def bind_runtime_identity(name: str, observed_fingerprint: str,
                          registry: MapRegistry) -> RuntimeMapIdentity:
    """Bind identity by fingerprint. A name-only match is never trusted."""
    pin = registry.pin(name)
    if pin is None:
        return RuntimeMapIdentity(name, observed_fingerprint, "", False,
                                  f"{name!r} is not a pinned map")
    if observed_fingerprint != pin.sha256:
        return RuntimeMapIdentity(
            name, observed_fingerprint, pin.sha256, False,
            "runtime fingerprint does not match the pin; the map sharing this "
            "name is NOT the pinned map")
    return RuntimeMapIdentity(name, observed_fingerprint, pin.sha256, True)


class ProbeOutcome(str, Enum):
    OK = "OK"
    UNAVAILABLE = "PROBE_UNSUPPORTED"   # the backend cannot answer
    ZERO_MAPS = "ZERO_MAPS"             # the server answered with nothing
    UNREACHABLE = "UNREACHABLE"


@dataclass
class ProbeResult:
    outcome: str
    maps: tuple[str, ...] = ()
    detail: str = ""
    remediation: str = ""

    def as_dict(self) -> dict:
        return {"outcome": self.outcome, "maps": list(self.maps),
                "detail": self.detail, "remediation": self.remediation}


def probe_maps(available_maps: Any) -> ProbeResult:
    """Distinguish 'cannot probe' from 'server has zero maps'.

    Collapsing these two is how a GUI ends up claiming a map is missing when
    the backend simply does not implement enumeration.
    """
    state = getattr(available_maps, "state", None)
    reason = getattr(available_maps, "reason", "") or ""
    if state == "PROBE_UNSUPPORTED":
        return ProbeResult(ProbeOutcome.UNAVAILABLE, (),
                           reason or "backend does not implement map enumeration",
                           "this is a capability gap, not an empty map set")
    if state == "EMPTY":
        return ProbeResult(ProbeOutcome.ZERO_MAPS, (),
                           reason or "the server reported zero maps",
                           "load or cook a map before continuing")
    names = tuple(getattr(available_maps, "value", None) or ())
    if not names:
        return ProbeResult(ProbeOutcome.ZERO_MAPS, (), "no maps returned",
                           "load or cook a map before continuing")
    return ProbeResult(ProbeOutcome.OK, names, f"{len(names)} maps", "")


# ---------------------------------------------------------------- cooking
class CookCapability(str, Enum):
    BLOCKED_OPERATOR_INSTALL = "UE426_BLOCKED_OPERATOR_INSTALL"
    AVAILABLE = "AVAILABLE"


@dataclass(frozen=True)
class CookBudget:
    """Explicit, enforced budgets. Nothing launches outside them."""

    max_disk_gib: float = 60.0
    max_vram_mib: int = 5632          # never the full 6144 MiB
    max_wall_clock_minutes: int = 90
    free_disk_gib_required: float = 80.0


@dataclass
class CookCapabilityReport:
    capability: str
    editor_installed: bool
    editor_path: str = ""
    reasons: tuple[str, ...] = ()
    remediation: str = ""

    @property
    def can_cook(self) -> bool:
        return self.capability == CookCapability.AVAILABLE.value

    def as_dict(self) -> dict:
        return {"capability": self.capability, "can_cook": self.can_cook,
                "editor_installed": self.editor_installed,
                "editor_path": self.editor_path, "reasons": list(self.reasons),
                "remediation": self.remediation}


class MapCookingAdapter:
    """Diagnoses cooking capability and refuses to cook unless truly able.

    Offline tests never reach ``make import`` or ``UnrealEditor-Cmd``: the
    adapter refuses before reaching that point because the capability is
    blocked and budgets are unmet.
    """

    def __init__(self, budget: CookBudget | None = None,
                 editor_path: str = "") -> None:
        self.budget = budget or CookBudget()
        self.editor_path = editor_path
        self.cancelled = False

    def diagnose(self, *, editor_installed: bool | None = None) -> CookCapabilityReport:
        installed = bool(self.editor_path) if editor_installed is None else editor_installed
        reasons: list[str] = []
        if not installed:
            reasons.append(CookCapability.BLOCKED_OPERATOR_INSTALL.value)
        if not self.budget:
            reasons.append("no budget configured")
        if self.budget and self.budget.max_vram_mib >= 6144:
            reasons.append("VRAM budget must be below the full device capacity")
        capability = (CookCapability.AVAILABLE.value
                      if installed and not reasons
                      else CookCapability.BLOCKED_OPERATOR_INSTALL.value)
        return CookCapabilityReport(
            capability=capability,
            editor_installed=installed,
            editor_path=self.editor_path,
            reasons=tuple(reasons) or (),
            remediation=("install UE4.26 and record CARLA_GUI_UE426_ROOT, then "
                         "re-run diagnosis") if not installed else "",
        )

    def check_budgets(self, free_disk_gib: float,
                      total_vram_mib: int) -> Result:
        if free_disk_gib < self.budget.free_disk_gib_required:
            return Result.blocked(
                f"only {free_disk_gib} GiB free; "
                f"{self.budget.free_disk_gib_required} GiB required to cook",
                remediation="free disk or cook on another volume")
        if total_vram_mib < self.budget.max_vram_mib:
            return Result.blocked(
                f"device VRAM {total_vram_mib} MiB is below the "
                f"{self.budget.max_vram_mib} MiB cook budget")
        if self.budget.max_vram_mib >= total_vram_mib:
            return Result.blocked(
                "cook budget must leave headroom; never budget the whole device")
        return Result.success(True)

    def cook(self, *, free_disk_gib: float, total_vram_mib: int,
             editor_installed: bool | None = None,
             token: CancellationToken | None = None) -> Result:
        """Cook, if and only if capability and budgets both pass.

        Offline tests always reach a refusal here: the capability is blocked
        unless an editor is genuinely present.
        """
        if token is not None:
            token.raise_if_cancelled()

        capability = self.diagnose(editor_installed=editor_installed)
        if not capability.can_cook:
            return Result.blocked(
                f"cooking is blocked: {capability.capability}",
                remediation=capability.remediation or "operator must install UE4.26")

        budget = self.check_budgets(free_disk_gib, total_vram_mib)
        if not budget.ok:
            return budget

        return Result.blocked(
            "live cook requires explicit approval and an isolated environment",
            remediation="obtain live approval under a dedicated lease (Q22)")