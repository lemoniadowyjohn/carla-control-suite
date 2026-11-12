"""Adversarial encoding-aware XML admission regression controls for V104."""
from __future__ import annotations

import pytest
from pathlib import Path
from types import SimpleNamespace

from ultimate_pipeline.quality.final_artifact_gates import (
    UnsafeXMLError,
    parse_xodr_bytes,
)
from ultimate_pipeline.pipeline_stages.stage_08_hygiene import _step8h_map_hygiene


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


def test_production_hygiene_stage_rejects_dtd_before_any_repair_parser(
    tmp_path, monkeypatch
) -> None:
    """The actual stage entrypoint must reject hostile input before repair."""
    from ultimate_pipeline.quality import map_hygiene

    def forbidden_legacy_parse(*_args, **_kwargs):
        raise AssertionError("legacy ElementTree.parse path was reached")

    monkeypatch.setattr(map_hygiene.ET, "parse", forbidden_legacy_parse)
    payload = (
        b'<!DOCTYPE OpenDRIVE [<!ENTITY roadname "hostile">]>'
        b'<OpenDRIVE><header/><road id="1" name="&roadname;" '
        b'length="1" junction="-1"/></OpenDRIVE>'
    )
    source = tmp_path / "candidate.xodr"
    source.write_bytes(payload)
    out_dir = tmp_path / "reports"
    stage = SimpleNamespace(
        settings=SimpleNamespace(ENABLE_MAP_HYGIENE=True), out_dir=out_dir
    )

    with pytest.raises(UnsafeXMLError):
        _step8h_map_hygiene(stage, str(source))

    assert not (out_dir / "08h1_island_quarantined.xodr").exists()


def test_production_quality_wrapper_admits_before_legacy_xml_parser(
    tmp_path, monkeypatch
) -> None:
    """The MainPipeline wrapper must reject DTD before a path parser sees it."""
    import xml.etree.ElementTree as ET

    from ultimate_pipeline.main_pipeline import MainPipeline

    source = tmp_path / "hostile.xodr"
    source.write_bytes(
        b'<!DOCTYPE OpenDRIVE [<!ENTITY x "expanded">]>'
        b'<OpenDRIVE><header/><road name="&x;"/></OpenDRIVE>'
    )
    original_parse = ET.parse
    legacy_candidate_reads = []

    def guarded_parse(path, *args, **kwargs):
        if str(path) == str(source):
            legacy_candidate_reads.append(str(path))
        return original_parse(path, *args, **kwargs)

    monkeypatch.setattr(ET, "parse", guarded_parse)
    monkeypatch.setenv("UP_STRICT_QUALITY_GATES", "1")
    pipeline = MainPipeline.__new__(MainPipeline)
    pipeline.settings = SimpleNamespace(ENABLE_QUALITY_GATES_WRAPPER=True)
    pipeline.out_dir = str(tmp_path / "reports")

    with pytest.raises(RuntimeError, match="Quality gate failures"):
        pipeline._run_quality_gates_wrapper(str(source))
    assert legacy_candidate_reads == []


def test_mandatory_gates_share_admitted_snapshot_and_reject_late_replacement(
    tmp_path, monkeypatch
) -> None:
    """Path-based gates see admitted bytes; late source replacement blocks all."""
    import hashlib

    from ultimate_pipeline.quality import final_artifact_gates as gates

    source = tmp_path / "candidate.xodr"
    admitted = ROOT + b"\n"
    source.write_bytes(admitted)
    seen_paths = []

    def first_gate(path, _root):
        seen_paths.append(path)
        assert Path(path).read_bytes() == admitted
        source.write_bytes(ROOT + b"<!-- replaced during gate pass -->\n")
        return {"ok": True, "status": "PASS"}

    def second_gate(path, _root):
        seen_paths.append(path)
        assert Path(path).read_bytes() == admitted
        return {"ok": True, "status": "PASS"}

    monkeypatch.setattr(
        gates, "_gate_table", lambda _scope: {"first": first_gate, "second": second_gate}
    )
    reports = gates.compute_final_artifact_reports(
        str(source), expected_sha256=hashlib.sha256(admitted).hexdigest()
    )
    assert len(seen_paths) == 2
    assert all(Path(path) != source for path in seen_paths)
    assert {report["status"] for report in reports.values()} == {gates.STATUS_BLOCKED_INPUT}
