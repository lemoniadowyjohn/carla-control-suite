#!/usr/bin/env python3
"""DEF-01 regression: experiment_map_pair_authority CLI must accept --out and
write the result JSON, returning an int exit code in {0, 1}.
"""

import json
import sys

from ultimate_pipeline.perception.experiment_map_pair_authority import main


def _write_pair(tmp_path, manual, auto):
    manual_path = tmp_path / "manual.json"
    auto_path = tmp_path / "auto.json"
    manual_path.write_text(json.dumps(manual), encoding="utf-8")
    auto_path.write_text(json.dumps(auto), encoding="utf-8")
    return manual_path, auto_path


def test_cli_writes_out_and_returns_int_exit_code(tmp_path, monkeypatch):
    """A syntactically valid pair must write --out and return an int in {0, 1}."""
    manual = {"map_type": "xodr", "not_ingolstadt": True}
    auto = {"map_type": "xodr"}
    manual_path, auto_path = _write_pair(tmp_path, manual, auto)
    out_path = tmp_path / "result.json"

    monkeypatch.setattr(
        sys, "argv",
        [
            "experiment_map_pair_authority",
            "--manual", str(manual_path),
            "--auto", str(auto_path),
            "--out", str(out_path),
        ],
    )

    exit_code = main()

    assert isinstance(exit_code, int) and not isinstance(exit_code, bool)
    assert exit_code in (0, 1)
    assert out_path.exists(), "CLI must write the --out result file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert "valid" in payload


def test_cli_invalid_pair_returns_1(tmp_path, monkeypatch):
    """An incomplete/invalid pair must return exit code 1."""
    manual = {}  # missing governed manual-arm identity fields
    auto = {}    # missing map_type / xodr_sha256
    manual_path, auto_path = _write_pair(tmp_path, manual, auto)
    out_path = tmp_path / "result.json"

    monkeypatch.setattr(
        sys, "argv",
        [
            "experiment_map_pair_authority",
            "--manual", str(manual_path),
            "--auto", str(auto_path),
            "--out", str(out_path),
        ],
    )

    exit_code = main()

    assert exit_code == 1
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload.get("valid") is False
