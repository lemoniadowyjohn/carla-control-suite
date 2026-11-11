"""Stage 8's ordinary-road lane-link advisory must inspect the map it just wrote.

Since 714ed04c the advisory called ``check_lane_link_targets_exist(fixed_out)``.
``fixed_out`` was the old Stage-8 laneSection-repair output; when that repair
moved to Stage 7 (GAP-048) the name disappeared, so the call raised NameError on
every run and the broad ``except`` swallowed it: the advisory never ran.
"""
import ast
from pathlib import Path

STAGE8 = (
    Path(__file__).resolve().parents[2]
    / "ultimate_pipeline"
    / "pipeline_stages"
    / "stage_08_integrity.py"
)


def _step8_function() -> ast.FunctionDef:
    tree = ast.parse(STAGE8.read_text(encoding="utf-8"))
    return next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_step8_markings_and_integrity"
    )


def test_stage8_never_loads_the_removed_fixed_out_name():
    loads = [
        n.lineno
        for n in ast.walk(_step8_function())
        if isinstance(n, ast.Name) and n.id == "fixed_out" and isinstance(n.ctx, ast.Load)
    ]
    assert loads == [], f"stage 8 still reads undefined `fixed_out` at lines {loads}"


def test_lane_link_advisory_checks_final_out():
    calls = [
        n
        for n in ast.walk(_step8_function())
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "check_lane_link_targets_exist"
    ]
    assert len(calls) == 1
    arg = calls[0].args[0]
    assert isinstance(arg, ast.Name) and arg.id == "final_out"
