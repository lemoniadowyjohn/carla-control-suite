from __future__ import annotations

import builtins
import json
from pathlib import Path

from click.testing import CliRunner

from ultimate_pipeline.cli import cli
from ultimate_pipeline.entrypoints import ENTRYPOINTS
from ultimate_pipeline.tools.repo_health import build_repo_health, write_repo_health


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_repo_health_marks_missing_runtime_as_incomplete_not_pass() -> None:
    payload = build_repo_health(
        _repo_root(),
        test_result="PASS",
        run_pip_check=False,
        verify_maps=False,
        runtime_status="NOT_RUN",
    )
    assert payload["sections"]["runtime_verification"]["status"] == "NOT_RUN"
    assert payload["overall_status"] == "INCOMPLETE"


def test_write_repo_health_writes_json_and_markdown(tmp_path: Path) -> None:
    payload = build_repo_health(
        _repo_root(),
        test_result="PASS",
        run_pip_check=False,
        verify_maps=False,
        runtime_status="NOT_RUN",
    )
    paths = write_repo_health(tmp_path, payload)
    assert Path(paths["json"]).is_file()
    assert Path(paths["markdown"]).is_file()
    written = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert written["overall_status"] == "INCOMPLETE"
    assert "Runtime verification" in Path(paths["markdown"]).read_text(encoding="utf-8")


def test_up_health_json_stdout_is_parseable(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "health",
            "--out-dir",
            str(tmp_path),
            "--test-result",
            "PASS",
            "--skip-pip-check",
            "--skip-map-hash",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["overall_status"] == "INCOMPLETE"
    assert payload["sections"]["runtime_verification"]["status"] == "NOT_RUN"


def test_up_research_status_json_uses_current_rq_table() -> None:
    result = CliRunner().invoke(cli, ["research", "status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rq_status"]["RQ3"] == ["DEFERRED_RUNTIME"]
    assert "DEFERRED_EXTERNAL_DATA" in payload["rq_status"]["RQ5"]


def test_entrypoint_registry_names_canonical_cli_and_pipeline_authority() -> None:
    assert ENTRYPOINTS["cli"].module == "ultimate_pipeline.cli"
    assert ENTRYPOINTS["pipeline"].module == "ultimate_pipeline.main_pipeline"
    assert ENTRYPOINTS["pipeline_legacy_shim"].module == "ultimate_pipeline.run_pipeline"


def test_run_pipeline_shim_restores_print_after_pipeline_call(monkeypatch) -> None:
    import ultimate_pipeline.main_pipeline as main_pipeline
    import ultimate_pipeline.run_pipeline as run_pipeline

    original_print = builtins.print

    def fake_main(argv):
        print("inside shim")
        assert argv == ["--help"]
        return 0

    monkeypatch.setattr(main_pipeline, "main", fake_main)
    assert run_pipeline.main(["--help"]) == 0
    assert builtins.print is original_print
