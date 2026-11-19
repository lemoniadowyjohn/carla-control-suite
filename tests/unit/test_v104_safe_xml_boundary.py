"""V104 — security regression tests for the V103-O1 evidence runners.

CodeQL findings 4551601346 and 4551601397: the evidence runners parsed
untrusted map bytes with ``xml.etree.ElementTree`` directly.  They now use
``reports/v103/o1/safe_xml.py``, which rejects a DOCTYPE/ENTITY declaration
in **every** supported encoding and over the **whole** file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "reports" / "v103" / "o1"))

from safe_xml import (  # noqa: E402
    MAX_XML_BYTES,
    UnsafeXMLError,
    find_doctype_or_entity,
    safe_parse,
)


def _write(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_plain_document_is_accepted(tmp_path):
    path = _write(tmp_path, "ok.xodr", b"<OpenDRIVE><road id='1'/></OpenDRIVE>")
    root = safe_parse(path)
    assert root.tag == "OpenDRIVE"


def test_ascii_doctype_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        "dtd.xodr",
        b"<!DOCTYPE OpenDRIVE [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]>"
        b"<OpenDRIVE/>",
    )
    with pytest.raises(UnsafeXMLError, match="DOCTYPE/ENTITY"):
        safe_parse(path)


def test_utf16_doctype_is_rejected(tmp_path):
    payload = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE OpenDRIVE [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        "<OpenDRIVE/>"
    )
    path = _write(tmp_path, "utf16.xodr", payload.encode("utf-16"))
    with pytest.raises(UnsafeXMLError, match="DOCTYPE/ENTITY"):
        safe_parse(path)


def test_utf16le_without_bom_is_rejected(tmp_path):
    payload = (
        '<!DOCTYPE OpenDRIVE [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        "<OpenDRIVE/>"
    )
    path = _write(tmp_path, "utf16le.xodr", payload.encode("utf-16-le"))
    with pytest.raises(UnsafeXMLError, match="DOCTYPE/ENTITY"):
        safe_parse(path)


def test_doctype_beyond_a_length_window_is_still_rejected(tmp_path):
    """The scan covers the whole file, not a bounded prefix."""
    padding = b"<!-- " + (b"x" * (1 << 16)) + b" -->"
    payload = b"<OpenDRIVE>" + padding + b"<!DOCTYPE x>" + b"</OpenDRIVE>"
    path = _write(tmp_path, "late.xodr", payload)
    assert len(payload) > (1 << 16)
    with pytest.raises(UnsafeXMLError, match="DOCTYPE/ENTITY"):
        safe_parse(path)


def test_oversized_document_is_rejected(tmp_path, monkeypatch):
    import safe_xml

    monkeypatch.setattr(safe_xml, "MAX_XML_BYTES", 16)
    path = _write(tmp_path, "big.xodr", b"<OpenDRIVE>" + b"x" * 64 + b"</OpenDRIVE>")
    with pytest.raises(UnsafeXMLError, match="limit"):
        safe_parse(path)


def test_literal_text_in_comments_and_cdata_is_allowed(tmp_path):
    payload = (
        b"<!-- a comment mentioning <!DOCTYPE but not as a declaration -->"
        b"<OpenDRIVE><road id='1'><!-- inner --></road></OpenDRIVE>"
    )
    path = _write(tmp_path, "comment.xodr", payload)
    root = safe_parse(path)
    assert root.tag == "OpenDRIVE"


def test_find_helper_reports_the_encoding(tmp_path):
    assert find_doctype_or_entity(b"<!DOCTYPE x>") == "decoded"
    assert find_doctype_or_entity(b"<!doctype x>") == "decoded"
    assert find_doctype_or_entity(b"<!ENTITY x>") == "decoded"
    assert find_doctype_or_entity("<!DOCTYPE x>".encode("utf-16")) == "decoded"
    assert find_doctype_or_entity(b"<OpenDRIVE/>") is None
    # Literal declaration text inside a comment is not a declaration.
    assert (
        find_doctype_or_entity(b"<!-- <!DOCTYPE x> --><OpenDRIVE/>") is None
    )
