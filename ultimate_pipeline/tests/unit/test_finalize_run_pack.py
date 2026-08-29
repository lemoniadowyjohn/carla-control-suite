# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/utils/finalize_run_pack.py.

Live: write_signature_json + write_success_txt imported and called by both
main_pipeline.py and run_full_domain_gap.py as the final integrity/success
marker step of a run. Zero prior test coverage.
"""
from __future__ import annotations

import hashlib
import json

from ultimate_pipeline.utils.finalize_run_pack import (
    write_signature_json,
    write_success_txt,
)


def test_signature_json_hashes_files_correctly(tmp_path):
    f = tmp_path / "final.xodr"
    f.write_text("<OpenDRIVE/>", encoding="utf-8")
    sig = write_signature_json(str(tmp_path), ["final.xodr"])

    expected_hash = hashlib.sha256(f.read_bytes()).hexdigest()
    assert sig["files"]["final.xodr"] == expected_hash
    assert sig["hash_algorithm"] == "sha256"

    written = json.loads((tmp_path / "signature.json").read_text())
    assert written == sig


def test_signature_json_uses_posix_style_relative_keys(tmp_path):
    nested = tmp_path / "reports" / "out.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("{}", encoding="utf-8")
    sig = write_signature_json(str(tmp_path), ["reports/out.json"])
    assert "reports/out.json" in sig["files"]


def test_signature_json_skips_missing_files_silently(tmp_path):
    sig = write_signature_json(str(tmp_path), ["does_not_exist.xodr"])
    assert sig["files"] == {}


def test_signature_json_skips_files_outside_out_dir(tmp_path):
    outside_dir = tmp_path.parent / "outside_area"
    outside_dir.mkdir(exist_ok=True)
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("not part of this run", encoding="utf-8")

    out_dir = tmp_path / "run_out"
    out_dir.mkdir()
    sig = write_signature_json(str(out_dir), [str(outside_file)])
    assert sig["files"] == {}


def test_signature_json_skips_empty_or_none_entries(tmp_path):
    sig = write_signature_json(str(tmp_path), ["", None])
    assert sig["files"] == {}


def test_success_txt_written_with_timestamp_and_summary(tmp_path):
    write_success_txt(str(tmp_path), summary="run_full_domain_gap")
    content = (tmp_path / "SUCCESS.txt").read_text()
    assert content.startswith("OK ")
    assert "run_full_domain_gap" in content


def test_success_txt_without_summary_is_still_valid(tmp_path):
    write_success_txt(str(tmp_path))
    content = (tmp_path / "SUCCESS.txt").read_text()
    assert content.startswith("OK ")
    assert content.strip() == content.split("\n")[0]  # only the OK line, no summary
