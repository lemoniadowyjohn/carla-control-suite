"""Adversarial encoding-aware XML admission regression controls for V104."""
from __future__ import annotations

import pytest

from ultimate_pipeline.quality.final_artifact_gates import (
    UnsafeXMLError,
    parse_xodr_bytes,
)


ROOT = b"<OpenDRIVE><header revMajor='1' revMinor='4'/></OpenDRIVE>"


def _utf16le(xml: str) -> bytes:
    return b"\xff\xfe" + xml.encode("utf-16-le")


def _utf16be(xml: str) -> bytes:
    return b"\xfe\xff" + xml.encode("utf-16-be")


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b'<!DOCTYPE OpenDRIVE><OpenDRIVE><header/></OpenDRIVE>', id="utf8-doctype"),
        pytest.param(_utf16le('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE OpenDRIVE><OpenDRIVE><header/></OpenDRIVE>'), id="utf16le-doctype"),
        pytest.param(_utf16be('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE OpenDRIVE><OpenDRIVE><header/></OpenDRIVE>'), id="utf16be-doctype"),
        pytest.param(b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE OpenDRIVE><OpenDRIVE><header/></OpenDRIVE>', id="utf8-bom-doctype"),
        pytest.param(b'<!-- <OpenDRIVE decoy ' + b'x' * (70 * 1024) + b' -->\n<!DOCTYPE OpenDRIVE [<!ENTITY e "expanded">]><OpenDRIVE><header/>&e;</OpenDRIVE>', id="late-doctype-after-64k-decoy"),
        pytest.param(b'<!DOCTYPE OpenDRIVE [<!ENTITY e "internal">]><OpenDRIVE><header/>&e;</OpenDRIVE>', id="internal-entity"),
        pytest.param(b'<!DOCTYPE OpenDRIVE SYSTEM "file:///etc/passwd"><OpenDRIVE><header/></OpenDRIVE>', id="external-subset"),
        pytest.param(b'<!DOCTYPE OpenDRIVE [<!ENTITY ext SYSTEM "file:///etc/passwd">]><OpenDRIVE><header/>&ext;</OpenDRIVE>', id="external-entity"),
    ],
)
def test_actual_doctype_and_entities_are_rejected(payload: bytes) -> None:
    with pytest.raises(UnsafeXMLError):
        parse_xodr_bytes(payload)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b'<?xml version="1.0" encoding="UTF-8"?>' + ROOT, id="utf8-declaration"),
        pytest.param(b'\xef\xbb\xbf' + ROOT, id="utf8-bom"),
        pytest.param(_utf16le('<?xml version="1.0" encoding="UTF-16"?><OpenDRIVE><header/></OpenDRIVE>'), id="utf16le-bom-declaration"),
        pytest.param(_utf16be('<?xml version="1.0" encoding="UTF-16"?><OpenDRIVE><header/></OpenDRIVE>'), id="utf16be-bom-declaration"),
    ],
)
def test_supported_valid_encodings_are_accepted(payload: bytes) -> None:
    assert parse_xodr_bytes(payload).tag == "OpenDRIVE"


def test_declaration_text_in_comment_is_not_an_active_doctype() -> None:
    payload = b'<!-- <!DOCTYPE OpenDRIVE [<!ENTITY e "bad">]> -->' + ROOT
    assert parse_xodr_bytes(payload).tag == "OpenDRIVE"


def test_declaration_text_in_cdata_is_not_an_active_doctype() -> None:
    payload = b'<OpenDRIVE><header/><userData><![CDATA[<!DOCTYPE OpenDRIVE>]]></userData></OpenDRIVE>'
    assert parse_xodr_bytes(payload).tag == "OpenDRIVE"
