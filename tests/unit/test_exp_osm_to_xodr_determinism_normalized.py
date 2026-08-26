"""Thesis future-work item #13 (byte-level determinism root cause, secondary sources):
empirically, the ONLY byte-level difference between 3 repeated Osm2Odr conversions of the
same pinned OSM input (reports/post_audit_hardening/C15_RQ4_DR/determinism/run_00{0,1,2}.xodr)
is the wall-clock timestamp -- appearing in exactly two places, the leading XML comment
("generated on ... by") and <header date="...">. The bbox (north/south/east/west) and every
other byte are identical across all 3 runs (verified directly: diff shows exactly those 2
lines changed, file sizes byte-identical). This resolves the thesis's open question ("bbox
float accumulation, XML element order... have not been isolated") for this pipeline stage:
there is no other source. This module operationalizes that as a normalized-hash check so
future determinism runs get an automatic pass/fail on "any OTHER source of nondeterminism"
instead of requiring a manual diff of an 80+MB file.
"""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.experiments.thesis.exp_osm_to_xodr_determinism import (
    _normalize_timestamps,
    _sha256_normalized_text,
)


def test_normalize_timestamps_strips_both_known_locations():
    text = (
        "<!-- generated on 2026-08-20 15:11:28 by osm2odr -->\n"
        '<header revMajor="1" revMinor="4" name="" version="1.00" '
        'date="Thu Aug 20 15:11:28 2026" north="5472743.54" south="5458671.57" '
        'east="845943.06" west="832672.90">\n'
    )
    normalized = _normalize_timestamps(text)
    assert "2026-08-20 15:11:28" not in normalized
    assert "Thu Aug 20 15:11:28 2026" not in normalized
    # Everything else (crucially the bbox) must survive untouched.
    assert 'north="5472743.54" south="5458671.57"' in normalized
    assert 'east="845943.06" west="832672.90"' in normalized


def test_normalize_timestamps_only_differing_by_timestamp_yields_equal_text():
    a = (
        "<!-- generated on 2026-08-20 15:11:28 by x -->\n"
        '<header date="Thu Aug 20 15:11:28 2026" north="1.0" south="2.0">\n'
    )
    b = (
        "<!-- generated on 2026-08-20 15:12:51 by x -->\n"
        '<header date="Thu Aug 20 15:12:51 2026" north="1.0" south="2.0">\n'
    )
    assert a != b
    assert _normalize_timestamps(a) == _normalize_timestamps(b)


def test_normalize_timestamps_does_not_mask_a_real_structural_difference():
    a = '<header date="Thu Aug 20 15:11:28 2026" north="1.0" south="2.0">\n'
    b = '<header date="Thu Aug 20 15:11:28 2026" north="1.0" south="9.9">\n'
    assert _normalize_timestamps(a) != _normalize_timestamps(b)


def test_sha256_normalized_text_matches_across_timestamp_only_diff(tmp_path: Path):
    a = tmp_path / "a.xodr"
    b = tmp_path / "b.xodr"
    a.write_text(
        "<!-- generated on 2026-08-20 15:11:28 by x -->\n"
        '<header date="Thu Aug 20 15:11:28 2026" north="1.0">\n',
        encoding="utf-8",
    )
    b.write_text(
        "<!-- generated on 2026-08-20 15:12:51 by x -->\n"
        '<header date="Thu Aug 20 15:12:51 2026" north="1.0">\n',
        encoding="utf-8",
    )
    assert _sha256_normalized_text(a) == _sha256_normalized_text(b)


# --- Integration-style: verify against the REAL C15 determinism artifacts on disk ---

_DETERMINISM_DIR = Path("reports/post_audit_hardening/C15_RQ4_DR/determinism")


def test_real_c15_determinism_runs_are_raw_nonidentical_but_timestamp_normalized_identical():
    runs = sorted(_DETERMINISM_DIR.glob("run_*.xodr"))
    assert len(runs) == 3, f"expected 3 real determinism runs, found {len(runs)}"

    raw_hashes = set()
    normalized_hashes = set()
    for run in runs:
        import hashlib

        raw_hashes.add(hashlib.sha256(run.read_bytes()).hexdigest())
        normalized_hashes.add(_sha256_normalized_text(run))

    # Raw bytes differ (this is the known, thesis-documented timestamp nondeterminism).
    assert len(raw_hashes) == 3
    # Once the timestamp is normalized away, all 3 real runs collapse to ONE hash --
    # empirical proof there is no other (bbox/element-order/etc.) source of divergence.
    assert len(normalized_hashes) == 1
