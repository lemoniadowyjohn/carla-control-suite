#!/usr/bin/env python3
"""CHAT-09 / B1: test that main() no longer raises UnboundLocalError on is_main.

The bug: train_launcher.py:437 read `is_main` before line 441 assigned it.
The fix: move `_init_ddp()` and `is_main = (rank == 0)` above the
`_revoke_stale_success()` block.
"""
import sys
import tempfile
from pathlib import Path

# Make imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def test_is_main_ordering_fix():
    """Verify that the is_main ordering bug is fixed.

    This test verifies the source code ordering and that the
    UnboundLocalError is no longer possible.
    """
    # Verify source: is_main assignment must precede first use
    src = Path("ultimate_pipeline/perception/train_launcher.py").read_text(encoding='utf-8')
    lines = src.splitlines()
    assign_line = None
    first_use_line = None
    for i, line in enumerate(lines, 1):
        if 'is_main = (rank == 0)' in line and assign_line is None:
            assign_line = i
        if 'if is_main:' in line and first_use_line is None:
            stripped = line.strip()
            if stripped.startswith('if is_main:'):
                first_use_line = i
    assert assign_line is not None, "is_main assignment not found"
    assert first_use_line is not None, "is_main use not found"
    assert assign_line < first_use_line, (
        f"is_main assigned at line {assign_line} but used at line {first_use_line}"
    )
    print(f"PASS: is_main assigned at line {assign_line}, first used at line {first_use_line}")

    # Now verify that the main() function can be parsed without UnboundLocalError
    # by checking the AST - the assignment must come before any use
    import ast
    tree = ast.parse(src)
    # Find the main function
    main_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'main':
            main_func = node
            break
    assert main_func is not None, "main() function not found"

    # Walk the main function body and track is_main assignments/uses
    class IsMainVisitor(ast.NodeVisitor):
        def __init__(self):
            self.assign_lineno = None
            self.use_linenos = []

        def visit_Assign(self, node):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'is_main':
                    if self.assign_lineno is None:
                        self.assign_lineno = node.lineno
            self.generic_visit(node)

        def visit_If(self, node):
            if isinstance(node.test, ast.Name) and node.test.id == 'is_main':
                self.use_linenos.append(node.lineno)
            self.generic_visit(node)

    visitor = IsMainVisitor()
    visitor.visit(main_func)
    assert visitor.assign_lineno is not None, "is_main assignment not found in main()"
    assert visitor.use_linenos, "is_main use not found in main()"
    assert visitor.assign_lineno < min(visitor.use_linenos), (
        f"is_main assigned at line {visitor.assign_lineno} but used at line {min(visitor.use_linenos)}"
    )
    print(f"PASS: AST check - is_main assigned at {visitor.assign_lineno}, first used at {min(visitor.use_linenos)}")

    # Verify the fix is in place by checking the actual code structure
    # The fix moved ddp_enabled, rank, world_size = _init_ddp(args.ddp)
    # and is_main = (rank == 0) BEFORE the _revoke_stale_success block
    init_ddp_line = None
    revoke_line = None
    for i, line in enumerate(lines, 1):
        if '_init_ddp(args.ddp)' in line and init_ddp_line is None:
            init_ddp_line = i
        if '_revoke_stale_success(out_dir)' in line and revoke_line is None:
            revoke_line = i
    assert init_ddp_line is not None, "_init_ddp call not found"
    assert revoke_line is not None, "_revoke_stale_success call not found"
    assert init_ddp_line < revoke_line, (
        f"_init_ddp at line {init_ddp_line} but _revoke_stale_success at line {revoke_line}"
    )
    print(f"PASS: _init_ddp at line {init_ddp_line}, _revoke_stale_success at line {revoke_line}")

    print("\n=== B1 is_main ordering test: ALL PASS ===")


if __name__ == "__main__":
    test_is_main_ordering_fix()