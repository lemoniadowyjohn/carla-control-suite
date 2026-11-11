#!/usr/bin/env python3
"""CHAT-09 / B1: test that the launcher never reads `is_main` before assigning it.

The bug: train_launcher.py:437 read `is_main` before line 441 assigned it, so
every launch raised UnboundLocalError.

The training body now lives in `_main_impl()` (`main()` only wraps it with DDP
cleanup). Stale SUCCESS revocation deliberately happens before DDP init, guarded
by a pre-init rank check; that ordering is covered behaviourally by
tests/unit/test_rq5_train_launcher_initialization.py, so this test only pins the
static property that caused the crash.
"""
import ast
import sys
from pathlib import Path

# Make imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

LAUNCHER = Path(__file__).resolve().parents[2] / "perception" / "train_launcher.py"


def _uses_is_main(test: ast.AST) -> bool:
    return any(isinstance(n, ast.Name) and n.id == "is_main" for n in ast.walk(test))


def test_is_main_ordering_fix():
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    impl = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_main_impl"),
        None,
    )
    assert impl is not None, "_main_impl() not found in train_launcher.py"

    assign_lines = [
        n.lineno
        for n in ast.walk(impl)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "is_main" for t in n.targets)
    ]
    use_lines = [
        n.lineno for n in ast.walk(impl) if isinstance(n, ast.If) and _uses_is_main(n.test)
    ]
    assert assign_lines, "is_main assignment not found in _main_impl()"
    assert use_lines, "is_main use not found in _main_impl()"
    assert min(assign_lines) < min(use_lines), (
        f"is_main assigned at line {min(assign_lines)} but used at line {min(use_lines)}"
    )

    # The merge of both B1 fixes once produced two _init_ddp() calls; a second
    # init_process_group() fails under real DDP.
    init_calls = [
        n
        for n in ast.walk(impl)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_init_ddp"
    ]
    assert len(init_calls) == 1, f"_init_ddp() called {len(init_calls)} times in _main_impl()"


if __name__ == "__main__":
    test_is_main_ordering_fix()
