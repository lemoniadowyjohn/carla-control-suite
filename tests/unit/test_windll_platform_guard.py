"""GAP-055 recurrence guard: no module-level ctypes.WinDLL outside a win32 gate.

CI runs on Linux, where ctypes.WinDLL does not exist. pytest executes
module-level code during COLLECTION -- before any skipif marker -- so an
unconditional WinDLL call in an imported module aborts the entire run
(exit 2, "Interrupted: N errors during collection"). Every WinDLL call in
the governed modules must therefore live either inside a function body
(call time, Windows-only paths) or inside an `if sys.platform == "win32":`
block (import time, safe everywhere).
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

GUARDED_MODULES = [
    "scripts/control_plane.py",
    "scripts/job_supervision.py",
    "ultimate_pipeline/governance/single_writer/os_lock.py",
    "ultimate_pipeline/governance/single_writer/lease_store.py",
    "ultimate_pipeline/governance/single_writer/job_supervision.py",
]

# Test files whose subject is Windows-only machinery must carry a
# platform skip marker (import safety alone would let their items run and
# fail on Linux).
GATED_TEST_MODULES = [
    "tests/unit/test_single_writer_control_plane.py",
    "tests/unit/test_harness_governance_contract.py",
    "tests/unit/test_receipt_reconciler.py",
    "tests/unit/test_t6_owner_identity_authority.py",
]


def _is_platform_win32_check(node: ast.If) -> bool:
    src = ast.dump(node.test)
    return "sys" in src and "platform" in src and "win" in src


def _unguarded_windll_calls(tree: ast.Module):
    """Yield (lineno,) for WinDLL calls outside functions and win32 gates."""
    bad = []

    def visit(node, in_func, in_win32_gate):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, True, in_win32_gate)
            elif isinstance(child, ast.If) and _is_platform_win32_check(child):
                visit(child, in_func, True)
            elif isinstance(child, ast.Call):
                func = child.func
                is_windll = (
                    (isinstance(func, ast.Attribute) and func.attr == "WinDLL")
                    or (isinstance(func, ast.Name) and func.id == "WinDLL")
                )
                if is_windll and not in_func and not in_win32_gate:
                    bad.append(child.lineno)
                visit(child, in_func, in_win32_gate)
            else:
                visit(child, in_func, in_win32_gate)

    visit(tree, False, False)
    return bad


def test_no_unguarded_module_level_windll():
    offenders = {}
    for rel in GUARDED_MODULES:
        path = REPO / rel
        assert path.is_file(), f"guarded module missing: {rel}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        bad = _unguarded_windll_calls(tree)
        if bad:
            offenders[rel] = bad
    assert not offenders, (
        "module-level ctypes.WinDLL outside a function or "
        f"`if sys.platform == 'win32':` gate (breaks Linux collection): {offenders}"
    )


def test_windows_only_test_modules_carry_platform_skip():
    missing = []
    for rel in GATED_TEST_MODULES:
        text = (REPO / rel).read_text(encoding="utf-8")
        if "sys.platform" not in text or "skipif" not in text:
            missing.append(rel)
    assert not missing, (
        f"Windows-only test modules without a platform skipif marker: {missing}"
    )
