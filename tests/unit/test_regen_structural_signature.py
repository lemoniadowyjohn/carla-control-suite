"""C11 follow-up (self-identified in C11_REPRODUCIBILITY_NUANCE.md): pinning-by-sha only
guarantees identity of a specific artifact, not byte-reproducibility across re-conversions
(Osm2Odr is byte-non-deterministic, C15). The honest reproducibility check is STRUCTURAL
(num_roads/num_junctions/total_road_length), not byte-sha equality. This adds:
  1. compute_structural_signature(xodr_path) -- reused by provenance + verification.
  2. regen_provenance.json gains a "structural_signature" key (wired via _emit_candidate).
  3. --verify-structural <a.xodr> <b.xodr> CLI mode: exit 0 if structurally equal, else 1.
"""
from __future__ import annotations

from pathlib import Path

import scripts.regen_map_of_record as regen

_ROAD_A = (
    '<road name="" length="10.0" id="1" junction="-1">'
    '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
    '<lanes><laneSection s="0"><center><lane id="0" type="driving"/></center></laneSection></lanes>'
    "</road>"
)
_ROAD_B = (
    '<road name="" length="20.0" id="2" junction="7">'
    '<planView><geometry s="0" x="0" y="0" hdg="0" length="20.0"><line/></geometry></planView>'
    '<lanes><laneSection s="0"><center><lane id="0" type="driving"/></center></laneSection></lanes>'
    "</road>"
)


def _write_xodr(path: Path, roads_xml: str, junctions_xml: str = "") -> Path:
    path.write_text(
        f'<?xml version="1.0"?><OpenDRIVE><header/>{roads_xml}{junctions_xml}</OpenDRIVE>',
        encoding="utf-8",
    )
    return path


def test_compute_structural_signature_counts_roads_junctions_length(tmp_path):
    xodr = _write_xodr(
        tmp_path / "a.xodr", _ROAD_A + _ROAD_B, '<junction id="7" name=""/>'
    )
    sig = regen.compute_structural_signature(xodr)
    assert sig["num_roads"] == 2
    assert sig["num_junctions"] == 1
    assert abs(sig["total_road_length"] - 30.0) < 1e-6


def test_structural_signature_matches_ignores_byte_differences(tmp_path):
    # Same structure, different formatting/whitespace/sha256 -- must still match.
    xodr_a = _write_xodr(tmp_path / "a.xodr", _ROAD_A)
    xodr_b = tmp_path / "b.xodr"
    xodr_b.write_text(
        _write_xodr(tmp_path / "a2.xodr", _ROAD_A).read_text(encoding="utf-8") + "\n\n",
        encoding="utf-8",
    )
    assert regen._sha256_file(xodr_a) != regen._sha256_file(xodr_b)  # byte-different (precondition)
    sig_a = regen.compute_structural_signature(xodr_a)
    sig_b = regen.compute_structural_signature(xodr_b)
    assert regen.structural_signatures_match(sig_a, sig_b)


def test_structural_signature_mismatch_detected(tmp_path):
    xodr_a = _write_xodr(tmp_path / "a.xodr", _ROAD_A)
    xodr_b = _write_xodr(tmp_path / "b.xodr", _ROAD_A + _ROAD_B)
    sig_a = regen.compute_structural_signature(xodr_a)
    sig_b = regen.compute_structural_signature(xodr_b)
    assert not regen.structural_signatures_match(sig_a, sig_b)


def test_cmd_verify_structural_exits_0_on_match(tmp_path, capsys):
    xodr_a = _write_xodr(tmp_path / "a.xodr", _ROAD_A)
    xodr_b = _write_xodr(tmp_path / "b.xodr", _ROAD_A)
    ns = regen.argparse.Namespace(verify_structural=[str(xodr_a), str(xodr_b)])
    assert regen.cmd_verify_structural(ns) == 0
    assert "MATCH" in capsys.readouterr().out.upper()


def test_cmd_verify_structural_exits_1_on_mismatch(tmp_path, capsys):
    xodr_a = _write_xodr(tmp_path / "a.xodr", _ROAD_A)
    xodr_b = _write_xodr(tmp_path / "b.xodr", _ROAD_A + _ROAD_B)
    ns = regen.argparse.Namespace(verify_structural=[str(xodr_a), str(xodr_b)])
    assert regen.cmd_verify_structural(ns) == 1
    assert "MISMATCH" in capsys.readouterr().out.upper()
