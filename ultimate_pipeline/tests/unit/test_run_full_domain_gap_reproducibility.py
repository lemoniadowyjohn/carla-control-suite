from __future__ import annotations

import json
import sys
from pathlib import Path

from ultimate_pipeline.run_full_domain_gap import (
    _cli_main,
    validate_reproducibility_preconditions,
)


def test_validate_reproducibility_preconditions_warns_for_missing_paths(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_11"
    run_dir.mkdir()
    existing_auto = run_dir / "auto.xodr"
    existing_auto.write_text("<OpenDRIVE />", encoding="utf-8")
    report_path = run_dir / "full_report.json"
    report_path.write_text(
        json.dumps(
            {
                "manual_xodr": str(run_dir / "manual_maps" / "manual_ingolstadt_grid0828.xodr"),
                "auto_xodr": str(existing_auto),
            }
        ),
        encoding="utf-8",
    )

    warnings = validate_reproducibility_preconditions(report_path)

    assert len(warnings) == 1
    assert "manual_xodr" in warnings[0]
    assert "does not exist" in warnings[0]


def test_validate_reproducibility_preconditions_returns_empty_when_paths_exist(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_ok"
    run_dir.mkdir()
    manual = run_dir / "manual.xodr"
    auto = run_dir / "auto.xodr"
    manual.write_text("<OpenDRIVE />", encoding="utf-8")
    auto.write_text("<OpenDRIVE />", encoding="utf-8")
    report_path = run_dir / "full_report.json"
    report_path.write_text(
        json.dumps(
            {
                "manual_xodr": str(manual),
                "auto_xodr": str(auto),
            }
        ),
        encoding="utf-8",
    )

    warnings = validate_reproducibility_preconditions(report_path)

    assert warnings == []


def test_cli_check_reproducibility_prints_warnings_and_returns_zero(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    run_dir = tmp_path / "run_cli"
    run_dir.mkdir()
    report_path = run_dir / "full_report.json"
    report_path.write_text(
        json.dumps(
            {
                "manual_xodr": str(run_dir / "missing_manual.xodr"),
                "auto_xodr": str(run_dir / "missing_auto.xodr"),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_full_domain_gap.py", "--check-reproducibility", str(run_dir)],
    )

    exit_code = _cli_main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "manual_xodr" in captured.out
    assert "auto_xodr" in captured.out
