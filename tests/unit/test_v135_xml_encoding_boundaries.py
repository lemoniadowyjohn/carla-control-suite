"""F08 XML encoding/DTD/UTF-16 boundary tests (V135, test-only)."""
from __future__ import annotations

import pytest

from ultimate_pipeline.quality.xml_admission import (
    UnsafeXMLError,
    check_xml_boundary,
    parse_xodr_bytes,
)

MINIMAL_XODR_UTF8 = b'<?xml version="1.0" encoding="UTF-8"?>\n<OpenDRIVE></OpenDRIVE>\n'


def test_minimal_utf8_opendrive_admitted():
    root = parse_xodr_bytes(MINIMAL_XODR_UTF8)
    assert root.tag == "OpenDRIVE"
    check_xml_boundary(MINIMAL_XODR_UTF8)


@pytest.mark.parametrize(
    "decl",
    [
        b'<?xml version="1.0" encoding="UTF-16"?>',
        b'<?xml version="1.0" encoding="UTF-16LE"?>',
        b'<?xml version="1.0" encoding="UTF-16BE"?>',
    ],
)
def test_utf16_declarations_rejected_without_matching_bytes(decl):
    # Declaring UTF-16 while providing UTF-8 byte payload must fail closed.
    data = decl + b"\n<OpenDRIVE></OpenDRIVE>"
    with pytest.raises(UnsafeXMLError):
        parse_xodr_bytes(data)


def test_utf16le_encoded_opendrive_without_doctype_admitted_when_well_formed():
    xml = '<?xml version="1.0" encoding="UTF-16LE"?>\n<OpenDRIVE></OpenDRIVE>'
    data = xml.encode("utf-16-le")
    root = parse_xodr_bytes(data)
    assert root.tag == "OpenDRIVE"


def test_utf16le_with_bom_and_doctype_rejected():
    # UTF-16LE BOM + DOCTYPE must be rejected (no entity/DTD bypass).
    xml = '<?xml version="1.0" encoding="UTF-16LE"?>\n<!DOCTYPE OpenDRIVE [<!ENTITY x "y">]>\n<OpenDRIVE>&x;</OpenDRIVE>'
    data = b"\xff\xfe" + xml.encode("utf-16-le")
    with pytest.raises(UnsafeXMLError):
        parse_xodr_bytes(data)


def test_utf16be_with_bom_and_doctype_rejected():
    xml = '<?xml version="1.0" encoding="UTF-16BE"?>\n<!DOCTYPE OpenDRIVE [<!ENTITY x "y">]>\n<OpenDRIVE>&x;</OpenDRIVE>'
    data = b"\xfe\xff" + xml.encode("utf-16-be")
    with pytest.raises(UnsafeXMLError):
        parse_xodr_bytes(data)


def test_utf8_doctype_rejected():
    data = b'<?xml version="1.0"?>\n<!DOCTYPE OpenDRIVE [<!ENTITY x "y">]>\n<OpenDRIVE>&x;</OpenDRIVE>'
    with pytest.raises(UnsafeXMLError):
        parse_xodr_bytes(data)


def test_unsupported_encoding_declaration_rejected():
    data = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<OpenDRIVE></OpenDRIVE>'
    with pytest.raises(UnsafeXMLError):
        parse_xodr_bytes(data)


def test_empty_and_non_bytes_rejected():
    with pytest.raises(UnsafeXMLError):
        check_xml_boundary(b"")
    with pytest.raises(TypeError):
        parse_xodr_bytes("not-bytes")  # type: ignore[arg-type]
