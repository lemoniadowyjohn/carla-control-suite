"""V94 RQ1: the legacy v1 trial CLI cannot claim a failed run succeeded.

The actual source function AST is executed without importing the costly CARLA
pipeline. This exercises the production CLI decision, not a parallel mock
implementation of that decision.
"""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SOURCE = Path(__file__).resolve().parents[2] / "tools" / "rq1_trial_run.py"


def _source_function(name: str, namespace: dict):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    funcs = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(funcs) == 1
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            funcs[0],
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace[name]


def _main(argv, run_one):
    stderr = io.StringIO()
    output = {"calls": []}
    def wrapped(*args):
        output["calls"].append(args)
        return run_one(*args)
    namespace = {
        "sys": SimpleNamespace(argv=argv, stderr=stderr),
        "Path": Path,
        "json": json,
        "run_single_trial": wrapped,
    }
    main = _source_function("main", namespace)
    output["exit_code"] = main()
    output["stderr"] = stderr.getvalue()
    return output


@pytest.mark.parametrize("failure", ["FAILED: RuntimeError", "FAILED_INCOMPLETE_RECEIPT"])
def test_failed_trial_propagates_nonzero_exit(failure):
    out = _main(
        ["rq1_trial_run.py", "1", "--mode=B"],
        lambda *args: {"status": failure, "run": 1, "mode": "B"},
    )
    assert out["exit_code"] == 1
    assert len(out["calls"]) == 1


def test_legacy_success_reports_zero_exit():
    out = _main(
        ["rq1_trial_run.py", "1", "--mode=B"],
        lambda *args: {"status": "ok", "run": 1, "mode": "B"},
    )
    assert out["exit_code"] == 0
    assert len(out["calls"]) == 1


def test_fake_rq1a_mode_is_rejected_before_pipeline_execution():
    out = _main(
        ["rq1_trial_run.py", "1", "--mode=A"],
        lambda *args: pytest.fail("Mode A started downstream pipeline"),
    )
    assert out["exit_code"] == 2
    assert out["calls"] == []
    assert "not implemented" in out["stderr"]


def test_legacy_cli_without_run_number_exits_nonzero():
    out = _main(["rq1_trial_run.py"], lambda *args: pytest.fail("run started"))
    assert out["exit_code"] == 2
    assert out["calls"] == []


def test_cli_entrypoint_exits_using_main_return_code():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    tail = tree.body[-1]
    assert isinstance(tail, ast.If)
    assert any(
        isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "SystemExit"
        for node in ast.walk(tail)
    ), "module execution must propagate main() status to the OS"


def test_legacy_v1_digest_cannot_be_rebranded_as_normalized():
    source = SOURCE.read_text(encoding="utf-8")
    assert "normalized_xodr_sha = None" in source
    assert "normalized_xodr_sha = final_xodr_sha" not in source
    assert 'structural_sig = map_acceptance.get("payload_sha256")' not in source
