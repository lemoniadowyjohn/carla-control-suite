"""Regression coverage for rank ownership before rank-gated RQ5 side effects.

This check deliberately parses the launcher instead of importing it: the
offline governance environment used for this regression does not provide
PyTorch.  It protects the concrete initialization ordering that previously
raised ``UnboundLocalError`` before model construction.  Runtime DDP behavior
remains covered by the PyTorch-dependent suite when that environment exists.
"""

import ast
from pathlib import Path


_LAUNCHER = (
    Path(__file__).resolve().parents[2]
    / "ultimate_pipeline"
    / "perception"
    / "train_launcher.py"
)


def _main_function():
    tree = ast.parse(_LAUNCHER.read_text(encoding="utf-8"))
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )


def _is_main_assignment_line(main):
    for node in ast.walk(main):
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "is_main"
            for target in node.targets
        ):
            return node.lineno
    raise AssertionError("main() does not establish is_main rank ownership")


def _ddp_initialization_line(main):
    for node in ast.walk(main):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if isinstance(node.value.func, ast.Name) and node.value.func.id == "_init_ddp":
            return node.lineno
    raise AssertionError("main() does not initialize DDP rank ownership")


def test_rank_ownership_precedes_stale_success_revocation():
    """Rank must be established before the rank-zero-only SUCCESS cleanup."""
    main = _main_function()
    ddp_line = _ddp_initialization_line(main)
    assignment_line = _is_main_assignment_line(main)

    revoke_if_lines = []
    for node in ast.walk(main):
        if not isinstance(node, ast.If):
            continue
        if not isinstance(node.test, ast.Name) or node.test.id != "is_main":
            continue
        if any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "_revoke_stale_success"
            for child in ast.walk(node)
        ):
            revoke_if_lines.append(node.lineno)

    assert len(revoke_if_lines) == 1
    assert ddp_line < assignment_line
    assert assignment_line < revoke_if_lines[0]
