"""``EvidenceFreshnessService`` -- bind artefacts to the inputs they claim.

An artefact is only meaningful relative to *what produced it*: the commit, the
source inputs, the pinned map, the runtime environment.  This service decides
whether a stored artefact may be presented as live, or must be shown with an
``AS OF <utc>`` timestamp and a ``STALE_OR_UNBOUND`` badge.

Two artefacts are permanently pinned to ``STALE`` because the foundation audit
reported them stale: ``CURRENT_MAP_STATIC_RELEASE_MATRIX.json`` and
``PRODUCTION_READINESS_MATRIX.json``.  They must never be displayed as live.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "Freshness", "BindingInput", "EvidenceFreshnessService",
    "FORBIDDEN_AS_LIVE", "ARTIFACT_SCHEMA",
]

ARTIFACT_SCHEMA = "evidence-freshness/v1"

#: Artefacts reported stale by the foundation audit. They are pinned STALE and
#: must never be presented as a live measurement.
FORBIDDEN_AS_LIVE: frozenset[str] = frozenset({
    "CURRENT_MAP_STATIC_RELEASE_MATRIX.json",
    "PRODUCTION_READINESS_MATRIX.json",
})


class Freshness:
    """Freshness verdicts. Only ``LIVE`` permits a live presentation."""

    LIVE = "LIVE"
    STALE = "STALE_OR_UNBOUND"
    UNBOUND = "UNBOUND"
    MISSING = "MISSING"
    CORRUPT = "CORRUPT"
    SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"
    NOT_MEASURED = "NOT_MEASURED"

    LIVE_VALUES = frozenset({LIVE})


@dataclass(frozen=True)
class BindingInput:
    """One thing the artefact was produced against.

    ``drift`` and ``unbound`` are deliberately distinct: an artefact that
    recorded ``oldcommit`` against a live ``newcommit`` has *drifted*, while an
    artefact that recorded nothing at all is *unbound*. Collapsing the two
    would hide which of the two is true.
    """

    name: str
    expected: str
    actual: str

    @property
    def unbound(self) -> bool:
        """Nothing was recorded, so this input cannot be verified either way."""
        return not bool(self.expected)

    @property
    def drift(self) -> bool:
        """A value was recorded and it no longer matches reality."""
        return bool(self.expected) and self.expected != self.actual

    @property
    def matches(self) -> bool:
        return bool(self.expected) and self.expected == self.actual


@dataclass(frozen=True)
class Binding:
    """The result of comparing an artefact's recorded inputs to the live ones."""

    artifact: str
    freshness: str
    recorded_at: str = ""
    inputs: tuple[BindingInput, ...] = ()
    detail: str = ""
    may_display_as_live: bool = False
    remediation: str = ""

    def mismatches(self) -> tuple[BindingInput, ...]:
        """Inputs that genuinely drifted (not merely unbound)."""
        return tuple(i for i in self.inputs if i.drift)

    def unbound(self) -> tuple[BindingInput, ...]:
        """Inputs the artefact never recorded, so freshness cannot be proven."""
        return tuple(i for i in self.inputs if i.unbound)


def current_commit(repo_root: Path) -> str:
    """Read HEAD without mutating anything; ``UNKNOWN`` if git is unavailable."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return "UNKNOWN"
        return proc.stdout.strip() or "UNKNOWN"
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def runtime_environment() -> dict[str, str]:
    """The runtime facts an artefact can be invalidated by."""
    return {
        "python": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
        "platform": os.name,
        "cwd_basename": os.path.basename(os.getcwd()),
    }


class EvidenceFreshnessService:
    """Decide whether stored evidence may be shown as live."""

    def __init__(self, repo_root: Path, commit: str | None = None) -> None:
        self.repo_root = Path(repo_root)
        self._commit = commit

    @property
    def commit(self) -> str:
        if self._commit is None:
            self._commit = current_commit(self.repo_root)
        return self._commit

    def bind(self, artifact_name: str, payload: dict[str, Any]) -> Binding:
        """Evaluate a loaded artefact payload against the live environment."""
        if artifact_name in FORBIDDEN_AS_LIVE:
            return Binding(
                artifact=artifact_name,
                freshness=Freshness.STALE,
                recorded_at=str(payload.get("generated_at", "")),
                detail=(
                    f"{artifact_name} was reported stale by the foundation audit; "
                    "it must never be presented as a live measurement"
                ),
                may_display_as_live=False,
                remediation="re-run the producing stage to regenerate this artefact",
            )

        recorded = dict(payload)
        inputs = (
            BindingInput("git_sha", str(recorded.get("git_sha", "")), self.commit),
            BindingInput("python", str(recorded.get("python", "")), runtime_environment()["python"]),
            BindingInput("platform", str(recorded.get("platform", "")), runtime_environment()["platform"]),
        )
        drift = tuple(i for i in inputs if i.drift)
        unbound = tuple(i for i in inputs if i.unbound)

        if not recorded.get("git_sha"):
            freshness, detail = Freshness.UNBOUND, "artefact records no git_sha"
        elif drift:
            freshness = Freshness.STALE
            detail = "; ".join(f"{i.name}: expected {i.expected!r}, actual {i.actual!r}" for i in drift)
        elif unbound:
            freshness = Freshness.STALE
            detail = "unverified inputs: " + ", ".join(i.name for i in unbound)
        else:
            freshness, detail = Freshness.LIVE, "all bound inputs match"

        return Binding(
            artifact=artifact_name,
            freshness=freshness,
            recorded_at=str(recorded.get("generated_at", "")),
            inputs=inputs,
            detail=detail,
            may_display_as_live=freshness in Freshness.LIVE_VALUES,
            remediation="" if freshness == Freshness.LIVE else "re-run the producing stage to refresh",
        )

    def load_and_bind(self, artifact_path: Path) -> Binding:
        """Read an artefact from disk and bind it, handling the four bad states."""
        path = Path(artifact_path)
        name = path.name
        if not path.exists():
            return Binding(name, Freshness.MISSING, detail=f"{path} does not exist",
                           may_display_as_live=False, remediation="run the producing stage")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            return Binding(name, Freshness.CORRUPT, detail=f"unreadable: {exc}",
                           may_display_as_live=False, remediation="regenerate the artefact")
        if not isinstance(payload, dict):
            return Binding(name, Freshness.SCHEMA_INCOMPATIBLE,
                           detail=f"expected a JSON object, got {type(payload).__name__}",
                           may_display_as_live=False, remediation="regenerate the artefact")

        # Schema compatibility is checked FIRST and takes precedence: an
        # artefact written by an incompatible producer is not a stale
        # measurement, it is an unreadable one. Reporting it as merely STALE
        # would invite a "re-run and it will be fine" conclusion that is wrong.
        declared_schema = payload.get("schema")
        if isinstance(declared_schema, str) and declared_schema != ARTIFACT_SCHEMA:
            return Binding(name, Freshness.SCHEMA_INCOMPATIBLE,
                           detail=f"schema {declared_schema!r} is not {ARTIFACT_SCHEMA!r}",
                           may_display_as_live=False,
                           remediation="migrate the artefact to the current schema")

        return self.bind(name, payload)