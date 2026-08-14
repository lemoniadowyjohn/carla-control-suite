from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.verify_candidate_digest import main, sha256_file, verify

REPO = Path(__file__).resolve().parents[2]
CAND = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate"
SIGNED = "6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02"
REPAIRED = CAND / "ingolstadt_perception_final_repaired.xodr"
SUPERSEDED = CAND / "ingolstadt_fixed_final.xodr"


def test_sha256_file_matches_hashlib(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello-carla")
    assert sha256_file(p) == hashlib.sha256(b"hello-carla").hexdigest()


def test_verify_synthetic_match_and_mismatch(tmp_path):
    p = tmp_path / "x.xodr"
    p.write_bytes(b"<OpenDRIVE/>")
    digest = hashlib.sha256(b"<OpenDRIVE/>").hexdigest()
    assert verify(p, digest) is True
    assert verify(p, digest.upper()) is True  # case-insensitive
    assert verify(p, "0" * 64) is False


def test_verify_missing_is_false(tmp_path):
    assert verify(tmp_path / "nope.xodr", "0" * 64) is False


def test_main_missing_returns_1(tmp_path):
    assert main(["--xodr", str(tmp_path / "nope.xodr"), "--expected", "0" * 64]) == 1


def test_main_synthetic_match_returns_0(tmp_path):
    p = tmp_path / "x.xodr"
    p.write_bytes(b"abc")
    assert main(["--xodr", str(p), "--expected", hashlib.sha256(b"abc").hexdigest()]) == 0


@pytest.mark.skipif(not REPAIRED.exists(), reason="signed candidate 6bac3570 absent (untracked ~80MB)")
def test_signed_candidate_is_go():
    assert verify(REPAIRED, SIGNED) is True
    assert main(["--xodr", str(REPAIRED), "--expected", SIGNED]) == 0


@pytest.mark.skipif(not SUPERSEDED.exists(), reason="superseded candidate absent")
def test_superseded_candidate_is_nogo():
    # Pointing the gate at the superseded 80ebb00 while expecting the signed
    # 6bac3570 must be NO-GO -- this is the wasted-runtime trap the gate prevents.
    assert verify(SUPERSEDED, SIGNED) is False
    assert main(["--xodr", str(SUPERSEDED), "--expected", SIGNED]) == 1
