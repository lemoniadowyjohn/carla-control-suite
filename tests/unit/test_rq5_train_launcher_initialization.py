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
        if isinstance(node, ast.FunctionDef) and node.name == "_main_impl"
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


def test_proven_rank_ownership_precedes_stale_success_revocation():
    """A proven owner must exist before the rank-zero-only SUCCESS cleanup."""
    main = _main_function()
    preinit_lines = [
        node.lineno
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_preinit_artifact_rank"
    ]

    revoke_lines = [
        node.lineno
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_revoke_stale_success"
    ]

    assert len(preinit_lines) == 1
    assert len(revoke_lines) == 2
    assert preinit_lines[0] < min(revoke_lines)


def test_preinit_cleanup_uses_rank_not_local_rank_and_precedes_admission():
    """Early failures cannot retain SUCCESS when rank-zero ownership is known."""
    source = _LAUNCHER.read_text(encoding="utf-8")
    main = _main_function()
    preinit_calls = [
        node.lineno
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_preinit_artifact_rank"
    ]
    acceptance_calls = [
        node.lineno
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "enforce_dataset_acceptance"
    ]
    assert len(preinit_calls) == 1
    assert len(acceptance_calls) == 1
    assert preinit_calls[0] < acceptance_calls[0]
    helper = source[source.index("def _preinit_artifact_rank"):source.index("def _build_model")]
    assert 'os.environ.get("LOCAL_RANK")' not in helper


def test_ddp_initialization_failure_cleans_up_an_initialized_group():
    """A partial process-group initialization must be torn down before raise."""
    tree = ast.parse(_LAUNCHER.read_text(encoding="utf-8"))
    init_ddp = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_init_ddp"
    )
    cleanup_calls = [
        node
        for node in ast.walk(init_ddp)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "destroy_process_group"
    ]
    assert cleanup_calls


def test_ddp_environment_is_coherent_and_main_always_cleans_up():
    """Distributed ownership is validated and the public entrypoint has a finally."""
    tree = ast.parse(_LAUNCHER.read_text(encoding="utf-8"))
    init_ddp = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_init_ddp"
    )
    public_main = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    source = _LAUNCHER.read_text(encoding="utf-8")
    assert "--ddp requires both WORLD_SIZE and RANK" in source
    assert any(isinstance(node, ast.Try) and node.finalbody for node in public_main.body)
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "destroy_process_group"
        for node in ast.walk(public_main)
    )
    assert any(isinstance(node, ast.Raise) for node in ast.walk(init_ddp))
