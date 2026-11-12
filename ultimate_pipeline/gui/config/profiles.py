"""Profile import / export / diff with atomic writes, backups and migrations.

Guarantees:

* **Atomic** -- every write goes to a temp file then ``os.replace``.
* **Backed up** -- the previous file is preserved before an overwrite.
* **Migrated** -- a schema version is always declared; an unknown version is
  rejected rather than guessed at.
* **Round-trip** -- ``export -> import -> export`` is byte-identical for values
  the registry knows. ``settings.Settings.to_dict`` has no inverse; this module
  supplies one.
* **No silent loss** -- dropping a field on load is an error, not a merge.
* **Secrets stay opaque** -- a SECRET-classified value is exported as a
  reference marker, never the literal.
* **No silent env override** -- an import reports staged vs effective values and
  the precedence rule, and requires explicit confirmation for irreversible keys.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ultimate_pipeline.gui.config.metadata import (
    UNSET,
    SettingsRegistry,
    env_name_for,
    live_value,
    load_registry,
)
from ultimate_pipeline.gui.config.validation import (
    Severity,
    ValidationReport,
    validate_profile,
)

__all__ = [
    "PROFILE_SCHEMA", "SUPPORTED_SCHEMA_VERSIONS", "SECRET_MARKER",
    "ProfileError", "UnknownSchemaVersion", "FieldLossError", "Precedence",
    "StagedValue", "ProfileDiff", "Profile", "ProfileStore",
]

PROFILE_SCHEMA = "carla-gui-profile/v1"
SUPPORTED_SCHEMA_VERSIONS = (1,)
SECRET_MARKER = "[SECRET_REFERENCE_NOT_EXPORTED]"


class ProfileError(Exception):
    """Base class for profile failures. Never swallowed by an adapter."""


class UnknownSchemaVersion(ProfileError):
    pass


class FieldLossError(ProfileError):
    pass


@dataclass(frozen=True)
class Precedence:
    """Where a value actually comes from."""

    ENV = "ENVIRONMENT"
    PROFILE = "PROFILE"
    DEFAULT = "DEFAULT"
    UNBOUND = "UNBOUND"

    @property
    def rank(self) -> int:
        return {Precedence.ENV: 3, Precedence.PROFILE: 2,
                Precedence.DEFAULT: 1, Precedence.UNBOUND: 0}[self]


@dataclass(frozen=True)
class StagedValue:
    """A proposed value plus what would actually win."""

    setting_id: str
    staged: Any
    effective: Any
    precedence: str
    env_name: str = ""
    shadowed_by_env: bool = False

    def as_dict(self) -> dict:
        return {
            "setting_id": self.setting_id,
            "staged": self.staged,
            "effective": self.effective,
            "precedence": self.precedence,
            "env_name": self.env_name,
            "shadowed_by_env": self.shadowed_by_env,
        }


@dataclass(frozen=True)
class ProfileDiff:
    added: dict[str, Any]
    changed: dict[str, tuple[Any, Any]]
    removed: tuple[str, ...]
    secret_count: int
    shadowed_by_env: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "added": self.added,
            "changed": {k: list(v) for k, v in self.changed.items()},
            "removed": list(self.removed),
            "secret_count": self.secret_count,
            "shadowed_by_env": list(self.shadowed_by_env),
        }

    def __bool__(self) -> bool:
        return bool(self.added or self.changed or self.removed)


@dataclass
class Profile:
    """A staged, not-yet-applied set of settings."""

    name: str
    values: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SUPPORTED_SCHEMA_VERSIONS[0]

    def to_payload(self) -> dict:
        return {
            "schema": PROFILE_SCHEMA,
            "schema_version": self.schema_version,
            "name": self.name,
            "values": dict(sorted(self.values.items())),
        }


class ProfileStore:
    """Atomic, backed-up, versioned profile persistence."""

    def __init__(self, root: Path, registry: SettingsRegistry | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry = registry or load_registry()

    # -- paths ------------------------------------------------------------
    def path_for(self, name: str) -> Path:
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_.")
        if not safe:
            raise ProfileError(f"unsafe profile name: {name!r}")
        return self.root / f"{safe}.json"

    # -- atomic write ------------------------------------------------------
    def _atomic_write(self, target: Path, text: str) -> None:
        tmp = target.with_suffix(target.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)

    def _backup(self, target: Path) -> Path | None:
        if not target.exists():
            return None
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        backup = target.with_suffix(f".{stamp}.bak")
        shutil.copy2(target, backup)
        return backup

    # -- export ------------------------------------------------------------
    def export(self, profile: Profile) -> dict[str, Any]:
        """Write a profile. Secret values are replaced by a reference marker."""
        values: dict[str, Any] = {}
        secrets = 0
        for setting_id, value in sorted(profile.values.items()):
            meta = self.registry.one(setting_id)
            if meta is None:
                raise ProfileError(f"unknown setting id in export: {setting_id}")
            if meta.safety_class == "SECRET":
                secrets += 1
                values[setting_id] = SECRET_MARKER
            else:
                values[setting_id] = value
        payload = {
            "schema": PROFILE_SCHEMA,
            "schema_version": profile.schema_version,
            "name": profile.name,
            "values": values,
            "secret_values_withheld": secrets,
        }
        target = self.path_for(profile.name)
        backup = self._backup(target)
        self._atomic_write(target, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return {"path": str(target), "backup": str(backup) if backup else None,
                "secret_values_withheld": secrets}

    # -- import ------------------------------------------------------------
    def load(self, name: str) -> Profile:
        path = self.path_for(name)
        if not path.is_file():
            raise ProfileError(f"no such profile: {name}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProfileError(f"corrupt profile {name}: {exc}") from exc
        return self.from_payload(payload, source=str(path))

    def from_payload(self, payload: Any, source: str = "<memory>") -> Profile:
        if not isinstance(payload, dict):
            raise ProfileError(f"{source}: profile must be a JSON object")
        schema = payload.get("schema")
        if schema != PROFILE_SCHEMA:
            raise UnknownSchemaVersion(
                f"{source}: unsupported profile schema {schema!r}; expected {PROFILE_SCHEMA!r}"
            )
        version = payload.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnknownSchemaVersion(
                f"{source}: unsupported schema_version {version!r}; "
                f"supported: {list(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        raw_values = payload.get("values")
        if not isinstance(raw_values, dict):
            raise ProfileError(f"{source}: 'values' must be an object")

        missing = [f for f in ("schema", "schema_version", "name", "values") if f not in payload]
        if missing:
            raise FieldLossError(f"{source}: required fields missing: {missing}")

        # Strict top-level schema: an unknown top-level key means the producer
        # wrote something this reader does not understand. Silently accepting it
        # would let a future format silently lose data on re-export.
        allowed = {"schema", "schema_version", "name", "values", "secret_values_withheld"}
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise FieldLossError(
                f"{source}: unexpected top-level field(s) {unexpected}; "
                "refusing to import a format this reader does not fully understand"
            )

        for key in raw_values:
            if self.registry.one(key) is None:
                raise ProfileError(f"{source}: unknown setting id {key!r} (refusing to drop it)")

        report = validate_profile(raw_values, self.registry)
        errors = [i for i in report.issues if i.severity == Severity.ERROR]
        if errors:
            raise ProfileError(
                f"{source}: validation failed: "
                + "; ".join(f"{e.setting_id}: {e.message}" for e in errors)
            )

        values = dict(raw_values)
        if values != {k: v for k, v in sorted(values.items())}:
            raise FieldLossError(f"{source}: values did not round-trip byte-identically")
        return Profile(name=str(payload["name"]), values=values, schema_version=version)

    # -- diff and precedence ----------------------------------------------
    def diff(self, current: Profile, incoming: Profile) -> ProfileDiff:
        a, b = current.values, incoming.values
        added = {k: b[k] for k in b if k not in a}
        changed = {k: (a[k], b[k]) for k in b if k in a and a[k] != b[k]}
        removed = tuple(sorted(k for k in a if k not in b))
        secrets = sum(
            1 for k in set(b) | set(a)
            if (self.registry.one(k) and self.registry.one(k).safety_class == "SECRET")
        )
        shadowed = tuple(sorted(k for k in b if env_name_for(k) in os.environ))
        return ProfileDiff(added, changed, removed, secrets, shadowed)

    def stage(self, values: dict[str, Any], env: dict[str, str] | None = None) -> list[StagedValue]:
        """Present staged vs effective with explicit precedence.

        A profile value shadowed by an environment variable is flagged so the
        UI can say so instead of silently appearing to do nothing.
        """
        environ = os.environ if env is None else env
        staged: list[StagedValue] = []
        for setting_id, value in sorted(values.items()):
            meta = self.registry.one(setting_id)
            binds_to = meta.binds_to if meta else "UNBOUND"
            env_name = env_name_for(setting_id)
            if env_name in environ:
                staged.append(StagedValue(
                    setting_id, value, environ[env_name], Precedence.ENV, env_name, True
                ))
                continue
            effective = live_value(setting_id, binds_to)
            if effective is UNSET:
                staged.append(StagedValue(setting_id, value, None, Precedence.UNBOUND))
            else:
                staged.append(StagedValue(setting_id, value, effective, Precedence.PROFILE))
        return staged

    def requires_confirmation(self, values: dict[str, Any]) -> tuple[str, ...]:
        """Irreversible or secret-classified ids that need typed confirmation."""
        out = []
        for setting_id in sorted(values):
            meta = self.registry.one(setting_id)
            if meta and meta.safety_class in ("IRREVERSIBLE", "SECRET"):
                out.append(setting_id)
        return tuple(out)

    def report(self, values: dict[str, Any], env: dict[str, str] | None = None) -> ValidationReport:
        return validate_profile(values, self.registry)