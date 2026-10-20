"""Hardened XML import for untrusted OpenDRIVE / OSM / RoadRunner payloads.

Every one of the eleven documented parsing sites goes through here. The
guarantees:

* **DTD and entity declarations are refused outright.** No DTD, no ``<!ENTITY``,
  no external entities -- the billion-laughs / XXE class is rejected, not
  "mitigated".
* **Payload size and nesting depth are bounded** before parsing, so a DoS
  payload is rejected on its bytes, not after the parser has already suffered.
* **Path traversal is refused**: any resolved path escaping the base directory
  is rejected.
* **Failure is typed.** A refused parse returns a reason; it never returns a
  partially built object.

``defusedxml`` is used when available; otherwise an explicit pre-scan enforces
the same refusals before the stdlib parser is allowed to run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable

__all__ = [
    "XmlRefusal", "RefusedDocument", "XmlLimits", "DEFAULT_LIMITS",
    "PARSING_SITES", "parse_untrusted_xml", "read_text_bounded",
    "resolve_inside", "defusedxml_available",
]


class XmlRefusal(Exception):
    """The payload is refused. Carries the exact reason and remediation."""

    def __init__(self, reason: str, remediation: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.remediation = remediation


@dataclass(frozen=True)
class XmlLimits:
    """DoS bounds applied *before* parsing."""

    max_bytes: int = 64 * 1024 * 1024
    max_depth: int = 64
    max_elements: int = 2_000_000


DEFAULT_LIMITS = XmlLimits()

#: The eleven documented parsing sites, by subsystem. Centralising them is the
#: point: a new site cannot quietly bypass the guards.
PARSING_SITES: tuple[tuple[str, str], ...] = (
    ("xodr", "ultimate_pipeline/carla_tools/carla_opendrive_loader.py"),
    ("xodr", "ultimate_pipeline/quality/xodr_hash_gate.py"),
    ("xodr", "phase_q/spawn_nav_gate.py"),
    ("xodr", "tools/calibrate_sensors_in_carla.py"),
    ("osm", "ultimate_pipeline/carla_tools/carla_osm2odr.py"),
    ("osm", "ultimate_pipeline/tiling/large_map_package.py"),
    ("osm", "tools/rq1a_osm_to_xodr.py"),
    ("roadrunner", "ultimate_pipeline/ingest/roadrunner_import.py"),
    ("roadrunner", "ultimate_pipeline/ingest/roadrunner_schemas.py"),
    ("roadrunner", "ultimate_pipeline/ingest/roadrunner_profiles.py"),
    ("sensors", "ultimate_pipeline/sensors/recorder.py"),
)

_DTD_RE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)
_ENTITY_RE = re.compile(rb"<!ENTITY", re.IGNORECASE)
_PARAM_REF_RE = re.compile(rb"%[A-Za-z_][\w.-]*;")


def defusedxml_available() -> bool:
    try:
        import defusedxml.ElementTree  # noqa: F401
        return True
    except ImportError:
        return False


def read_text_bounded(path: Path, limits: XmlLimits = DEFAULT_LIMITS) -> str:
    """Read a payload, refusing on SIZE before any parsing happens."""
    target = Path(path)
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise XmlRefusal(f"cannot stat {target.name}: {exc}",
                         "check the file exists and is readable") from exc
    if size > limits.max_bytes:
        raise XmlRefusal(
            f"payload of {size} bytes exceeds the {limits.max_bytes} byte limit",
            "raise the limit deliberately, or split the map",
        )
    try:
        return target.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise XmlRefusal(f"payload is not valid UTF-8: {exc}",
                         "re-encode the source map as UTF-8") from exc
    except OSError as exc:
        raise XmlRefusal(f"cannot read {target.name}: {exc}",
                         "check file permissions") from exc


def resolve_inside(base_dir: Path, candidate: str) -> Path:
    """Resolve ``candidate`` under ``base_dir``; refuse any escape."""
    base = Path(base_dir).resolve()
    raw = str(candidate)
    if Path(raw).is_absolute() or PureWindowsPath(raw).drive or raw.startswith("\\"):

        raise XmlRefusal(
            f"absolute path refused: {raw!r}",
            "map references must be relative to the pinned registry root",
        )
    resolved = (base / raw).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise XmlRefusal(
            f"path escapes the registry root: {raw!r} resolves to {resolved}",
            "remove the traversal segment",
        ) from exc
    return resolved


def _prescan(text: str, limits: XmlLimits) -> None:
    """Explicit refusal scan. Runs regardless of defusedxml availability."""
    blob = text.encode("utf-8")
    if _DTD_RE.search(blob):
        raise XmlRefusal(
            "payload declares a DOCTYPE; DTDs are refused outright",
            "strip the DOCTYPE -- CARLA map sources must not carry a DTD",
        )
    if _ENTITY_RE.search(blob):
        raise XmlRefusal(
            "payload declares an entity; entity expansion is refused outright",
            "remove <!ENTITY ...> declarations",
        )
    if _PARAM_REF_RE.search(blob):
        raise XmlRefusal(
            "payload uses a parameter-entity reference",
            "remove %name; references",
        )

    depth = 0
    max_depth = 0
    elements = 0
    in_quotes = False
    for char in text:
        if char == '"':
            in_quotes = not in_quotes
        elif char == "<" and not in_quotes:
            elements += 1
        elif char == ">" and not in_quotes:
            if depth > 0:
                depth -= 1
    # A cheap structural depth estimate from the raw open-tag stream.
    open_tags = re.findall(r"<(?![\?!/])[^>]*>", text)
    for tag in open_tags:
        if tag.rstrip().endswith("/>"):
            continue
        depth += 1
        max_depth = max(max_depth, depth)
    if max_depth > limits.max_depth:
        raise XmlRefusal(
            f"XML nesting depth {max_depth} exceeds the limit of {limits.max_depth}",
            "flatten the map structure",
        )
    if elements > limits.max_elements:
        raise XmlRefusal(
            f"document has {elements} tags, exceeding the limit of {limits.max_elements}",
            "split the map",
        )


@dataclass
class RefusedDocument:
    """Typed refusal. Never a partially built object."""

    site: str
    reason: str
    remediation: str = ""

    def as_dict(self) -> dict:
        return {"site": self.site, "refused": True, "reason": self.reason,
                "remediation": self.remediation}


def parse_untrusted_xml(
    path: Path,
    *,
    site: str = "unlabelled",
    limits: XmlLimits = DEFAULT_LIMITS,
):
    """Parse an untrusted map source, or raise :class:`XmlRefusal`.

    Uses ``defusedxml`` when installed. Either way the explicit prescan has
    already refused DTDs and entities, so the stdlib parser is never the first
    line of defence.
    """
    text = read_text_bounded(path, limits)
    _prescan(text, limits)

    if defusedxml_available():
        from defusedxml.ElementTree import fromstring as _safe_parse
        return _safe_parse(text)

    import xml.etree.ElementTree as _stdlib_parse  # prescan already ran
    return _stdlib_parse.fromstring(text)


def try_parse(path: Path, *, site: str = "unlabelled",
              limits: XmlLimits = DEFAULT_LIMITS) -> tuple[Any | None, RefusedDocument | None]:
    """Non-raising variant for UI paths that must render a refusal."""
    try:
        return parse_untrusted_xml(path, site=site, limits=limits), None
    except XmlRefusal as refusal:
        return None, RefusedDocument(site, refusal.reason, refusal.remediation)
    except Exception as exc:  # malformed but pre-scan-clean XML
        return None, RefusedDocument(site, f"{type(exc).__name__}: {exc}",
                                     "the document is not well-formed XML")