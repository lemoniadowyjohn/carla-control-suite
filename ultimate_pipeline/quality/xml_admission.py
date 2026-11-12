"""Bounded, encoding-aware XML admission for untrusted OpenDRIVE bytes.

The parser rejects DTDs before any entity declaration can be used and never
resolves external entities. It builds the ElementTree consumed by quality
checks from the same Expat parse, avoiding a second parser with weaker policy.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat
from pathlib import Path

MAX_XODR_BYTES = 512 * 1024 * 1024
MAX_XML_DEPTH = 256
MAX_XML_ELEMENTS = 5_000_000
MAX_XML_ATTRIBUTES_PER_ELEMENT = 512

_SUPPORTED_ENCODINGS = {"UTF-8", "UTF8", "UTF-16", "UTF-16LE", "UTF-16BE"}


class UnsafeXMLError(ValueError):
    """The XML input is malformed, unsupported, unsafe, or outside limits."""


def _expanded_name(name: str) -> str:
    # Expat namespace mode returns ``uri}local``; ElementTree uses ``{uri}local``.
    return "{" + name if "}" in name and not name.startswith("{") else name


def _parse(data: bytes, *, build_tree: bool) -> ET.Element | None:
    if not isinstance(data, bytes):
        raise TypeError("OpenDRIVE input must be immutable bytes")
    if not data:
        raise UnsafeXMLError("OpenDRIVE input is empty")
    if len(data) > MAX_XODR_BYTES:
        raise UnsafeXMLError(
            f"OpenDRIVE input is {len(data)} bytes; limit is {MAX_XODR_BYTES}"
        )

    builder = ET.TreeBuilder() if build_tree else None
    parser = expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True
    parser.ordered_attributes = False

    depth = 0
    elements = 0
    root_name: str | None = None

    def reject_declaration(*_args: object) -> None:
        raise UnsafeXMLError("DOCTYPE and entity declarations are forbidden")

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal depth, elements, root_name
        depth += 1
        elements += 1
        if depth > MAX_XML_DEPTH:
            raise UnsafeXMLError(f"XML nesting exceeds {MAX_XML_DEPTH}")
        if elements > MAX_XML_ELEMENTS:
            raise UnsafeXMLError(f"XML element count exceeds {MAX_XML_ELEMENTS}")
        if len(attrs) > MAX_XML_ATTRIBUTES_PER_ELEMENT:
            raise UnsafeXMLError(
                f"XML element has more than {MAX_XML_ATTRIBUTES_PER_ELEMENT} attributes"
            )
        expanded = _expanded_name(name)
        if root_name is None:
            root_name = expanded
        if builder is not None:
            builder.start(expanded, {_expanded_name(k): v for k, v in attrs.items()})

    def end(name: str) -> None:
        nonlocal depth
        if builder is not None:
            builder.end(_expanded_name(name))
        depth -= 1

    def data_handler(value: str) -> None:
        if builder is not None and value:
            builder.data(value)

    def xml_declaration(_version: str, encoding: str | None, _standalone: int) -> None:
        if encoding is not None and encoding.upper().replace("_", "-") not in _SUPPORTED_ENCODINGS:
            raise UnsafeXMLError(f"unsupported XML encoding {encoding!r}")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = data_handler
    parser.XmlDeclHandler = xml_declaration
    parser.StartDoctypeDeclHandler = reject_declaration
    parser.EntityDeclHandler = reject_declaration
    parser.UnparsedEntityDeclHandler = reject_declaration
    parser.ExternalEntityRefHandler = reject_declaration
    parser.SkippedEntityHandler = reject_declaration
    parser.CommentHandler = lambda _text: None
    if not parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER):
        raise UnsafeXMLError("Expat could not disable parameter-entity parsing")

    try:
        parser.Parse(data, True)
    except UnsafeXMLError:
        raise
    except (expat.ExpatError, LookupError, UnicodeError, ValueError) as exc:
        raise UnsafeXMLError(f"XML admission failed: {exc}") from exc

    if root_name != "OpenDRIVE":
        raise UnsafeXMLError(f"expected OpenDRIVE root, found {root_name!r}")
    if builder is None:
        return None
    try:
        root = builder.close()
    except Exception as exc:
        raise UnsafeXMLError(f"cannot construct OpenDRIVE tree: {exc}") from exc
    if not isinstance(root, ET.Element):
        raise UnsafeXMLError("XML parser produced no document root")
    return root


def check_xml_boundary(data: bytes) -> None:
    """Validate complete syntax, encoding, declarations and complexity limits."""
    _parse(data, build_tree=False)


def parse_xodr_bytes(data: bytes) -> ET.Element:
    """Return a tree built by the same hardened parser that enforces policy."""
    root = _parse(data, build_tree=True)
    assert root is not None
    return root


def read_xodr_bytes(path: str | os.PathLike[str]) -> bytes:
    """Read one bounded file snapshot and reject concurrent in-place changes."""
    target = Path(path)
    try:
        with target.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if before.st_size > MAX_XODR_BYTES:
                raise UnsafeXMLError(
                    f"OpenDRIVE file is {before.st_size} bytes; limit is {MAX_XODR_BYTES}"
                )
            data = stream.read(MAX_XODR_BYTES + 1)
            after = os.fstat(stream.fileno())
    except UnsafeXMLError:
        raise
    except OSError as exc:
        raise UnsafeXMLError(f"cannot read OpenDRIVE input: {exc}") from exc
    if len(data) > MAX_XODR_BYTES:
        raise UnsafeXMLError(f"OpenDRIVE file exceeds {MAX_XODR_BYTES} bytes")
    before_identity = (before.st_size, before.st_mtime_ns, getattr(before, "st_ino", 0))
    after_identity = (after.st_size, after.st_mtime_ns, getattr(after, "st_ino", 0))
    if before_identity != after_identity or len(data) != after.st_size:
        raise UnsafeXMLError("OpenDRIVE file changed while it was being read")
    return data


def parse_xodr_file(path: str | os.PathLike[str]) -> ET.Element:
    """Read and parse a path through the bounded OpenDRIVE admission policy."""
    return parse_xodr_bytes(read_xodr_bytes(path))


@contextmanager
def admitted_xodr_snapshot(data: bytes, *, parent: str | os.PathLike[str] | None = None):
    """Expose admitted bytes to path-based legacy gates through a private snapshot.

    Several established quality gates accept a path and reopen it internally.
    Giving those gates the caller's mutable candidate path would let them
    inspect different bytes from the tree parsed at admission. This helper
    writes the already bounded and admitted bytes into a unique private temp
    directory and keeps that snapshot alive for the complete gate pass.
    """
    if not isinstance(data, bytes) or len(data) > MAX_XODR_BYTES:
        raise UnsafeXMLError("invalid or oversized admitted OpenDRIVE snapshot")
    # Co-locate with the candidate by default so large-map validation does not
    # unexpectedly consume a small system-temp volume.
    with tempfile.TemporaryDirectory(
        prefix="up-admitted-xodr-", dir=os.fspath(parent) if parent is not None else None
    ) as directory:
        snapshot = Path(directory) / "admitted.xodr"
        with snapshot.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            snapshot.chmod(0o400)
        except OSError:
            # The private directory remains isolated on platforms that do not
            # support POSIX permission bits (notably Windows).
            pass
        yield snapshot
