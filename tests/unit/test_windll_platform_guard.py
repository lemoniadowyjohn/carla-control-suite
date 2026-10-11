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
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

GUARDED_MODULES = [
    "scripts/control_plane.py",
    "scripts/job_supervision.py",
    "ultimate_pipeline/governance/single_writer/os_lock.py",
    "ultimate_pipeline/governance/single_writer/lease_store.py",
    "ultimate_pipeline/governance/single_writer/job_supervision.py",
    "tools/orphan_terminal_witness.py",
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

HANDLE_NAMES = {
    "_kernel32",
    "k32",
    "_ct_kernel32",
    "_k",
    "_CreateMutexW",
    "_WaitForSingleObject",
    "_ReleaseMutex",
    "_CloseHandle",
}


def _is_platform_win32_check(node: ast.If) -> bool:
    """Return True if node.test is `sys.platform == \"win32\"` (or equivalent)."""
    src = ast.unparse(node.test) if hasattr(ast, "unparse") else ast.dump(node.test)
    # Normalize: remove spaces, lower-case
    normalized = "".join(src.split()).lower()
    # Accept: sys.platform=="win32", sys.platform==\"win32\", etc.
    return ("sys.platform" in normalized and "win32" in normalized and "==" in normalized)


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


def _unguarded_handle_attribute_access(tree: ast.Module):
    """Yield (lineno,) for module-level handle attribute access (e.g. .argtypes, .restype) outside win32 gates."""
    bad = []

    def visit(node, in_func, in_win32_gate):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, True, in_win32_gate)
            elif isinstance(child, ast.If) and _is_platform_win32_check(child):
                visit(child, in_func, True)
            elif isinstance(child, ast.Assign):
                # Check if the assignment target chain starts from a known handle name
                # e.g., _kernel32.CreateMutexW.argtypes = [...] or k32.CreateJobObjectW.argtypes = [...]
                for target in child.targets:
                    if _target_originates_from_handle(target):
                        if not (in_func or in_win32_gate):
                            bad.append(target.lineno)
                # Also check value side? Not needed for guard; attribute writes are the risk.
            elif isinstance(child, ast.AnnAssign):
                if _target_originates_from_handle(child.target):
                    if not (in_func or in_win32_gate):
                        bad.append(child.target.lineno)
            else:
                visit(child, in_func, in_win32_gate)

    def _target_originates_from_handle(target: ast.AST) -> bool:
        """Return True if target is an Attribute/Name chain whose root is a handle name."""
        if isinstance(target, ast.Name):
            return target.id in HANDLE_NAMES
        if isinstance(target, ast.Attribute):
            # Recurse on value
            return _target_originates_from_handle(target.value) and target.attr in {
                "argtypes",
                "restype",
            }
        # Subscript, etc. not expected
        return False

    visit(tree, False, False)
    return bad


def test_no_unguarded_module_level_windll():
    offenders = {}
    for rel in GUARDED_MODULES:
        path = REPO / rel
        assert path.is_file(), f"guarded module missing: {rel}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        windll_offenders = _unguarded_windll_calls(tree)
        attr_offenders = _unguarded_handle_attribute_access(tree)
        if windll_offenders or attr_offenders:
            offenders[rel] = {
                "windll": windll_offenders,
                "attribute": attr_offenders,
            }
    assert not offenders, (
        "module-level ctypes.WinDLL or handle attribute access outside a function or "
        f"`if sys.platform == 'win32':` gate (breaks Linux collection): {offenders}"
    )


def test_windows_only_test_modules_carry_platform_skip():
    """Each Windows-only test module must carry a platform skip marker
    (pytest.mark.skipif or pytest.skip with allow_module_level=True) so that
    on non-Windows the module is skipped at collection time, preventing
    import-time WinDLL errors."""
    missing = []
    for rel in GATED_TEST_MODULES:
        text = (REPO / rel).read_text(encoding="utf-8")
        # Check for pytest.skip with allow_module_level=True anywhere in the file,
        # OR a pytestmark skipif that references sys.platform and "win".
        has_skip_marker = (
            "pytest.skip" in text
            and "allow_module_level=True" in text
        ) or (
            "pytestmark" in text
            and "skipif" in text
            and "sys.platform" in text
            and "win" in text.lower()
        )
        if not has_skip_marker:
            missing.append(rel)
    assert not missing, (
        "Windows-only test modules without a platform skip marker: {missing}"
    )


def test_modules_import_without_windll():
    """Behavioral test: simulate non-Windows by deleting ctypes attrs and patching sys.platform."""
    code = textwrap.dedent(
        '''
        import sys
        import ctypes
        import os
        # Patch platform first
        sys.platform = "linux"
        # Delete Windows-specific attributes
        for attr in ("WinDLL", "windll", "oledll", "get_last_error", "WinError"):
            if hasattr(ctypes, attr):
                delattr(ctypes, attr)
        # Import the guarded modules
        repo = os.environ["GAP055_REPO"]
        sys.path.insert(0, repo)
        sys.path.insert(0, os.path.join(repo, "scripts"))
        # Import all six guarded modules
        import importlib
        for mod in (
            "ultimate_pipeline.governance.single_writer.os_lock",
            "ultimate_pipeline.governance.single_writer.lease_store",
            "ultimate_pipeline.governance.single_writer.job_supervision",
            "scripts.control_plane",
            "scripts.job_supervision",
            "tools.orphan_terminal_witness",
        ):
            importlib.import_module(mod)
        # If we reach here, imports succeeded (no WinDLL at import time)
        # Now test that actual use fails loudly (explicit OSError, not fake)
        from ultimate_pipeline.governance.single_writer import os_lock, lease_store, job_supervision
        import scripts.control_plane as control_plane
        import scripts.job_supervision as job_supervision_scripts
        # Test os_lock
        try:
            os_lock.NamedMutex().acquire()
            assert False, "Expected OSError from NamedMutex.acquire()"
        except OSError as exc:
            assert "requires Windows" in str(exc)
        # Test lease_store
        try:
            lease_store.process_creation_time(1)
            assert False, "Expected OSError from process_creation_time()"
        except OSError as exc:
            assert "requires Windows" in str(exc)
        try:
            lease_store.new_lease("op", [], "fp", "ns")
            assert False, "Expected OSError from new_lease()"
        except OSError as exc:
            assert "requires Windows" in str(exc)
        # Test job_supervision (single_writer)
        try:
            job_supervision.create_job()
            assert False, "Expected OSError from create_job()"
        except OSError as exc:
            assert "requires Windows" in str(exc)
        try:
            job = job_supervision.create_job()
            job_supervision.process_parent_map()
            assert False, "Expected OSError from process_parent_map()"
        except OSError as exc:
            assert "requires Windows" in str(exc)
        try:
            job_supervision.spawn_in_job(job_supervision.create_job(), ["echo", "hello"])
            assert False, "Expected OSError from spawn_in_job()"
        except OSError as exc:
            assert "requires Windows" in str(exc)
        # Test control_plane
        try:
            control_plane.MutexHandle().try_acquire()
            assert False, "Expected OSError from try_acquire()"
        except OSError as exc:
            assert "requires Windows" in str(exc)
        # Test scripts/job_supervision
        try:
            sup = job_supervision_scripts.JobSupervisor()
            sup.create()
            assert False, "Expected OSError from JobSupervisor.create()"
        except OSError as exc:
            assert "requires Windows" in str(exc)
        try:
            sup = job_supervision_scripts.JobSupervisor()
            sup.spawn(["echo", "hello"])
            assert False, "Expected OSError from JobSupervisor.spawn()"
        except OSError as exc:
            assert "requires Windows" in str(exc)
        # Test orphan_terminal_witness
        import tools.orphan_terminal_witness as witness
        try:
            witness.main()
            assert False, "Expected OSError from orphan_terminal_witness.main()"
        except OSError as exc:
            assert "requires Windows" in str(exc)
        '''
    )
    env = os.environ.copy()
    env["GAP055_REPO"] = str(REPO)
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Process failed with stdout={result.stdout!r} stderr={result.stderr!r}"
    # If we got here, all imports and calls behaved as expected

