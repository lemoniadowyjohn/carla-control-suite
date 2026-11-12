"""Safe XML parsing for the V103-O1 evidence runners.

V104 security finding (CodeQL `python.lang.security.use-defused-xml-parse`):
the evidence runners used ``xml.etree.ElementTree.parse`` directly on
untrusted map bytes.

``defusedxml`` is not installed in this environment, so this module provides
an equivalent, self-contained guard:

* the raw bytes are scanned for a DOCTYPE or ENTITY declaration **in every
  encoding the file may actually use** (ASCII/UTF-8, UTF-16LE, UTF-16BE) --
  a UTF-16 encoded declaration is NOT matched by an ASCII byte pattern;
* the scan covers the **whole** file, not a bounded prefix, so a
  declaration cannot be hidden past a length limit;
* the size is bounded;
* only then is the document parsed.

A DOCTYPE or ENTITY declaration is rejected outright: OpenDRIVE never needs
one, and it is the vector for entity-expansion and external-entity attacks.
"""

from __future__ import annotations

import os
import re
from typing import Optional

__all__ = [
    "UnsafeXMLError",
    "MAX_XML_BYTES",
    "find_doctype_or_entity",
    "safe_parse",
]

#: Hard upper bound on the document size we will scan and parse.
MAX_XML_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB

_ASCII_DECL = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_UTF16LE_DECL = re.compile(rb"<\x00!\x00(?:D\x00O\x00C\x00T\x00Y\x00P\x00E\x00|E\x00N\x00T\x00I\x00T\x00Y\x00)", re.IGNORECASE)
_UTF16BE_DECL = re.compile(rb"\x00<\x00!\x00(?:D\x00O\x00C\x00T\x00Y\x00P\x00E\x00|\x00E\x00N\x00T\x00I\x00T\x00Y\x00)", re.IGNORECASE)

#: Comment and CDATA sections are not markup: literal ``<!DOCTYPE`` text
#: inside them is harmless and must be allowed.
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CDATA = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)
_DECL_TEXT = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


class UnsafeXMLError(ValueError):
    """The XML document violates the admission boundary."""


def _decode(data: bytes) -> tuple[str, bool]:
    """Decode the document with the encoding it actually uses.

    Returns ``(text, decoded_cleanly)``.  ``decoded_cleanly`` is False only
    when the bytes are not text in any encoding we recognise, in which case
    the document is rejected rather than scanned heuristically.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace"), True
    if data[:3] == b"\xef\xbb\xbf":
        return data.decode("utf-8-sig", errors="replace"), True

    # An XML declaration may name the encoding even without a BOM.
    head = data[:200].decode("ascii", errors="replace")
    match = re.search(r'encoding\s*=\s*["\']([\w-]+)["\']', head)
    if match:
        name = match.group(1).lower()
        if name in {"utf-16", "utf-16le", "utf-16be"}:
            try:
                return data.decode("utf-16"), True
            except Exception:
                return data.decode("utf-16", errors="replace"), True
        if name in {"latin-1", "iso-8859-1"}:
            return data.decode("latin-1", errors="replace"), True

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        # UTF-8 decoding succeeds on UTF-16LE bytes (the NUL bytes are valid
        # UTF-8 codepoints), so a document that still contains NUL bytes is
        # almost certainly UTF-16 without a BOM.  Re-decode it: the ASCII
        # spelling of a declaration would otherwise be interleaved with NUL
        # bytes and invisible to the scan.
        if "\x00" in text:
            for codec in ("utf-16-le", "utf-16-be"):
                try:
                    candidate = data.decode(codec)
                except Exception:
                    continue
                if "\x00" in candidate:
                    continue
                if "<" in candidate:
                    return candidate, True
        return text, True

    # A UTF-16 document without a BOM and without a declaration: the NUL
    # bytes give it away.
    if b"\x00" in data[:200]:
        for codec in ("utf-16-le", "utf-16-be"):
            try:
                return data.decode(codec), True
            except Exception:
                continue

    return data.decode("latin-1", errors="replace"), False


def find_doctype_or_entity(data: bytes) -> Optional[str]:
    """Return the offending declaration kind, or ``None`` when the document
    carries no DOCTYPE/ENTITY declaration in any supported encoding.

    The scan is performed on the *decoded* document with comment and CDATA
    sections removed, so:

    * literal ``<!DOCTYPE`` text inside a comment or a CDATA section is
      allowed (it is not markup);
    * a UTF-16 encoded declaration is detected (an ASCII byte pattern alone
      would miss it);
    * the scan covers the **whole** document, so a declaration cannot be
      hidden past a length window.

    A document that cannot be decoded as text is reported as
    ``"undecodable"`` and is rejected by the caller -- the boundary never
    falls back to a heuristic byte scan that would both miss UTF-16
    declarations and false-positive on comments.
    """
    text, decoded_cleanly = _decode(data)
    stripped = _CDATA.sub(" ", _COMMENT.sub(" ", text))
    if _DECL_TEXT.search(stripped):
        return "decoded"
    if not decoded_cleanly:
        return "undecodable"
    return None


def safe_parse(path: str | os.PathLike[str]):
    """Parse an XML document after enforcing the admission boundary.

    Raises :class:`UnsafeXMLError` for an oversized document or for any
    DOCTYPE / ENTITY declaration, in any supported encoding.
    """
    target = os.fspath(path)
    size = os.path.getsize(target)
    if size > MAX_XML_BYTES:
        raise UnsafeXMLError(
            f"artifact is {size} bytes > limit {MAX_XML_BYTES}"
        )
    with open(target, "rb") as handle:
        data = handle.read()

    kind = find_doctype_or_entity(data)
    if kind is not None:
        raise UnsafeXMLError(
            "DOCTYPE/ENTITY declarations are not permitted in this input "
            f"(encoding: {kind})"
        )

    import xml.etree.ElementTree as ET

    return ET.fromstring(data)
