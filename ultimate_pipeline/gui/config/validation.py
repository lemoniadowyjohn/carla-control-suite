"""Strict validation for staged settings.

Rules that matter:

* A range or enum is enforced **only** when the registry says it is known. The
  registry currently reports ``range_is_known = False`` for all 318 entries
  because the repository has no validation layer, so this module reports
  ``UNKNOWN`` rather than inventing bounds.
* An unknown setting id is a hard error, never a silent drop.
* A value whose type cannot be checked is reported as ``UNVERIFIED``, not
  accepted quietly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ultimate_pipeline.gui.config.metadata import (
    UNSET,
    SettingMeta,
    SettingsRegistry,
    load_registry,
)

__all__ = ["Severity", "ValidationIssue", "ValidationReport", "validate_setting",
           "validate_profile", "coerce_for_declared_type"]


class Severity:
    ERROR = "ERROR"
    WARNING = "WARNING"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class ValidationIssue:
    setting_id: str
    severity: str
    message: str
    remediation: str = ""

    def as_dict(self) -> dict:
        return {"setting_id": self.setting_id, "severity": self.severity,
                "message": self.message, "remediation": self.remediation}


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not any(i.severity == Severity.ERROR for i in self.issues)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == Severity.ERROR)

    @property
    def unverified(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == Severity.UNVERIFIED)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "issues": [i.as_dict() for i in self.issues]}


_BOOLISH = {"true": True, "false": False, "1": True, "0": False,
            "yes": True, "no": False, "on": True, "off": False}


def coerce_for_declared_type(value: Any, python_type: str | None) -> tuple[Any, bool]:
    """Coerce a JSON scalar to the declared type.

    Returns ``(value, coerced_ok)``. A type that is not declared, or a value
    that cannot be represented, is returned unchanged with ``coerced_ok=False``
    so the caller can report ``UNVERIFIED`` instead of pretending.
    """
    if python_type is None:
        return value, False
    kind = python_type.strip().lower()
    if isinstance(value, str):
        text = value.strip()
        if kind == "bool":
            if text.lower() in _BOOLISH:
                return _BOOLISH[text.lower()], True
            return value, False
        if kind == "int":
            try:
                return int(text), True
            except ValueError:
                return value, False
        if kind == "float":
            try:
                return float(text), True
            except ValueError:
                return value, False
        if kind == "str":
            return value, True
    if kind == "bool" and isinstance(value, bool):
        return value, True
    if kind == "int" and isinstance(value, int) and not isinstance(value, bool):
        return value, True
    if kind == "float" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), True
    if kind == "str" and isinstance(value, str):
        return value, True
    return value, False


def validate_setting(meta: SettingMeta, value: Any) -> ValidationIssue | None:
    """Validate one staged value against its metadata."""
    if value is UNSET:
        return ValidationIssue(
            meta.setting_id, Severity.UNVERIFIED,
            "no value staged and no default expression could be evaluated",
            "record a value, or leave UNSET and surface it as UNBOUND",
        )

    issues: list[ValidationIssue] = []

    coerced, ok = coerce_for_declared_type(value, meta.python_type)
    if meta.python_type and not ok:
        issues.append(ValidationIssue(
            meta.setting_id, Severity.UNVERIFIED,
            f"value {value!r} could not be checked against declared type {meta.python_type!r}",
            "fix the type, or widen the declared type in the registry",
        ))

    if meta.duplicated:
        issues.append(ValidationIssue(
            meta.setting_id, Severity.WARNING,
            f"declared at {meta.declaration_sites} sites; changing it may not take effect everywhere",
            "verify every declaration site after apply",
        ))

    # Range/enum is enforced ONLY when the registry knows it. It currently does
    # not, so this is an explicit UNVERIFIED rather than a fabricated bound.
    if not meta.range_is_known:
        issues.append(ValidationIssue(
            meta.setting_id, Severity.UNVERIFIED,
            f"range/enum is UNKNOWN ({meta.range_or_enum or 'not recorded'})",
            "add a validated range to the registry, or accept the value unverified",
        ))

    if meta.safety_class == "SECRET":
        issues.append(ValidationIssue(
            meta.setting_id, Severity.WARNING,
            "secret-classified setting; the value must never be exported",
            "store a reference, never the literal",
        ))

    if meta.safety_class == "IRREVERSIBLE":
        issues.append(ValidationIssue(
            meta.setting_id, Severity.WARNING,
            "irreversible setting; applying requires typed confirmation",
            "require DESTRUCTIVE_IRREVERSIBLE confirmation at apply time",
        ))

    if not meta.is_editable:
        issues.append(ValidationIssue(
            meta.setting_id, Severity.ERROR,
            meta.disabled_reason or "not editable",
            "no GUI write target; fix the declaration site",
        ))

    errors = [i for i in issues if i.severity == Severity.ERROR]
    if errors:
        return errors[0]
    # Report the most actionable issue, not merely the first one appended. A
    # type mismatch must not mask an irreversible-setting warning.
    order = {Severity.WARNING: 0, Severity.UNVERIFIED: 1}
    ranked = sorted(issues, key=lambda i: order.get(i.severity, 99))
    return ranked[0] if ranked else None


def validate_profile(values: dict[str, Any], registry: SettingsRegistry | None = None) -> ValidationReport:
    """Validate a whole profile payload. Unknown ids are hard errors."""
    reg = registry or load_registry()
    issues: list[ValidationIssue] = []
    for setting_id, value in sorted(values.items()):
        entries = reg.by_id(setting_id)
        if not entries:
            issues.append(ValidationIssue(
                setting_id, Severity.ERROR,
                "unknown setting id; it is not in the versioned registry",
                "reject the import rather than dropping the key silently",
            ))
            continue
        issue = validate_setting(entries[0], value)
        if issue is not None:
            issues.append(issue)
    return ValidationReport(tuple(issues))